"""Chandra engine adapter implementing the ``Parser`` protocol.

Thin wrapper over end-to-end VLM parsing (formula + handwriting + layout, single
model) via a self-hosted vLLM server. Mirrors the OvisOCR2 adapter; the only
differences are the engine id, the default endpoint/port, and the empty default
model name (Chandra must be configured before use). The HTTP contract is the
same OpenAI-compatible vLLM protocol, so the backend is model-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .config import ChandraConfig, ChandraError, resolve_chandra_config
from .backend import probe_chandra_vllm, parse_pdf_via_chandra_vllm


class ChandraParser:
    """PDF → Markdown via a self-hosted Chandra vLLM endpoint."""

    name = "chandra"
    needs_local_models = False  # vLLM is an external service

    @classmethod
    def is_available(cls) -> bool:
        # No hard Python import — always "available". Readiness gates whether
        # a parse can actually run (vLLM reachable / model configured).
        return True

    # ------------------------------------------------------------------
    # Parser protocol
    # ------------------------------------------------------------------

    def resolve_config(self) -> ChandraConfig:
        return resolve_chandra_config()

    def supported_formats(self) -> frozenset[str]:
        return frozenset({".pdf"})

    def signature(self, config: ChandraConfig) -> ParserSignature:
        model = config.model_name or "unconfigured"
        return ParserSignature.build(
            "chandra",
            f"vllm:{model}",
            {
                "image_dpi": config.image_dpi,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "language": config.language,
                "extra_prompt": config.extra_prompt,
            },
        )

    def is_ready(self, config: ChandraConfig) -> ReadinessReport:
        if not config.model_name:
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="Set the Chandra model name and vLLM address in "
                "Settings → Document Parsing before using this engine.",
            )
        ok, msg = probe_chandra_vllm(config)
        if ok:
            return ReadinessReport(ready=True)
        return ReadinessReport(ready=False, reason="not_configured", message=msg)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: ChandraConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        try:
            parse_pdf_via_chandra_vllm(
                source_path, workdir, config=config, on_output=on_output
            )
        except ParserError:
            raise
        except Exception as exc:
            raise ChandraError(
                f"Chandra parse failed for {Path(source_path).name}: {exc}"
            ) from exc


__all__ = ["ChandraParser"]
