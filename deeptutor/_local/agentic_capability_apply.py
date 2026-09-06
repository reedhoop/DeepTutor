"""Capability-fallback *application* logic for :class:`AgenticChatPipeline`.

The fork-specific routing *decision* is resolved by
``deeptutor._local.capability_fallback.resolve_for_turn``; this module only
*applies* the resulting decision onto a pipeline instance (swapping the active
LLM config, or recording OCR-extracted text for downstream substitution).

Keeping the application here — instead of inside the shared
``agentic_pipeline`` module — keeps that upstream file thin and rebase-friendly:
``agentic_pipeline`` only holds 3-4 line delegation stubs. The thin public
surface (``apply_llm_config`` / ``prepare_ocr_text_messages`` /
``apply_capability_fallback``) is intentionally importable so the pipeline's
instance-method stubs and tests keep calling the same names.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def apply_llm_config(pipeline: Any, cfg: "Any") -> None:
    """Reassign *pipeline*'s LLM config + derived attributes from *cfg*.

    Mirrors the attribute derivation in the pipeline's ``__init__``, including
    rebuilding ``pipeline._client_config`` — the snapshot
    ``_build_openai_client`` actually reads. A stale snapshot here would keep the
    HTTP client pointed at the primary model's endpoint/key even though the
    assignments below already changed ``pipeline.model`` (the request body would
    name the VLM while the client still targets the primary provider).
    """
    from deeptutor.runtime.agentic import LLMClientConfig

    pipeline.llm_config = cfg
    pipeline.binding = getattr(cfg, "binding", None) or "openai"
    pipeline.model = getattr(cfg, "model", None)
    pipeline.api_key = getattr(cfg, "api_key", None)
    pipeline.base_url = getattr(cfg, "base_url", None)
    pipeline.api_version = getattr(cfg, "api_version", None)
    pipeline.extra_headers = getattr(cfg, "extra_headers", None) or {}
    pipeline.reasoning_effort = getattr(cfg, "reasoning_effort", None)
    pipeline._client_config = LLMClientConfig(
        binding=pipeline.binding,
        model=pipeline.model,
        api_key=pipeline.api_key,
        base_url=pipeline.base_url,
        api_version=pipeline.api_version,
        extra_headers=pipeline.extra_headers or None,
        reasoning_effort=pipeline.reasoning_effort,
    )


def prepare_ocr_text_messages(
    messages: list[dict[str, Any]],
    ocr_text: str,
    language: "str | None",
) -> list[dict[str, Any]]:
    """Append OCR-extracted text to the last user message, replacing image parts.

    Used when the primary ``llm`` model cannot see images: the VLM/OCR path has
    already turned the attachments into text, so we send that text instead of
    image parts.
    """
    last_idx: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_idx = i
            break
    if last_idx is None:
        return messages
    msg = messages[last_idx]
    content = msg.get("content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        text = str(content)
    label = (
        "[图片OCR提取内容]"
        if language == "zh"
        else "[Image OCR extracted]"
    )
    text = f"{text}\n\n{label}\n{ocr_text}".strip()
    messages[last_idx] = {**msg, "content": text}
    return messages


def apply_capability_fallback(pipeline: Any, context: Any) -> None:
    """Stage-0 pre-flight: swap to a vision model or OCR-extract on an image gap.

    Resolves the right model/config for this turn when the user-attached content
    needs a capability the primary ``llm`` model lacks (today: vision). A
    ``vlm`` decision reassigns ``pipeline.llm_config`` so the whole turn
    transparently uses the vision model; an ``ocr_text`` decision records
    extracted text that replaces the image parts downstream.
    """
    from deeptutor._local.capability_fallback import resolve_for_turn

    pipeline._ocr_fallback_text = ""
    attachments = list(getattr(context, "attachments", None) or [])
    if not attachments:
        return
    decision = resolve_for_turn({"image"}, attachments)
    if decision.kind == "vlm" and decision.config is not None:
        apply_llm_config(pipeline, decision.config)
        logger.info(
            "capability fallback -> VLM model %s (%s)",
            decision.config.model,
            decision.note,
        )
    elif decision.kind == "ocr_text" and decision.extracted_text:
        pipeline._ocr_fallback_text = decision.extracted_text
        logger.info(
            "capability fallback -> OCR text (%d chars, %s)",
            len(decision.extracted_text),
            decision.note,
        )
