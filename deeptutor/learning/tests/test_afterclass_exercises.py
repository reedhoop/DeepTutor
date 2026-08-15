"""Tests for the afterclass_exercises integration.

Two layers, both hermetic (no real K12-KGraph data required):

* :class:`AfterclassIndex` — concept/skill name → KG id resolution and the
  ``by_concept`` inverted index.
* :func:`variant_exercises` — the new ``afterclass`` tier: preference,
  back-fill, empty-stem guard, exclude dedup, difficulty filter, and the
  expanded question-type mapping.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.capabilities.mastery import exercise_adapter as ea
from deeptutor.capabilities.mastery.exercise_adapter import (
    _afterclass_as_node,
    variant_exercises,
)
from deeptutor.services.afterclass_exercises import AfterclassIndex


# ── fake KG ──────────────────────────────────────────────────────────────── #


class FakeKG:
    """Minimal stand-in for :class:`KGIndex` — just the attributes the
    variant pipeline reads (nodes / adj / adj_rev / name_index)."""

    def __init__(self, *, name_index=None, nodes=None, adj=None, adj_rev=None):
        self.name_index = name_index or {}
        self.nodes = nodes or {}
        self.adj = adj or {}
        self.adj_rev = adj_rev or {}

    def get_node(self, nid):
        return self.nodes.get(nid)


def _acq(qid: str, **overrides) -> dict:
    """Build one afterclass-shaped question dict.

    The default answer is deliberately NOT ``"答案"`` — that literal is matched
    by ``exercise_to_quiz._ANSWER_PREFIX_RE`` (``^答案``) and stripped to empty,
    which would make every question look unanswerable. Use prose longer than
    ``_SHORT_ANSWER_MAX`` so a 简答题 stays ``open`` (its real-world shape)."""
    base = {
        "id": qid,
        "stem": f"题干 {qid}",
        "answer": "参考解答内容用于单元测试保持开放题型",
        "analysis": f"解析 {qid}",
        "type": "简答题",
        "difficulty": 2,
        "links": {"concept_names": [], "skill_names": []},
    }
    base.update(overrides)
    return base


def _kg_exe(eid: str, **overrides) -> dict:
    """Build one KG ``Exercise`` node dict."""
    base = {
        "id": eid,
        "label": "Exercise",
        "name": "",
        "properties": {"stem": f"kg题 {eid}", "answer": "A", "type": "选择题", "difficulty": 1},
    }
    base.update(overrides)
    return base


# ── Part A: AfterclassIndex name resolution ──────────────────────────────── #


def test_index_question_resolves_concept_names_to_kg_ids():
    kg = FakeKG(name_index={"正数": "cpt1", "负数": "cpt2"})
    idx = AfterclassIndex()
    idx._index_question(_acq("q1", links={"concept_names": ["正数", "负数"]}), kg)
    assert "cpt1" in idx.by_concept
    assert "cpt2" in idx.by_concept
    assert idx.by_concept["cpt1"][0]["id"] == "q1"
    assert idx.total == 1


def test_index_question_resolves_skill_names_alongside_concepts():
    kg = FakeKG(name_index={"正数": "cpt1", "判断物理变化": "skl1"})
    idx = AfterclassIndex()
    idx._index_question(
        _acq("q1", links={"concept_names": ["正数"], "skill_names": ["判断物理变化"]}), kg
    )
    assert set(idx.by_concept) == {"cpt1", "skl1"}


def test_index_question_dedups_when_concept_and_skill_resolve_same_id():
    """A name appearing in both concept_names and skill_names that resolves to
    the same KG id must index the question only once under that id."""
    kg = FakeKG(name_index={"正数": "cpt1"})
    idx = AfterclassIndex()
    idx._index_question(
        _acq("q1", links={"concept_names": ["正数"], "skill_names": ["正数"]}), kg
    )
    assert len(idx.by_concept["cpt1"]) == 1


def test_index_question_skips_unresolvable_names_but_still_counts():
    kg = FakeKG(name_index={})
    idx = AfterclassIndex()
    idx._index_question(_acq("q1", links={"concept_names": ["图谱里没有的概念"]}), kg)
    assert idx.by_concept == {}
    assert idx.total == 1  # counted, just unlinked


def test_index_question_skips_question_without_id():
    kg = FakeKG(name_index={"正数": "cpt1"})
    idx = AfterclassIndex()
    idx._index_question({"stem": "s", "links": {"concept_names": ["正数"]}}, kg)
    assert idx.by_concept == {}
    assert idx.total == 0


def test_questions_for_unknown_concept_returns_empty():
    assert AfterclassIndex().questions_for("nope") == []


# ── Part B: variant_exercises afterclass tier ────────────────────────────── #


@pytest.fixture
def patched_pipeline(monkeypatch):
    """Inject a fake KG + a controllable fake afterclass index into
    :mod:`exercise_adapter`. Returns ``(kg, afterclass_state)`` where
    ``afterclass_state`` is a dict ``concept_id -> [raw question]`` the test
    can populate."""
    kg = FakeKG()
    monkeypatch.setattr(ea, "get_kg", lambda: kg)
    monkeypatch.setattr(ea, "is_available", lambda: True)

    afterclass: dict[str, list[dict]] = {}

    class FakeIdx:
        def questions_for(self, concept_id):
            return afterclass.get(concept_id, [])

    monkeypatch.setattr(
        "deeptutor.services.afterclass_exercises.get_afterclass", lambda: FakeIdx()
    )
    return kg, afterclass


def test_afterclass_preferred_when_present(patched_pipeline):
    _, afterclass = patched_pipeline
    afterclass["cpt1"] = [_acq("ac1", analysis="富分析")]
    vs = variant_exercises("cpt1", count=3)
    assert vs and vs[0]["source"] == "afterclass"
    assert vs[0]["analysis"] == "富分析"
    assert vs[0]["exercise_id"] == "ac1"


def test_afterclass_preferred_over_kg_direct(patched_pipeline):
    kg, afterclass = patched_pipeline
    afterclass["cpt1"] = [_acq("ac1")]
    kg.adj_rev = {"tests_concept": {"cpt1": ["kgexe1"]}}
    kg.nodes = {"kgexe1": _kg_exe("kgexe1")}
    vs = variant_exercises("cpt1", count=3)
    assert vs[0]["source"] == "afterclass"
    # KG direct still appears as the second variant.
    assert any(v["source"] == "direct" for v in vs)


def test_afterclass_absent_falls_back_to_kg_direct(patched_pipeline):
    """When afterclass has nothing for the concept, the KG tiers behave as
    before — this is the backward-compat guarantee."""
    kg, afterclass = patched_pipeline
    afterclass["cpt1"] = []  # afterclass present but empty for this concept
    kg.adj_rev = {"tests_concept": {"cpt1": ["kgexe1"]}}
    kg.nodes = {"kgexe1": _kg_exe("kgexe1")}
    vs = variant_exercises("cpt1", count=3)
    assert vs and vs[0]["source"] == "direct"
    assert vs[0]["exercise_id"] == "kgexe1"


def test_empty_stem_afterclass_question_filtered(patched_pipeline):
    """An afterclass question with an empty stem must NOT leak its id as the
    question text (the P1-2 boundary fix)."""
    _, afterclass = patched_pipeline
    afterclass["cpt1"] = [_acq("ac1", stem="")]
    vs = variant_exercises("cpt1", count=3)
    assert vs == []


def test_exclude_dedups_afterclass_by_exercise_id(patched_pipeline):
    _, afterclass = patched_pipeline
    afterclass["cpt1"] = [_acq("ac1"), _acq("ac2"), _acq("ac3")]
    vs = variant_exercises("cpt1", count=5, exclude=["ac1"])
    assert [v["exercise_id"] for v in vs] == ["ac2", "ac3"]


def test_difficulty_filter_applies_to_afterclass(patched_pipeline):
    _, afterclass = patched_pipeline
    afterclass["cpt1"] = [_acq("ac1", difficulty=1), _acq("ac2", difficulty=3)]
    vs = variant_exercises("cpt1", count=5, difficulty=3)
    assert [v["exercise_id"] for v in vs] == ["ac2"]


def test_type_mapping_jieda_maps_to_open(patched_pipeline):
    """``解答题`` is one of the afterclass-only labels added to
    ``_TYPE_BASELINE``; it must map to ``open`` instead of falling through to
    keyword inference."""
    _, afterclass = patched_pipeline
    afterclass["cpt1"] = [_acq("ac1", type="解答题")]
    vs = variant_exercises("cpt1", count=1)
    assert vs[0]["question_type"] == "open"


def test_afterclass_as_node_name_is_empty():
    """The node projection must NOT copy the question id into ``name`` — an
    empty name keeps an empty-stem question empty so the caller filters it."""
    node = _afterclass_as_node(_acq("x"))
    assert node["name"] == ""
    assert node["id"] == "x"
    assert node["properties"]["stem"] == "题干 x"
    assert node["properties"]["analysis"] == "解析 x"


def test_kg_unavailable_raises(patched_pipeline, monkeypatch):
    monkeypatch.setattr(ea, "is_available", lambda: False)
    with pytest.raises(RuntimeError):
        variant_exercises("cpt1", count=1)


# ── Part C: worked-solution reveal after grading ──────────────────────────── #


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    """Point LearningStore at a temp workspace; yield a stable path id."""
    from deeptutor.learning.storage import LearningStore

    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(tmp_path) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return "test_path"


async def _build_basic(path_id):
    from deeptutor.capabilities.mastery.tools import MasteryBuildTool

    await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=[
            {
                "name": "Module 1",
                "knowledge_points": [{"name": "Truth tables", "type": "memory"}],
            }
        ],
    )


@pytest.fixture
def fake_variant(monkeypatch):
    """Stub variant_exercises to return one analysis-bearing afterclass quiz."""
    quiz = {
        "exercise_id": "math_7a_rjb_ch1_s1_t1",
        "question": "题干",
        "question_type": "short",
        "expected_answer": "答案",
        "options": [],
        "difficulty": 1,
        "difficulty_label": "基础",
        "source": "afterclass",
        "analysis": "解题分析内容",
    }
    monkeypatch.setattr(
        "deeptutor.capabilities.mastery.exercise_adapter.variant_exercises",
        lambda *a, **k: [quiz],
    )
    return quiz


@pytest.mark.asyncio
async def test_variant_exercise_persists_analysis(path_id, fake_variant):
    """variant_exercise must store the worked solution on the pending question
    so it survives to grading on a later turn."""
    from deeptutor.capabilities.mastery.tools import (
        MasteryStatusTool,
        VariantExerciseTool,
    )
    from deeptutor.learning.storage import LearningStore

    await _build_basic(path_id)
    kp_id = json.loads(
        (await MasteryStatusTool().execute(_mastery_path_id=path_id)).content
    )["next"]["knowledge_point_id"]

    await VariantExerciseTool().execute(
        _mastery_path_id=path_id, knowledge_point_id=kp_id
    )

    pending = LearningStore().load(path_id).pending_question
    assert pending is not None
    assert pending.analysis == "解题分析内容"


@pytest.mark.asyncio
async def test_mastery_grade_reveals_analysis(path_id, fake_variant):
    """After grading, mastery_grade must hand the worked solution back so the
    tutor can walk the learner through it."""
    from deeptutor.capabilities.mastery.tools import (
        MasteryGradeTool,
        MasteryStatusTool,
        VariantExerciseTool,
    )

    await _build_basic(path_id)
    kp_id = json.loads(
        (await MasteryStatusTool().execute(_mastery_path_id=path_id)).content
    )["next"]["knowledge_point_id"]

    registered = json.loads(
        (
            await VariantExerciseTool().execute(
                _mastery_path_id=path_id, knowledge_point_id=kp_id
            )
        ).content
    )
    from deeptutor.learning.storage import LearningStore

    pending = LearningStore().load(path_id).pending_question
    assert pending is not None
    grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=pending.question_id,
                answer="答案",
            )
        ).content
    )

    assert grade["is_correct"] is True
    assert grade["analysis"] == "解题分析内容"


@pytest.mark.asyncio
async def test_mastery_quiz_grade_has_empty_analysis(path_id):
    """LLM-authored questions (mastery_quiz) have no worked solution; the grade
    payload must carry an empty analysis rather than omit the key."""
    from deeptutor.capabilities.mastery.tools import (
        MasteryGradeTool,
        MasteryQuizTool,
        MasteryStatusTool,
    )

    await _build_basic(path_id)
    kp_id = json.loads(
        (await MasteryStatusTool().execute(_mastery_path_id=path_id)).content
    )["next"]["knowledge_point_id"]

    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="Pick a colour",
                expected_answer="blue",
                question_type="short",
            )
        ).content
    )
    grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=quiz["question_id"],
                answer="blue",
            )
        ).content
    )

    assert grade["is_correct"] is True
    assert grade["analysis"] == ""
