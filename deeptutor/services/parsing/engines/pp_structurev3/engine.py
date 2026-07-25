"""PP-StructureV3 engine adapter implementing the ``Parser`` protocol.

Wraps ``paddleocr.PPStructureV3`` — a fully local document-parsing pipeline
(layout detection + table/formula/chart/seal recognition). Unlike the vLLM
backends, it needs no external server; it downloads PaddleOCR model weights on
first run (gated by ``allow_local_model_download``).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .._versions import package_version
from .config import PPStructureV3Config, PPStructureV3Error, resolve_pp_structurev3_config

logger = logging.getLogger(__name__)

_SUPPORTED = frozenset({".pdf", ".png", ".jpg", ".jpeg"})

_MODEL_DIR_HINTS = ("paddleocr", "paddlex", "ppocr")


def _dir_nonempty(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except Exception:
        return False


def ppstructure_models_dir() -> Path:
    """Best-effort location of PaddleOCR's downloaded model weights.

    Resolved without importing paddleocr (heavy) so the readiness probe stays
    cheap — it mirrors where PaddleX/PaddleOCR cache models.
    """
    for env in ("PADDLEOCR_HOME", "PADDLE_HOME"):
        val = os.environ.get(env)
        if val:
            return Path(val).expanduser()
    return Path.home() / ".paddlex"


def _ppstructure_models_ready() -> bool:
    """Fail-closed check for downloaded PaddleOCR weights."""
    for env in ("PADDLEOCR_HOME", "PADDLE_HOME"):
        val = os.environ.get(env)
        if val and _dir_nonempty(Path(val).expanduser()):
            return True
    for base in (Path.home() / ".paddlex", Path.home() / ".paddleocr"):
        if _dir_nonempty(base):
            return True
    hf_home = os.environ.get("HF_HOME")
    hub = (
        Path(hf_home).expanduser() if hf_home else Path.home() / ".cache" / "huggingface"
    ) / "hub"
    try:
        if hub.is_dir():
            for child in hub.iterdir():
                name = child.name.lower()
                if (
                    child.is_dir()
                    and any(h in name for h in _MODEL_DIR_HINTS)
                    and any(child.iterdir())
                ):
                    return True
    except Exception:
        return False
    return False


class PPStructureV3Parser:
    name = "pp_structurev3"
    needs_local_models = True

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("paddleocr") is not None

    def resolve_config(self) -> PPStructureV3Config:
        return resolve_pp_structurev3_config()

    def supported_formats(self) -> frozenset[str]:
        return _SUPPORTED

    def signature(self, config: PPStructureV3Config) -> ParserSignature:
        return ParserSignature.build(
            "pp_structurev3",
            package_version("paddleocr"),
            {
                "device": config.device,
                "lang": config.lang,
                "use_formula_recognition": config.use_formula_recognition,
                "use_chart_recognition": config.use_chart_recognition,
                "use_seal_recognition": config.use_seal_recognition,
            },
        )

    def is_ready(self, config: PPStructureV3Config) -> ReadinessReport:
        if not self.is_available():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message=(
                    "PaddleOCR isn't installed "
                    "(pip install deeptutor[parse-pp-structurev3])."
                ),
            )
        if config.allow_local_model_download or _ppstructure_models_ready():
            return ReadinessReport(ready=True)
        return ReadinessReport(
            ready=False,
            reason="models_missing",
            message=(
                "PaddleOCR model weights aren't downloaded. Enable “Allow "
                "automatic model download” in Settings → Document Parsing, or "
                "they will be fetched on the first parse."
            ),
        )

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: PPStructureV3Config,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        if on_output:
            on_output(f"Running PP-StructureV3 on {Path(source_path).name}...")
        try:
            from paddleocr import PPStructureV3
        except Exception as exc:
            raise ParserError(
                "PP-StructureV3 requires paddleocr "
                "(pip install deeptutor[parse-pp-structurev3]): "
                f"{exc}"
            ) from exc
        # PPStructureV3 has no ``lang`` kwarg; map it to the official
        # ``text_recognition_model_name`` (en -> English OCR model).
        text_recognition_model_name = None
        if (config.lang or "ch").lower() in ("en", "english"):
            text_recognition_model_name = "en_PP-OCRv4_mobile_rec"
        try:
            pipeline = PPStructureV3(
                use_doc_orientation_classify=config.use_doc_orientation_classify,
                use_doc_unwarping=config.use_doc_unwarping,
                use_textline_orientation=config.use_textline_orientation,
                use_formula_recognition=config.use_formula_recognition,
                use_chart_recognition=config.use_chart_recognition,
                use_seal_recognition=config.use_seal_recognition,
                layout_threshold=config.layout_threshold,
                layout_nms=config.layout_nms,
                layout_unclip_ratio=config.layout_unclip_ratio,
                device=config.device,
                text_recognition_model_name=text_recognition_model_name,
            )
        except Exception as exc:
            raise ParserError(f"Failed to build PP-StructureV3 pipeline: {exc}") from exc

        try:
            output = pipeline.predict(str(source_path))
        except Exception as exc:
            raise ParserError(f"PP-StructureV3 predict failed: {exc}") from exc

        stem = Path(source_path).stem
        images_dir = Path(workdir) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        page_markdowns: list[str] = []
        try:
            for i, res in enumerate(output):
                page_dir = Path(workdir) / f"pp_sv3_page_{i + 1:04d}"
                page_dir.mkdir(parents=True, exist_ok=True)
                res.save_to_markdown(str(page_dir))
                md_files = sorted(page_dir.rglob("*.md"))
                md_text = md_files[0].read_text(encoding="utf-8") if md_files else ""
                # Hoist generated images into workdir/images so the
                # Markdown's relative `images/...` links resolve.
                for img in page_dir.rglob("*"):
                    if img.is_file() and img.suffix.lower() in {
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".webp",
                    }:
                        dest = images_dir / img.name
                        if dest.exists():
                            dest = images_dir / f"pp_sv3_{i + 1}_{img.name}"
                        shutil.copyfile(img, dest)
                page_markdowns.append(md_text.strip())
        except Exception as exc:
            raise ParserError(f"PP-StructureV3 output handling failed: {exc}") from exc

        final_md = _concatenate_markdown(pipeline, page_markdowns)
        (Path(workdir) / f"{stem}.md").write_text(final_md, encoding="utf-8")
        if on_output:
            on_output(f"Parsed {len(page_markdowns)} page(s) → {stem}.md")


def _concatenate_markdown(pipeline, pages_md: list[str]) -> str:
    """Join per-page Markdown, preferring PP-StructureV3's own concatenator."""
    concat = getattr(pipeline, "concatenate_markdown_pages", None)
    if callable(concat) and pages_md:
        try:
            return concat(pages_md)
        except Exception:
            pass
    return "\n\n".join(m for m in pages_md if m)


__all__ = ["PPStructureV3Parser"]
