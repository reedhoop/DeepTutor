"""Resolved PP-StructureV3 local pipeline configuration.

Schema follows the official ``paddleocr.PPStructureV3`` options.  The engine is
local (no vLLM server) — it downloads PaddleOCR model weights on first run,
gated by ``allow_local_model_download``.

Note: ``PPStructureV3`` has no ``lang`` parameter; the ``lang`` config field is
mapped to ``text_recognition_model_name`` (``en`` -> ``en_PP-OCRv4_mobile_rec``,
anything else -> default Chinese-English model).  ``use_chart_recognition``
defaults to ``False`` to match the official pipeline default.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import get_runtime_settings_service
from ...types import ParserError


class PPStructureV3Error(ParserError):
    """Raised when a PP-StructureV3 parse fails."""


@dataclass(frozen=True)
class PPStructureV3Config:
    device: str = "gpu"
    lang: str = "ch"
    use_doc_orientation_classify: bool = False
    use_doc_unwarping: bool = False
    use_textline_orientation: bool = False
    use_formula_recognition: bool = True
    use_chart_recognition: bool = False  # official PP-StructureV3 default
    use_seal_recognition: bool = True
    layout_threshold: float = 0.5
    layout_nms: bool = True
    layout_unclip_ratio: float = 1.0
    allow_local_model_download: bool = False


def resolve_pp_structurev3_config() -> PPStructureV3Config:
    svc = get_runtime_settings_service()
    s = svc.load_document_parsing(include_process_overrides=True)["engines"]["pp_structurev3"]
    return PPStructureV3Config(
        device=str(s.get("device") or "gpu").lower(),
        lang=str(s.get("lang") or "ch"),
        use_doc_orientation_classify=bool(s.get("use_doc_orientation_classify", False)),
        use_doc_unwarping=bool(s.get("use_doc_unwarping", False)),
        use_textline_orientation=bool(s.get("use_textline_orientation", False)),
        use_formula_recognition=bool(s.get("use_formula_recognition", True)),
        use_chart_recognition=bool(s.get("use_chart_recognition", False)),
        use_seal_recognition=bool(s.get("use_seal_recognition", True)),
        layout_threshold=float(s.get("layout_threshold", 0.5)),
        layout_nms=bool(s.get("layout_nms", True)),
        layout_unclip_ratio=float(s.get("layout_unclip_ratio", 1.0)),
        allow_local_model_download=bool(s.get("allow_local_model_download", False)),
    )


__all__ = ["PPStructureV3Config", "PPStructureV3Error", "resolve_pp_structurev3_config"]
