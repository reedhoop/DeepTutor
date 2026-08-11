"""Question splitter for ER-12 ``auto_split`` — whole-page exercise image →
per-question dicts.

OCR-first implementation with **zero LLM dependency**:

1. Decode the base64 image into a temporary PNG.
2. OCR it with PP-StructureV3 (PaddleOCR layout analysis + text/table/formula
   recognition, outputs markdown) — falls back to bare ``PaddleOCR`` text
   lines, then to ``None`` (the caller keeps its 400 hint).
3. Split the OCR text into per-question blocks by question-number regex.
4. Shape each block into a ``ReviewQuestionIn``-compatible dict.

The LLM-structured enrichment (stem/options/answer/knowledge-point mapping)
is deliberately NOT part of phase-1: it would make the endpoint depend on a
live external model. Callers receive plain-text stems they can review/edit
before submitting; the variant retrieval + error-book write path in the
review router already handle plain stems.

Wired through ``exercise_review_router._split_questions_from_image``'s
pluggable hook (``from deeptutor._local.question_splitter import
split_questions``).
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Question-number prefixes found on printed exam papers:
#   "1."  "1、"  "1．"  "1)"  "（1）"  "(4)"  "第5题"  "①"
_QUESTION_RE = re.compile(
    r"^\s*(?:"
    r"(?:第)?\d{1,3}\s*[.、．)）]"  # 1. / 2、 / 3． / 4)
    r"|[(（]\d{1,3}[)）]"          # (4) / （4）
    r"|第\d{1,3}题"                # 第5题
    r")",
)
# Option lines inside a question block:  "A."  "B、"  "C．"  "D)"
_OPTION_RE = re.compile(r"^\s*[A-H]\s*[.、．)）]", re.MULTILINE)

# Exam-sheet furniture that is not question content (header/footer noise).
_NOISE_LINE_RE = re.compile(
    r"得分|评卷|密封线|装订线|学校|班级|姓名|考号|准考证|注意事项|答题卡|试卷|总分|"
    r"题号|监考|考生|座位号|Score|Name|Class|Seat|Exam|Total|Instructions|"
    r"Read the following|请将答案|答案写在",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry (matches the pluggable hook signature)
# ---------------------------------------------------------------------------


def split_questions(image_base64: str) -> Optional[list[dict[str, Any]]]:
    """Split a whole-page exercise image into per-question dicts.

    Returns ``None`` when the image can't be decoded or OCR'd (the router
    answers 400 with a hint). Each dict matches ``ReviewQuestionIn`` fields;
    ``stem`` is plain OCR text — callers can review/edit before submitting.
    """
    raw = _decode_image(image_base64)
    if not raw:
        return None
    text = ""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "paper.png"
        img_path.write_bytes(raw)
        text = _ocr_text(img_path)
    if not text.strip():
        logger.info("question splitter: OCR produced no text")
        return None
    blocks = _split_by_question(text)
    questions = _to_question_dicts(blocks)
    if not questions:
        logger.info("question splitter: no question blocks found in OCR text")
        return None
    logger.info("question splitter: %d questions from OCR (%d chars)", len(questions), len(text))
    return questions


# ---------------------------------------------------------------------------
# Image decoding
# ---------------------------------------------------------------------------


def _decode_image(image_base64: str) -> bytes | None:
    """Decode a base64 image, tolerating a ``data:image/...;base64,`` prefix."""
    payload = (image_base64 or "").strip()
    if "," in payload and payload.split(",", 1)[0].startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        logger.debug("question splitter: invalid base64 payload")
        return None
    return raw if raw else None


# ---------------------------------------------------------------------------
# OCR (PP-StructureV3 first, bare PaddleOCR as fallback)
# ---------------------------------------------------------------------------


def _ocr_text(image_path: Path) -> str:
    """OCR *image_path* to text. PP-StructureV3 markdown first (keeps table /
    formula structure), then plain PaddleOCR lines. Empty string if unusable.
    """
    text = _ocr_with_ppstructurev3(image_path)
    if text.strip():
        return text
    text = _ocr_with_paddleocr(image_path)
    return text or ""


def _ocr_with_ppstructurev3(image_path: Path) -> str:
    try:
        from paddleocr import PPStructureV3
    except Exception as exc:  # noqa: BLE001 — paddleocr not installed
        logger.debug("PP-StructureV3 not available: %s", exc)
        return ""
    try:
        pipeline = PPStructureV3(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            use_formula_recognition=True,
            use_chart_recognition=False,
            use_seal_recognition=False,
            device="cpu",
        )
        results = pipeline.predict(str(image_path))
        with tempfile.TemporaryDirectory() as td:
            md_chunks: list[str] = []
            for i, res in enumerate(results or []):
                page_dir = Path(td) / f"page_{i}"
                page_dir.mkdir(parents=True, exist_ok=True)
                res.save_to_markdown(str(page_dir))
                for md in sorted(page_dir.rglob("*.md")):
                    md_chunks.append(md.read_text(encoding="utf-8"))
        return "\n".join(md_chunks)
    except Exception as exc:  # noqa: BLE001 — model weights missing / CPU issue
        logger.debug("PP-StructureV3 OCR failed: %s", exc)
        return ""


def _ocr_with_paddleocr(image_path: Path) -> str:
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # noqa: BLE001
        logger.debug("PaddleOCR not available: %s", exc)
        return ""
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = ocr.ocr(str(image_path), cls=True)
        lines: list[str] = []
        for page in result or []:
            for item in page or []:
                if item and len(item) >= 2:
                    lines.append(str(item[1][0]))
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 — API version drift
        logger.debug("PaddleOCR OCR failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Question splitting (pure, unit-testable)
# ---------------------------------------------------------------------------


def _split_by_question(text: str) -> list[str]:
    """Split OCR text into per-question blocks by question-number lines.

    A line starting with a question number opens a new block; everything
    else accumulates into the current block. Noise lines (exam furniture)
    are dropped entirely.
    """
    blocks: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _NOISE_LINE_RE.search(line) and not _QUESTION_RE.match(line):
            continue  # header/footer furniture — not question content
        if _QUESTION_RE.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _strip_noise_block(block: str) -> str:
    """Compress a question block: drop noise lines, collapse blank runs."""
    kept: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _NOISE_LINE_RE.search(line) and not (_QUESTION_RE.match(line) or _OPTION_RE.match(line)):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _to_question_dicts(blocks: list[str]) -> list[dict[str, Any]]:
    """Shape split blocks into ``ReviewQuestionIn``-compatible dicts."""
    questions: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        stem = _strip_noise_block(block)
        if not stem:
            continue
        questions.append(
            {
                "id": f"q{i + 1}",
                "stem": stem,
                "options": [],
                "answer": "",
                "analysis": "",
                "error_type": "",
                "kp_id": "",
            }
        )
    return questions


__all__ = [
    "split_questions",
    "_split_by_question",
    "_to_question_dicts",
    "_decode_image",
]
