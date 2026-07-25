"""Resolved PaddleOCR-VL VLM backend configuration.

Schema is identical to OvisOCR2 — both are vLLM-backed VLM engines.
Only the configuration key differs (``engines.paddleocr_vl``).
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import get_runtime_settings_service
from ...types import ParserError


class PaddleOCR_VLError(ParserError):
    """Raised when a PaddleOCR-VL parse fails."""


@dataclass(frozen=True)
class PaddleOCR_VLConfig:
    api_base_url: str = "http://127.0.0.1:8118/v1"
    api_token: str = ""
    model_name: str = "PaddleOCR-VL-1.6-0.9B"
    image_dpi: int = 200
    max_tokens: int = 4096
    temperature: float = 0.0
    language: str = "auto"
    timeout_s: int = 120
    max_concurrency: int = 4
    extra_prompt: str = ""
    # When True (default) and the local PP-DocLayoutV2 model is available, parse
    # region-by-region with the official task prompts; otherwise fall back to a
    # single whole-page call. Set False to always use whole-page mode.
    enable_layout: bool = True


def resolve_paddleocr_vl_config() -> PaddleOCR_VLConfig:
    svc = get_runtime_settings_service()
    s = svc.load_document_parsing(include_process_overrides=True)["engines"]["paddleocr_vl"]
    return PaddleOCR_VLConfig(
        api_base_url=str(s.get("api_base_url") or "http://127.0.0.1:8118/v1"),
        api_token=str(s.get("api_token") or ""),
        model_name=str(s.get("model_name") or "PaddleOCR-VL-1.6-0.9B"),
        image_dpi=int(s.get("image_dpi", 200)),
        max_tokens=int(s.get("max_tokens", 4096)),
        temperature=float(s.get("temperature", 0.0)),
        language=str(s.get("language") or "auto"),
        timeout_s=int(s.get("timeout_s", 120)),
        max_concurrency=int(s.get("max_concurrency", 4)),
        extra_prompt=str(s.get("extra_prompt") or ""),
        enable_layout=bool(s.get("enable_layout", True)),
    )


__all__ = ["PaddleOCR_VLConfig", "PaddleOCR_VLError", "resolve_paddleocr_vl_config"]
