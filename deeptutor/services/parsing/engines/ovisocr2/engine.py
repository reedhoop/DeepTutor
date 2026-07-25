"""OvisOCR2 engine adapter implementing the ``Parser`` protocol.

Thin wrapper over end-to-end VLM parsing via a self-hosted vLLM server.
Maps the ``Parser`` contract (``source_path`` in, write ``<stem>.md`` +
optional ``images/`` into ``workdir``) to vLLM HTTP calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .config import OvisOCR2Config, resolve_ovisocr2_config


class OvisOCR2Parser:
    """PDF → Markdown via a self-hosted OvisOCR2 vLLM endpoint."""

    name = "ovisocr2"
    needs_local_models = False  # vLLM is an external service

    @classmethod
    def is_available(cls) -> bool:
        # No hard Python import — always "available".  Readiness gates whether
        # a parse can actually run (vLLM reachable / model configured).
        return True

    # ------------------------------------------------------------------
    # Parser protocol
    # ------------------------------------------------------------------

    def resolve_config(self) -> OvisOCR2Config:
        return resolve_ovisocr2_config()

    def supported_formats(self) -> frozenset[str]:
        return frozenset({".pdf"})

    def signature(self, config: OvisOCR2Config) -> ParserSignature:
        return ParserSignature.build(
            "ovisocr2",
            f"vllm:{config.model_name}",
            {
                "image_dpi": config.image_dpi,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "language": config.language,
                "extra_prompt": config.extra_prompt,
            },
        )

    def is_ready(self, config: OvisOCR2Config) -> ReadinessReport:
        if not config.model_name:
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="Set the OvisOCR2 model name and vLLM address in "
                "Settings → Document Parsing.",
            )
        from .backend import probe_vllm

        ok, msg = probe_vllm(config)
        if ok:
            return ReadinessReport(ready=True)
        return ReadinessReport(ready=False, reason="not_configured", message=msg)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: OvisOCR2Config,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        from .backend import parse_pdf_via_vllm

        try:
            parse_pdf_via_vllm(source_path, workdir, config=config, on_output=on_output)
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError(
                f"OvisOCR2 parse failed for {Path(source_path).name}: {exc}"
            ) from exc


__all__ = ["OvisOCR2Parser"]
