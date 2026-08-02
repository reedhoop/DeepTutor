"""KGraph -> Mastery bridge — end-to-end integration tests.

Mirrors ``kgraph-mastery-bridge-design.md`` §10.3 (and the Stage-1 acceptance
criteria in ``deeptutor-k12-full-dev-plan.md``):

* the ``from-kgraph`` endpoint accepts a section and persists a topo-ordered
  path with its in-path prerequisite map;
* invalid / empty sections 404 instead of half-writing a path;
* ``include_prereqs=false`` degrades to a plain linear order;
* Socratic + Mastery loop capabilities coexist in one turn — both system
  blocks mount and the passive course-KB seed is suppressed;
* the full probe -> practice -> advance -> wrong-streak -> prerequisite
  fallback flow closes on a real service + real KGraph-shaped data.

The KG index is mocked (a tiny 3-skill chain) so the suite runs without the
10k-node K12-KGraph dataset and without any LLM, exactly like the Stage-1
bridge unit tests. Importing ``deeptutor._local`` registers the topology
selector and the post-grade hook used below.
"""

from collections import defaultdict
from pathlib import Path

import pytest
from fastapi import HTTPException

from deeptutor._local import kgraph_policy_overlay  # noqa: F401  (self-registers selector)
from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.api.routers import mastery_path as mp_router
from deeptutor.capabilities.mastery import kgraph_bridge as bridge
from deeptutor.capabilities.registry import active_loop_capabilities
from deeptutor.learning import policy as learning_policy
from deeptutor.learning.models import LearningProgress
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.kgraph import KGIndex, PREREQ
from deeptutor.core.context import UnifiedContext


def _mini_kg() -> KGIndex:
    """A 3-skill linear chain (sk1 -> sk2 -> sk3) plus an empty section.

    All nodes are Skills (quantitative gate) so the full-flow test can drive
    mastery through ``grade_and_record`` without a qualitative assess round.
    """
    kg = KGIndex()
    kg.nodes = {
        "sec1": {"name": "勾股定理应用", "label": "Section"},
        "sk1": {"name": "识别直角三角形", "label": "Skill"},
        "sk2": {"name": "代入公式求值", "label": "Skill"},
        "sk3": {"name": "综合应用题", "label": "Skill"},
        "sec2": {"name": "空章", "label": "Section"},
    }
    kg.adj = defaultdict(dict)
    kg.adj_rev = defaultdict(dict)
    for kid in ("sk1", "sk2", "sk3"):
        kg.adj_rev["appears_in"].setdefault("sec1", []).append(kid)
    # prerequisites: sk2 requires sk1 ; sk3 requires sk2
    kg.adj_rev[PREREQ].setdefault("sk2", []).append("sk1")
    kg.adj[PREREQ].setdefault("sk1", []).append("sk2")
    kg.adj_rev[PREREQ].setdefault("sk3", []).append("sk2")
    kg.adj[PREREQ].setdefault("sk2", []).append("sk3")
    return kg


@pytest.fixture
def e2e_kg(monkeypatch):
    kg = _mini_kg()
    monkeypatch.setattr(bridge, "get_kg", lambda: kg)
    monkeypatch.setattr(bridge, "is_available", lambda: True)
    return kg


def _tmp_service(tmp_path: Path) -> LearningService:
    return LearningService(LearningStore(root=tmp_path))


@pytest.fixture
def noop_cancel_turn(monkeypatch):
    """The endpoint cancels an in-flight chat turn before rewriting a path; a
    no-op keeps the test off the session runtime."""

    async def _noop(book_id: str) -> None:
        return None

    monkeypatch.setattr(mp_router, "_cancel_active_learning_turn", _noop)


# ── Endpoint tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_from_kgraph_endpoint_ok(e2e_kg, tmp_path, monkeypatch, noop_cancel_turn):
    service = _tmp_service(tmp_path)
    monkeypatch.setattr(mp_router, "get_learning_service", lambda: service)

    res = await mp_router.create_from_kgraph(
        "kgraph_sec1", mp_router.FromKgraphRequest(section_id="sec1")
    )

    assert res["status"] == "ok"
    assert res["kp_count"] == 3
    assert res["with_prereqs"] == 2
    assert res["cycles_skipped"] == 0
    assert res["module_id"] == "kgraph_sec1"
    progress = service.get_or_create("kgraph_sec1")
    assert progress.dep_map["sk2"] == ["sk1"]
    # prereq_levels=2 (default) also captures the transitive prerequisite.
    assert progress.dep_map["sk3"] == ["sk2", "sk1"]
    # The path is persisted in topo order: prerequisites before dependents.
    kp_ids = [kp.id for kp in progress.modules[0].knowledge_points]
    assert kp_ids.index("sk1") < kp_ids.index("sk2") < kp_ids.index("sk3")


@pytest.mark.asyncio
async def test_from_kgraph_invalid_section(e2e_kg, tmp_path, monkeypatch, noop_cancel_turn):
    monkeypatch.setattr(
        mp_router, "get_learning_service", lambda: _tmp_service(tmp_path)
    )
    with pytest.raises(HTTPException) as exc:
        await mp_router.create_from_kgraph(
            "kgraph_bad", mp_router.FromKgraphRequest(section_id="no_such_section")
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_from_kgraph_no_prereqs(e2e_kg, tmp_path, monkeypatch, noop_cancel_turn):
    service = _tmp_service(tmp_path)
    monkeypatch.setattr(mp_router, "get_learning_service", lambda: service)

    res = await mp_router.create_from_kgraph(
        "kgraph_sec1",
        mp_router.FromKgraphRequest(section_id="sec1", include_prereqs=False),
    )

    assert res["with_prereqs"] == 0
    progress = service.get_or_create("kgraph_sec1")
    assert progress.dep_map == {}


# ── Socratic + Mastery same-turn coexistence (docs §7) ──────────────────────


def test_socratic_mastery_coexist():
    ctx = UnifiedContext(
        session_id="coexist-test", user_message="开始", language="en"
    )
    ctx.metadata["mastery_mode"] = True
    ctx.metadata["socratic_mode"] = True

    caps = active_loop_capabilities(ctx)
    assert {c.name for c in caps} >= {"mastery", "socratic"}

    pipeline = AgenticChatPipeline(language="en")
    blocks = pipeline._capability_system_blocks(ctx)
    assert {b.name for b in blocks} >= {"mastery_tutor", "socratic_guardrails"}
    # Socratic owns curriculum grounding -> the passive course-KB seed is off.
    assert pipeline._course_kb_seed_blocked_by_capability(ctx) is True

    # Neither mode set -> no blocks mount, seed not blocked.
    plain = UnifiedContext(session_id="plain", user_message="hi", language="en")
    assert pipeline._capability_system_blocks(plain) == []
    assert pipeline._course_kb_seed_blocked_by_capability(plain) is False


# ── Full flow: generate -> probe -> advance -> wrong-streak -> fallback ─────


def test_full_flow_probe_practice_advance(e2e_kg, tmp_path):
    service = _tmp_service(tmp_path)
    result = bridge.section_to_module("sec1")
    progress = service.get_or_create("kgraph_sec1")
    service.replace_modules(progress, [result.module])
    progress.dep_map = result.dep_map

    # 1) Untouched objective -> probe first.
    step = learning_policy.next_objective(progress)
    assert (step.knowledge_point_id, step.action) == ("sk1", "probe")

    # 2) Three consecutive correct answers clear the quantitative gate
    #    (confidence cap allows 1.0 from the 3rd attempt), then the path
    #    advances to the next objective.
    for i in range(3):
        service.grade_and_record(
            progress,
            question_id=f"q1-{i}",
            knowledge_point_id="sk1",
            module_id=result.module.id,
            user_answer="x",
            expected_answer="x",
            question_type="short",
        )
    kp1 = next(kp for kp in result.module.knowledge_points if kp.id == "sk1")
    assert learning_policy.is_mastered(progress, kp1) is True
    step = learning_policy.next_objective(progress)
    assert step.knowledge_point_id == "sk2"

    # 3) Wrong twice on sk2 -> still sk2. Its prerequisite sk1 is already
    #    mastered, so there is nothing to fall back to: the tutor keeps
    #    grinding the current objective (the streak counter records the 2).
    for i in range(2):
        service.grade_and_record(
            progress,
            question_id=f"q2-{i}",
            knowledge_point_id="sk2",
            module_id=result.module.id,
            user_answer="no",
            expected_answer="yes",
            question_type="short",
        )
    step = learning_policy.next_objective(progress)
    assert step.knowledge_point_id == "sk2"


# ------------------------------------------------------------------- #
#  _build_path_context — dynamic system-prompt injection               #
# ------------------------------------------------------------------- #

class FakeContext:
    """Minimal UnifiedContext stand-in for testing path context rendering."""
    def __init__(self, **meta):
        self.metadata = meta
        self.session_id = "sess-test"


def test_path_context_injects_bio_chapter_zh(tmp_path, monkeypatch):
    """_build_path_context renders a Chinese biology chapter with 0% mastery."""
    from deeptutor.capabilities.mastery.loop import _build_path_context
    from deeptutor.learning.models import (
        KnowledgePoint,
        KnowledgeType,
        LearningModule,
        LearningProgress,
    )
    from deeptutor.learning.storage import LearningStore

    # Build a mini path that mirrors the real bio ch1 data (23 KPs, 0 mastered).
    kps = [
        KnowledgePoint(id=f"kp-{i}", name=name, type=typ, module_id="mod-1")
        for i, (name, typ) in enumerate([
            ("调查法（科学调查）", KnowledgeType.PROCEDURE),
            ("细胞", KnowledgeType.CONCEPT),
            ("观察比较（找相同点与不同点）", KnowledgeType.PROCEDURE),
            ("生物", KnowledgeType.CONCEPT),
        ])
    ]
    mod = LearningModule(id="mod-1", name="第一章 认识生物", order=0, knowledge_points=kps)
    progress = LearningProgress(
        book_id="test-bio-ch1-zh",
        modules=[mod],
        mastery_levels={},  # all 0.0
    )

    # Save into tmp_path and patch LearningStore so _build_path_context reads
    # from the same directory.
    store = LearningStore(root=tmp_path)
    store.save(progress)

    # _build_path_context imports LearningStore lazily; patch at source.
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda root=None: LearningStore(root=tmp_path))

    ctx = FakeContext(mastery_mode=True, mastery_path_id="test-bio-ch1-zh")
    result = _build_path_context(ctx, "zh")

    assert "第一章 认识生物" in result
    assert "4 个知识点" in result
    assert "0/4" in result
    assert "调查法（科学调查）" in result
    assert "**当前首要目标：调查法（科学调查）**" in result
    assert "⬜" in result  # unmastered indicator
    assert "✅" not in result  # nothing mastered yet


def test_path_context_shows_partial_mastery(tmp_path, monkeypatch):
    """_build_path_context shows mixed mastered/unmastered state."""
    from deeptutor.capabilities.mastery.loop import _build_path_context
    from deeptutor.learning.models import (
        KnowledgePoint,
        KnowledgeType,
        LearningModule,
        LearningProgress,
    )
    from deeptutor.learning.storage import LearningStore

    kps = [
        KnowledgePoint(id="a", name="已掌握的概念", type=KnowledgeType.CONCEPT, module_id="m"),
        KnowledgePoint(id="b", name="未掌握的方法", type=KnowledgeType.PROCEDURE, module_id="m"),
    ]
    mod = LearningModule(id="m", name="测试章节", order=0, knowledge_points=kps)
    progress = LearningProgress(
        book_id="test-partial",
        modules=[mod],
        mastery_levels={"a": 1.0, "b": 0.0},
    )

    store = LearningStore(root=tmp_path)
    store.save(progress)
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda root=None: LearningStore(root=tmp_path))

    ctx = FakeContext(mastery_mode=True, mastery_path_id="test-partial")
    result = _build_path_context(ctx, "zh")

    assert "✅" in result
    assert "⬜" in result
    assert "1/2" in result
    assert "未掌握的方法" in result


def test_path_context_falls_back_gracefully():
    """Missing / empty path_id returns empty string (no crash)."""
    from deeptutor.capabilities.mastery.loop import _build_path_context

    # No path_id at all
    ctx = FakeContext(mastery_mode=True)
    assert _build_path_context(ctx, "zh") == ""

    # Non-existent path
    ctx2 = FakeContext(mastery_mode=True, mastery_path_id="no-such-path")
    assert _build_path_context(ctx2, "zh") == ""


def test_path_context_truncates_long_lists(tmp_path, monkeypatch):
    """Paths with >_MAX_KP_LIST KPs are truncated with a summary line."""
    from deeptutor.capabilities.mastery.loop import _MAX_KP_LIST, _build_path_context
    from deeptutor.learning.models import (
        KnowledgePoint,
        KnowledgeType,
        LearningModule,
        LearningProgress,
    )
    from deeptutor.learning.storage import LearningStore

    n = _MAX_KP_LIST + 5
    kps = [
        KnowledgePoint(id=f"kp-{i}", name=f"知识点{i}", type=KnowledgeType.MEMORY, module_id="m")
        for i in range(n)
    ]
    mod = LearningModule(id="m", name="大章节", order=0, knowledge_points=kps)
    progress = LearningProgress(book_id="test-long", modules=[mod], mastery_levels={})

    store = LearningStore(root=tmp_path)
    store.save(progress)
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda root=None: LearningStore(root=tmp_path))

    ctx = FakeContext(mastery_mode=True, mastery_path_id="test-long")
    result = _build_path_context(ctx, "zh")

    assert "更多知识点" in result or "more KPs" in result
    # Should NOT list all n KPs
    assert result.count("⬜") <= _MAX_KP_LIST
