"""Pipeline integration for the capability-fallback VLM swap.

Regression for a P1 where ``AgenticChatPipeline._apply_llm_config`` reassigned
``self.binding/model/api_key/base_url`` but left ``self._client_config`` — the
snapshot ``_build_openai_client`` actually reads — pointing at the primary
model. The swap therefore never took effect at the HTTP layer even though the
request body named the VLM.
"""

from __future__ import annotations

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.services.llm.config import LLMConfig


def test_apply_llm_config_rebuilds_client_config() -> None:
    pipeline = AgenticChatPipeline(language="en")
    vlm = LLMConfig(
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        api_key="sk-vlm-key",
        base_url="https://vlm.example.invalid/v1",
        effective_url="https://vlm.example.invalid/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
        extra_headers={"x-vlm": "1"},
        reasoning_effort=None,
    )

    pipeline._apply_llm_config(vlm)

    # The loose attrs swap…
    assert pipeline.model == "Qwen/Qwen2.5-VL-7B-Instruct"
    assert pipeline.base_url == "https://vlm.example.invalid/v1"
    assert pipeline.api_key == "sk-vlm-key"
    # …and, critically, so must the client snapshot that _build_openai_client reads.
    assert pipeline._client_config.base_url == "https://vlm.example.invalid/v1"
    assert pipeline._client_config.api_key == "sk-vlm-key"
    assert pipeline._client_config.model == "Qwen/Qwen2.5-VL-7B-Instruct"
    assert pipeline._client_config.binding == "openai"
    assert pipeline._client_config.extra_headers == {"x-vlm": "1"}
