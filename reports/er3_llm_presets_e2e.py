#!/usr/bin/env python
"""ER-3 教育 LLM 预设 —— 端到端验证脚本（自带回滚）。

用法（必须用项目 venv）：
    cd D:\\00_aiStudy\\DeepTutor
    .venv\\Scripts\\python.exe reports/er3_llm_presets_e2e.py
    # 后端不在 8101 时：  --base-url http://localhost:8102

验证项：
    1. GET  /api/v1/settings/llm-presets            -> 200，恰好 3 个预设，字段完整
    2. OpenAPI 中两条路由均已注册
    3. POST /api/v1/settings/llm-presets/apply      -> 200，catalog 追加 profile 且被激活
    4. POST 未知 preset_id                          -> 404
    5. 回滚：删除测试期间新增的 profile，恢复原 active_profile_id / active_model_id

注意：本仓库默认单用户模式（auth 关闭），POST 会以 admin 身份直接通过。
若你开启了 data/user/settings/auth.json 的多用户鉴权，未带 cookie 的 POST 应返回 403，
此时脚本第 3/4 步会判为 SKIP 而非 FAIL。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# 必须在导入 deeptutor 之前：以脚本方式运行时 sys.path[0] 是 reports/，
# 会让 `import deeptutor` 命中 .venv/Lib/site-packages 里那份过时的非 editable 副本
# （症状：ModelCatalogService 缺少 update 等新方法）。强制优先使用仓库源码。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) in sys.path:
    sys.path.remove(str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT))

EXPECTED_PRESET_IDS = {"deepseek-reasoner", "qwen-math-plus", "qwen2.5"}
REQUIRED_PRESET_KEYS = {"id", "name", "binding", "base_url", "models"}

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    icon = {PASS: "[PASS]", FAIL: "[FAIL]", SKIP: "[SKIP]"}[status]
    print(f"{icon} {name}" + (f"  -- {detail}" if detail else ""))


def http(url: str, method: str = "GET", payload: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def read_llm_catalog() -> dict[str, Any]:
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    service = get_model_catalog_service()
    data = json.loads(service.path.read_text(encoding="utf-8"))
    return data["services"]["llm"]


def rollback(new_profile_ids: set[str], prev_profile: str, prev_model: str) -> None:
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    service = get_model_catalog_service()

    def _mutate(catalog: dict[str, Any]) -> None:
        llm = catalog["services"]["llm"]
        llm["profiles"] = [p for p in llm["profiles"] if p["id"] not in new_profile_ids]
        ids = {p["id"] for p in llm["profiles"]}
        if prev_profile in ids:
            llm["active_profile_id"] = prev_profile
            llm["active_model_id"] = prev_model
        elif llm["profiles"]:
            tgt = llm["profiles"][0]
            llm["active_profile_id"] = tgt["id"]
            llm["active_model_id"] = tgt["models"][0]["id"] if tgt.get("models") else ""

    service.update(_mutate)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8101")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"=== ER-3 E2E against {base} ===\n")

    # 自检：确保导入的是仓库源码而非 site-packages 中的过时副本
    import deeptutor

    pkg_dir = Path(deeptutor.__file__).resolve().parent
    if pkg_dir != _REPO_ROOT / "deeptutor":
        record(FAIL, "deeptutor 包来自仓库源码", f"实际来自 {pkg_dir}")
        print("\n请检查 sys.path，或在 venv 中卸载过时副本：pip uninstall deeptutor")
        return 1
    record(PASS, "deeptutor 包来自仓库源码", str(pkg_dir))

    # --- 1. 列预设 ---
    status, body = http(f"{base}/api/v1/settings/llm-presets")
    if status != 200:
        record(FAIL, "GET /llm-presets 返回 200", f"实际 {status}")
        return 1
    presets = body.get("presets") if isinstance(body, dict) else None
    if not isinstance(presets, list):
        record(FAIL, "响应含 presets 数组", f"实际 {type(body)}")
        return 1
    got_ids = {p.get("id") for p in presets}
    if got_ids == EXPECTED_PRESET_IDS:
        record(PASS, "GET /llm-presets 返回 3 个预设", ", ".join(sorted(got_ids)))
    else:
        record(FAIL, "预设 id 集合匹配", f"期望 {EXPECTED_PRESET_IDS}，实际 {got_ids}")

    missing = [
        (p.get("id"), sorted(REQUIRED_PRESET_KEYS - set(p)))
        for p in presets
        if REQUIRED_PRESET_KEYS - set(p)
    ]
    if missing:
        record(FAIL, "每个预设字段完整", f"缺字段: {missing}")
    else:
        record(PASS, "每个预设字段完整", "id/name/binding/base_url/models 齐全")

    # --- 2. OpenAPI 路由注册 ---
    status, spec = http(f"{base}/openapi.json")
    paths = set(spec.get("paths", {})) if isinstance(spec, dict) else set()
    want = {"/api/v1/settings/llm-presets", "/api/v1/settings/llm-presets/apply"}
    if want <= paths:
        record(PASS, "OpenAPI 已注册两条路由")
    else:
        record(FAIL, "OpenAPI 已注册两条路由", f"缺 {sorted(want - paths)}")

    # --- 3. apply 生效 ---
    before = read_llm_catalog()
    prev_profile = before.get("active_profile_id", "")
    prev_model = before.get("active_model_id", "")
    before_ids = {p["id"] for p in before["profiles"]}
    print(f"\n  (apply 前: {len(before_ids)} 个 profile, active={prev_profile})")

    status, body = http(
        f"{base}/api/v1/settings/llm-presets/apply",
        method="POST",
        payload={"preset_id": "deepseek-reasoner"},
    )
    new_ids: set[str] = set()
    if status == 403:
        record(SKIP, "POST apply 追加并激活 profile", "已开启鉴权，未带 cookie -> 403（预期行为）")
        record(SKIP, "POST 未知 preset_id 返回 404", "已开启鉴权，鉴权先于业务校验")
    elif status != 200:
        record(FAIL, "POST apply 返回 200", f"实际 {status}: {body}")
    else:
        after = read_llm_catalog()
        after_ids = {p["id"] for p in after["profiles"]}
        new_ids = after_ids - before_ids
        if len(new_ids) == 1:
            record(PASS, "apply 新增 1 个 profile", next(iter(new_ids)))
        else:
            record(FAIL, "apply 新增 1 个 profile", f"实际新增 {len(new_ids)} 个")

        added = next((p for p in after["profiles"] if p["id"] in new_ids), None)
        if added and after.get("active_profile_id") == added["id"]:
            record(PASS, "新 profile 被设为 active", added["id"])
        else:
            record(FAIL, "新 profile 被设为 active", f"active={after.get('active_profile_id')}")

        if added and added.get("models"):
            model_name = added["models"][0].get("model")
            if model_name == "deepseek-reasoner":
                record(PASS, "模型字段正确", model_name)
            else:
                record(FAIL, "模型字段正确", f"实际 {model_name}")
            if after.get("active_model_id") == added["models"][0]["id"]:
                record(PASS, "active_model_id 指向新模型")
            else:
                record(FAIL, "active_model_id 指向新模型", str(after.get("active_model_id")))
        else:
            record(FAIL, "新 profile 含 models", "models 为空")

        # --- 4. 未知 id -> 404 ---
        status, body = http(
            f"{base}/api/v1/settings/llm-presets/apply",
            method="POST",
            payload={"preset_id": "__does_not_exist__"},
        )
        if status == 404:
            record(PASS, "POST 未知 preset_id 返回 404")
        else:
            record(FAIL, "POST 未知 preset_id 返回 404", f"实际 {status}: {body}")

    # --- 5. 回滚 ---
    if new_ids:
        rollback(new_ids, prev_profile, prev_model)
        final = read_llm_catalog()
        final_ids = {p["id"] for p in final["profiles"]}
        clean = not (new_ids & final_ids) and final_ids == before_ids
        restored = final.get("active_profile_id") == prev_profile
        if clean and restored:
            record(PASS, "回滚干净", f"{len(final_ids)} 个 profile, active={prev_profile}")
        else:
            record(
                FAIL,
                "回滚干净",
                f"残留={sorted(new_ids & final_ids)}, active={final.get('active_profile_id')}",
            )
    else:
        print("\n  (无需回滚)")

    # --- 汇总 ---
    n_fail = sum(1 for s, _, _ in results if s == FAIL)
    n_pass = sum(1 for s, _, _ in results if s == PASS)
    n_skip = sum(1 for s, _, _ in results if s == SKIP)
    print(f"\n=== 汇总: {n_pass} passed, {n_fail} failed, {n_skip} skipped ===")
    if n_fail:
        for s, name, detail in results:
            if s == FAIL:
                print(f"  FAILED: {name} -- {detail}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
