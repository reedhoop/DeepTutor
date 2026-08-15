#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_k12.py — 一键部署「全功能 + K12」的 reedhoop/DeepTutor

为什么需要它
------------
DeepTutor 基础部署已经很省事（PyPI / 源码 / Docker / `deeptutor init`+`start`），
但 reedhoop 这个 K12 fork 在基础上叠了三层「没人帮你自动化」的东西：

  1. K12-KGraph 外置仓库（默认要放在 DeepTutor 同级 `../K12-KGraph-data`，
     或设环境变量 `K12_KGRAPH_DATA_DIR`）；
  2. 4 个 VLM 解析引擎（ovisocr2 / paddleocr_vl / pp_structurev3 / chandra）
     需要外部 vLLM 服务 + HF/ModelScope 权重，且 `deeptutor init` 完全不提示；
  3. K12 相关配置（KGraph 路径 / VLM / 语音 API key）全要手动补。

本脚本把这些变成「一条命令」，并做成 **幂等 + agent 友好**（`--json` / `--non-interactive`）。

设计要点（对齐 deepseek-harness 的「一个命令 + 运行时解析 + 给 agent 的文档」思路）
- 纯标准库编排，脚本本身不需要 venv 即可运行；
- 每步幂等：已完成的跳过重做，状态清晰（[OK]/[SKIP]/[FAIL]）；
- 配置全部来自环境变量或 `.deploy-k12.env`，无人值守；
- `--json` 输出 NDJSON 事件流，便于 agent 解析。

用法
----
  # 注意：脚本在仓库内，须先 clone 再从这个目录里运行（不能用空目录一条命令）
  git clone https://github.com/reedhoop/DeepTutor.git mytutor && cd mytutor
  # 先写好 .deploy-k12.env（至少 LLM_* / EMBEDDING_*），再一条命令
  python scripts/deploy_k12.py all --non-interactive      # = all（缺密钥会直接失败）

  # 分步
  python scripts/deploy_k12.py preflight
  python scripts/deploy_k12.py clone
  python scripts/deploy_k12.py install
  python scripts/deploy_k12.py configure
  python scripts/deploy_k12.py start
  python scripts/deploy_k12.py status

  # agent 模式
  python scripts/deploy_k12.py all --non-interactive --json

配置（环境变量或 .deploy-k12.env，KEY=VALUE，# 开头为注释）
  DEEPTUTOR_REPO        DeepTutor fork 地址  默认 https://github.com/reedhoop/DeepTutor.git
  DEEPTUTOR_BRANCH      分支                  默认 main
  K12_KGRAPH_REPO       K12-KGraph 仓库       默认 https://hf-mirror.com/datasets/lhpku20010120/K12-KGraph
  DEEPTUTOR_HOME        工作区目录            默认当前目录
  BACKEND_PORT          后端端口              默认 8001
  FRONTEND_PORT         前端端口              默认 3782
  INSTALL_EXTRAS        pip extras 逗号列表   默认 ""（建议 "math-animator" 开启数学动画）
  DEV                   是否 dev 模式启动       默认 false

  # 模型配置（缺省时仍会 seed 一个空 profile，启动后在 Settings 页面补）
  LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_NAME / LLM_BINDING
  EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_BINDING
  TTS_API_KEY / TTS_BASE_URL / TTS_MODEL / TTS_VOICE / TTS_BINDING
  STT_API_KEY / STT_BASE_URL / STT_MODEL / STT_BINDING

  VLM_SEED              是否写入 4 个 VLM 引擎默认配置  默认 true
  KGRAPH_WARM           是否预热 node_vectors（需 embedding key，较慢）默认 false
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------
DEFAULTS = {
    "DEEPTUTOR_REPO": "https://github.com/reedhoop/DeepTutor.git",
    "DEEPTUTOR_BRANCH": "main",
    "K12_KGRAPH_REPO": "https://hf-mirror.com/datasets/lhpku20010120/K12-KGraph",
    "BACKEND_PORT": "8001",
    "FRONTEND_PORT": "3782",
    "INSTALL_EXTRAS": "",
    "DEV": "false",
    "VLM_SEED": "true",
    "KGRAPH_WARM": "false",
}

# 4 个 K12 VLM 引擎的默认切片（与 deeptutor/_local/engine_defaults.py 保持一致）。
# 若运行时能 import 到真实的 DEFAULT_EXTERNAL_ENGINE_SLICES 则以代码为准，否则用此兜底。
FALLBACK_VLM_SLICES = {
    "ovisocr2": {
        "api_base_url": "http://127.0.0.1:8200/v1",
        "api_token": "",
        "model_name": "ATH-MaaS/OvisOCR2",
        "image_dpi": 200,
        "max_tokens": 16384,
        "temperature": 0.0,
        "language": "auto",
        "timeout_s": 120,
        "max_concurrency": 4,
        "extra_prompt": "",
    },
    "paddleocr_vl": {
        "api_base_url": "http://127.0.0.1:8118/v1",
        "api_token": "",
        "model_name": "PaddleOCR-VL-1.6-0.9B",
        "image_dpi": 200,
        "max_tokens": 4096,
        "temperature": 0.0,
        "language": "auto",
        "timeout_s": 120,
        "max_concurrency": 4,
        "extra_prompt": "",
        "enable_layout": True,
    },
    "pp_structurev3": {
        "device": "gpu",
        "lang": "ch",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "use_formula_recognition": True,
        "use_chart_recognition": False,
        "use_seal_recognition": True,
        "layout_threshold": 0.5,
        "layout_nms": True,
        "layout_unclip_ratio": 1.0,
        "allow_local_model_download": False,
    },
    "chandra": {
        "api_base_url": "http://127.0.0.1:8230/v1",
        "api_token": "",
        "model_name": "",  # 故意留空：需用户部署 Chandra 的 vLLM 后填入
        "image_dpi": 200,
        "max_tokens": 16384,
        "temperature": 0.0,
        "language": "auto",
        "timeout_s": 120,
        "max_concurrency": 4,
        "extra_prompt": "",
    },
}


# ---------------------------------------------------------------------------
# 日志（人类可读 + JSON 事件流）
# ---------------------------------------------------------------------------
class Log:
    def __init__(self, json_mode: bool = False):
        self.json_mode = json_mode

    def _emit(self, level: str, step: str, status: str, detail: str = ""):
        if self.json_mode:
            rec = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "step": step,
                "status": status,
                "detail": detail,
            }
            sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        else:
            icon = {"OK": "✅", "SKIP": "⏭️ ", "FAIL": "❌", "INFO": "ℹ️ ", "RUN": "🚀"}.get(status, "·")
            line = f"{icon} [{step}] {detail or status}"
            print(line)

    def ok(self, step, detail=""):
        self._emit("info", step, "OK", detail)

    def skip(self, step, detail=""):
        self._emit("info", step, "SKIP", detail)

    def fail(self, step, detail=""):
        self._emit("error", step, "FAIL", detail)

    def info(self, step, detail=""):
        self._emit("info", step, "INFO", detail)

    def run(self, step, detail=""):
        self._emit("info", step, "RUN", detail)


log = Log()


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------
def load_config(cli_home: str | None) -> dict:
    cfg = dict(DEFAULTS)
    # 1) .deploy-k12.env（若存在）
    envfile = Path(".deploy-k12.env")
    if envfile.exists():
        for raw in envfile.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    # 2) 进程环境变量（覆盖）
    for k in DEFAULTS:
        if k in os.environ:
            cfg[k] = os.environ[k]
    # 3) 模型相关变量（只有 env 里有才带）
    for k in (
        "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_NAME", "LLM_BINDING",
        "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_BINDING",
        "TTS_API_KEY", "TTS_BASE_URL", "TTS_MODEL", "TTS_VOICE", "TTS_BINDING",
        "STT_API_KEY", "STT_BASE_URL", "STT_MODEL", "STT_BINDING",
        "K12_KGRAPH_DATA_DIR",
    ):
        if k in os.environ:
            cfg[k] = os.environ[k]
    # 4) DEEPTUTOR_HOME
    home = cli_home or cfg.get("DEEPTUTOR_HOME") or os.getcwd()
    cfg["DEEPTUTOR_HOME"] = os.path.abspath(home)
    return cfg


def kgraph_dir(cfg: dict) -> Path:
    if cfg.get("K12_KGRAPH_DATA_DIR"):
        return Path(cfg["K12_KGRAPH_DATA_DIR"]).resolve()
    return Path(cfg["DEEPTUTOR_HOME"]).resolve().parent / "K12-KGraph-data"


def venv_python(cfg: dict) -> Path:
    home = Path(cfg["DEEPTUTOR_HOME"])
    if os.name == "nt":
        return home / ".venv" / "Scripts" / "python.exe"
    return home / ".venv" / "bin" / "python"


def deeptutor_bin(cfg: dict) -> Path:
    home = Path(cfg["DEEPTUTOR_HOME"])
    if os.name == "nt":
        return home / ".venv" / "Scripts" / "deeptutor.exe"
    return home / ".venv" / "bin" / "deeptutor"


# ---------------------------------------------------------------------------
# 各步骤
# ---------------------------------------------------------------------------
def step_preflight(cfg: dict) -> bool:
    log.run("preflight", "检查运行环境")
    ok = True
    # Python
    py = shutil.which("python3") or shutil.which("python")
    if not py:
        log.fail("preflight", "未找到 python3")
        ok = False
    else:
        ver = subprocess.run([py, "-c", "import sys;print(sys.version_info[:2])"],
                             capture_output=True, text=True).stdout.strip()
        log.info("preflight", f"python = {ver}")
    # Node
    node = shutil.which("node")
    if not node:
        log.fail("preflight", "未找到 node（需 >= 20）")
        ok = False
    else:
        v = subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip()
        log.info("preflight", f"node = {v}")
    # npm
    if not shutil.which("npm"):
        log.fail("preflight", "未找到 npm")
        ok = False
    # git
    if not shutil.which("git"):
        log.fail("preflight", "未找到 git")
        ok = False
    # KGraph 目录
    kd = kgraph_dir(cfg)
    log.info("preflight", f"K12-KGraph 目标目录 = {kd}")
    if not kd.exists():
        log.info("preflight", "K12-KGraph 尚未克隆（clone 步骤会处理）")
    # API key 提示（非致命，仅 preflight 时给出，便于提前发现）
    if not (cfg.get("LLM_API_KEY") and cfg.get("LLM_BASE_URL") and cfg.get("LLM_MODEL")):
        log.info("preflight", "未检测到完整 LLM_* 配置；部署前请提供，否则 app 能启动但无法辅导")
    if not (cfg.get("EMBEDDING_API_KEY") and cfg.get("EMBEDDING_BASE_URL") and cfg.get("EMBEDDING_MODEL")):
        log.info("preflight", "未检测到完整 EMBEDDING_* 配置；KGraph 语义检索将不可用")
    return ok


def step_clone(cfg: dict) -> bool:
    home = Path(cfg["DEEPTUTOR_HOME"])
    repo = cfg["DEEPTUTOR_REPO"]
    branch = cfg["DEEPTUTOR_BRANCH"]

    # --- DeepTutor 本身 ---
    git_dir = home / ".git"
    if git_dir.exists():
        try:
            origin = subprocess.run(
                ["git", "-C", str(home), "remote", "get-url", "origin"],
                capture_output=True, text=True,
            ).stdout.strip()
        except Exception:
            origin = ""
        if origin and (repo in origin or "reedhoop/DeepTutor" in origin):
            log.skip("clone", f"DeepTutor 已存在且 origin 匹配：{home}")
        else:
            log.skip("clone", f"目录已是 git 仓库（origin={origin or '?'}），跳过克隆；如需切换请手动处理")
    else:
        home.mkdir(parents=True, exist_ok=True)
        log.run("clone", f"克隆 DeepTutor → {home}")
        r = subprocess.run(
            ["git", "clone", "--branch", branch, repo, str(home)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            log.fail("clone", r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "git clone 失败")
            return False
        log.ok("clone", "DeepTutor 克隆完成")

    # --- K12-KGraph ---
    kd = kgraph_dir(cfg)
    if kd.exists() and (kd / ".git").exists():
        log.skip("clone", f"K12-KGraph 已存在：{kd}")
    else:
        kd.parent.mkdir(parents=True, exist_ok=True)
        log.run("clone", f"克隆 K12-KGraph → {kd}")
        # 若仓库含 git-lfs 大文件，先确保 lfs 已初始化（失败也不阻断，仅提示）
        try:
            subprocess.run(["git", "lfs", "install"], capture_output=True, text=True, timeout=60)
        except Exception:
            pass
        r = subprocess.run(
            ["git", "clone", cfg["K12_KGRAPH_REPO"], str(kd)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            log.fail("clone", "K12-KGraph 克隆失败：" + (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "未知错误")
                     + "（可手动 git clone 后设 K12_KGRAPH_DATA_DIR）")
            # 不致命：缺 KGraph 时大部分功能降级
        else:
            log.ok("clone", "K12-KGraph 克隆完成")

    # 写入 K12_KGRAPH_DATA_DIR 供后续启动使用
    cfg["K12_KGRAPH_DATA_DIR"] = str(kd)
    return True


def step_install(cfg: dict) -> bool:
    home = Path(cfg["DEEPTUTOR_HOME"])
    vpy = venv_python(cfg)
    if vpy.exists():
        log.skip("install", f"venv 已存在：{vpy}")
    else:
        log.run("install", "创建 venv 并安装后端依赖（可能较慢）")
        py = shutil.which("python3") or shutil.which("python")
        subprocess.run([py, "-m", "venv", str(home / ".venv")], check=True)
        subprocess.run([str(vpy), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        extras = cfg.get("INSTALL_EXTRAS", "").strip()
        spec = ".[" + extras + "]" if extras else "."
        r = subprocess.run(
            [str(vpy), "-m", "pip", "install", "-e", spec],
            cwd=str(home), capture_output=True, text=True,
        )
        if r.returncode != 0:
            log.fail("install", "pip install 失败：" + r.stderr.strip().splitlines()[-1])
            return False
        log.ok("install", "后端依赖安装完成")

    # 前端
    web = home / "web"
    lock = web / "package-lock.json"
    if lock.exists():
        log.run("install", "安装前端依赖 (npm ci)")
        r = subprocess.run(["npm", "ci", "--legacy-peer-deps"], cwd=str(web),
                           capture_output=True, text=True)
    else:
        log.run("install", "安装前端依赖 (npm install)")
        r = subprocess.run(["npm", "install", "--legacy-peer-deps"], cwd=str(web),
                           capture_output=True, text=True)
    if r.returncode != 0:
        log.fail("install", "npm 安装失败：" + r.stderr.strip().splitlines()[-1])
        return False
    log.ok("install", "前端依赖安装完成")
    return True


def _seed_runtime_baseline(cfg: dict) -> None:
    """调用 DeepTutor 自带的初始化，先把默认 settings 文件建出来。"""
    vpy = venv_python(cfg)
    code = (
        "import os;"
        "os.environ['DEEPTUTOR_HOME']=os.environ.get('DEEPTUTOR_HOME','.');"
        "from deeptutor.services.setup.init import init_user_directories;"
        "init_user_directories();"
        "from deeptutor.services.config import ensure_runtime_settings_files;"
        "ensure_runtime_settings_files();"
        "print('baseline-ok')"
    )
    env = dict(os.environ)
    env["DEEPTUTOR_HOME"] = cfg["DEEPTUTOR_HOME"]
    r = subprocess.run([str(vpy), "-c", code], cwd=cfg["DEEPTUTOR_HOME"],
                       capture_output=True, text=True, env=env)
    if "baseline-ok" not in r.stdout and r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "init 失败")


def _get_vlm_slices():
    try:
        from deeptutor._local.engine_defaults import DEFAULT_EXTERNAL_ENGINE_SLICES
        return {k: dict(v) for k, v in DEFAULT_EXTERNAL_ENGINE_SLICES.items()}
    except Exception:
        return {k: dict(v) for k, v in FALLBACK_VLM_SLICES.items()}


def _profile_from_env(prefix: str, cfg: dict, pid: str, pname: str) -> dict | None:
    """根据 LLM_/EMBEDDING_/TTS_/STT_ 前缀构造一个 profile。"""
    key = cfg.get(f"{prefix}_API_KEY", "").strip()
    base = cfg.get(f"{prefix}_BASE_URL", "").strip()
    model = cfg.get(f"{prefix}_MODEL", "").strip()
    if not (key and base and model):
        return None
    binding = cfg.get(f"{prefix}_BINDING", "openai").strip() or "openai"
    name = cfg.get(f"{prefix}_NAME", pname).strip() or pname
    mid = model
    return {
        "id": pid,
        "name": name,
        "binding": binding,
        "base_url": base,
        "api_key": key,
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": mid, "name": name, "model": model}],
    }


def _merge_profile(services: dict, svc: str, profile: dict, make_active: bool):
    """把 profile 合并进 services[svc]（去重按 id），可选设为 active。"""
    entry = services.setdefault(svc, {"profiles": []})
    profiles = entry.setdefault("profiles", [])
    existing = {p.get("id"): p for p in profiles}
    if profile["id"] in existing:
        existing[profile["id"]].update(profile)
    else:
        profiles.append(profile)
    if make_active:
        entry["active_profile_id"] = profile["id"]
        entry["active_model_id"] = profile["models"][0]["id"]


def step_configure(cfg: dict) -> bool:
    home = Path(cfg["DEEPTUTOR_HOME"])
    settings = home / "data" / "user" / "settings"
    settings.mkdir(parents=True, exist_ok=True)

    log.run("configure", "生成基础 settings 文件")
    try:
        _seed_runtime_baseline(cfg)
    except Exception as e:
        log.fail("configure", f"基础初始化失败：{e}")
        return False

    # ---- model_catalog.json ----
    mc_path = settings / "model_catalog.json"
    if mc_path.exists():
        mc = json.loads(mc_path.read_text(encoding="utf-8"))
    else:
        mc = {"version": 1, "services": {}}
    services = mc.setdefault("services", {})

    llm = _profile_from_env("LLM", cfg, "k12-bootstrap-llm", "K12-Bootstrap-LLM")
    emb = _profile_from_env("EMBEDDING", cfg, "k12-bootstrap-embedding", "K12-Bootstrap-Embedding")
    tts = _profile_from_env("TTS", cfg, "k12-bootstrap-tts", "K12-Bootstrap-TTS")
    stt = _profile_from_env("STT", cfg, "k12-bootstrap-stt", "K12-Bootstrap-STT")

    if llm:
        _merge_profile(services, "llm", llm, True)
        log.ok("configure", "已写入 LLM profile（active）")
    else:
        log.skip("configure", "未提供 LLM_* 环境变量，跳过（启动后在 Settings 补）")

    if emb:
        _merge_profile(services, "embedding", emb, True)
        log.ok("configure", "已写入 Embedding profile（active）")
    else:
        log.skip("configure", "未提供 EMBEDDING_*（KGraph 语义检索需 embedding）")

    if tts:
        _merge_profile(services, "tts", tts, True)
        log.ok("configure", "已写入 TTS profile（active）")
    else:
        log.skip("configure", "未提供 TTS_*（语音输出需 TTS）")

    if stt:
        _merge_profile(services, "stt", stt, True)
        log.ok("configure", "已写入 STT profile（active）")
    else:
        log.skip("configure", "未提供 STT_*（语音输入需 STT）")

    mc_path.write_text(json.dumps(mc, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- system.json（端口 + VLM 引擎默认切片）----
    sys_path = settings / "system.json"
    if sys_path.exists():
        sysm = json.loads(sys_path.read_text(encoding="utf-8"))
    else:
        sysm = {}
    sysm["backend_port"] = int(cfg.get("BACKEND_PORT", 8001))
    sysm["frontend_port"] = int(cfg.get("FRONTEND_PORT", 3782))

    if cfg.get("VLM_SEED", "true").lower() == "true":
        dp = sysm.setdefault("document_parsing", {"version": 2, "engines": {}})
        dp.setdefault("version", 2)
        engines = dp.setdefault("engines", {})
        slices = _get_vlm_slices()
        added = []
        for name, slice_cfg in slices.items():
            if name not in engines:
                engines[name] = dict(slice_cfg)
                added.append(name)
        # 若没有任何 engine 被设成 active，保持默认；否则不动
        if added:
            log.ok("configure", "已写入 VLM 引擎默认配置：" + ", ".join(added))
            log.info("configure", "这些引擎的 vLLM 服务需另行拉起（见 K12_DEPLOY.md §VLM）")
        else:
            log.skip("configure", "VLM 引擎配置已存在，跳过覆盖")
        sysm["document_parsing"] = dp

    sys_path.write_text(json.dumps(sysm, indent=2, ensure_ascii=False), encoding="utf-8")
    log.ok("configure", f"已写入 {sys_path.name}（端口 {sysm['backend_port']}/{sysm['frontend_port']}）")

    # ---- KGraph 环境变量落盘（供 start 步骤与手动重启读取）----
    env_out = home / ".deploy-k12.runtime.env"
    env_out.write_text(
        f"K12_KGRAPH_DATA_DIR={cfg.get('K12_KGRAPH_DATA_DIR', '')}\n",
        encoding="utf-8",
    )
    return True


def step_start(cfg: dict, wait: bool = True) -> bool:
    home = Path(cfg["DEEPTUTOR_HOME"])
    binp = deeptutor_bin(cfg)
    if not binp.exists():
        log.fail("start", f"未找到 deeptutor 可执行文件：{binp}（请先 install）")
        return False
    # 载入 KGraph 环境变量
    env = dict(os.environ)
    env["DEEPTUTOR_HOME"] = cfg["DEEPTUTOR_HOME"]
    rt = home / ".deploy-k12.runtime.env"
    if rt.exists():
        for line in rt.read_text(encoding="utf-8").splitlines():
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()

    log.run("start", f"后台启动 DeepTutor（端口 {cfg['FRONTEND_PORT']}）")
    logfile = home / "deploy-k12.start.log"
    flags = ["start"]
    if cfg.get("DEV", "false").lower() == "true":
        flags.append("--dev")
    kwargs = dict(cwd=str(home), env=env)
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    with open(logfile, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen([str(binp), *flags], stdout=fh, stderr=subprocess.STDOUT, **kwargs)
    # 写 pid 文件
    (home / ".deploy-k12.pid").write_text(str(proc.pid), encoding="utf-8")
    log.ok("start", f"已启动 (pid={proc.pid})，日志：{logfile}")
    if wait:
        log.info("start", "等待服务就绪（最多 90s）…")
        import time
        for _ in range(90):
            if _health(cfg):
                log.ok("start", f"前端已就绪：http://127.0.0.1:{cfg['FRONTEND_PORT']}")
                return True
            time.sleep(1)
        log.info("start", "服务未在 90s 内就绪，请查看日志；可稍后运行 `status`")
    return True


def _health(cfg: dict) -> bool:
    import urllib.request
    url = f"http://127.0.0.1:{cfg['FRONTEND_PORT']}/"
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def step_status(cfg: dict) -> bool:
    home = Path(cfg["DEEPTUTOR_HOME"])
    fe = cfg["FRONTEND_PORT"]
    be = cfg["BACKEND_PORT"]
    log.run("status", "健康检查")
    up = _health(cfg)
    if up:
        log.ok("status", f"前端在线：http://127.0.0.1:{fe}")
    else:
        log.fail("status", f"前端未响应：http://127.0.0.1:{fe}")
    # 后端
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{be}/", timeout=2) as r:
            log.ok("status", f"后端在线：http://127.0.0.1:{be} (HTTP {r.status})")
    except Exception:
        log.fail("status", f"后端未响应：http://127.0.0.1:{be}")
    pidf = home / ".deploy-k12.pid"
    if pidf.exists():
        log.info("status", f"pid 文件：{pidf.read_text(encoding='utf-8').strip()}")
    return up


def step_stop(cfg: dict) -> bool:
    home = Path(cfg["DEEPTUTOR_HOME"])
    pidf = home / ".deploy-k12.pid"
    if not pidf.exists():
        log.skip("stop", "无 pid 文件")
        return True
    pid = pidf.read_text(encoding="utf-8").strip()
    log.run("stop", f"停止进程 {pid}")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
    else:
        subprocess.run(["kill", pid], capture_output=True)
    pidf.unlink(missing_ok=True)
    log.ok("stop", "已发送停止信号")
    return True


def _required_keys_present(cfg: dict):
    """部署全功能 K12 版至少需要 LLM 与 Embedding 配置，否则 app 无法辅导。"""
    missing = []
    if not (cfg.get("LLM_API_KEY") and cfg.get("LLM_BASE_URL") and cfg.get("LLM_MODEL")):
        missing.append("LLM_API_KEY/LLM_BASE_URL/LLM_MODEL")
    if not (cfg.get("EMBEDDING_API_KEY") and cfg.get("EMBEDDING_BASE_URL") and cfg.get("EMBEDDING_MODEL")):
        missing.append("EMBEDDING_API_KEY/EMBEDDING_BASE_URL/EMBEDDING_MODEL")
    return (len(missing) == 0, missing)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="一键部署 K12 版 DeepTutor")
    ap.add_argument("command", nargs="?", default="all",
                    choices=["all", "preflight", "clone", "install", "configure", "start", "status", "stop"],
                    help="子命令（默认 all）")
    ap.add_argument("--home", help="DEEPTUTOR_HOME 工作区目录")
    ap.add_argument("--non-interactive", action="store_true", help="无人值守（目前所有步骤本就非交互，占位）")
    ap.add_argument("--json", action="store_true", help="输出 NDJSON 事件流（agent 模式）")
    ap.add_argument("--skip-key-check", action="store_true", help="跳过 LLM/EMBEDDING 配置门禁（仅部署空壳时用）")
    args = ap.parse_args(argv)

    global log
    log = Log(json_mode=args.json)

    cfg = load_config(args.home)

    log.info("bootstrap", f"DEEPTUTOR_HOME = {cfg['DEEPTUTOR_HOME']}")
    log.info("bootstrap", f"K12_KGRAPH_DATA_DIR = {cfg.get('K12_KGRAPH_DATA_DIR') or '(待 clone)'}")

    cmd = args.command
    if cmd in ("all", "preflight"):
        if not step_preflight(cfg):
            return _exit(False, "preflight 未通过")
    if cmd in ("all", "configure"):
        if not args.skip_key_check:
            ok_keys, missing = _required_keys_present(cfg)
            if not ok_keys:
                log.fail("requirements",
                         f"缺少必需配置：{', '.join(missing)}。请写入 .deploy-k12.env 或环境变量后重跑；"
                         f"若只需部署空壳可加 --skip-key-check")
                return _exit(False, "缺少 LLM/EMBEDDING 配置")
    if cmd in ("all", "clone"):
        if not step_clone(cfg):
            return _exit(False, "clone 失败")
    if cmd in ("all", "install"):
        if not step_install(cfg):
            return _exit(False, "install 失败")
    if cmd in ("all", "configure"):
        if not step_configure(cfg):
            return _exit(False, "configure 失败")
    if cmd in ("all", "start"):
        if not step_start(cfg, wait=(cmd == "all")):
            return _exit(False, "start 失败")
    if cmd == "status":
        ok = step_status(cfg)
        return _exit(ok, "status 完成")
    if cmd == "stop":
        step_stop(cfg)
        return _exit(True, "stop 完成")

    if cmd == "all":
        log.ok("bootstrap", f"部署完成！打开 http://127.0.0.1:{cfg['FRONTEND_PORT']}")
        log.info("bootstrap", "如需 K12 VLM 引擎真正可用，请起对应 vLLM 服务（见 K12_DEPLOY.md §VLM）")
    return _exit(True, "done")


def _exit(ok: bool, msg: str) -> int:
    if not log.json_mode:
        print(("✅ " if ok else "❌ ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
