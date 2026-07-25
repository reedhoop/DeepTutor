"""PaddleOCR-VL engine adapter implementing the ``Parser`` protocol.

Implements the official PaddleOCR-VL guidance: optional PP-DocLayoutV2
layout-assisted regional parsing (task prompts per region) with a whole-page
fallback.  The VLM itself runs on a self-hosted vLLM server; PP-DocLayoutV2
(when layout mode is enabled) runs locally via Paddle Inference.

Recommended PaddleOCR-VL serving (OpenAI-compatible /v1/chat/completions):

  # Official launcher (pre-configured perf tuning; listens on :8118):
  paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --backend vllm --port 8118

  # Or via Docker (NVIDIA GPU, CUDA >= 12.6):
  docker run --gpus all --network host \\
    ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-nvidia-gpu \\
    paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --host 0.0.0.0 --port 8118 --backend vllm

  # Raw vLLM (also works, but skips PaddleOCR's tuned defaults):
  vllm serve PaddlePaddle/PaddleOCR-VL-1.6 \\
    --trust-remote-code --max-num-batched-tokens 16384 \\
    --no-enable-prefix-caching --mm-processor-cache-gb 0

Set api_base_url=http://127.0.0.1:8118/v1 and model_name=PaddleOCR-VL-1.6-0.9B.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from ..ovisocr2.backend import probe_vllm
from .backend import parse_pdf_via_paddleocr_vl
from .config import PaddleOCR_VLConfig, resolve_paddleocr_vl_config


class PaddleOCR_VLParser:
    """PDF → Markdown via a self-hosted PaddleOCR-VL vLLM endpoint."""

    name = "paddleocr_vl"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    # ------------------------------------------------------------------
    # Parser protocol
    # ------------------------------------------------------------------

    def resolve_config(self) -> PaddleOCR_VLConfig:
        return resolve_paddleocr_vl_config()

    def supported_formats(self) -> frozenset[str]:
        return frozenset({".pdf"})

    def signature(self, config: PaddleOCR_VLConfig) -> ParserSignature:
        return ParserSignature.build(
            "paddleocr_vl",
            f"vllm:{config.model_name}",
            {
                "image_dpi": config.image_dpi,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "language": config.language,
                "extra_prompt": config.extra_prompt,
                "enable_layout": config.enable_layout,
            },
        )

    def is_ready(self, config: PaddleOCR_VLConfig) -> ReadinessReport:
        if not config.model_name:
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="Set the PaddleOCR-VL model name and vLLM address in "
                "Settings → Document Parsing.",
            )
        ok, msg = probe_vllm(config)  # type: ignore[arg-type]
        return (
            ReadinessReport(ready=True)
            if ok
            else ReadinessReport(ready=False, reason="not_configured", message=msg)
        )

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: PaddleOCR_VLConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        try:
            parse_pdf_via_paddleocr_vl(source_path, workdir, config=config, on_output=on_output)
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError(
                f"PaddleOCR-VL parse failed for {Path(source_path).name}: {exc}"
            ) from exc


__all__ = ["PaddleOCR_VLParser"]
