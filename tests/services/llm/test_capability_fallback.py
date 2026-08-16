"""Tests for the capability-aware LLM fallback router.

Hermetic: the catalog and primary model are faked via monkeypatch, so no real
model/API/OCR engine is touched. Covers the four tiers (explicit vlm slot,
auto-discovery, OCR extraction, degrade), the primary-vision passthrough, and
— importantly — the *fail-closed* guarantees that keep auto-discovery from
handing an image to something that cannot take one.

The primary fixture uses ``deepseek-chat``, not ``gpt-4o-mini``: the latter
matches the ``gpt-4o`` vision prefix, so a "text primary" built from it would
pass the vision check and every tier assertion below would silently test the
passthrough instead.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from deeptutor._local import capability_fallback as cf
from deeptutor.services.llm.capabilities import (
    model_name_implies_vision,
    model_vision_confirmed,
    supports_vision,
)
from deeptutor.services.llm.config import LLMConfig


def _profile(pid: str, models: list[dict], binding: str = "openai") -> dict:
    return {
        "id": pid,
        "name": pid,
        "binding": binding,
        "base_url": "https://example.invalid/v1",
        "api_key": "sk-x",
        "models": models,
    }


def _service(pid: str, mid: str, models: list[dict], binding: str = "openai") -> dict:
    return {
        "active_profile_id": pid,
        "active_model_id": mid,
        "profiles": [_profile(pid, models, binding)],
    }


def _catalog(
    *,
    vlm_models: list[dict] | None = None,
    extra_llm_models: list[dict] | None = None,
    tts_models: list[dict] | None = None,
) -> dict:
    llm_models = [{"id": "llm-m", "name": "Text", "model": "deepseek-chat"}]
    llm_models.extend(extra_llm_models or [])
    services: dict = {"llm": _service("llm-p", "llm-m", llm_models, binding="deepseek")}
    if vlm_models:
        services["vlm"] = _service("vlm-p", vlm_models[0]["id"], vlm_models)
    if tts_models:
        services["tts"] = _service("tts-p", tts_models[0]["id"], tts_models)
    return {"services": services}


class _FakeCatalogSvc:
    def __init__(self, catalog: dict) -> None:
        self._catalog = catalog

    def load(self) -> dict:
        return self._catalog


class _Att:
    def __init__(self, b64: str = "") -> None:
        self.type = "image"
        self.base64 = b64
        self.url = ""


def _patch_catalog(monkeypatch, catalog: dict) -> None:
    monkeypatch.setattr(cf, "get_model_catalog_service", lambda: _FakeCatalogSvc(catalog))


def _patch_ocr(monkeypatch, engine: str | None, text: str = "OCRed worksheet text") -> None:
    monkeypatch.setattr("deeptutor._local.engine_router.first_ready_ocr_engine", lambda: engine)

    class _FakeDoc:
        markdown = text

    class _FakeParseSvc:
        def parse(self, path, engine=None):  # noqa: ARG002
            return _FakeDoc()

    monkeypatch.setattr(
        "deeptutor.services.parsing.service.get_parse_service", lambda: _FakeParseSvc()
    )


@pytest.fixture
def text_primary(monkeypatch):
    """A primary model that genuinely cannot see images."""
    primary = LLMConfig(
        model="deepseek-chat",
        api_key="sk",
        base_url="https://api.deepseek.com/v1",
        binding="deepseek",
        provider_name="deepseek",
        provider_mode="standard",
    )
    assert not supports_vision(primary.binding, primary.model), "fixture must be text-only"
    monkeypatch.setattr(cf, "get_llm_config", lambda: primary)
    yield primary


# --------------------------------------------------------------------------
# tiers
# --------------------------------------------------------------------------


def test_t1_explicit_vlm_slot(monkeypatch, text_primary):
    """A model in the vlm slot is trusted: the slot itself declares intent."""
    _patch_catalog(monkeypatch, _catalog(vlm_models=[{"id": "vlm-m", "model": "gpt-4o"}]))
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "vlm"
    assert d.config is not None and d.config.model == "gpt-4o"
    assert "vlm-slot" in d.tiers_considered


def test_t1_slot_accepts_unknown_model_name(monkeypatch, text_primary):
    """An unrecognised name in the vlm slot still wins — user config is king."""
    _patch_catalog(
        monkeypatch, _catalog(vlm_models=[{"id": "vlm-m", "model": "some-new-vision-llm-v9"}])
    )
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "vlm"
    assert d.config is not None and d.config.model == "some-new-vision-llm-v9"


def test_t1_slot_vetoed_by_explicit_capabilities(monkeypatch, text_primary):
    """An explicit text-only declaration overrides the slot and we fall through."""
    _patch_catalog(
        monkeypatch,
        _catalog(vlm_models=[{"id": "vlm-m", "model": "mystery", "capabilities": ["text"]}]),
    )
    _patch_ocr(monkeypatch, None)
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "degrade"


def test_t1_vlm_slot_resolves_gateway_default_base_url(monkeypatch, text_primary):
    """The vlm slot must reuse provider matching, not a hand-rolled config.

    A gateway binding (openrouter) with an empty base_url must fall back to the
    provider's default endpoint — otherwise the swap targets OpenAI's default
    while "Run test" succeeds against openrouter.
    """
    vlm_profile = {
        "id": "vlm-p",
        "name": "VLM",
        "binding": "openrouter",
        "base_url": "",
        "api_key": "sk-or-x",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "vlm-m", "name": "q", "model": "qwen/qwen2.5-vl-7b-instruct"}],
    }
    catalog = _catalog(vlm_models=[{"id": "vlm-m", "model": "qwen/qwen2.5-vl-7b-instruct"}])
    catalog["services"]["vlm"] = {
        "active_profile_id": "vlm-p",
        "active_model_id": "vlm-m",
        "profiles": [vlm_profile],
    }
    _patch_catalog(monkeypatch, catalog)
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "vlm"
    assert d.config is not None
    assert d.config.binding == "openrouter"
    assert d.config.base_url == "https://openrouter.ai/api/v1"


def test_resolve_catalog_pair_fills_gateway_default_base_url():
    """The fork resolver reuses upstream matching for a non-llm (profile, model)."""
    from deeptutor._local.capability_resolver import resolve_catalog_pair

    profile = {
        "id": "vlm-p",
        "name": "VLM",
        "binding": "openrouter",
        "base_url": "",
        "api_key": "sk-or-x",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "vlm-m", "model": "qwen/qwen2.5-vl-7b-instruct"}],
    }
    catalog = {"version": 1, "services": {"llm": {"active_profile_id": None, "profiles": []}}}
    resolved = resolve_catalog_pair(profile, profile["models"][0], catalog=catalog)
    assert resolved.binding == "openrouter"
    assert resolved.model == "qwen/qwen2.5-vl-7b-instruct"
    assert resolved.base_url == "https://openrouter.ai/api/v1"


def test_resolve_catalog_pair_raises_on_empty_model():
    from deeptutor._local.capability_resolver import resolve_catalog_pair

    with pytest.raises(ValueError):
        resolve_catalog_pair({"id": "p"}, {"model": ""})


def test_t2_auto_discovery_by_name(monkeypatch, text_primary):
    """A ``-vl`` model elsewhere in the catalog is discovered without any table edit."""
    _patch_catalog(
        monkeypatch,
        _catalog(extra_llm_models=[{"id": "llm-v", "model": "Qwen/Qwen2.5-VL-7B-Instruct"}]),
    )
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "vlm"
    assert d.config is not None and d.config.model == "Qwen/Qwen2.5-VL-7B-Instruct"
    assert "auto-discover" in d.tiers_considered


def test_t2_auto_discovery_by_declared_capability(monkeypatch, text_primary):
    """An explicit ``capabilities`` declaration is enough, name notwithstanding."""
    _patch_catalog(
        monkeypatch,
        _catalog(
            extra_llm_models=[
                {"id": "llm-v", "model": "house-brand-42", "capabilities": ["text", "image"]}
            ]
        ),
    )
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "vlm"
    assert d.config is not None and d.config.model == "house-brand-42"


def test_t2_prefers_cheaper_model(monkeypatch, text_primary):
    _patch_catalog(
        monkeypatch,
        _catalog(
            extra_llm_models=[
                {"id": "big", "model": "qwen2.5-vl-72b-instruct"},
                {"id": "small", "model": "qwen2.5-vl-3b-instruct-lite"},
            ]
        ),
    )
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.config is not None and d.config.model == "qwen2.5-vl-3b-instruct-lite"


def test_t3_ocr_extraction(monkeypatch, text_primary):
    _patch_catalog(monkeypatch, _catalog())  # no vlm slot, no vision model
    _patch_ocr(monkeypatch, "docling")
    d = cf.resolve_for_turn({"image"}, [_Att(b64="aGVsbG8=")])
    assert d.kind == "ocr_text"
    assert "OCRed" in d.extracted_text
    assert "ocr" in d.tiers_considered


def test_t4_degrade(monkeypatch, text_primary):
    _patch_catalog(monkeypatch, _catalog())
    _patch_ocr(monkeypatch, None)
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "degrade"
    assert d.config is not None and d.config.model == "deepseek-chat"


def test_ocr_with_no_extractable_bytes_degrades(monkeypatch, text_primary):
    """A ready engine but unreadable attachment must not fake success."""
    _patch_catalog(monkeypatch, _catalog())
    _patch_ocr(monkeypatch, "docling")
    d = cf.resolve_for_turn({"image"}, [_Att()])  # empty base64, no url
    assert d.kind == "degrade"


# --------------------------------------------------------------------------
# passthrough / no-op paths
# --------------------------------------------------------------------------


def test_primary_vision_passthrough(monkeypatch):
    """The user's own vision model is never rerouted."""
    primary = LLMConfig(
        model="gpt-4o",
        api_key="sk",
        base_url="https://api.openai.com/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
    )
    monkeypatch.setattr(cf, "get_llm_config", lambda: primary)
    _patch_catalog(monkeypatch, _catalog(vlm_models=[{"id": "vlm-m", "model": "gpt-4o-mini"}]))
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "primary"


def test_no_image_is_primary(monkeypatch, text_primary):
    _patch_catalog(monkeypatch, _catalog(vlm_models=[{"id": "vlm-m", "model": "gpt-4o"}]))
    d = cf.resolve_for_turn({"image"}, [])
    assert d.kind == "primary"


# --------------------------------------------------------------------------
# fail-closed guarantees
# --------------------------------------------------------------------------


def test_discovery_ignores_openai_compatible_text_model(monkeypatch, text_primary):
    """The generic ``openai`` binding claims vision for everything it serves.

    A GLM/DeepSeek text model behind an OpenAI-compatible gateway must not be
    auto-selected just because the provider table is optimistic.
    """
    _patch_catalog(monkeypatch, _catalog(extra_llm_models=[{"id": "llm-x", "model": "glm-5.2"}]))
    assert supports_vision("openai", "glm-5.2") is True  # the loose view says yes...
    assert model_vision_confirmed({"model": "glm-5.2"}, "openai") is False  # ...strict says no
    _patch_ocr(monkeypatch, None)
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "degrade"


def test_discovery_ignores_non_chat_services(monkeypatch, text_primary):
    """``gpt-4o-mini-tts`` looks vision-capable by prefix but is a speech endpoint."""
    _patch_catalog(monkeypatch, _catalog(tts_models=[{"id": "tts-m", "model": "gpt-4o-mini-tts"}]))
    _patch_ocr(monkeypatch, None)
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "degrade"


def test_discovery_skips_model_without_name(monkeypatch, text_primary):
    _patch_catalog(
        monkeypatch,
        _catalog(extra_llm_models=[{"id": "blank", "model": "", "capabilities": ["text", "image"]}]),
    )
    _patch_ocr(monkeypatch, None)
    d = cf.resolve_for_turn({"image"}, [_Att()])
    assert d.kind == "degrade"


# --------------------------------------------------------------------------
# capability helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("gpt-4o", True),
        ("gpt-4o-mini", True),
        ("gpt-4o-mini-tts", False),
        ("gpt-4o-transcribe", False),
        ("claude-sonnet-4-5", True),
        ("Qwen/Qwen2.5-VL-7B-Instruct", True),
        ("qwen3-32b", False),
        ("deepseek-chat", False),
        ("glm-4.5v", True),
        ("glm-5.2", False),
        ("brand-new-omni-model", True),
        ("llava-1.6", True),
        ("some-text-model", False),
    ],
)
def test_model_name_implies_vision(name, expected):
    assert model_name_implies_vision(name) is expected


def test_explicit_capabilities_are_authoritative_both_ways():
    assert model_vision_confirmed({"model": "gpt-4o", "capabilities": ["text"]}, "openai") is False
    assert model_vision_confirmed({"model": "mystery", "capabilities": ["image"]}, "openai") is True


# --------------------------------------------------------------------------
# catalog normalization
# --------------------------------------------------------------------------


def test_catalog_adds_vlm_service_without_stamping_capabilities():
    """``vlm`` is added; ``capabilities`` must stay absent (= infer, not text-only)."""
    raw = {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "name": "P",
                        "binding": "openai",
                        "base_url": "x",
                        "api_key": "k",
                        "models": [{"id": "m", "model": "gpt-4o-mini"}],
                    }
                ],
            },
        },
    }
    tmp = Path(tempfile.mktemp(suffix=".json"))
    tmp.write_text(json.dumps(raw), encoding="utf-8")
    from deeptutor.services.config.model_catalog import ModelCatalogService

    cat = ModelCatalogService(path=tmp).load()
    assert "vlm" in cat["services"]
    model = cat["services"]["llm"]["profiles"][0]["models"][0]
    assert "capabilities" not in model
