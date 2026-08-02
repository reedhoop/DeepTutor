"""Error book — cause attribution, weak-point ranking, and root-cause backfill.

What the engine already does (verified against the code, not assumed):

* ``LearningService.record_quiz_attempt`` already opens an ``ErrorRecord`` on a
  wrong answer, appends retries, and graduates it on a later correct answer.
* ``SpacedRepetitionScheduler.build_review_queue`` already gives knowledge
  points with an open error record ``priority = 1`` — ahead of every type-based
  priority.

So collection and review priority are NOT re-implemented here. This module adds
the three things that were genuinely missing:

1. **Cause attribution with structure.** ``grading.classify_error`` only splits
   "blank answer" from "everything else". :func:`infer_error_type` reads the
   KGraph dependency map, the knowledge type, and the streak counter, so a
   wrong answer whose *prerequisite* is unmastered is filed as structural
   rather than as a careless application slip.
2. **Weak-point ranking.** A single score over mastery, error volume, and the
   current wrong streak, with the root-cause reason in plain Chinese.
3. **Root-cause backfill.** Review order that puts an unmastered prerequisite
   *before* the knowledge point that keeps failing.

This complements — does not duplicate — the Stage 1 policy overlay: that one
moves the *teaching cursor* back to a prerequisite mid-lesson; this one orders
*review and re-practice* after the fact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgeType,
    LearningProgress,
)
from deeptutor.learning.policy import find_knowledge_point, is_mastered

if TYPE_CHECKING:
    from deeptutor.learning.models import KnowledgePoint

# A KP missed this many times in a row is a method problem, not a slip.
_STUCK_STREAK = 3
# Weak-point score weights (sum to 1.0 before the structural bonus).
_W_MASTERY, _W_ERRORS, _W_STREAK = 0.5, 0.3, 0.2
_ERROR_SATURATION, _STREAK_SATURATION = 5, 3
# Added when an unmastered prerequisite explains the failure — root causes
# outrank symptoms even at equal mastery.
_STRUCTURAL_BONUS = 0.15

ERROR_TYPE_LABELS: dict[ErrorType, str] = {
    ErrorType.KNOWLEDGE_STRUCTURAL: "知识结构性",
    ErrorType.UNDERSTANDING_DEVIATION: "理解偏差型",
    ErrorType.APPLICATION_ERROR: "应用错误",
    ErrorType.METACOGNITIVE: "元认知型",
}


@dataclass(frozen=True)
class WeakPoint:
    knowledge_point_id: str
    name: str
    module_id: str
    mastery: float
    error_count: int
    consecutive_wrong: int
    unmet_prereqs: list[str] = field(default_factory=list)
    score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── cause attribution ─────────────────────────────────────────────────────


def unmet_prerequisites(progress: LearningProgress, kp_id: str) -> list[str]:
    """In-path prerequisites of *kp_id* that are not mastered yet.

    Prerequisites outside the current path are assumed known (the learner may
    have covered them elsewhere) — same rule as the policy overlay.
    """
    unmet: list[str] = []
    for pid in progress.dep_map.get(kp_id, []):
        prereq, _, _ = find_knowledge_point(progress, pid)
        if prereq is not None and not is_mastered(progress, prereq):
            unmet.append(pid)
    return unmet


def infer_error_type(
    progress: LearningProgress, kp_id: str, user_answer: str = ""
) -> ErrorType:
    """Classify *why* an answer was wrong, using structure the grader can't see.

    Order matters: a blank answer is self-reported ignorance; an unmastered
    prerequisite is the root cause whatever the surface mistake looks like; a
    long streak on one point is a method problem; a concept-type miss is a
    comprehension gap; everything else is an application slip.
    """
    if not user_answer.strip():
        return ErrorType.METACOGNITIVE
    if unmet_prerequisites(progress, kp_id):
        return ErrorType.KNOWLEDGE_STRUCTURAL
    if progress.consecutive_wrong.get(kp_id, 0) >= _STUCK_STREAK:
        return ErrorType.METACOGNITIVE
    kp_type = progress.knowledge_types.get(kp_id)
    if kp_type in (KnowledgeType.CONCEPT, KnowledgeType.DESIGN):
        return ErrorType.UNDERSTANDING_DEVIATION
    return ErrorType.APPLICATION_ERROR


def refine_latest_error(progress: LearningProgress, kp_id: str, correct: bool) -> None:
    """Post-grade hook: re-file the record the engine just opened.

    ``record_quiz_attempt`` classifies from the answer text alone; by the time
    this runs the attempt is recorded and the streak counter updated, so the
    structural signals are all available. Only open records are touched — a
    graduated record keeps the cause it was closed with.
    """
    if correct or not kp_id:
        return
    attempt = next(
        (a for a in reversed(progress.quiz_attempts) if a.knowledge_point_id == kp_id),
        None,
    )
    record = next(
        (
            r
            for r in reversed(progress.error_records)
            if r.knowledge_point_id == kp_id and r.status in ("active", "retrying")
        ),
        None,
    )
    if record is None:
        return
    refined = infer_error_type(progress, kp_id, str(attempt.user_answer or "") if attempt else "")
    record.error_type = refined
    if attempt is not None:
        attempt.error_type = refined


# ── weak points + backfill ────────────────────────────────────────────────


def weak_points(progress: LearningProgress, top_k: int = 5) -> list[WeakPoint]:
    """Rank the learner's weakest knowledge points, worst first.

    Only points with a real signal (unmastered, or with an error record) are
    returned, so an untouched path yields an empty list rather than a wall of
    zero-mastery placeholders.
    """
    error_counts: dict[str, int] = {}
    for record in progress.error_records:
        if record.status in ("active", "retrying"):
            error_counts[record.knowledge_point_id] = (
                error_counts.get(record.knowledge_point_id, 0) + 1
            )

    attempted = {a.knowledge_point_id for a in progress.quiz_attempts}
    ranked: list[WeakPoint] = []
    for module in progress.modules:
        for kp in module.knowledge_points:
            errors = error_counts.get(kp.id, 0)
            if is_mastered(progress, kp) and not errors:
                continue
            if not errors and kp.id not in attempted:
                continue  # not yet studied — weak-by-default is not a signal
            ranked.append(_score(progress, kp, module.id, errors))

    ranked.sort(key=lambda w: (-w.score, w.knowledge_point_id))
    return ranked[:top_k]


def _score(
    progress: LearningProgress, kp: KnowledgePoint, module_id: str, errors: int
) -> WeakPoint:
    mastery = progress.mastery_levels.get(kp.id, 0.0)
    streak = progress.consecutive_wrong.get(kp.id, 0)
    unmet = unmet_prerequisites(progress, kp.id)
    score = (
        _W_MASTERY * (1.0 - mastery)
        + _W_ERRORS * min(errors, _ERROR_SATURATION) / _ERROR_SATURATION
        + _W_STREAK * min(streak, _STREAK_SATURATION) / _STREAK_SATURATION
    )
    if unmet:
        score += _STRUCTURAL_BONUS
    return WeakPoint(
        knowledge_point_id=kp.id,
        name=kp.name,
        module_id=module_id,
        mastery=round(mastery, 3),
        error_count=errors,
        consecutive_wrong=streak,
        unmet_prereqs=unmet,
        score=round(score, 4),
        reason=_reason(progress, kp, errors, streak, unmet),
    )


def _reason(
    progress: LearningProgress,
    kp: KnowledgePoint,
    errors: int,
    streak: int,
    unmet: list[str],
) -> str:
    if unmet:
        names = "、".join(_kp_name(progress, pid) for pid in unmet[:2])
        return f"前置「{names}」尚未掌握，先补根因"
    if streak >= _STUCK_STREAK:
        return f"连续答错 {streak} 次，方法可能有偏差"
    if errors:
        return f"错题 {errors} 道待订正"
    return "掌握度未达标，建议再练"


def _kp_name(progress: LearningProgress, kp_id: str) -> str:
    kp, _, _ = find_knowledge_point(progress, kp_id)
    return kp.name if kp else kp_id


def review_backfill(progress: LearningProgress, top_k: int = 3) -> list[str]:
    """Re-practice order for the weakest points, root causes first.

    For each weak point its unmastered prerequisites are emitted *before* it,
    so the learner rebuilds the foundation instead of grinding the symptom.
    """
    ordered: list[str] = []
    for weak in weak_points(progress, top_k=top_k):
        for pid in weak.unmet_prereqs:
            if pid not in ordered:
                ordered.append(pid)
        if weak.knowledge_point_id not in ordered:
            ordered.append(weak.knowledge_point_id)
    return ordered


# ── queries ───────────────────────────────────────────────────────────────


def filter_records(
    progress: LearningProgress,
    *,
    error_type: ErrorType | str | None = None,
    status: str | None = None,
    knowledge_point_id: str | None = None,
) -> list[ErrorRecord]:
    """Error records matching every supplied filter, newest first."""
    wanted = ErrorType(error_type) if isinstance(error_type, str) else error_type
    records = [
        r
        for r in progress.error_records
        if (wanted is None or r.error_type == wanted)
        and (status is None or r.status == status)
        and (knowledge_point_id is None or r.knowledge_point_id == knowledge_point_id)
    ]
    records.sort(key=lambda r: r.created_at, reverse=True)
    return records


def summarize(progress: LearningProgress, top_k: int = 5) -> dict:
    """Error-book payload for the REST layer / dashboard."""
    open_records = [r for r in progress.error_records if r.status in ("active", "retrying")]
    by_type: dict[str, int] = {}
    for record in open_records:
        label = ERROR_TYPE_LABELS.get(record.error_type, record.error_type.value)
        by_type[label] = by_type.get(label, 0) + 1
    return {
        "book_id": progress.book_id,
        "total_records": len(progress.error_records),
        "open_records": len(open_records),
        "graduated_records": sum(1 for r in progress.error_records if r.status == "graduated"),
        "by_error_type": by_type,
        "weak_points": [w.to_dict() for w in weak_points(progress, top_k=top_k)],
        "backfill_order": review_backfill(progress, top_k=top_k),
        "records": [
            {
                "id": r.id,
                "knowledge_point_id": r.knowledge_point_id,
                "knowledge_point_name": _kp_name(progress, r.knowledge_point_id),
                "module_id": r.module_id,
                "error_type": r.error_type.value,
                "error_type_label": ERROR_TYPE_LABELS.get(r.error_type, ""),
                "status": r.status,
                "retry_count": len(r.retry_history),
                "created_at": r.created_at,
            }
            for r in filter_records(progress)
        ],
    }


__all__ = [
    "ERROR_TYPE_LABELS",
    "WeakPoint",
    "filter_records",
    "infer_error_type",
    "refine_latest_error",
    "review_backfill",
    "summarize",
    "unmet_prerequisites",
    "weak_points",
]
