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

import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

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
    except Exception as exc:
        logger.debug("PyMuPDF unavailable; defaulting scan degree to 'mixed': %s", exc)
        return "mixed"

    try:
        doc = fitz.open(source_path)
    except Exception as exc:
        logger.debug("Could not open %s for scan-degree; defaulting to 'mixed': %s", source_path, exc)
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
    except Exception as exc:
        logger.debug("Scan-degree inference failed for %s; defaulting to 'mixed': %s", source_path, exc)
        return "mixed"
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _routing_ttls() -> Tuple[float, float]:
    """Readiness/scan cache TTLs from document-parsing settings.

    Falls back to the module defaults when settings are unavailable (e.g. a unit
    test process that never boots the settings service).
    """
    try:
        from deeptutor.services.config.runtime_settings import load_document_parsing_settings

        s = load_document_parsing_settings() or {}
        rttl = float(str(s.get("readiness_ttl") or _READINESS_TTL))
        sttl = float(str(s.get("scan_ttl") or _SCAN_TTL))
        return (rttl, sttl)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Falling back to default routing TTLs: %s", exc)
        return (_READINESS_TTL, _SCAN_TTL)


def _engine_ready(engine: str, *, ttl: float | None = None) -> bool:
    """Probe an engine's readiness with a short-TTL cache.

    ``ttl`` is the readiness cache window. Callers that already resolved it
    (``resolve_engine``) pass it in so we don't re-read settings per probe —
    ``load_document_parsing_settings`` is uncached upstream, so calling it
    inside this per-engine loop would re-read disk + re-normalize every engine
    slice on each probe.
    """
    now = time.time()
    cached = _READINESS_CACHE.get(engine)
    if ttl is None:
        ttl, _ = _routing_ttls()
    if cached is not None and now - cached[0] < ttl:
        return cached[1]
    try:
        from deeptutor.services.parsing.engines import get_parser

        parser = get_parser(engine)
        ok = bool(parser.is_ready(parser.resolve_config()).ready)
    except Exception as exc:
        logger.warning(
            "Readiness probe for engine %r failed; treating as not-ready: %s", engine, exc
        )
        ok = False
    _READINESS_CACHE[engine] = (now, ok)
    return ok


def _first_ready(candidates: Tuple[str, ...], ttl: float) -> Optional[str]:
    for eng in candidates:
        if _engine_ready(eng, ttl=ttl):
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

    # Resolve both TTLs once for the whole routing decision. The settings read
    # is uncached upstream (disk read + full 8-engine normalization per call),
    # so resolving it per-probe inside the loops below would be a real cost.
    rttl, sttl = _routing_ttls()

    # Scan-degree (cached per file).
    fhash = _file_hash(src)
    now = time.time()
    cached_degree = _SCAN_CACHE.get(fhash)
    if cached_degree is not None and now - cached_degree[0] < sttl:
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

    chosen = _first_ready(preferred, rttl)
    if chosen:
        return chosen

    # Nothing in the preferred pool is ready — try the other pool, then the
    # user's explicit fallback (which may be a vLLM engine they keep running).
    other = _LIGHT_ENGINES if degree != "text" else _OCR_ENGINES
    chosen = _first_ready(other, rttl)
    if chosen:
        return chosen
    return fallback
