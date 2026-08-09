"""Local overlay — default config slices + normalization for our engines.

Mirrors the upstream ``_DEFAULT_*_ENGINE`` slices and
``_normalize_*_engine`` methods, but kept entirely in this file so that
``runtime_settings.py`` only needs a small hook to merge them in.

This module must stay import-safe in any order: the engine-id constants are
*ours* and defined right here (not in ``runtime_settings``), and the only
upstream helpers we reuse (``_string`` / ``_coerce_bool`` /
``_coerce_clamped_int``) are imported lazily inside functions. Nothing at
module top level imports ``deeptutor`` — so a fresh process may import
``deeptutor._local`` first without tripping a circular import through the
``runtime_settings`` hook.
"""

from __future__ import annotations

import math
from typing import Any, Dict

# Our engine ids. These used to live in runtime_settings' shared constant
# block; keeping them here removes four diff hunks from the upstream file and
# breaks the module-top import cycle. Values are the persisted settings keys
# and must never change.
OVISOCR2 = "ovisocr2"
PADDLEOCR_VL = "paddleocr_vl"
PP_STRUCTUREV3 = "pp_structurev3"
CHANDRA = "chandra"

EXTERNAL_ENGINE_IDS = frozenset({OVISOCR2, PADDLEOCR_VL, PP_STRUCTUREV3, CHANDRA})


def _coerce_float(
    value: Any, default: float, low: float | None = None, high: float | None = None
) -> float:
    """Local copy of the float coercion helper (upstream modules each keep
    their own private ``_coerce_float``; we follow the same pattern so the
    upstream ``runtime_settings`` stays untouched)."""
    try:
        coerced = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if math.isnan(coerced):
        return default
    if low is not None and coerced < low:
        return low
    if high is not None and coerced > high:
        return high
    return coerced

# OvisOCR2 engine slice. End-to-end VLM parsing via a self-hosted vLLM
# server — no local model download, no pip package needed.
# Serve with ``vllm serve ATH-MaaS/OvisOCR2 --port 8200`` (vLLM >= 0.22.1).
# We default to :8200 instead of vLLM's stock :8000 — 8000 is far too
# commonly taken by other local dev servers.  max_tokens=16384 matches the
# official model-card sampling params.
_OVISOCR2_DEFAULT: Dict[str, Any] = {
    "api_base_url": "http://127.0.0.1:8200/v1",
    "api_token": "",
    "model_name": "ATH-MaaS/OvisOCR2",
    "image_dpi": 200,
    "max_tokens": 16384,
    "temperature": 0.0,
    "language": "auto",
    "timeout_s": 120,
    "max_concurrency": 4,
    "extra_prompt": "",
}

# PaddleOCR-VL engine slice. Same vLLM schema as OvisOCR2, plus
# ``enable_layout`` to toggle the official PP-DocLayoutV2 layout-assisted
# regional parsing (falls back to whole-page when unavailable).
_PADDLEOCR_VL_DEFAULT: Dict[str, Any] = {
    **_OVISOCR2_DEFAULT,
    "enable_layout": True,
    # Official PaddleOCR-VL-1.6 vLLM launcher (``paddleocr genai_server``)
    # listens on :8118 and serves ``PaddleOCR-VL-1.6-0.9B`` by default.
    "api_base_url": "http://127.0.0.1:8118/v1",
    "model_name": "PaddleOCR-VL-1.6-0.9B",
    # Regional/whole-page parsing needs far less headroom than OvisOCR2's
    # page-level 16384; keep the PaddleOCR-VL default at 4096.
    "max_tokens": 4096,
}

# PP-StructureV3 engine slice. Local PaddleOCR pipeline (like MinerU/Docling)
# — no vLLM server. Mirrors the official PPStructureV3 options.
_PP_STRUCTUREV3_DEFAULT: Dict[str, Any] = {
    "device": "gpu",
    "lang": "ch",
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": False,
    "use_formula_recognition": True,
    "use_chart_recognition": False,
    "use_seal_recognition": True,
    "layout_threshold": 0.5,
    "layout_nms": True,
    "layout_unclip_ratio": 1.0,
    "allow_local_model_download": False,
}

# Chandra engine slice. Same vLLM schema as OvisOCR2 (formula + handwriting +
# layout single model). Defaults to a dedicated port (:8230) so it never collides
# with the OvisOCR2 :8200 / PaddleOCR-VL :8118 vLLM endpoints. ``model_name`` is
# intentionally empty — the engine refuses to run until the user deploys Chandra's
# vLLM service and fills in the name + address in Settings.
_CHANDRA_DEFAULT: Dict[str, Any] = {
    **_OVISOCR2_DEFAULT,
    "api_base_url": "http://127.0.0.1:8230/v1",
    "model_name": "",
    # Unified single-model parsing needs page-level headroom like OvisOCR2.
    "max_tokens": 16384,
}

# Default per-engine config slices (formerly ``_DEFAULT_*_ENGINE``).
DEFAULT_EXTERNAL_ENGINE_SLICES: Dict[str, Dict[str, Any]] = {
    OVISOCR2: _OVISOCR2_DEFAULT,
    PADDLEOCR_VL: _PADDLEOCR_VL_DEFAULT,
    PP_STRUCTUREV3: _PP_STRUCTUREV3_DEFAULT,
    CHANDRA: _CHANDRA_DEFAULT,
}


def _norm_ovisocr2(
    settings: dict[str, Any],
    *,
    default_api_base_url: str = "http://127.0.0.1:8200/v1",
    default_model_name: str = "ATH-MaaS/OvisOCR2",
    default_max_tokens: int = 16384,
) -> Dict[str, Any]:
    """Normalize the OvisOCR2 / PaddleOCR-VL engine slice."""
    from deeptutor.services.config.runtime_settings import (
        _coerce_clamped_int,
        _string,
    )

    return {
        "api_base_url": _string(settings.get("api_base_url")).rstrip("/")
        or default_api_base_url,
        "api_token": _string(settings.get("api_token")),
        "model_name": _string(settings.get("model_name")) or default_model_name,
        "image_dpi": _coerce_clamped_int(settings.get("image_dpi"), 200, 72, 600),
        "max_tokens": _coerce_clamped_int(
            settings.get("max_tokens"), default_max_tokens, 256, 32768
        ),
        "temperature": _coerce_float(settings.get("temperature"), 0.0, 0.0, 2.0),
        "language": _string(settings.get("language")) or "auto",
        "timeout_s": _coerce_clamped_int(settings.get("timeout_s"), 120, 10, 600),
        "max_concurrency": _coerce_clamped_int(
            settings.get("max_concurrency"), 4, 1, 16
        ),
        "extra_prompt": _string(settings.get("extra_prompt")),
    }


def _norm_chandra(
    settings: dict[str, Any],
    *,
    default_api_base_url: str = "http://127.0.0.1:8230/v1",
    default_max_tokens: int = 16384,
) -> Dict[str, Any]:
    """Normalize the Chandra engine slice (vLLM, same shape as OvisOCR2)."""
    return _norm_ovisocr2(
        settings,
        default_api_base_url=default_api_base_url,
        default_model_name="",
        default_max_tokens=default_max_tokens,
    )


def normalize_external_engines(engines_in: dict[str, Any]) -> Dict[str, Any]:
    """Return the normalized slices for our three engines.

    Used by ``RuntimeSettingsService._normalize_document_parsing`` via a single
    ``engines_out.update(normalize_external_engines(engines_in))`` call, so the
    upstream method body only gains one line for all our engines.
    """
    from deeptutor.services.config.runtime_settings import (
        _coerce_bool,
        _string,
    )

    out: Dict[str, Any] = {}
    out[OVISOCR2] = _norm_ovisocr2(engines_in.get(OVISOCR2) or {})
    paddle = _norm_ovisocr2(
        engines_in.get(PADDLEOCR_VL) or {},
        default_api_base_url="http://127.0.0.1:8118/v1",
        default_model_name="PaddleOCR-VL-1.6-0.9B",
        default_max_tokens=4096,
    )
    paddle["enable_layout"] = _coerce_bool(
        (engines_in.get(PADDLEOCR_VL) or {}).get("enable_layout"), True
    )
    out[PADDLEOCR_VL] = paddle

    pp = engines_in.get(PP_STRUCTUREV3) or {}
    device = _string(pp.get("device")).lower()
    if device not in ("gpu", "cpu"):
        device = "gpu"
    out[PP_STRUCTUREV3] = {
        "device": device,
        "lang": _string(pp.get("lang")) or "ch",
        "use_doc_orientation_classify": _coerce_bool(
            pp.get("use_doc_orientation_classify"), False
        ),
        "use_doc_unwarping": _coerce_bool(pp.get("use_doc_unwarping"), False),
        "use_textline_orientation": _coerce_bool(
            pp.get("use_textline_orientation"), False
        ),
        "use_formula_recognition": _coerce_bool(
            pp.get("use_formula_recognition"), True
        ),
        "use_chart_recognition": _coerce_bool(pp.get("use_chart_recognition"), False),
        "use_seal_recognition": _coerce_bool(pp.get("use_seal_recognition"), True),
        "layout_threshold": _coerce_float(pp.get("layout_threshold"), 0.5, 0.0, 1.0),
        "layout_nms": _coerce_bool(pp.get("layout_nms"), True),
        "layout_unclip_ratio": _coerce_float(
            pp.get("layout_unclip_ratio"), 1.0, 0.0, 4.0
        ),
        "allow_local_model_download": _coerce_bool(
            pp.get("allow_local_model_download"), False
        ),
    }
    out[CHANDRA] = _norm_chandra(engines_in.get(CHANDRA) or {})
    return out


# ── Auto-routing (local overlay feature) ──────────────────────────────────
# When routing_mode == "auto", the ParseService picks the best engine *per
# document* instead of always using the single active engine. Defaults live
# here so the upstream ``runtime_settings`` stays untouched (only gains the
# routing_mode/fallback_engine keys via the runtime overlay). Manual is the
# default — it leaves parsing behaviour 100% unchanged.
VALID_ROUTING_MODES = ("manual", "auto")
DEFAULT_ROUTING_MODE = "manual"
DEFAULT_FALLBACK_ENGINE = ""

# Auto-routing cache TTLs (seconds). Kept here so they can be surfaced as
# document-parsing settings (see ``runtime_overlay``) instead of being hard-coded
# in ``engine_router``. Bounds: 1s (floor — a shorter window is meaningless) to
# 24h (ceiling — caches must eventually refresh).
DEFAULT_READINESS_TTL = 300.0
DEFAULT_SCAN_TTL = 3600.0


def normalize_routing(settings: dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize the routing_mode / fallback_engine settings.

    ``routing_mode`` is coerced to a known mode; ``fallback_engine`` must be a
    real engine id (from the upstream ``factory.KNOWN_ENGINES``) or it is
    dropped to "" (meaning "use the active engine"). The two cache TTLs are
    coerced to floats within a sane range.
    """
    from deeptutor.services.parsing.engines import factory

    raw_mode = str(settings.get("routing_mode") or DEFAULT_ROUTING_MODE).strip().lower()
    mode = raw_mode if raw_mode in VALID_ROUTING_MODES else DEFAULT_ROUTING_MODE
    raw_fb = str(settings.get("fallback_engine") or "").strip().lower()
    fallback = raw_fb if raw_fb in factory.KNOWN_ENGINES else DEFAULT_FALLBACK_ENGINE
    readiness_ttl = _coerce_float(settings.get("readiness_ttl"), DEFAULT_READINESS_TTL, 1.0, 86400.0)
    scan_ttl = _coerce_float(settings.get("scan_ttl"), DEFAULT_SCAN_TTL, 1.0, 86400.0)
    return {
        "routing_mode": mode,
        "fallback_engine": fallback,
        "readiness_ttl": readiness_ttl,
        "scan_ttl": scan_ttl,
    }
