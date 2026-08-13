"""Unit tests for the ER-14 motivation overlay
(``deeptutor._local.motivation_overlay``).

Covers the streak / max-correct-run / activity-date derivation helpers and the
badge builder with exact boundary assertions, plus an endpoint-level check of
the points economy using mocked storage.
"""

from __future__ import annotations

from datetime import date, timedelta
from time import mktime
from unittest import mock

import pytest

from deeptutor._local import motivation_overlay as mod
from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgeType,
    LearningProgress,
    QuizAttempt,
)


def _ts(d: date) -> float:
    """Seconds-since-epoch for midnight of *d* (local time)."""
    return float(mktime(d.timetuple()))


# ---------------------------------------------------------------------------
# _activity_dates
# ---------------------------------------------------------------------------


def test_activity_dates_collects_all_sources():
    today = date.today()
    y = today - timedelta(days=1)
    progress = LearningProgress(
        book_id="b",
        created_at=_ts(y),
        updated_at=_ts(today),
        quiz_attempts=[
            QuizAttempt(
                question_id="q1", knowledge_point_id="kp", is_correct=True,
                timestamp=_ts(today),
            ),
            QuizAttempt(
                question_id="q2", knowledge_point_id="kp", is_correct=False,
                timestamp=_ts(y),
            ),
        ],
        error_records=[
            ErrorRecord(
                id="e1", question_id="q2", knowledge_point_id="kp",
                module_id="m", error_type=ErrorType.APPLICATION_ERROR,
                created_at=_ts(y - timedelta(days=1)),
            ),
        ],
    )
    days = mod._activity_dates(progress)
    assert days == {y - timedelta(days=1), y, today}


def test_activity_dates_skips_missing_timestamps():
    # 0.0 / None timestamps are falsy → skipped, so no activity day is derived.
    progress = LearningProgress(book_id="b", created_at=0.0, updated_at=0.0)
    assert mod._activity_dates(progress) == set()


# ---------------------------------------------------------------------------
# _max_correct_run
# ---------------------------------------------------------------------------


def _attempts(flags: list[bool], offsets: list[int] | None = None) -> list[QuizAttempt]:
    base = _ts(date.today())
    offsets = offsets or list(range(len(flags)))
    return [
        QuizAttempt(
            question_id=f"q{i}", knowledge_point_id="kp", is_correct=flag,
            timestamp=base + off,
        )
        for i, (flag, off) in enumerate(zip(flags, offsets))
    ]


def test_max_correct_run_empty():
    assert mod._max_correct_run([]) == (0, None)


def test_max_correct_run_all_correct():
    run, ts = mod._max_correct_run(_attempts([True, True, True]))
    assert run == 3 and ts is not None


def test_max_correct_run_all_wrong():
    assert mod._max_correct_run(_attempts([False, False])) == (0, None)


def test_max_correct_run_interleaved():
    run, _ = mod._max_correct_run(_attempts([True, True, False, True, True, True]))
    assert run == 3


def test_max_correct_run_sorts_by_timestamp():
    # Flags arrive out of time order: T@20, T@0, F@10.
    # Chronologically: T(0), F(10), T(20) → best run = 1.
    attempts = [
        QuizAttempt(question_id="a", knowledge_point_id="k", is_correct=True, timestamp=20),
        QuizAttempt(question_id="b", knowledge_point_id="k", is_correct=True, timestamp=0),
        QuizAttempt(question_id="c", knowledge_point_id="k", is_correct=False, timestamp=10),
    ]
    run, _ = mod._max_correct_run(attempts)
    assert run == 1

    # F@30, T@0, T@10 → chronologically T,T,F → best run = 2.
    attempts2 = [
        QuizAttempt(question_id="a", knowledge_point_id="k", is_correct=False, timestamp=30),
        QuizAttempt(question_id="b", knowledge_point_id="k", is_correct=True, timestamp=0),
        QuizAttempt(question_id="c", knowledge_point_id="k", is_correct=True, timestamp=10),
    ]
    run2, _ = mod._max_correct_run(attempts2)
    assert run2 == 2


# ---------------------------------------------------------------------------
# _streak_stats
# ---------------------------------------------------------------------------


def test_streak_empty():
    s = mod._streak_stats(set())
    assert s["current"] == 0 and s["longest"] == 0 and s["active_days"] == 0
    assert s["last_active"] is None and s["today_active"] is False
    assert s["recent"] == []


def test_streak_single_day_today():
    s = mod._streak_stats({date.today()})
    assert s["current"] == 1 and s["longest"] == 1 and s["active_days"] == 1
    assert s["today_active"] is True


def test_streak_three_consecutive_days():
    today = date.today()
    days = {today, today - timedelta(days=1), today - timedelta(days=2)}
    s = mod._streak_stats(days)
    assert s["current"] == 3 and s["longest"] == 3 and s["active_days"] == 3


def test_streak_grace_keeps_current_when_last_active_yesterday():
    today = date.today()
    y = today - timedelta(days=1)
    days = {y, y - timedelta(days=1), y - timedelta(days=2)}
    s = mod._streak_stats(days)
    assert s["current"] == 3  # yesterday-anchored streak survives until today ends
    assert s["longest"] == 3
    assert s["today_active"] is False


def test_streak_broken_when_last_active_two_days_ago():
    today = date.today()
    two = today - timedelta(days=2)
    s = mod._streak_stats({two, two - timedelta(days=1)})
    assert s["current"] == 0  # gap of 2 days kills the current streak
    assert s["longest"] == 2


def test_streak_longest_survives_gap_but_current_does_not():
    today = date.today()
    s = mod._streak_stats({today, today - timedelta(days=5), today - timedelta(days=6)})
    assert s["longest"] == 2 and s["current"] == 1


def test_streak_duplicate_dates_deduplicated():
    today = date.today()
    s = mod._streak_stats({today, today})
    assert s["active_days"] == 1 and s["longest"] == 1


def test_streak_recent_strip_length_and_flags():
    today = date.today()
    s = mod._streak_stats({today, today - timedelta(days=3)})
    assert len(s["recent"]) == 14
    assert s["recent"][-1]["date"] == today.isoformat()
    assert s["recent"][-1]["active"] is True
    assert s["recent"][0]["active"] is False  # 13 days ago
    assert sum(1 for r in s["recent"] if r["active"]) == 2


# ---------------------------------------------------------------------------
# _build_badges
# ---------------------------------------------------------------------------


def _badges(**kw) -> list[dict]:
    defaults = dict(
        total_quizzes=0, mastered_count=0, mastered_types=set(), max_run=0,
        longest_streak=0, active_days=0, error_graduated=False,
        first_quiz_ts=None, mastery_ref_ts=None, run_end_ts=None,
        graduated_ts=None, last_active_ts=None,
        diagnose_count=0, diagnose_last_ts=None,
    )
    defaults.update(kw)
    return mod._build_badges(**defaults)


def test_badges_all_zero():
    badges = _badges()
    assert len(badges) == 14
    assert all(b["earned"] is False for b in badges)
    assert all(b["progress"] == 0.0 for b in badges)
    assert all("earned_at" not in b for b in badges)
    assert [b["id"] for b in badges] == [
        "first_quiz", "first_mastery", "quiz_run_5", "streak_3", "streak_7",
        "streak_30", "mastery_10", "mastery_50", "mastery_100",
        "error_graduate", "all_types", "active_10", "diagnose_1", "diagnose_10",
    ]


def test_badges_first_quiz_boundary():
    assert _badges(total_quizzes=0)[0]["earned"] is False
    one = _badges(total_quizzes=1, first_quiz_ts=123.0)
    assert one[0]["earned"] is True and one[0]["earned_at"] == 123.0


def test_badges_streak_thresholds():
    ls3 = _badges(longest_streak=3, last_active_ts=9.0)
    assert ls3[3]["earned"] is True and ls3[3]["earned_at"] == 9.0  # streak_3
    assert ls3[4]["earned"] is False  # streak_7
    # progress is rounded to 3 decimals.
    assert ls3[4]["progress"] == 0.429
    ls7 = _badges(longest_streak=7)
    assert ls7[4]["earned"] is True and ls7[5]["earned"] is False  # streak_30
    ls30 = _badges(longest_streak=30)
    assert ls30[5]["earned"] is True


def test_badges_quiz_run_capped_progress():
    # max_run=10 → quiz_run_5 progress caps at 1.0.
    badges = _badges(max_run=10, run_end_ts=5.0)
    assert badges[2]["progress"] == 1.0 and badges[2]["earned"] is True


def test_badges_mastery_and_types():
    b10 = _badges(mastered_count=10)
    assert b10[6]["earned"] is True  # mastery_10
    assert b10[7]["earned"] is False  # mastery_50
    all_types = _badges(mastered_types={t.value for t in KnowledgeType})
    assert all_types[10]["earned"] is True  # all_types
    assert _badges(mastered_types={"memory", "concept"})[10]["earned"] is False
    assert _badges(mastered_types={"memory", "concept"})[10]["progress"] == pytest.approx(0.5)


def test_badges_error_graduate():
    assert _badges(error_graduated=False)[9]["earned"] is False
    g = _badges(error_graduated=True, graduated_ts=7.0)
    assert g[9]["earned"] is True and g[9]["progress"] == 1.0
    assert g[9]["earned_at"] == 7.0


def test_badges_active_10():
    assert _badges(active_days=9)[11]["earned"] is False
    assert _badges(active_days=10, last_active_ts=3.0)[11]["earned"] is True


# ---------------------------------------------------------------------------
# GET /motivation (endpoint, mocked storage)
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
    summaries = [{"book_id": bid, "name": bid} for bid in books]
    service = _FakeService(summaries)
    stack = [
        mock.patch.object(mod, "LearningStore", return_value=store),
        mock.patch.object(mod, "LearningService", return_value=service),
        mock.patch.object(mod, "_diagnoses_stats", return_value=(0, None)),
    ]
    for p in stack:
        p.start()
    return stack


@pytest.mark.asyncio
async def test_motivation_empty_state():
    stack = _patched_endpoint({})
    try:
        out = await mod.motivation()
    finally:
        for p in stack:
            p.stop()
    assert out["has_data"] is False
    assert out["points"]["total"] == 0
    assert out["streak"]["current"] == 0
    assert all(b["earned"] is False for b in out["badges"])


@pytest.mark.asyncio
async def test_motivation_points_economy():
    today = date.today()
    base = _ts(today)
    progress = LearningProgress(
        book_id="b",
        created_at=base,
        updated_at=base,
        mastery_levels={"kp1": 0.9, "kp2": 0.4},
        knowledge_types={"kp1": KnowledgeType.CONCEPT},
        quiz_attempts=[
            QuizAttempt(question_id="q1", knowledge_point_id="kp1", is_correct=True, timestamp=base),
            QuizAttempt(question_id="q2", knowledge_point_id="kp1", is_correct=False, timestamp=base),
            QuizAttempt(question_id="q3", knowledge_point_id="kp1", is_correct=True, timestamp=base),
        ],
    )
    stack = _patched_endpoint({"b": progress})
    try:
        out = await mod.motivation()
    finally:
        for p in stack:
            p.stop()

    # quiz=3 → 15; correct=2 → 20; mastered=1 → 20; active_days=1 → 15; badges…
    # earned badges: first_quiz, first_mastery, quiz_run_5? (max_run=2 no) …
    # Let the economy recompute from the returned breakdown instead of
    # hardcoding the badge count.
    bd = out["points"]["breakdown"]
    assert bd["quiz_attempts"] == 15
    assert bd["correct"] == 20
    assert bd["mastered"] == 20
    assert bd["active_days"] == 15
    earned = sum(1 for b in out["badges"] if b["earned"])
    assert out["points"]["total"] == bd["quiz_attempts"] + bd["correct"] + bd["mastered"] + bd["active_days"] + earned * 50
    assert out["has_data"] is True
    assert out["streak"]["active_days"] == 1
    assert out["badges"][0]["earned"] is True  # first_quiz


@pytest.mark.asyncio
async def test_motivation_mastered_badge_reflects_threshold():
    today = date.today()
    base = _ts(today)
    progress = LearningProgress(
        book_id="b",
        created_at=base,
        updated_at=base,
        mastery_levels={"kp1": 0.79},  # just below the 0.8 threshold
    )
    stack = _patched_endpoint({"b": progress})
    try:
        out = await mod.motivation()
    finally:
        for p in stack:
            p.stop()
    # 0.79 is NOT mastered → no mastery badges, no mastered points.
    assert out["badges"][1]["earned"] is False  # first_mastery
    assert out["points"]["breakdown"]["mastered"] == 0


# ---------------------------------------------------------------------------
# diagnose badges + _diagnoses_stats (ER-12 linkage)
# ---------------------------------------------------------------------------


def test_badges_diagnose_thresholds():
    none = _badges()
    assert none[12]["id"] == "diagnose_1" and none[12]["earned"] is False
    assert none[13]["id"] == "diagnose_10" and none[13]["earned"] is False
    one = _badges(diagnose_count=1, diagnose_last_ts=50.0)
    assert one[12]["earned"] is True and one[12]["earned_at"] == 50.0
    assert one[13]["earned"] is False
    ten = _badges(diagnose_count=10)
    assert ten[13]["earned"] is True and ten[13]["progress"] == 1.0


def test_diagnoses_stats_reads_file(tmp_path, monkeypatch):
    from deeptutor.services import path_service as ps

    class _Fake:
        def get_workspace_dir(self):
            return tmp_path

    monkeypatch.setattr(ps, "get_path_service", lambda: _Fake())
    # missing file → (0, None)
    assert mod._diagnoses_stats() == (0, None)
    # valid file → count + max created_at
    path = tmp_path / "study" / "diagnoses.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[{"id":"a","created_at":100},{"id":"b","created_at":300}]',
        encoding="utf-8",
    )
    assert mod._diagnoses_stats() == (2, 300.0)


def test_diagnoses_stats_tolerates_corrupt(tmp_path, monkeypatch):
    from deeptutor.services import path_service as ps

    class _Fake:
        def get_workspace_dir(self):
            return tmp_path

    monkeypatch.setattr(ps, "get_path_service", lambda: _Fake())
    path = tmp_path / "study" / "diagnoses.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    assert mod._diagnoses_stats() == (0, None)
