"""Educational LLM presets (ER-3).

Ready-to-use LLM provider profiles for common education scenarios. The
settings panel surfaces these as a "one-click select" so an administrator can
instantiate a complete, working profile — provider binding, base URL and model
— without hand-filling every field.

This module is part of the ``deeptutor._local`` overlay: it holds the preset
*data* only. The serving router lives in ``llm_presets_router.py`` and is mounted
by ``deeptutor.api.main`` under ``/api/v1/settings`` (with the settings router's
``_auth`` dependency), so no upstream file is edited.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

# Each preset is a complete LLM catalog profile (minus the user's API key).
# ``binding`` is always "openai" because all three providers expose an
# OpenAI-compatible chat completions endpoint.
EDUCATIONAL_LLM_PRESETS: list[dict[str, Any]] = [
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek-Reasoner",
        "description": (
            "DeepSeek 深度推理模型，擅长数学/物理的多步推导、解题与讲题。"
            "适合需要链式思考的 K12 理科场景。"
        ),
        "binding": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "models": [
            {
                "model": "deepseek-reasoner",
                "name": "DeepSeek-Reasoner",
                "context_window": "64000",
            },
        ],
    },
    {
        "id": "qwen-math-plus",
        "name": "Qwen-Math-Plus",
        "description": (
            "阿里通义千问数学增强模型（DashScope 兼容模式），擅长 K12 "
            "数学题求解、步骤讲解与验算。"
        ),
        "binding": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "models": [
            {
                "model": "qwen-math-plus",
                "name": "Qwen Math Plus",
                "context_window": "32768",
            },
        ],
    },
    {
        "id": "qwen2.5",
        "name": "Qwen2.5-Instruct",
        "description": (
            "通义千问 Qwen2.5 通用指令模型（DashScope 兼容模式），适合语文/"
            "英语/综合问答、写作与代码辅助。"
        ),
        "binding": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "models": [
            {
                "model": "qwen2.5-72b-instruct",
                "name": "Qwen2.5-72B-Instruct",
                "context_window": "131072",
            },
        ],
    },
]


def get_educational_llm_presets() -> list[dict[str, Any]]:
    """Return the educational LLM presets as deep copies (no shared mutable state)."""
    return copy.deepcopy(EDUCATIONAL_LLM_PRESETS)


def build_profile_from_preset(preset_id: str) -> dict[str, Any] | None:
    """Build a catalog-ready LLM profile dict from a preset id.

    Fresh UUIDs are generated so repeated applications never collide. Returns
    ``None`` when the id is unknown.
    """
    preset = next(
        (p for p in EDUCATIONAL_LLM_PRESETS if p["id"] == preset_id), None
    )
    if preset is None:
        return None

    profile_id = f"llm-profile-{uuid.uuid4().hex[:8]}"
    models = [
        {
            "id": f"llm-model-{uuid.uuid4().hex[:8]}",
            "name": m.get("name", m["model"]),
            "model": m["model"],
            "context_window": m.get("context_window", ""),
        }
        for m in preset["models"]
    ]
    return {
        "id": profile_id,
        "name": preset["name"],
        "binding": preset["binding"],
        "base_url": preset["base_url"],
        "api_key": preset["api_key"],
        "api_version": "",
        "extra_headers": {},
        "models": models,
    }
