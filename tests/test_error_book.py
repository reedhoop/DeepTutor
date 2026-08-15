"""Stage 3 — error book: cause attribution, weak-point ranking, backfill."""

from __future__ import annotations

from unittest import mock

import pytest

from deeptutor.capabilities.mastery import error_book as eb
from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    QuizAttempt,
)


@pytest.fixture(autouse=True)
def _pin_zh_response_language():
    """weak_points / summarize are now language-aware; pin the response
    language to zh so the Chinese assertions below stay deterministic
    regardless of the host's interface.json."""
    with mock.patch.object(eb, "get_response_language", return_value="zh"):
        yield


def _progress(**kwargs) -> LearningProgress:
    """A two-KP path: ``kp_base`` (memory) is a prerequisite of ``kp_top``."""
    module = LearningModule(
        id="m1",
        name="模块一",
        order=0,
        knowledge_points=[
            KnowledgePoint(id="kp_base", name="底层概念", type=KnowledgeType.MEMORY, module_id="m1"),
            KnowledgePoint(id="kp_top", name="上层技能", type=KnowledgeType.PROCEDURE, module_id="m1"),
            KnowledgePoint(id="kp_idea", name="核心观念", type=KnowledgeType.CONCEPT, module_id="m1"),
        ],
    )
    defaults = dict(
        book_id="b1",
        modules=[module],
        dep_map={"kp_top": ["kp_base"], "kp_base": [], "kp_idea": []},
        knowledge_types={
            "kp_base": KnowledgeType.MEMORY,
            "kp_top": KnowledgeType.PROCEDURE,
            "kp_idea": KnowledgeType.CONCEPT,
        },
    )
    defaults.update(kwargs)
    return LearningProgress(**defaults)


def _wrong_attempt(kp_id: str, answer: str = "错的", qid: str = "q1") -> QuizAttempt:
    return QuizAttempt(
        question_id=qid,
        knowledge_point_id=kp_id,
        module_id="m1",
        is_correct=False,
        user_answer=answer,
        error_type=ErrorType.APPLICATION_ERROR,
    )


def _record(kp_id: str, error_type=ErrorType.APPLICATION_ERROR, status="active") -> ErrorRecord:
    return ErrorRecord(
        id=f"r_{kp_id}_{status}",
        question_id="q1",
        knowledge_point_id=kp_id,
        module_id="m1",
        error_type=error_type,
        status=status,
    )


# ── cause attribution ─────────────────────────────────────────────────────


def test_blank_answer_is_metacognitive():
    assert eb.infer_error_type(_progress(), "kp_top", "") == ErrorType.METACOGNITIVE


def test_unmastered_prerequisite_is_structural():
    """The root cause outranks the surface mistake."""
    progress = _progress(mastery_levels={"kp_base": 0.2})
    assert eb.infer_error_type(progress, "kp_top", "写错了") == ErrorType.KNOWLEDGE_STRUCTURAL


def test_mastered_prerequisite_is_application_error():
    progress = _progress(mastery_levels={"kp_base": 1.0})
    assert eb.infer_error_type(progress, "kp_top", "写错了") == ErrorType.APPLICATION_ERROR


def test_concept_type_is_understanding_deviation():
    progress = _progress(mastery_levels={"kp_base": 1.0})
    assert eb.infer_error_type(progress, "kp_idea", "我觉得是…") == ErrorType.UNDERSTANDING_DEVIATION


def test_long_streak_is_metacognitive():
    """Three misses in a row on a point with no missing prerequisite is a
    method problem, not a slip."""
    progress = _progress(mastery_levels={"kp_base": 1.0}, consecutive_wrong={"kp_top": 3})
    assert eb.infer_error_type(progress, "kp_top", "又错了") == ErrorType.METACOGNITIVE


def test_external_prerequisite_is_not_structural():
    """A prerequisite outside the path is assumed known (same rule as the
    policy overlay), so it must not force a structural verdict."""
    progress = _progress(dep_map={"kp_top": ["kp_elsewhere"]}, mastery_levels={"kp_base": 1.0})
    assert eb.infer_error_type(progress, "kp_top", "写错了") == ErrorType.APPLICATION_ERROR


def test_refine_latest_error_upgrades_open_record():
    """The post-grade hook re-files the record the engine just opened."""
    progress = _progress(
        mastery_levels={"kp_base": 0.1},
        quiz_attempts=[_wrong_attempt("kp_top")],
        error_records=[_record("kp_top")],
    )
    eb.refine_latest_error(progress, "kp_top", correct=False)
    assert progress.error_records[0].error_type == ErrorType.KNOWLEDGE_STRUCTURAL
    assert progress.quiz_attempts[0].error_type == ErrorType.KNOWLEDGE_STRUCTURAL


def test_refine_leaves_graduated_records_alone():
    progress = _progress(
        mastery_levels={"kp_base": 0.1},
        quiz_attempts=[_wrong_attempt("kp_top")],
        error_records=[_record("kp_top", status="graduated")],
    )
    eb.refine_latest_error(progress, "kp_top", correct=False)
    assert progress.error_records[0].error_type == ErrorType.APPLICATION_ERROR


def test_refine_is_a_noop_on_correct_answers():
    progress = _progress(error_records=[_record("kp_top")])
    eb.refine_latest_error(progress, "kp_top", correct=True)
    assert progress.error_records[0].error_type == ErrorType.APPLICATION_ERROR


# ── weak points ───────────────────────────────────────────────────────────


def test_get_weak_kps_ranks_worst_first():
    progress = _progress(
        mastery_levels={"kp_base": 0.9, "kp_top": 0.2, "kp_idea": 0.5},
        quiz_attempts=[
            _wrong_attempt("kp_top"),
            _wrong_attempt("kp_idea"),
            _wrong_attempt("kp_base"),
        ],
        error_records=[_record("kp_top"), _record("kp_idea")],
    )
    ranked = eb.weak_points(progress, top_k=3)
    assert ranked[0].knowledge_point_id == "kp_top"
    assert ranked[0].score > ranked[1].score


def test_weak_points_skip_untouched_objectives():
    """A path nobody has practised yet is not "all weak"."""
    assert eb.weak_points(_progress()) == []


def test_weak_point_reports_root_cause():
    progress = _progress(
        mastery_levels={"kp_base": 0.1, "kp_top": 0.3},
        quiz_attempts=[_wrong_attempt("kp_top")],
        error_records=[_record("kp_top")],
    )
    top = next(w for w in eb.weak_points(progress, top_k=3) if w.knowledge_point_id == "kp_top")
    assert top.unmet_prereqs == ["kp_base"]
    assert "底层概念" in top.reason


def test_structural_bonus_outranks_equal_mastery():
    """Two points at equal mastery: the one whose prerequisite is missing
    ranks higher, because fixing it fixes both."""
    progress = _progress(
        mastery_levels={"kp_base": 0.3, "kp_top": 0.3, "kp_idea": 0.3},
        quiz_attempts=[_wrong_attempt("kp_top"), _wrong_attempt("kp_idea")],
    )
    ranked = {w.knowledge_point_id: w.score for w in eb.weak_points(progress, top_k=5)}
    assert ranked["kp_top"] > ranked["kp_idea"]


# ── backfill + queries ────────────────────────────────────────────────────


def test_schedule_review_priority_puts_prereq_first():
    """Root-cause backfill: rebuild the foundation before the symptom."""
    progress = _progress(
        mastery_levels={"kp_base": 0.1, "kp_top": 0.2},
        quiz_attempts=[_wrong_attempt("kp_top")],
        error_records=[_record("kp_top")],
    )
    order = eb.review_backfill(progress, top_k=2)
    assert order.index("kp_base") < order.index("kp_top")


def test_error_type_filter():
    progress = _progress(
        error_records=[
            _record("kp_top", ErrorType.KNOWLEDGE_STRUCTURAL),
            _record("kp_idea", ErrorType.UNDERSTANDING_DEVIATION),
        ]
    )
    structural = eb.filter_records(progress, error_type=ErrorType.KNOWLEDGE_STRUCTURAL)
    assert [r.knowledge_point_id for r in structural] == ["kp_top"]
    # The legacy Chinese label resolves to the same enum member.
    assert eb.filter_records(progress, error_type="知识结构性") == structural


def test_status_filter():
    progress = _progress(
        error_records=[_record("kp_top"), _record("kp_idea", status="graduated")]
    )
    assert [r.knowledge_point_id for r in eb.filter_records(progress, status="graduated")] == [
        "kp_idea"
    ]


def test_summarize_payload_shape():
    progress = _progress(
        mastery_levels={"kp_base": 0.1, "kp_top": 0.2},
        quiz_attempts=[_wrong_attempt("kp_top")],
        error_records=[
            _record("kp_top", ErrorType.KNOWLEDGE_STRUCTURAL),
            _record("kp_idea", status="graduated"),
        ],
    )
    payload = eb.summarize(progress, top_k=3)
    assert payload["open_records"] == 1
    assert payload["graduated_records"] == 1
    assert payload["by_error_type"] == {"知识结构性": 1}
    assert payload["backfill_order"][0] == "kp_base"
    assert payload["records"][0]["knowledge_point_name"] in ("上层技能", "核心观念")
