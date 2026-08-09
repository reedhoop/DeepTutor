"""Resolved Chandra VLM backend configuration.

Mirrors ``ovisocr2/config.py``: a frozen dataclass that decouples the persisted
``document_parsing.json`` engine slice from the parser implementation. The parser
code never touches the storage shape directly — it asks for a
:class:`ChandraConfig` and gets validated, ready-to-use values.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import get_runtime_settings_service
from ...types import ParserError


class ChandraError(ParserError):
    """Raised when a Chandra parse fails (vLLM unreachable, unexpected response,
    misconfiguration). Carries a user-facing message."""


@dataclass(frozen=True)
class ChandraConfig:
    """Validated Chandra VLM parsing configuration.

    All fields map 1:1 to the engine slice in ``document_parsing.json``.

    ``api_token`` is intentionally named that way (not ``api_key``) so the
    settings payload's ``redacted`` auto-strips it before sending the slice to
    the frontend.

    ``model_name`` is empty by default: Chandra is a self-hosted vLLM service the
    user must deploy; the engine refuses to run until a real model name + address
    are configured (see :meth:`ChandraParser.is_ready`).
    """

    # Deploy with e.g. ``vllm serve <chandra-model-id> --port 8230`` (port chosen
    # distinct from the OvisOCR2 :8200 / PaddleOCR-VL :8118 vLLM endpoints).
    api_base_url: str = "http://127.0.0.1:8230/v1"
    api_token: str = ""
    model_name: str = ""
    image_dpi: int = 200
    max_tokens: int = 16384
    temperature: float = 0.0
    language: str = "auto"
    timeout_s: int = 120
    max_concurrency: int = 4
    extra_prompt: str = ""


def resolve_chandra_config() -> ChandraConfig:
    """Load the effective Chandra config from ``document_parsing.json``."""
    svc = get_runtime_settings_service()
    s = svc.load_document_parsing(include_process_overrides=True)["engines"]["chandra"]
    return ChandraConfig(
        api_base_url=str(s.get("api_base_url") or "http://127.0.0.1:8230/v1"),
        api_token=str(s.get("api_token") or ""),
        model_name=str(s.get("model_name") or ""),
        image_dpi=int(s.get("image_dpi", 200)),
        max_tokens=int(s.get("max_tokens", 16384)),
        temperature=float(s.get("temperature", 0.0)),
        language=str(s.get("language") or "auto"),
        timeout_s=int(s.get("timeout_s", 120)),
        max_concurrency=int(s.get("max_concurrency", 4)),
        extra_prompt=str(s.get("extra_prompt") or ""),
    )


__all__ = ["ChandraConfig", "ChandraError", "resolve_chandra_config"]
