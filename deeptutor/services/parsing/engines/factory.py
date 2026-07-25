"""Parser engine registry.

Maps an engine name to its adapter class, mirroring the RAG pipeline factory
(``services/rag/factory.py``). Engine modules import their third-party deps
lazily, so importing this registry is cheap and never fails on a missing
optional dependency.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any, Callable, Dict, List

from deeptutor.services.config.runtime_settings import (
    DOCUMENT_PARSING_ENGINE_DOCLING,
    DOCUMENT_PARSING_ENGINE_LITEPARSE,
    DOCUMENT_PARSING_ENGINE_MARKITDOWN,
    DOCUMENT_PARSING_ENGINE_MINERU,
    DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM,
    DOCUMENT_PARSING_ENGINE_TEXT_ONLY,
)

from ..base import Parser
from ..types import ParserError


def _mineru_class():
    from .mineru.engine import MinerUParser

    return MinerUParser


def _text_only_class():
    from .text_only.engine import TextOnlyParser

    return TextOnlyParser


def _docling_class():
    from .docling.engine import DoclingParser

    return DoclingParser


def _markitdown_class():
    from .markitdown.engine import MarkItDownParser

    return MarkItDownParser


def _liteparse_class():
    from .liteparse.engine import LiteParseParser

    return LiteParseParser


def _pymupdf4llm_class():
    from .pymupdf4llm.engine import PyMuPDF4LLMParser

    return PyMuPDF4LLMParser


# name -> zero-arg loader returning the engine class.
_ENGINE_LOADERS: Dict[str, Callable[[], Any]] = {
    DOCUMENT_PARSING_ENGINE_TEXT_ONLY: _text_only_class,
    DOCUMENT_PARSING_ENGINE_MINERU: _mineru_class,
    DOCUMENT_PARSING_ENGINE_DOCLING: _docling_class,
    DOCUMENT_PARSING_ENGINE_MARKITDOWN: _markitdown_class,
    DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM: _pymupdf4llm_class,
    DOCUMENT_PARSING_ENGINE_LITEPARSE: _liteparse_class,
}

KNOWN_ENGINES = frozenset(_ENGINE_LOADERS)

# Engine ids backed by a remote vLLM endpoint (no local pip package). Our
# overlay (deeptutor/_local) populates this; upstream leaves it empty.
_REMOTE_ENGINE_IDS: set[str] = set()

# Pip package names for version detection (engine_id → distribution name).
# Engines not listed here get ``None`` (built-in / remote / no local package).
# Map each pip-installable engine to its candidate PyPI package name(s),
# tried in order.  MinerU renamed its package from ``magic-pdf`` to ``mineru``
# (current), so both are listed as fallbacks.
_ENGINE_PACKAGES: Dict[str, List[str]] = {
    DOCUMENT_PARSING_ENGINE_MINERU: ["mineru", "magic-pdf"],
    DOCUMENT_PARSING_ENGINE_DOCLING: ["docling"],
    DOCUMENT_PARSING_ENGINE_MARKITDOWN: ["markitdown"],
}


def _engine_version(engine_id: str) -> str | None:
    """Return the installed pip version for *engine_id*, or ``None``.

    Returns ``"built-in"`` for engines that ship inside ``deeptutor`` itself
    (text_only, pymupdf4llm), ``"remote"`` for VLM engines that have no
    local package (ovisocr2, paddleocr_vl), or the actual ``<version>``
    string from ``importlib.metadata`` for pip-installable packages.
    """
    # Built-in engines (always available, no separate package).
    if engine_id in (
        DOCUMENT_PARSING_ENGINE_TEXT_ONLY,
        DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM,
    ):
        return "built-in"
    # VLM engines (remote vLLM endpoint, no local pip package).
    if engine_id in _REMOTE_ENGINE_IDS:
        return "remote"
    pkgs = _ENGINE_PACKAGES.get(engine_id)
    if pkgs:
        for pkg in pkgs:
            try:
                return importlib.metadata.version(pkg)
            except importlib.metadata.PackageNotFoundError:
                continue
    return None


# Static UI metadata (kept here so list_engines never imports engine deps).
_ENGINE_META: Dict[str, Dict[str, Any]] = {
    DOCUMENT_PARSING_ENGINE_TEXT_ONLY: {
        "name": "Text-only",
        "description": (
            "Built-in plain text extraction for PDF/Office/text files. No "
            "optional parser package, no model download, no layout structure."
        ),
        "needs_local_models": False,
    },
    DOCUMENT_PARSING_ENGINE_MINERU: {
        "name": "MinerU",
        "description": (
            "Highest-fidelity multimodal parsing (layout, tables, formulas). "
            "Local CLI downloads models, or use the hosted cloud API. Supports "
            "PDF, common images, DOCX, PPTX, and XLSX."
        ),
        "needs_local_models": True,
    },
    DOCUMENT_PARSING_ENGINE_DOCLING: {
        "name": "Docling",
        "description": (
            "Structured conversion across Docling's current document, image, e-book, "
            "email, audio/video, and data formats. Runs locally or against Docling "
            "Serve; some formats require system tools."
        ),
        "needs_local_models": True,
    },
    DOCUMENT_PARSING_ENGINE_MARKITDOWN: {
        "name": "markitdown",
        "description": (
            "Microsoft MarkItDown with every built-in format extra: PDF, modern "
            "Office, legacy XLS, e-books, mail, audio, images, notebooks, feeds, "
            "archives, and text. Markdown output; no local models."
        ),
        "needs_local_models": False,
    },
    DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM: {
        "name": "PyMuPDF4LLM",
        "description": (
            "Current CPU-only PyMuPDF layout/OCR conversion with image extraction. "
            "Supports PDF, XPS, e-books, SVG, text/Markdown, and PyMuPDF image "
            "formats; no CUDA or first-run model download."
        ),
        "needs_local_models": False,
    },
    DOCUMENT_PARSING_ENGINE_LITEPARSE: {
        "name": "LiteParse",
        "description": (
            "Fast Rust-backed parser from LlamaIndex for PDF, Office, OpenDocument, "
            "iWork, and images. Markdown output and optional image extraction; "
            "Office-family inputs require LibreOffice."
        ),
        "needs_local_models": False,
    },
    DOCUMENT_PARSING_ENGINE_TIKA: {
        "name": "Tika",
        "description": (
            "Remote Apache Tika 4 server with content-based detection for more than "
            "a thousand types, including custom server parsers. No local Python "
            "package; use the current full server image for OCR/system backends."
        ),
        "needs_local_models": False,
    },
}


def _normalize_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def get_parser(name: str) -> Parser:
    """Return an engine instance for ``name`` (raises if unknown)."""
    loader = _ENGINE_LOADERS.get(_normalize_name(name))
    if loader is None:
        raise ParserError(f"Unknown document-parsing engine: {name!r}")
    return loader()()


def is_engine_available(name: str) -> bool:
    loader = _ENGINE_LOADERS.get(_normalize_name(name))
    if loader is None:
        return False
    try:
        return bool(loader().is_available())
    except Exception:
        return False


# Engines whose ``is_ready()`` probes a remote vLLM endpoint — they never
# qualify as "ready" from a static probe; the live ``readiness`` dict from
# the settings endpoint is authoritative. Our added VLM engines, by stable id.
_VLM_ENGINE_IDS = frozenset({"ovisocr2", "paddleocr_vl"})


def _engine_ready(engine_id: str, available: bool, needs_local_models: bool) -> bool:
    """Best-effort readiness check for ``list_engines()``.

    - Engines that don't need local models **and** are not remote VLM engines
      are *ready* as soon as they are ``available`` (no heavyweight import).
    - Remote VLM engines always return ``False`` here — the settings page
      ``readiness`` dict covers the live server probe.
    - Only engines with ``needs_local_models=True`` trigger instantiation
      so we can run ``is_ready()`` (model-weight directory checks).
    """
    if not available:
        return False
    # VLM engines need a live vLLM server — skip static probe.
    if engine_id in _VLM_ENGINE_IDS:
        return False
    # Fast path: no local-model dependency → available implies ready.
    if not needs_local_models:
        return True
    loader = _ENGINE_LOADERS.get(_normalize_name(engine_id))
    if loader is None:
        return False
    try:
        # loader() returns the class; () instantiates it (same as get_parser).
        parser = loader()()
        config = parser.resolve_config()
        report = parser.is_ready(config)
        return report.ready
    except Exception:
        # Engine may raise on resolve_config / is_ready (e.g. missing
        # optional sub-deps).  Treat as "not ready" rather than crashing.
        return False


def list_engines() -> List[Dict[str, Any]]:
    """Describe engines for the settings UI picker.

    The ``ready`` field is a cheap static best-effort probe.  For engines
    that require local model weights it performs a lightweight filesystem
    check; for everything else it mirrors ``available``.  The live
    ``readiness`` dict (computed per-request by the settings endpoint) is
    authoritative for the detail panel.
    """
    import time

    # Cache for 60s: the probe below imports heavyweight model packages
    # (docling, mineru, paddleocr) and resolves configs — re-running it on
    # every request adds several seconds of latency to the settings page.
    _cached = getattr(list_engines, "_cache", None)
    _cached_ts = getattr(list_engines, "_ts", 0.0)
    if _cached is not None and (time.monotonic() - _cached_ts) < 60.0:
        return _cached

    out: List[Dict[str, Any]] = []
    for engine_id, meta in _ENGINE_META.items():
        avail = is_engine_available(engine_id)
        out.append(
            {
                "id": engine_id,
                "name": meta["name"],
                "description": meta["description"],
                "needs_local_models": meta["needs_local_models"],
                "available": avail,
                "version": _engine_version(engine_id),
                "ready": _engine_ready(engine_id, avail, meta["needs_local_models"]),
            }
        )
    list_engines._cache = out
    list_engines._ts = time.monotonic()
    return out


__all__ = ["KNOWN_ENGINES", "get_parser", "is_engine_available", "list_engines"]

# ── Local overlay (our custom engines) ──────────────────────────────────────
# Appended last so upstream edits above never conflict with our additions.
# Registers our engines into the registry via deeptutor/_local.
from deeptutor._local import apply_factory_overlay

apply_factory_overlay()
