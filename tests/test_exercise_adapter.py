"""Stage 3 — KGraph Exercise -> mastery_quiz adapter + variant lookup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deeptutor.capabilities.mastery.exercise_adapter import (
    exercise_to_quiz,
    extract_options,
    variant_exercises,
)


def _exercise(eid: str, **props) -> dict:
    return {"id": eid, "label": "Exercise", "name": props.get("stem", ""), "properties": props}


class _FakeKG:
    """Minimal stand-in for ``KGIndex`` covering the four widening tiers."""

    def __init__(self, nodes: dict, adj: dict | None = None, adj_rev: dict | None = None):
        self._nodes = nodes
        self.adj = adj or {}
        self.adj_rev = adj_rev or {}

    def get_node(self, nid: str):
        return self._nodes.get(nid)


def _patch_kg(kg: _FakeKG):
    return (
        patch("deeptutor.capabilities.mastery.exercise_adapter.get_kg", return_value=kg),
        patch("deeptutor.capabilities.mastery.exercise_adapter.is_available", return_value=True),
    )


# ── exercise_to_quiz ──────────────────────────────────────────────────────


def test_exercise_to_quiz_choice():
    """A 选择题 stem yields question_type='choice' with extracted options."""
    node = _exercise(
        "exe1",
        stem="下列说法正确的是（ ）\nA. 第一项\nB. 第二项\nC. 第三项\nD. 第四项",
        answer="C",
        difficulty=2,
        type="选择题",
    )
    quiz = exercise_to_quiz(node, "cpt1")
    assert quiz["question_type"] == "choice"
    assert quiz["expected_answer"] == "C"
    assert quiz["options"] == ["A: 第一项", "B: 第二项", "C: 第三项", "D: 第四项"]
    assert quiz["difficulty"] == 2
    assert quiz["difficulty_label"] == "常规"
    assert quiz["exercise_id"] == "exe1"


def test_exercise_to_quiz_short():
    """A 填空题 with a terse answer stays exact/fuzzy-gradable."""
    quiz = exercise_to_quiz(
        _exercise("exe2", stem="水的化学式是____。", answer="H2O", difficulty=1, type="填空题"),
        "cpt1",
    )
    assert quiz["question_type"] == "short"
    assert quiz["expected_answer"] == "H2O"
    assert quiz["options"] == []
    assert quiz["difficulty_label"] == "基础"


def test_exercise_to_quiz_open():
    """A prose answer is graded by keyword overlap, never exact match."""
    long_answer = "光合作用是绿色植物利用光能，把二氧化碳和水转化成储存能量的有机物，并且释放出氧气的过程。"
    quiz = exercise_to_quiz(
        _exercise("exe3", stem="简述光合作用。", answer=long_answer, difficulty=3, type="简答题"),
        "cpt1",
    )
    assert quiz["question_type"] == "open"
    assert quiz["difficulty_label"] == "进阶"


def test_long_answer_overrides_short_baseline():
    """A 填空题 whose answer runs past 50 chars can never match exactly —
    it is promoted to keyword grading."""
    prose = "由于同位角相等，所以两直线平行；" * 4
    quiz = exercise_to_quiz(
        _exercise("exe3b", stem="补全推理过程：____", answer=prose, type="填空题"), "cpt1"
    )
    assert len(prose) > 50
    assert quiz["question_type"] == "open"


def test_terse_answer_overrides_open_baseline():
    """A 简答题 answered in one word is better served by fuzzy matching."""
    quiz = exercise_to_quiz(
        _exercise("exe3c", stem="细胞的能量工厂是什么？", answer="线粒体", type="简答题"),
        "cpt1",
    )
    assert quiz["question_type"] == "short"


def test_judge_becomes_two_option_choice():
    """判断题 with a single verdict becomes an A/B card, not free text."""
    quiz = exercise_to_quiz(
        _exercise("exe4", stem="能够运动的物体就一定是生物。", answer="×", type="判断题"),
        "cpt1",
    )
    assert quiz["question_type"] == "choice"
    assert quiz["expected_answer"] == "B"
    assert quiz["options"] == ["A: 正确（√）", "B: 错误（×）"]


def test_judge_with_explanation_still_resolves():
    """A verdict trailed by reasoning still resolves to one label."""
    quiz = exercise_to_quiz(
        _exercise("exe5", stem="植物也进行呼吸作用。", answer="√（植物也进行呼吸）", type="判断题"),
        "cpt1",
    )
    assert quiz["question_type"] == "choice"
    assert quiz["expected_answer"] == "A"


def test_negated_verdict_is_false():
    """'不正确' contains '正确' — it must not be read as true."""
    quiz = exercise_to_quiz(
        _exercise("exe6", stem="该说法是否成立？", answer="不正确", type="判断题"),
        "cpt1",
    )
    assert quiz["expected_answer"] == "B"


def test_multipart_judge_degrades():
    """A multi-statement 判断题 cannot be a single choice — it degrades."""
    quiz = exercise_to_quiz(
        _exercise(
            "exe7",
            stem="判断：（1）生物的环境是指生存地点。（2）非生物因素只有阳光。",
            answer="（1）×（2）×",
            type="判断题",
        ),
        "cpt1",
    )
    assert quiz["question_type"] != "choice"
    assert quiz["options"] == []


def test_multi_answer_choice_degrades():
    """A multi-select answer ('B、D') must not be graded as one label."""
    quiz = exercise_to_quiz(
        _exercise(
            "exe8",
            stem="下列正确的是（ ）\nA. 甲\nB. 乙\nC. 丙\nD. 丁",
            answer="正确答案：B、D。",
            type="选择题",
        ),
        "cpt1",
    )
    assert quiz["question_type"] != "choice"
    # The "正确答案：" prefix is stripped so fuzzy grading has a fair chance.
    assert quiz["expected_answer"] == "B、D。"


def test_answer_with_body_resolves_to_label():
    """'D（幼虫、成虫）' resolves to label D."""
    quiz = exercise_to_quiz(
        _exercise(
            "exe9",
            stem="处于哪个阶段？（）\nA. 幼虫、卵\nB. 蛹、若虫\nC. 若虫、成虫\nD. 幼虫、成虫",
            answer="D（幼虫、成虫）",
            type="选择题",
        ),
        "cpt1",
    )
    assert quiz["question_type"] == "choice"
    assert quiz["expected_answer"] == "D"


def test_options_survive_letters_in_prose():
    """Stray capitals in the stem must not shift or break the option block."""
    stem = "下列关于 F、Cl、Br、I 的比较，不正确的是（ ）。\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
    assert extract_options(stem) == ["A: 甲", "B: 乙", "C: 丙", "D: 丁"]


def test_options_inline_after_bracket():
    """Options packed inline after '（）' are still extracted."""
    stem = "正确的是：（）A. 甲; B. 乙; C. 丙; D. 丁"
    assert extract_options(stem) == ["A: 甲", "B: 乙", "C: 丙", "D: 丁"]


def test_no_options_when_stem_has_none():
    assert extract_options("孟德尔测交子代表型比例应为（ ）") == []


def test_missing_properties_degrades_without_raising():
    quiz = exercise_to_quiz({"id": "exe0", "label": "Exercise", "properties": {}}, "cpt1")
    assert quiz["question"] == ""
    assert quiz["expected_answer"] == ""
    assert quiz["difficulty"] is None


# ── variant_exercises ─────────────────────────────────────────────────────


def _tiered_kg() -> _FakeKG:
    """cptA has one direct exercise, its section holds another, a neighbouring
    concept a third, and the chapter a fourth — one per widening tier."""
    nodes = {
        "cptA": {"id": "cptA", "label": "Concept", "name": "A"},
        "cptB": {"id": "cptB", "label": "Concept", "name": "B"},
        "sec1": {"id": "sec1", "label": "Section", "name": "第一节"},
        "sec2": {"id": "sec2", "label": "Section", "name": "第二节"},
        "ch1": {"id": "ch1", "label": "Chapter", "name": "第一章"},
        "exeDirect": _exercise("exeDirect", stem="直接题", answer="a1", difficulty=3, type="填空题"),
        "exeSection": _exercise("exeSection", stem="同节题", answer="a2", difficulty=1, type="填空题"),
        "exeNeighbor": _exercise("exeNeighbor", stem="邻接题", answer="a3", difficulty=2, type="填空题"),
        "exeChapter": _exercise("exeChapter", stem="同章题", answer="a4", difficulty=2, type="填空题"),
        "exeEmpty": {"id": "exeEmpty", "label": "Exercise", "properties": {}},
    }
    adj = {
        "appears_in": {"cptA": ["sec1"], "cptB": ["sec2"]},
        "is_part_of": {"sec1": ["ch1"], "sec2": ["ch1"]},
        "prerequisites_for": {"cptA": []},
    }
    adj_rev = {
        "tests_concept": {"cptA": ["exeDirect"], "cptB": ["exeNeighbor"]},
        "appears_in": {"sec1": ["cptA", "exeDirect", "exeSection", "exeEmpty"], "sec2": ["exeChapter"]},
        "is_part_of": {"ch1": ["sec1", "sec2"]},
        "prerequisites_for": {"cptA": ["cptB"]},
    }
    return _FakeKG(nodes, adj, adj_rev)


def test_variant_exercise_widens_through_tiers():
    """Direct edges are sparse, so the lookup must widen to fill the count."""
    kg_patch, avail_patch = _patch_kg(_tiered_kg())
    with kg_patch, avail_patch:
        variants = variant_exercises("cptA", count=4)
    assert [v["exercise_id"] for v in variants] == [
        "exeDirect",
        "exeSection",
        "exeNeighbor",
        "exeChapter",
    ]
    assert [v["source"] for v in variants] == ["direct", "section", "neighbor", "chapter"]


def test_variant_exercise_returns_at_least_two():
    """The doc's acceptance bar: >= 2 variants for a concept with one direct."""
    kg_patch, avail_patch = _patch_kg(_tiered_kg())
    with kg_patch, avail_patch:
        variants = variant_exercises("cptA", count=2)
    assert len(variants) == 2
    assert len({v["exercise_id"] for v in variants}) == 2


def test_variant_difficulty_filter():
    kg_patch, avail_patch = _patch_kg(_tiered_kg())
    with kg_patch, avail_patch:
        variants = variant_exercises("cptA", count=5, difficulty="基础")
    assert [v["exercise_id"] for v in variants] == ["exeSection"]
    assert all(v["difficulty"] == 1 for v in variants)


def test_variant_excludes_attempted():
    kg_patch, avail_patch = _patch_kg(_tiered_kg())
    with kg_patch, avail_patch:
        variants = variant_exercises("cptA", count=2, exclude=["exeDirect"])
    assert "exeDirect" not in {v["exercise_id"] for v in variants}


def test_variant_skips_unanswerable_exercises():
    """An Exercise node with no stem/answer is dropped, not served."""
    kg_patch, avail_patch = _patch_kg(_tiered_kg())
    with kg_patch, avail_patch:
        variants = variant_exercises("cptA", count=10)
    assert "exeEmpty" not in {v["exercise_id"] for v in variants}


def test_variant_requires_dataset():
    with patch(
        "deeptutor.capabilities.mastery.exercise_adapter.is_available", return_value=False
    ), pytest.raises(RuntimeError, match="K12-KGraph"):
        variant_exercises("cptA")
