"""Unit tests for the ER-13 study-archive overlay
(``deeptutor._local.study_archive_router``).

Covers the per-path rollup helper (``_progress_stats``) and the aggregate
endpoint with mocked storage: empty state, invalid/skipped books, weak-point
merging across books, timeline ordering and overall rollup.
"""

from __future__ import annotations

from time import mktime
from unittest import mock
from datetime import date, timedelta

import pytest

from deeptutor._local import study_archive_router as mod
from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    QuizAttempt,
)


def _ts(days_ago: int) -> float:
    return float(mktime((date.today() - timedelta(days=days_ago)).timetuple()))


def _progress(
    book_id: str,
    mastery: dict[str, float] | None = None,
    kps: list[str] | None = None,
    errors_open: int = 0,
    errors_graduated: int = 0,
    quizzes: int = 0,
    updated_days_ago: int = 0,
) -> LearningProgress:
    mastery = mastery or {}
    kp_ids = kps or list(mastery)
    module = LearningModule(
        id="m1", name=f"{book_id} 模块", order=0,
        knowledge_points=[
            KnowledgePoint(id=kid, name=f"KP {kid}", type=KnowledgeType.MEMORY, module_id="m1")
            for kid in kp_ids
        ],
    )
    progress = LearningProgress(book_id=book_id, modules=[module])
    progress.mastery_levels = dict(mastery)
    progress.updated_at = _ts(updated_days_ago)
    for i in range(errors_open):
        progress.error_records.append(
            ErrorRecord(
                id=f"o{i}", question_id=f"oq{i}", knowledge_point_id=kp_ids[i % max(len(kp_ids), 1)],
                module_id="m1", error_type=ErrorType.APPLICATION_ERROR,
                status="active" if i % 2 == 0 else "retrying", created_at=_ts(1),
            )
        )
    for i in range(errors_graduated):
        progress.error_records.append(
            ErrorRecord(
                id=f"g{i}", question_id=f"gq{i}", knowledge_point_id=kp_ids[i % max(len(kp_ids), 1)],
                module_id="m1", error_type=ErrorType.APPLICATION_ERROR,
                status="graduated", created_at=_ts(2),
            )
        )
    for i in range(quizzes):
        progress.quiz_attempts.append(
            QuizAttempt(
                question_id=f"qz{i}", knowledge_point_id=kp_ids[i % max(len(kp_ids), 1)],
                module_id="m1", is_correct=i % 2 == 0, timestamp=_ts(updated_days_ago),
            )
        )
    return progress


# ---------------------------------------------------------------------------
# _progress_stats
# ---------------------------------------------------------------------------


def test_progress_stats_empty_path():
    p = LearningProgress(book_id="b")
    st = mod._progress_stats(p)
    assert st["kp_count"] == 0
    assert st["mastered_count"] == 0
    assert st["avg_mastery"] == 0.0
    assert st["quiz_count"] == 0 and st["error_count"] == 0


def test_progress_stats_counts_module_kps_when_no_mastery():
    p = _progress("b", kps=["a", "b", "c"])
    st = mod._progress_stats(p)
    assert st["kp_count"] == 3
    assert st["mastered_count"] == 0
    assert st["avg_mastery"] == 0.0


def test_progress_stats_mastery_rollup():
    p = _progress("b", mastery={"a": 0.9, "b": 0.5, "c": 0.8})
    st = mod._progress_stats(p)
    assert st["kp_count"] == 3
    assert st["mastered_count"] == 2  # 0.9 & 0.8 ≥ 0.8; 0.5 not
    assert st["avg_mastery"] == 0.7333  # round((0.9+0.5+0.8)/3, 4)


def test_progress_stats_error_count_only_open():
    p = _progress("b", mastery={"a": 0.4}, errors_open=3, errors_graduated=2)
    st = mod._progress_stats(p)
    assert st["error_count"] == 3  # active/retrying only


# ---------------------------------------------------------------------------
# GET /archive (endpoint, mocked storage)
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, books: dict[str, LearningProgress]) -> None:
        self._books = books

    def load(self, book_id: str):
        return self._books.get(book_id)


class _FakeService:
    def __init__(self, summaries: list[dict]) -> None:
        self._summaries = summaries

    def list_progress(self) -> dict:
        return {"summaries": self._summaries, "errors": []}


def _patched_endpoint(books: dict[str, LearningProgress]):
    store = _FakeStore(books)
    service = _FakeService([{"book_id": bid, "name": f"{bid}名"} for bid in books])
    stack = [
        mock.patch.object(mod, "LearningStore", return_value=store),
        mock.patch.object(mod, "LearningService", return_value=service),
    ]
    for p in stack:
        p.start()
    return stack


@pytest.mark.asyncio
async def test_archive_empty():
    stack = _patched_endpoint({})
    try:
        out = await mod.study_archive()
    finally:
        for p in stack:
            p.stop()
    assert out["books"] == [] and out["timeline"] == [] and out["weak_points"] == []
    assert out["overall"] == {
        "path_count": 0, "kp_count": 0, "mastered_count": 0,
        "avg_mastery_pct": 0.0, "quiz_count": 0, "error_count": 0,
    }


@pytest.mark.asyncio
async def test_archive_skips_missing_progress():
    # Summary exists but store.load returns None → skipped entirely.
    store = _FakeStore({})
    service = _FakeService([{"book_id": "missing", "name": "x"}])
    stack = [
        mock.patch.object(mod, "LearningStore", return_value=store),
        mock.patch.object(mod, "LearningService", return_value=service),
    ]
    for p in stack:
        p.start()
    try:
        out = await mod.study_archive()
    finally:
        for p in stack:
            p.stop()
    assert out["books"] == []
    assert out["overall"]["path_count"] == 0


@pytest.mark.asyncio
async def test_archive_rollup_and_timeline_order():
    older = _progress("old", mastery={"a": 0.9, "b": 0.3}, errors_open=1, quizzes=4, updated_days_ago=5)
    newer = _progress("new", mastery={"c": 0.8}, errors_open=2, quizzes=2, updated_days_ago=1)
    stack = _patched_endpoint({"old": older, "new": newer})
    try:
        out = await mod.study_archive()
    finally:
        for p in stack:
            p.stop()

    # Timeline is newest-updated first.
    assert [b["book_id"] for b in out["timeline"]] == ["new", "old"]
    assert out["overall"]["path_count"] == 2
    assert out["overall"]["kp_count"] == 3  # 2 + 1
    assert out["overall"]["mastered_count"] == 2
    assert out["overall"]["quiz_count"] == 6
    assert out["overall"]["error_count"] == 3
    # 2 mastered / 3 kp → 66.7%
    assert out["overall"]["avg_mastery_pct"] == pytest.approx(66.7, abs=0.1)

    by_id = {b["book_id"]: b for b in out["books"]}
    assert by_id["new"]["name"] == "new名"
    assert by_id["new"]["error_count"] == 2


@pytest.mark.asyncio
async def test_archive_weak_points_merged_across_books():
    # Same weak kp appears in two books — the higher-score entry wins.
    p1 = _progress("b1", mastery={"a": 0.1, "b": 0.9})
    p1.consecutive_wrong = {"a": 3}
    p1.dep_map = {"a": []}
    p1.error_records.append(
        ErrorRecord(id="e1", question_id="q1", knowledge_point_id="a", module_id="m1",
                    error_type=ErrorType.APPLICATION_ERROR, status="active", created_at=_ts(1))
    )
    p2 = _progress("b2", mastery={"a": 0.6, "c": 0.9})
    p2.consecutive_wrong = {"a": 0}
    p2.error_records.append(
        ErrorRecord(id="e2", question_id="q2", knowledge_point_id="a", module_id="m1",
                    error_type=ErrorType.APPLICATION_ERROR, status="active", created_at=_ts(1))
    )
    stack = _patched_endpoint({"b1": p1, "b2": p2})
    try:
        out = await mod.study_archive()
    finally:
        for p in stack:
            p.stop()

    # Exactly one merged entry for kp "a", coming from the higher-score book.
    ids = [w["knowledge_point_id"] for w in out["weak_points"]]
    assert ids.count("a") == 1
    merged = next(w for w in out["weak_points"] if w["knowledge_point_id"] == "a")
    assert merged["error_count"] == 1  # the winning book's count
    assert out["weak_points"] == sorted(out["weak_points"], key=lambda w: -w["score"])
