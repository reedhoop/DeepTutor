#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_prod_service.py - install / uninstall / status for DeepTutor Windows services (NSSM).

Python replacement for the earlier PowerShell NSSM installers
(install-prod-service.ps1 / uninstall-prod-service.ps1, removed in favor of
this script), avoiding the PowerShell landmines hit in production deployment:
  * reserved $Args automatic variable silently emptying launch args
  * $ErrorActionPreference="Stop" turning native stderr into terminating errors
  * `sc` being an alias for Set-Content instead of the Service Control Manager

Services:
  DeepTutorBackend  : <repo>/.venv/Scripts/python.exe -m uvicorn deeptutor.api.main:app \
                        --host 0.0.0.0 --port 8002 --log-level info --no-access-log \
                        --ws-max-size 43341141 --timeout-keep-alive 300
  DeepTutorFrontend : node .next/standalone/server.js   (cwd = web, PORT=3800, depends on backend)

Each service: Start=Automatic (boot), AppExit Default=Restart (crash self-heal), throttle 5s.

Requires an ELEVATED shell (installing services writes to the Service Control Manager).

Usage:
  python scripts/install_prod_service.py install [--skip-build] [--dry-run]
      [--backend-port N] [--frontend-port N] [--k12-data-dir DIR] [--k12-cache-dir DIR]
      [--enable-auth] [--secure-cookies] [--nssm-path PATH]
  python scripts/install_prod_service.py uninstall [--dry-run] [--nssm-path PATH]
  python scripts/install_prod_service.py status
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB_DIR = REPO / "web"
DATA_DIR = REPO / "data"
BIN_DIR = REPO / "scripts" / "bin"

BACKEND_SVC = "DeepTutorBackend"
FRONTEND_SVC = "DeepTutorFrontend"
NSSM_VERSION = "2.24"

_STATE_NAMES = {
    1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING", 4: "RUNNING",
    5: "CONTINUE_PENDING", 6: "PAUSE_PENDING", 7: "PAUSED",
}


def out(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print("[WARN] " + msg, flush=True)


def err(msg: str) -> None:
    print("[ERROR] " + msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# low-level helpers (subprocess-based; no PowerShell involved)
# ---------------------------------------------------------------------------
def run(cmd, **kw):
    """Run a command, capture output, never raise on non-zero exit code.
    A timeout guard (default 30s) prevents any hung child from blocking the
    whole installer."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    kw.setdefault("timeout", 30)
    try:
        return subprocess.run(cmd, **kw)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, "", f"timed out after {kw['timeout']}s")


def sc(args):
    """Invoke the Windows Service Control Manager (sc.exe)."""
    return run(["sc.exe"] + args)


def service_exists(name: str) -> bool:
    return sc(["query", name]).returncode == 0


def service_state(name: str) -> str:
    r = sc(["query", name])
    if r.returncode != 0:
        return "NOT_INSTALLED"
    m = re.search(r"STATE\s*:\s*(\d+)", r.stdout or "")
    if not m:
        return "UNKNOWN"
    return _STATE_NAMES.get(int(m.group(1)), "UNKNOWN")


def stop_service(name: str, timeout: float = 25.0) -> str:
    if not service_exists(name):
        return "NOT_INSTALLED"
    st = service_state(name)
    if st in ("STOPPED", "STOP_PENDING"):
        return st
    r = sc(["stop", name])  # RC 0 = stopped/stopping; 1062 = not running (race, fine)
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = service_state(name)
        if st in ("STOPPED", "STOP_PENDING", "NOT_INSTALLED"):
            break
        time.sleep(1)
    return service_state(name)


def wait_service_gone(name: str, timeout: float = 35.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not service_exists(name):
            return True
        time.sleep(2)
    return False


def delete_service(name: str, timeout: float = 35.0) -> bool:
    """Delete a service. Tolerates 1060 (missing) and 1072 (already marked for
    deletion) and waits for the SCM to actually drop the registration."""
    if not service_exists(name):
        return True
    r = sc(["delete", name])
    if r.returncode in (0, 1060, 1072):
        return wait_service_gone(name, timeout)
    return False


def check_admin(dry_run: bool) -> None:
    r = run(["net", "session"])
    if r.returncode == 0:
        return
    if dry_run:
        warn("Not elevated; dry-run only (no SCM changes will be made).")
        return
    err("Administrator privileges required (SCM writes). Re-run this from an elevated prompt.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# resolution: python / node / nssm / K12
# ---------------------------------------------------------------------------
def resolve_python() -> str:
    prod_py = REPO / ".venv" / "Scripts" / "python.exe"
    if prod_py.exists():
        return str(prod_py)
    dev_py = REPO.parent / "DeepTutor" / ".venv" / "Scripts" / "python.exe"
    if dev_py.exists():
        warn(f"Prod-local .venv not found; falling back to the DEV venv at: {dev_py}")
        return str(dev_py)
    err(f"No Python venv found. Create one first: cd {REPO}; python -m venv .venv; .venv\\Scripts\\pip install -e .")
    sys.exit(1)


def resolve_node() -> str:
    n = shutil.which("node")
    if not n:
        err("'node' not found on PATH. Install Node.js 22+ and re-run.")
        sys.exit(1)
    return n


def resolve_nssm(explicit: str) -> str:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return str(p.resolve())
        err(f"NssmPath not found: {explicit}")
        sys.exit(1)
    on_path = shutil.which("nssm")
    if on_path:
        return on_path
    local = BIN_DIR / "nssm.exe"
    if local.exists():
        return str(local)
    url = f"https://nssm.cc/release/nssm-{NSSM_VERSION}.zip"
    out(f"==> NSSM not found; downloading {url} ...")
    try:
        zip_path = Path(tempfile.gettempdir()) / f"nssm-{NSSM_VERSION}.zip"
        urllib.request.urlretrieve(url, zip_path)
        extract = Path(tempfile.mkdtemp(prefix="nssm-"))
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract)
        cand = extract / f"nssm-{NSSM_VERSION}" / "win64" / "nssm.exe"
        if not cand.exists():
            cand = extract / f"nssm-{NSSM_VERSION}" / "win32" / "nssm.exe"
        if not cand.exists():
            raise FileNotFoundError("nssm.exe not found in archive")
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cand, local)
        out(f"==> NSSM installed to {local}")
        return str(local)
    except Exception as e:  # noqa: BLE001
        warn(f"NSSM download failed: {e}")
        warn(f"Download nssm-{NSSM_VERSION}.zip from https://nssm.cc and place nssm.exe in {BIN_DIR}, then re-run.")
        sys.exit(1)


def fix_drive(p: str) -> str:
    """Normalize git-bash style /d/foo -> D:/foo."""
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)
    return f"{m.group(1)}:/{m.group(2)}" if m else p


def resolve_k12(args) -> tuple[str, str]:
    data = args.k12_data_dir or os.environ.get("K12_KGRAPH_DATA_DIR", "")
    if not data:
        in_repo = REPO / "K12-KGraph-data"
        if in_repo.exists():
            data = str(in_repo)
    if not data:
        sibling = REPO.parent / "K12-KGraph-data"
        if sibling.exists():
            data = str(sibling)
    if data:
        data = fix_drive(data)
        p = Path(data)
        data = str(p.resolve()) if p.exists() else ""
    cache = args.k12_cache_dir or os.environ.get("K12_KGRAPH_CACHE_DIR", "")
    if not cache:
        cache = str(DATA_DIR / "knowledge_bases" / "k12_kg")
    cache = fix_drive(cache)
    return data, cache


# ---------------------------------------------------------------------------
# optional steps: auth + frontend build
# ---------------------------------------------------------------------------
def apply_auth(args) -> None:
    if not args.enable_auth:
        return
    auth_file = DATA_DIR / "user" / "settings" / "auth.json"
    if not auth_file.exists():
        warn(f"auth.json not found at {auth_file}; cannot enable auth automatically.")
        return
    try:
        auth = json.loads(auth_file.read_text(encoding="utf-8"))
        auth["enabled"] = True
        auth["cookie_secure"] = bool(args.secure_cookies)
        auth_file.write_text(json.dumps(auth, ensure_ascii=False, indent=2), encoding="utf-8")
        out(f"==> Auth ENABLED (cookie_secure={auth['cookie_secure']}).")
    except Exception as e:  # noqa: BLE001
        warn(f"Failed to update {auth_file}: {e}")


def build_frontend(args) -> None:
    if args.skip_build:
        server = WEB_DIR / ".next" / "standalone" / "server.js"
        if not server.exists():
            warn(f"--skip-build set but {server} not found; the frontend service will fail to start.")
        return
    if args.dry_run:
        out("    [DRY-RUN] would run: npm install + next build (add --skip-build to reuse an existing build)")
        return
    npm = shutil.which("npm")
    if not npm:
        err("'npm' not found on PATH; needed for the build (or pass --skip-build).")
        sys.exit(1)
    env = dict(os.environ, BACKEND_PORT=str(args.backend_port),
               DEEPTUTOR_API_BASE_URL=f"http://localhost:{args.backend_port}")
    out("==> npm install")
    r = run([npm, "install"], cwd=str(WEB_DIR), env=env)
    if r.returncode != 0:
        err("npm install failed; see output above.")
        sys.exit(1)
    out("==> next build")
    r = run([npm, "run", "build"], cwd=str(WEB_DIR), env=env)
    if r.returncode != 0:
        err("next build failed; see output above.")
        sys.exit(1)
    standalone = WEB_DIR / ".next" / "standalone"
    if standalone.exists():
        out("==> copying static assets into standalone dir")
        if (WEB_DIR / "public").exists():
            shutil.copytree(WEB_DIR / "public", standalone / "public", dirs_exist_ok=True)
        if (WEB_DIR / ".next" / "static").exists():
            shutil.copytree(WEB_DIR / ".next" / "static", standalone / ".next" / "static", dirs_exist_ok=True)


# ---------------------------------------------------------------------------
# service install / uninstall
# ---------------------------------------------------------------------------
def install_one(nssm: str, name: str, app: str, launch_args, workdir: Path,
                env, log: Path, deps, dry_run: bool) -> bool:
    if service_exists(name):
        out(f"==> Service {name} already exists; stopping and removing (idempotent re-install).")
        if not dry_run:
            stop_service(name)
            deleted = delete_service(name)
            if not deleted:
                err(f"Could not remove existing service {name}. If it is stuck in STOP_PENDING / "
                    f"marked for deletion, wait a few seconds and re-run, or delete it manually: "
                    f"sc.exe delete {name}")
                return False
    out(f"==> install service {name}")
    if dry_run:
        out(f"    [DRY-RUN] {nssm} install {name} \"{app}\" {' '.join(launch_args)}")
        return True

    # register the exe ONLY, then set everything explicitly - the reliable
    # cross-version path (passing args through `nssm install` can yield an
    # empty AppParameters and an instantly-exiting service).
    r = run([nssm, "install", name, app])
    if r.returncode != 0:
        err(f"nssm install {name} failed (exit {r.returncode}).")
        return False

    def nset(key: str, *val):
        rr = run([nssm, "set", name, key, *val])
        if rr.returncode != 0:
            warn(f"nssm set {name} {key} failed (exit {rr.returncode}).")

    if launch_args:
        nset("AppParameters", " ".join(launch_args))
        # guard against the empty-AppParameters bug that produced REPL-only
        # services; abort loudly instead of registering a broken service.
        # (nssm prints values as UTF-16, so strip the NUL bytes before checking.)
        chk = run([nssm, "get", name, "AppParameters"])
        stored = (chk.stdout or "").replace("\x00", "").strip()
        if chk.returncode != 0 or not stored:
            err(f"AppParameters for {name} is EMPTY after set - aborting to avoid a broken service.")
            return False
    nset("AppDirectory", str(workdir))
    nset("Start", "SERVICE_AUTO_START")
    nset("AppExit", "Default", "Restart")
    nset("AppThrottle", "5000")
    nset("AppStdout", str(log))
    nset("AppStderr", str(log))
    if env:
        nset("AppEnvironmentExtra", "\n".join(env))
    if deps:
        nset("DependOnService", " ".join(deps))
    return True


def start_and_verify(nssm: str, name: str, timeout: float = 90.0, dry_run: bool = False):
    if dry_run:
        out(f"    [DRY-RUN] {nssm} start {name}")
        return True
    run([nssm, "start", name])
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = service_state(name)
        if st == "RUNNING":
            out(f"  {name}: RUNNING")
            return True
        time.sleep(2)
    st = service_state(name)
    warn(f"{name}: not RUNNING after {timeout:.0f}s (state={st}). Check the service log.")
    return False


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_install(args) -> int:
    print("=" * 46)
    print(" DeepTutor service installer (Python)")
    print("=" * 46)
    python = resolve_python()
    node = resolve_node()
    k12_data, k12_cache = resolve_k12(args)
    nssm = resolve_nssm(args.nssm_path)
    check_admin(args.dry_run)
    apply_auth(args)
    build_frontend(args)

    print(f" Repo          : {REPO}")
    print(f" Python        : {python}")
    print(f" Node          : {node}")
    print(f" NSSM          : {nssm}")
    print(f" Backend port  : {args.backend_port}")
    print(f" Frontend port : {args.frontend_port}")
    if k12_data:
        print(f" K12 data dir  : {k12_data}")
    else:
        warn(" K12 data dir NOT set -> K12 features disabled")
    print(f" K12 cache dir : {k12_cache}")
    print("=" * 46)

    backend_args = ["-m", "uvicorn", "deeptutor.api.main:app",
                    "--host", "0.0.0.0", "--port", str(args.backend_port),
                    "--log-level", "info", "--no-access-log",
                    "--ws-max-size", "43341141",
                    "--timeout-keep-alive", "300"]
    backend_env = []
    if k12_data:
        backend_env.append(f"K12_KGRAPH_DATA_DIR={k12_data}")
    backend_env += [f"K12_KGRAPH_CACHE_DIR={k12_cache}", f"BACKEND_PORT={args.backend_port}"]

    frontend_args = [".next/standalone/server.js"]
    frontend_env = [f"PORT={args.frontend_port}", "HOSTNAME=0.0.0.0",
                    f"BACKEND_PORT={args.backend_port}",
                    f"DEEPTUTOR_API_BASE_URL=http://localhost:{args.backend_port}"]

    backend_log = REPO / "prod-backend.log"
    frontend_log = REPO / "prod-frontend.log"

    ok_b = install_one(nssm, BACKEND_SVC, python, backend_args, REPO, backend_env,
                       backend_log, [], args.dry_run)
    ok_f = install_one(nssm, FRONTEND_SVC, node, frontend_args, WEB_DIR, frontend_env,
                       frontend_log, [BACKEND_SVC], args.dry_run)
    if not (ok_b and ok_f):
        err("Install failed; fix the reported service and re-run.")
        return 1

    if not args.dry_run:
        out("==> starting services")
        start_and_verify(nssm, BACKEND_SVC, dry_run=False)
        start_and_verify(nssm, FRONTEND_SVC, dry_run=False)

    out("")
    out("Done. Services:")
    out(f"  {BACKEND_SVC}  -> http://localhost:{args.backend_port}  (log: {backend_log})")
    out(f"  {FRONTEND_SVC} -> http://localhost:{args.frontend_port} (log: {frontend_log})")
    out("")
    out("Manage with:")
    out(f"  nssm restart {BACKEND_SVC} / {FRONTEND_SVC}")
    out(f"  Get-Service {BACKEND_SVC},{FRONTEND_SVC}")
    out("  Uninstall: python scripts/install_prod_service.py uninstall")
    return 0


def cmd_uninstall(args) -> int:
    check_admin(args.dry_run)
    nssm = resolve_nssm(args.nssm_path)
    for name in (BACKEND_SVC, FRONTEND_SVC):
        if not service_exists(name):
            out(f"  {name}: not installed (skip)")
            continue
        out(f"==> stopping and removing {name}")
        if args.dry_run:
            out(f"    [DRY-RUN] stop + delete {name}")
            continue
        stop_service(name)
        ok = delete_service(name)
        out(f"    {'removed' if ok else 'FAILED to remove (see above)'}")
    out("done.")
    return 0


def cmd_status(_args) -> int:
    for name in (BACKEND_SVC, FRONTEND_SVC):
        out(f"  {name}: {service_state(name)}")
    return 0


def main() -> None:
    if os.name != "nt":
        err("This script is Windows-only (NSSM services).")
        sys.exit(1)
    p = argparse.ArgumentParser(description="DeepTutor NSSM service installer (Python)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("install", help="install the two Windows services")
    pi.add_argument("--skip-build", action="store_true", help="reuse existing web/.next build")
    pi.add_argument("--dry-run", action="store_true", help="print what would happen, install nothing")
    pi.add_argument("--backend-port", type=int, default=8002)
    pi.add_argument("--frontend-port", type=int, default=3800)
    pi.add_argument("--k12-data-dir", default="")
    pi.add_argument("--k12-cache-dir", default="")
    pi.add_argument("--enable-auth", action="store_true")
    pi.add_argument("--secure-cookies", action="store_true")
    pi.add_argument("--nssm-path", default="")
    pi.set_defaults(func=cmd_install)

    pu = sub.add_parser("uninstall", help="stop and remove the services")
    pu.add_argument("--dry-run", action="store_true")
    pu.add_argument("--nssm-path", default="")
    pu.set_defaults(func=cmd_uninstall)

    ps_ = sub.add_parser("status", help="print service states")
    ps_.set_defaults(func=cmd_status)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
