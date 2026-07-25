"""Local overlay — registers our custom document-parsing engines.

This package holds *all* of our custom-engine logic so that the upstream
``factory.py`` / ``runtime_settings.py`` only need a tiny, stable hook at the
end of the module. When we rebase onto an active upstream, upstream's edits to
the registry dicts / default slices never collide with ours: our data lives
here, and the hook is an additive call that upstream will never touch.

Lifecycle:
  * ``factory.py`` (end of module)  -> ``apply_factory_overlay()``
  * ``runtime_settings.py`` (end)  -> ``apply_runtime_overlay(globals())``

Both are idempotent and only *add* to upstream structures.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

# ---------------------------------------------------------------------------
# Lazy loader definitions (formerly inline in factory.py). Each returns the
# parser class for one of our engines; the engine modules themselves remain
# under deeptutor/services/parsing/engines/<name>/ as independent new files.
# ---------------------------------------------------------------------------


def _ovisocr2_class() -> Callable[[], Any]:
    from deeptutor.services.parsing.engines.ovisocr2.engine import OvisOCR2Parser

    return OvisOCR2Parser


def _paddleocr_vl_class() -> Callable[[], Any]:
    from deeptutor.services.parsing.engines.paddleocr_vl.engine import PaddleOCR_VLParser

    return PaddleOCR_VLParser


def _pp_structurev3_class() -> Callable[[], Any]:
    from deeptutor.services.parsing.engines.pp_structurev3.engine import PPStructureV3Parser

    return PPStructureV3Parser


# Static UI metadata (formerly inline in factory._ENGINE_META). Kept here so
# list_engines() never has to import our engine dependencies.
_ENGINE_META: Dict[str, Dict[str, Any]] = {
    "ovisocr2": {
        "name": "OvisOCR2",
        "description": (
            "End-to-end VLM parsing (layout, tables, formulas) via a "
            "self-hosted vLLM server. Single-model, image-to-Markdown. "
            "PDF only; no local model download."
        ),
        "needs_local_models": False,
    },
    "paddleocr_vl": {
        "name": "PaddleOCR-VL",
        "description": (
            "End-to-end VLM parsing via a self-hosted vLLM server. "
            "109-language support, handwriting, historical documents. "
            "PDF only; no local model download."
        ),
        "needs_local_models": False,
    },
    "pp_structurev3": {
        "name": "PP-StructureV3",
        "description": (
            "PaddleOCR's local document-parsing pipeline (layout, tables, "
            "formulas, charts, seals). Runs entirely on-device via Paddle "
            "Inference — no vLLM server. Best fidelity for Chinese / complex "
            "layouts; downloads PaddleOCR model weights on first run."
        ),
        "needs_local_models": True,
    },
}


def apply_factory_overlay() -> None:
    """Merge our engines into the upstream factory registry.

    Must run after the upstream module body has defined ``_ENGINE_LOADERS``,
    ``_ENGINE_META``, ``_ENGINE_PACKAGES``, ``_REMOTE_ENGINE_IDS`` and
    ``KNOWN_ENGINES``. Importing factory lazily avoids a circular import
    (factory imports this module at its own end).
    """
    from deeptutor.services.parsing.engines import factory as _f

    from deeptutor._local.engine_defaults import (
        OVISOCR2,
        PADDLEOCR_VL,
        PP_STRUCTUREV3,
    )

    _f._ENGINE_LOADERS.update(
        {
            OVISOCR2: _ovisocr2_class,
            PADDLEOCR_VL: _paddleocr_vl_class,
            PP_STRUCTUREV3: _pp_structurev3_class,
        }
    )
    _f._ENGINE_META.update(_ENGINE_META)
    # version detection: PP-StructureV3 ships as the ``paddleocr`` pip package.
    _f._ENGINE_PACKAGES.setdefault(PP_STRUCTUREV3, ["paddleocr"])
    # VLM engines are remote vLLM endpoints with no local pip package.
    _f._REMOTE_ENGINE_IDS.update({OVISOCR2, PADDLEOCR_VL})
    # KNOWN_ENGINES was computed at import time, before this hook ran.
    _f.KNOWN_ENGINES = frozenset(_f._ENGINE_LOADERS)
