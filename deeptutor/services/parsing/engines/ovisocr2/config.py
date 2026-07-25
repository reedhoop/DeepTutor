"""Resolved OvisOCR2 VLM backend configuration.

Mirrors ``mineru/config.py``: a frozen dataclass that decouples the
persisted ``document_parsing.json`` engine slice from the parser
implementation.  The parser code never touches the storage shape
directly — it asks for an :class:`OvisOCR2Config` and gets validated,
ready-to-use values.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import get_runtime_settings_service
from ...types import ParserError


class OvisOCR2Error(ParserError):
    """Raised when an OvisOCR2 parse fails (vLLM unreachable, unexpected
    response, misconfiguration).  Carries a user-facing message."""


@dataclass(frozen=True)
class OvisOCR2Config:
    """Validated OvisOCR2 VLM parsing configuration.

    All fields map 1:1 to the engine slice in ``document_parsing.json``.
    ``api_token`` is intentionally named that way (not ``api_key``) so the
    settings payload's ``redacted`` auto-strips it before sending the slice
    to the frontend.
    """

    # Serve with ``vllm serve ATH-MaaS/OvisOCR2 --port 8200`` (vLLM >= 0.22.1);
    # we default to :8200 instead of vLLM's stock :8000 because 8000 is far
    # too commonly taken by other local dev servers.  max_tokens=16384 /
    # temperature=0.0 are the official model-card sampling params.
    api_base_url: str = "http://127.0.0.1:8200/v1"
    api_token: str = ""
    model_name: str = "ATH-MaaS/OvisOCR2"
    image_dpi: int = 200
    max_tokens: int = 16384
    temperature: float = 0.0
    language: str = "auto"
    timeout_s: int = 120
    max_concurrency: int = 4
    extra_prompt: str = ""


def resolve_ovisocr2_config() -> OvisOCR2Config:
    """Load the effective OvisOCR2 config from ``document_parsing.json``."""
    svc = get_runtime_settings_service()
    s = svc.load_document_parsing(include_process_overrides=True)["engines"]["ovisocr2"]
    return OvisOCR2Config(
        api_base_url=str(s.get("api_base_url") or "http://127.0.0.1:8200/v1"),
        api_token=str(s.get("api_token") or ""),
        model_name=str(s.get("model_name") or "ATH-MaaS/OvisOCR2"),
        image_dpi=int(s.get("image_dpi", 200)),
        max_tokens=int(s.get("max_tokens", 16384)),
        temperature=float(s.get("temperature", 0.0)),
        language=str(s.get("language") or "auto"),
        timeout_s=int(s.get("timeout_s", 120)),
        max_concurrency=int(s.get("max_concurrency", 4)),
        extra_prompt=str(s.get("extra_prompt") or ""),
    )


__all__ = ["OvisOCR2Config", "OvisOCR2Error", "resolve_ovisocr2_config"]
