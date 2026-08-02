"""Tests for the KGraph -> Mastery bridge (Stage 1).

The KG index is mocked (a 5-node mini graph) so the suite runs without the
10k-node K12-KGraph dataset and without any LLM. Importing ``deeptutor._local``
registers the topology selector and the post-grade hook used below.
"""

from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from deeptutor._local import kgraph_policy_overlay, kgraph_service_overlay  # noqa: F401
from deeptutor.capabilities.mastery import kgraph_bridge as bridge
from deeptutor.learning import policy as learning_policy
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.service import LearningService
from deeptutor.services.kgraph import KGIndex, PREREQ


def _mini_kg() -> KGIndex:
    kg = KGIndex()
    kg.nodes = {
        "sec1": {"name": "勾股定理", "label": "Section"},
        "c1": {"name": "直角三角形", "label": "Concept"},
        "c2": {"name": "勾股定理表述", "label": "Concept"},
        "s1": {"name": "应用求值", "label": "Skill"},
        "sec2": {"name": "空章", "label": "Section"},
    }
    kg.adj = defaultdict(dict)
    kg.adj_rev = defaultdict(dict)
    # appears_in edges: c1/c2/s1 belong to sec1
    for kid in ("c1", "c2", "s1"):
        kg.adj_rev["appears_in"].setdefault("sec1", []).append(kid)
        kg.adj["appears_in"].setdefault(kid, []).append("sec1")
    # prerequisites: c2 requires c1 ; s1 requires c2
    kg.adj_rev[PREREQ].setdefault("c2", []).append("c1")
    kg.adj[PREREQ].setdefault("c1", []).append("c2")
    kg.adj_rev[PREREQ].setdefault("s1", []).append("c2")
    kg.adj[PREREQ].setdefault("c2", []).append("s1")
    return kg


@pytest.fixture
def mini_kg(monkeypatch):
    kg = _mini_kg()
    monkeypatch.setattr(bridge, "get_kg", lambda: kg)
    monkeypatch.setattr(bridge, "is_available", lambda: True)
    return kg


# ── Bridge pure-function tests ──────────────────────────────────────────────


def test_section_to_module_basic(mini_kg):
    r = bridge.section_to_module("sec1")
    assert r.stats["total_kps"] == 3
    assert {kp.id for kp in r.module.knowledge_points} == {"c1", "c2", "s1"}
    assert r.module.name == "勾股定理"
    types = {kp.id: kp.type for kp in r.module.knowledge_points}
    assert types["c1"] == KnowledgeType.CONCEPT
    assert types["s1"] == KnowledgeType.PROCEDURE


def test_topo_order(mini_kg):
    r = bridge.section_to_module("sec1")
    order = [kp.id for kp in r.module.knowledge_points]
    assert order.index("c1") < order.index("c2") < order.index("s1")
    assert r.stats["cycles_skipped"] == 0


def test_dep_map_internal_only(mini_kg):
    r = bridge.section_to_module("sec1")
    # prereq_levels=2 -> transitive prerequisites are captured (s1 -> c2 -> c1)
    assert r.dep_map["c1"] == []
    assert r.dep_map["c2"] == ["c1"]
    assert r.dep_map["s1"] == ["c2", "c1"]


def test_empty_section(mini_kg):
    r = bridge.section_to_module("sec2")
    assert r.stats["total_kps"] == 0
    assert r.module.knowledge_points == []


def test_label_to_type_mapping():
    assert bridge._LABEL_TO_TYPE["Concept"] == KnowledgeType.CONCEPT
    assert bridge._LABEL_TO_TYPE["Skill"] == KnowledgeType.PROCEDURE
    # Exercises are assessment material, not learning goals: they must NOT be
    # mapped to a knowledge type, and must be excluded from TEACHABLE so they
    # never become a mastery objective (they reach the learner via the
    # variant_exercise quiz path instead).
    assert "Exercise" not in bridge._LABEL_TO_TYPE
    assert "Exercise" not in bridge.TEACHABLE
    assert bridge.TEACHABLE == frozenset({"Concept", "Skill"})


def test_unavailable_raises(monkeypatch):
    monkeypatch.setattr(bridge, "is_available", lambda: False)
    with pytest.raises(RuntimeError):
        bridge.section_to_module("sec1")


# ── Policy topology-selector tests ───────────────────────────────────────────


def _progress_from_bridge(r: bridge.BridgeResult) -> LearningProgress:
    return LearningProgress(
        book_id="b1", modules=[r.module], dep_map=dict(r.dep_map)
    )


def test_selector_picks_first_available(mini_kg):
    p = _progress_from_bridge(bridge.section_to_module("sec1"))
    step = learning_policy.next_objective(p)
    assert step.knowledge_point_id == "c1"


def test_selector_skips_blocked_by_prereq(mini_kg):
    p = _progress_from_bridge(bridge.section_to_module("sec1"))
    p.mastery_levels["c1"] = 1.0
    p.qualitative_mastery["c1"] = True
    step = learning_policy.next_objective(p)
    assert step.knowledge_point_id == "c2"


def test_wrong_trigger_fallback(mini_kg):
    p = _progress_from_bridge(bridge.section_to_module("sec1"))
    p.consecutive_wrong = {"c2": 2}  # stuck on c2, c1 not mastered
    step = learning_policy.next_objective(p)
    assert step.knowledge_point_id == "c1"


def test_linear_fallback_when_no_dep_map():
    mod = LearningModule(
        id="m1",
        name="手写",
        order=0,
        knowledge_points=[
            KnowledgePoint(id=k, name=k, type=KnowledgeType.CONCEPT, module_id="m1")
            for k in ("x", "y", "z")
        ],
    )
    p = LearningProgress(book_id="b1", modules=[mod])  # dep_map empty
    step = learning_policy.next_objective(p)
    assert step.knowledge_point_id == "x"


# ── Service post-grade hook tests ───────────────────────────────────────────


def test_hook_updates_consecutive_wrong():
    p = LearningProgress(book_id="b1")
    kgraph_service_overlay._update_consecutive_wrong(p, "a", correct=False)
    assert p.consecutive_wrong["a"] == 1
    kgraph_service_overlay._update_consecutive_wrong(p, "a", correct=True)
    assert "a" not in p.consecutive_wrong


def test_replace_modules_clears_wrong():
    mod = LearningModule(
        id="m1",
        name="m",
        order=0,
        knowledge_points=[
            KnowledgePoint(id="a", name="a", type=KnowledgeType.CONCEPT, module_id="m1")
        ],
    )
    service = LearningService(store=MagicMock())
    p = LearningProgress(book_id="b1", modules=[mod])
    p.consecutive_wrong = {"a": 3}
    service.replace_modules(p, [mod])
    assert p.consecutive_wrong == {}


# ── Models compatibility tests ──────────────────────────────────────────────


def test_new_fields_default_empty():
    p = LearningProgress(book_id="b1")
    assert p.dep_map == {}
    assert p.consecutive_wrong == {}


def test_serialization_includes_new():
    p = LearningProgress(book_id="b1")
    dump = p.model_dump()
    assert "dep_map" in dump and "consecutive_wrong" in dump


# ── Overlay degradation & registration-order guards ─────────────────────────


def test_overlay_unregistered_falls_back_to_linear(monkeypatch):
    # The "overlay never imported" state (_kp_selector=None): next_objective
    # must fall back to the plain linear scan. To make the fallback actually
    # observable, the module's KP order differs from its dependency order —
    # the topology selector would skip y (its prereq x is unmastered) and pick
    # x, while the linear scan picks the first unmastered KP, y.
    monkeypatch.setattr(learning_policy, "_kp_selector", None)
    mod = LearningModule(
        id="m1",
        name="m",
        order=0,
        knowledge_points=[
            KnowledgePoint(id="y", name="y", type=KnowledgeType.PROCEDURE, module_id="m1"),
            KnowledgePoint(id="x", name="x", type=KnowledgeType.PROCEDURE, module_id="m1"),
        ],
    )
    p = LearningProgress(book_id="b1", modules=[mod], dep_map={"y": ["x"]})
    step = learning_policy.next_objective(p)
    assert step.knowledge_point_id == "y"


def test_hook_registration_order_guards_errorbook():
    # kgraph_errorbook_overlay (refine_latest_error) reads the consecutive_wrong
    # streak that kgraph_service_overlay (_update_consecutive_wrong) maintains,
    # so its post-grade hook must be registered after it. This locks the
    # load-bearing import order in _local/__init__.py.
    from deeptutor.learning.service import _post_grade_hooks

    names = [getattr(h, "__name__", "") for h in _post_grade_hooks]
    assert "_update_consecutive_wrong" in names
    assert "refine_latest_error" in names
    assert names.index("_update_consecutive_wrong") < names.index("refine_latest_error")
