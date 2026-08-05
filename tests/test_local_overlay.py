"""Unit tests for our local overlay modules (``deeptutor._local.*``).

These cover the custom auto-routing engines and the KGraph mastery-bridge
helpers that live entirely in our fork (never patched into upstream files), so
rebasing upstream stays conflict-free.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

from deeptutor._local import engine_defaults, engine_router, kp_index
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)


def _progress() -> LearningProgress:
    module = LearningModule(
        id="m1",
        name="模块一",
        order=0,
        knowledge_points=[
            KnowledgePoint(id="kp_a", name="底层", type=KnowledgeType.MEMORY, module_id="m1"),
            KnowledgePoint(id="kp_b", name="上层", type=KnowledgeType.PROCEDURE, module_id="m1"),
        ],
    )
    return LearningProgress(book_id="b1", modules=[module])


def test_kp_index_fast_and_build():
    prog = _progress()
    kp, mid, mname = kp_index.find_knowledge_point_fast(prog, "kp_a")
    assert kp is not None and kp.id == "kp_a"
    assert mid == "m1" and mname == "模块一"

    # Missing id returns the (None, "", "") sentinel — O(1), no linear scan.
    assert kp_index.find_knowledge_point_fast(prog, "nope") == (None, "", "")

    # One-shot index build helper.
    idx = kp_index.build_kp_index(prog)
    assert idx["kp_b"][0].id == "kp_b"


def _fake_fitz(pages):
    """Build a fake ``fitz`` module whose ``open()`` yields a doc with ``pages``."""
    mod = types.ModuleType("fitz")

    class _Page:
        def __init__(self, text: str) -> None:
            self._t = text

        def get_text(self) -> str:
            return self._t

    class _Doc:
        def __init__(self, ps) -> None:
            self._ps = ps

        def __len__(self) -> int:
            return len(self._ps)

        def __getitem__(self, i: int) -> "_Page":
            return _Page(self._ps[i])

        def close(self) -> None:
            pass

    def _open(_path):
        return _Doc(pages)

    mod.open = _open
    return mod


def test_engine_router_scan_degree():
    p = Path("dummy.pdf")
    with mock.patch.dict(sys.modules, {"fitz": _fake_fitz(["a", "b"])}):
        assert engine_router._sample_scan_degree(p) == "text"
    with mock.patch.dict(sys.modules, {"fitz": _fake_fitz(["", ""])}):
        assert engine_router._sample_scan_degree(p) == "image"
    with mock.patch.dict(sys.modules, {"fitz": _fake_fitz(["a", ""])}):
        assert engine_router._sample_scan_degree(p) == "mixed"


def test_engine_router_resolve_fallback():
    # Manual mode never auto-selects — returns the explicit fallback.
    assert (
        engine_router.resolve_engine("doc.pdf", fallback="docling", routing_mode="manual")
        == "docling"
    )
    # Non-PDF files bypass the classification pass and use the fallback.
    assert (
        engine_router.resolve_engine("doc.docx", fallback="docling", routing_mode="auto")
        == "docling"
    )
    assert (
        engine_router.resolve_engine("img.png", fallback="mineru", routing_mode="auto")
        == "mineru"
    )


def test_routing_ttls_fallback_to_defaults():
    with mock.patch(
        "deeptutor.services.config.runtime_settings.load_document_parsing_settings",
        side_effect=RuntimeError("settings unavailable"),
    ):
        rttl, sttl = engine_router._routing_ttls()
    assert rttl == engine_router._READINESS_TTL
    assert sttl == engine_router._SCAN_TTL


def test_routing_ttls_reads_settings():
    fake = {"readiness_ttl": 10, "scan_ttl": 20}
    with mock.patch(
        "deeptutor.services.config.runtime_settings.load_document_parsing_settings",
        return_value=fake,
    ):
        rttl, sttl = engine_router._routing_ttls()
    assert rttl == 10.0
    assert sttl == 20.0


def test_normalize_routing_includes_ttls():
    out = engine_defaults.normalize_routing({})
    assert out["routing_mode"] == "manual"
    assert out["readiness_ttl"] == engine_defaults.DEFAULT_READINESS_TTL
    assert out["scan_ttl"] == engine_defaults.DEFAULT_SCAN_TTL

    # Custom values are honored and coerced to float.
    out2 = engine_defaults.normalize_routing({"readiness_ttl": "900", "routing_mode": "auto"})
    assert out2["readiness_ttl"] == 900.0
    assert out2["routing_mode"] == "auto"


def test_local_overlay_imports_cleanly():
    import deeptutor._local

    assert callable(deeptutor._local.apply_kgraph_overlay)
