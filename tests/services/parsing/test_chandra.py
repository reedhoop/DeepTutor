"""Unit tests for the ER-5 Chandra engine registration and auto-routing.

Covers the full registration chain (engine_defaults → engines_registry →
factory), config normalization, readiness gating, list_engines surface, and
the engine_router preference for deployed Chandra on image/mixed layouts.
"""

from __future__ import annotations

import pytest

from deeptutor.services.parsing.engines import factory
from deeptutor.services.parsing.base import ReadinessReport
from deeptutor.services.parsing.engines.chandra.config import ChandraConfig
from deeptutor.services.parsing.engines.chandra.engine import ChandraParser
from deeptutor.services.parsing.engines.chandra import engine as chandra_engine

import deeptutor._local.engine_router as router
import deeptutor._local.engine_defaults as engine_defaults


# ---------------------------------------------------------------------------
# Registration chain
# ---------------------------------------------------------------------------


def test_chandra_registered_in_factory_registry() -> None:
    assert "chandra" in factory.KNOWN_ENGINES
    assert "chandra" in factory._REMOTE_ENGINE_IDS
    assert "chandra" in factory._VLM_ENGINE_IDS
    assert "chandra" in engine_defaults.EXTERNAL_ENGINE_IDS
    assert "chandra" in engine_defaults.DEFAULT_EXTERNAL_ENGINE_SLICES


def test_get_parser_returns_chandra_parser() -> None:
    parser = factory.get_parser("chandra")
    assert isinstance(parser, ChandraParser)
    assert parser.name == "chandra"
    assert parser.needs_local_models is False
    assert parser.is_available() is True
    assert parser.supported_formats() == frozenset({".pdf"})


def test_chandra_meta_in_engines_registry() -> None:
    from deeptutor._local.engines_registry import _ENGINE_META

    meta = _ENGINE_META["chandra"]
    assert meta["name"] == "Chandra"
    assert meta["needs_local_models"] is False
    assert "formula + handwriting + layout" in meta["description"]


# ---------------------------------------------------------------------------
# Config normalization (engine_defaults.normalize_external_engines)
# ---------------------------------------------------------------------------


def test_chandra_normalize_defaults() -> None:
    norm = engine_defaults.normalize_external_engines({})
    c = norm["chandra"]
    assert c["api_base_url"] == "http://127.0.0.1:8230/v1"
    # Empty model name is the ER-5 contract: refuse to run until configured.
    assert c["model_name"] == ""
    assert c["max_tokens"] == 16384
    assert c["temperature"] == 0.0
    assert c["language"] == "auto"
    assert c["image_dpi"] == 200


def test_chandra_normalize_preserves_overrides() -> None:
    norm = engine_defaults.normalize_external_engines(
        {
            "chandra": {
                "api_base_url": "http://127.0.0.1:9999/v1/",
                "model_name": "HKU/Chandra-OCR",
                "language": "zh",
                "extra_prompt": "Keep math notation as LaTeX.",
                "max_tokens": 8192,
            }
        }
    )
    c = norm["chandra"]
    # Trailing slash is stripped by normalization.
    assert c["api_base_url"] == "http://127.0.0.1:9999/v1"
    assert c["model_name"] == "HKU/Chandra-OCR"
    assert c["language"] == "zh"
    assert c["extra_prompt"] == "Keep math notation as LaTeX."
    assert c["max_tokens"] == 8192


def test_chandra_config_defaults_match_engine_slice() -> None:
    cfg = ChandraConfig()
    assert cfg.api_base_url == "http://127.0.0.1:8230/v1"
    assert cfg.model_name == ""
    assert cfg.max_tokens == 16384
    assert cfg.image_dpi == 200
    assert cfg.temperature == 0.0
    assert cfg.language == "auto"
    assert cfg.timeout_s == 120
    assert cfg.max_concurrency == 4
    assert cfg.extra_prompt == ""


# ---------------------------------------------------------------------------
# Readiness (is_ready / probe)
# ---------------------------------------------------------------------------


def test_chandra_is_ready_unconfigured() -> None:
    parser = ChandraParser()
    report = parser.is_ready(ChandraConfig())
    assert report.ready is False
    assert report.reason == "not_configured"
    assert "model name" in report.message


def test_chandra_is_ready_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # engine.py imports probe_chandra_vllm into its own namespace
    # (``from .backend import probe_chandra_vllm``) — patch that module so the
    # real vLLM endpoint is never contacted.
    monkeypatch.setattr(
        chandra_engine, "probe_chandra_vllm", lambda config: (True, "Ready to parse.")
    )
    report = ChandraParser().is_ready(ChandraConfig(model_name="HKU/Chandra-OCR"))
    assert report.ready is True


def test_chandra_is_ready_probe_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chandra_engine, "probe_chandra_vllm", lambda config: (False, "vLLM down")
    )
    report = ChandraParser().is_ready(ChandraConfig(model_name="HKU/Chandra-OCR"))
    assert report.ready is False
    assert report.reason == "not_configured"
    assert "vLLM down" in report.message


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


def test_chandra_signature_tracks_config() -> None:
    parser = ChandraParser()
    unconfigured = parser.signature(ChandraConfig()).hash()
    configured = parser.signature(ChandraConfig(model_name="HKU/Chandra-OCR")).hash()
    tweaked = parser.signature(
        ChandraConfig(model_name="HKU/Chandra-OCR", extra_prompt="Keep LaTeX.")
    ).hash()
    assert unconfigured != configured
    assert configured != tweaked
    assert "unconfigured" in parser.signature(ChandraConfig()).engine_version
    assert "vllm:HKU/Chandra-OCR" in parser.signature(
        ChandraConfig(model_name="HKU/Chandra-OCR")
    ).engine_version


# ---------------------------------------------------------------------------
# list_engines surface
# ---------------------------------------------------------------------------


def test_chandra_list_engines_entry() -> None:
    factory.list_engines._cache = None
    factory.list_engines._ts = 0.0
    engines = {entry["id"]: entry for entry in factory.list_engines()}
    ce = engines["chandra"]
    assert ce["name"] == "Chandra"
    assert ce["available"] is True
    assert ce["needs_local_models"] is False
    assert ce["version"] == "remote"
    # Static probe stays False for remote VLM engines; the settings endpoint's
    # live readiness dict is authoritative.
    assert ce["ready"] is False


# ---------------------------------------------------------------------------
# engine_router: deployed Chandra preferred for image/mixed only
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_router_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every router test with empty caches so monkeypatched scan-degree
    and readiness probes are actually exercised."""
    monkeypatch.setattr(router, "_READINESS_CACHE", {})
    monkeypatch.setattr(router, "_SCAN_CACHE", {})


def _deploy_chandra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a deployed Chandra vLLM endpoint (readiness probe succeeds)."""
    monkeypatch.setattr(
        ChandraParser,
        "is_ready",
        lambda self, cfg: ReadinessReport(ready=True),
    )


def test_router_prefers_deployed_chandra_for_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deploy_chandra(monkeypatch)
    monkeypatch.setattr(router, "_sample_scan_degree", lambda *a, **k: "image")
    assert (
        router.resolve_engine("a.pdf", fallback="docling", routing_mode="auto")
        == "chandra"
    )


def test_router_prefers_deployed_chandra_for_mixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deploy_chandra(monkeypatch)
    monkeypatch.setattr(router, "_sample_scan_degree", lambda *a, **k: "mixed")
    assert (
        router.resolve_engine("a.pdf", fallback="docling", routing_mode="auto")
        == "chandra"
    )


def test_router_skips_chandra_for_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _deploy_chandra(monkeypatch)
    monkeypatch.setattr(router, "_sample_scan_degree", lambda *a, **k: "text")
    result = router.resolve_engine("a.pdf", fallback="docling", routing_mode="auto")
    # Chandra is only preferred for image/mixed layouts; text-native docs keep
    # the existing light-engine pool.
    assert result != "chandra"


def test_router_never_picks_undeployed_chandra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Nothing ready (including chandra) → falls through to the fallback engine.
    monkeypatch.setattr(
        router, "_engine_ready", lambda engine, ttl=None: False
    )
    monkeypatch.setattr(router, "_sample_scan_degree", lambda *a, **k: "mixed")
    result = router.resolve_engine("a.pdf", fallback="docling", routing_mode="auto")
    assert result == "docling"
    assert result != "chandra"


def test_router_manual_mode_returns_fallback() -> None:
    assert (
        router.resolve_engine("a.pdf", fallback="mineru", routing_mode="manual")
        == "mineru"
    )
