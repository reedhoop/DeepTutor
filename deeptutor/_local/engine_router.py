"""Local overlay — per-document engine auto-routing.

When ``Document Parsing → routing_mode == "auto"``, the ParseService asks
this module to pick the best engine for a given file instead of always using
the single active engine.

Design notes (keep this file import-safe and dependency-light):
- No module-top ``deeptutor`` imports — ``factory`` / ``get_parser`` are
  imported lazily inside functions, so a fresh process may import
  ``deeptutor._local`` first without a circular-import cycle.
- Classification is cheap (samples a few pages with PyMuPDF) and the result is
  cached per file hash so repeated parses of the same PDF are free.
- Readiness is probed through each engine's ``is_ready()`` and cached with a
  short TTL, so a not-downloaded model isn't re-probed on every call.
- vLLM-backed engines (ovisocr2 / paddleocr_vl) are intentionally excluded
  from the auto candidate pool: they depend on an external server the user
  must start manually, so auto-routing never silently picks an engine that
  can't run. They remain reachable only via manual mode or ``fallback_engine``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Optional, Tuple

# Engines the auto-router may pick. OCR-capable engines handle scanned/image
# and mixed pages; lightweight engines are fine for text-native documents.
_OCR_ENGINES: Tuple[str, ...] = (
    "docling",
    "mineru",
    "pp_structurev3",
)
_LIGHT_ENGINES: Tuple[str, ...] = (
    "text_only",
    "pymupdf4llm",
    "markitdown",
)

# Readiness probe cache: engine id -> (timestamp, ready bool).
_READINESS_CACHE: Dict[str, Tuple[float, bool]] = {}
_READINESS_TTL = 300.0

# Per-file scan-degree cache: file hash -> (timestamp, degree).
_SCAN_CACHE: Dict[str, Tuple[float, str]] = {}
_SCAN_TTL = 3600.0


def _file_hash(source_path: Path) -> str:
    """Cheap, stable identity for a PDF file (size + mtime)."""
    try:
        st = source_path.stat()
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return str(source_path)


def _sample_scan_degree(source_path: Path, sample: int = 5) -> str:
    """Classify a PDF as 'image' (scanned), 'text' (native), or 'mixed'.

    Samples the first ``sample`` pages: if none have extractable text it's a
    scanned image; if all do it's text-native; otherwise it's mixed. Any
    failure defaults to 'mixed' (safest — assume OCR may be needed).
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return "mixed"

    try:
        doc = fitz.open(source_path)
    except Exception:
        return "mixed"

    try:
        n = max(1, min(sample, len(doc)))
        text_pages = 0
        for i in range(n):
            if doc[i].get_text().strip():
                text_pages += 1
        if text_pages == 0:
            return "image"
        if text_pages >= n:
            return "text"
        return "mixed"
    except Exception:
        return "mixed"
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _engine_ready(engine: str) -> bool:
    """Probe an engine's readiness with a short-TTL cache."""
    now = time.time()
    cached = _READINESS_CACHE.get(engine)
    if cached is not None and now - cached[0] < _READINESS_TTL:
        return cached[1]
    try:
        from deeptutor.services.parsing.engines import get_parser

        parser = get_parser(engine)
        ok = bool(parser.is_ready(parser.resolve_config()).ready)
    except Exception:
        ok = False
    _READINESS_CACHE[engine] = (now, ok)
    return ok


def _first_ready(candidates: Tuple[str, ...]) -> Optional[str]:
    for eng in candidates:
        if _engine_ready(eng):
            return eng
    return None


def resolve_engine(
    source_path: str | Path,
    *,
    fallback: str,
    routing_mode: str = "manual",
) -> str:
    """Pick the best engine for ``source_path`` under ``routing_mode``.

    Returns ``fallback`` (the active engine) when routing is disabled or no
    suitable engine is ready — so callers can use the result directly without
    re-checking. Readiness failures never raise; they just fall through.
    """
    if routing_mode != "auto":
        return fallback

    src = Path(source_path)
    if src.suffix.lower() not in (".pdf", ".pdfa", ".pdfx"):
        # Non-PDF (docx / images / markdown): let the active engine handle it
        # rather than spending a classification pass.
        return fallback

    # Scan-degree (cached per file).
    fhash = _file_hash(src)
    now = time.time()
    cached_degree = _SCAN_CACHE.get(fhash)
    if cached_degree is not None and now - cached_degree[0] < _SCAN_TTL:
        degree = cached_degree[1]
    else:
        degree = _sample_scan_degree(src)
        _SCAN_CACHE[fhash] = (now, degree)

    # Preferred pool by document type.
    preferred: Tuple[str, ...]
    if degree == "image":
        preferred = _OCR_ENGINES
    elif degree == "text":
        preferred = _LIGHT_ENGINES
    else:  # mixed
        preferred = _OCR_ENGINES + _LIGHT_ENGINES

    chosen = _first_ready(preferred)
    if chosen:
        return chosen

    # Nothing in the preferred pool is ready — try the other pool, then the
    # user's explicit fallback (which may be a vLLM engine they keep running).
    other = _LIGHT_ENGINES if degree != "text" else _OCR_ENGINES
    chosen = _first_ready(other)
    if chosen:
        return chosen
    return fallback
