"""Motivation overlay (ER-14): lightweight gamification — read-only derivation.

Mounted onto the FastAPI ``app`` at API-startup via ``deeptutor.api.main`` under
the shared ``/api/v1/study`` prefix (same as the ER-13 study-archive router),
with the ``_auth`` dependency attached at mount time.

Like the study-archive router, this MUST NOT be wired through a top-level
``apply_*_overlay()`` call in ``_local/__init__.py`` — doing so re-triggers the
circular import reported for ER-13 (``_local`` → ``api.routers`` →
``learning.prompts`` → ``services.config`` half-initialised).

All outputs are *derived* from existing ``LearningProgress`` / ``quiz_attempts``
/ ``error_records`` data. Nothing here writes learning state, so it stays
rebase-safe and never perturbs the mastery serialization or the one-way upstream
sync contract. Per the ER-14 spec, this is personal-progress only — no
competitive leaderboard.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter

from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore

router = APIRouter()

_MASTERY_THRESHOLD = 0.8

# Point economy (purely cosmetic, fully derived from underlying activity).
_PTS_PER_QUIZ = 5
_PTS_PER_CORRECT = 10
_PTS_PER_MASTERED = 20
_PTS_PER_ACTIVE_DAY = 15
_PTS_PER_BADGE = 50


def _activity_dates(progress: Any) -> set[date]:
    """Every calendar day on which the learner touched this path."""
    out: set[date] = set()
    for ts in (progress.created_at, progress.updated_at):
        if ts:
            out.add(datetime.fromtimestamp(ts).date())
    for q in progress.quiz_attempts:
        out.add(datetime.fromtimestamp(q.timestamp).date())
    for e in progress.error_records:
        out.add(datetime.fromtimestamp(e.created_at).date())
    return out


def _max_correct_run(attempts: list[Any]) -> tuple[int, float | None]:
    """Longest run of consecutive correct quiz answers (global, time-ordered).

    Returns (run_length, timestamp_of_last_correct_in_run or None).
    """
    ordered = sorted(attempts, key=lambda a: a.timestamp)
    best = cur = 0
    best_end_ts: float | None = None
    cur_end_ts: float | None = None
    for a in ordered:
        if a.is_correct:
            cur += 1
            cur_end_ts = a.timestamp
            if cur > best:
                best = cur
                best_end_ts = cur_end_ts
        else:
            cur = 0
            cur_end_ts = None
    return best, best_end_ts


def _streak_stats(dates: set[date]) -> dict[str, Any]:
    if not dates:
        return {
            "current": 0,
            "longest": 0,
            "active_days": 0,
            "last_active": None,
            "today_active": False,
            "recent": [],
        }
    today = date.today()
    sorted_dates = sorted(dates)

    # Longest consecutive run.
    longest = 1
    cur = 1
    for i in range(1, len(sorted_dates)):
        gap = (sorted_dates[i] - sorted_dates[i - 1]).days
        if gap == 1:
            cur += 1
            longest = max(longest, cur)
        elif gap == 0:
            continue
        else:
            cur = 1

    # Current streak: ends today, or yesterday if today hasn't happened yet.
    current = 0
    if today in dates:
        d = today
        current = 1
        while (d - timedelta(days=1)) in dates:
            current += 1
            d -= timedelta(days=1)
    elif (today - timedelta(days=1)) in dates:
        d = today - timedelta(days=1)
        current = 1
        while (d - timedelta(days=1)) in dates:
            current += 1
            d -= timedelta(days=1)

    # Last 14 days activity strip (oldest first).
    recent = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        recent.append({"date": d.isoformat(), "active": d in dates})

    return {
        "current": current,
        "longest": longest,
        "active_days": len(dates),
        "last_active": max(dates).isoformat(),
        "today_active": today in dates,
        "recent": recent,
    }


@router.get("/motivation")
async def motivation() -> dict[str, Any]:
    """Lightweight, read-only motivation layer across all learning paths.

    Derives a learning streak, a mastery-badge catalogue, and a points total
    entirely from existing practice/mastery data. Never writes learning state.
    """
    store = LearningStore()
    service = LearningService(store)
    summaries = (service.list_progress().get("summaries", []) or [])

    activity: set[date] = set()
    all_quizzes: list[Any] = []
    mastered_kp: set[str] = set()
    mastered_types: set[str] = set()
    error_graduated = False
    graduated_ts: float | None = None
    first_quiz_ts: float | None = None
    mastery_ref_ts: float | None = None

    for s in summaries:
        bid = s.get("book_id")
        if not bid:
            continue
        progress = store.load(bid)
        if progress is None:
            continue

        activity |= _activity_dates(progress)
        all_quizzes.extend(progress.quiz_attempts)

        for kp_id, lvl in (progress.mastery_levels or {}).items():
            if lvl >= _MASTERY_THRESHOLD:
                mastered_kp.add(kp_id)
                ktype = progress.knowledge_types.get(kp_id)
                if ktype:
                    mastered_types.add(str(ktype))
                if mastery_ref_ts is None:
                    mastery_ref_ts = progress.updated_at

        for e in progress.error_records:
            if e.status in ("review", "graduated"):
                error_graduated = True
                if graduated_ts is None:
                    graduated_ts = e.created_at

        if progress.quiz_attempts:
            fq = min(a.timestamp for a in progress.quiz_attempts)
            if first_quiz_ts is None or fq < first_quiz_ts:
                first_quiz_ts = fq

    max_run, run_end_ts = _max_correct_run(all_quizzes)
    streak = _streak_stats(activity)

    total_quizzes = len(all_quizzes)
    correct = sum(1 for a in all_quizzes if a.is_correct)
    has_data = bool(total_quizzes or mastered_kp or streak["active_days"])

    last_active_ts = (
        datetime.fromisoformat(streak["last_active"]).timestamp()
        if streak["last_active"]
        else None
    )

    badges = _build_badges(
        total_quizzes=total_quizzes,
        mastered_count=len(mastered_kp),
        mastered_types=mastered_types,
        max_run=max_run,
        longest_streak=streak["longest"],
        active_days=streak["active_days"],
        error_graduated=error_graduated,
        first_quiz_ts=first_quiz_ts,
        mastery_ref_ts=mastery_ref_ts,
        run_end_ts=run_end_ts,
        graduated_ts=graduated_ts,
        last_active_ts=last_active_ts,
    )
    earned_count = sum(1 for b in badges if b["earned"])

    points = {
        "total": (
            total_quizzes * _PTS_PER_QUIZ
            + correct * _PTS_PER_CORRECT
            + len(mastered_kp) * _PTS_PER_MASTERED
            + streak["active_days"] * _PTS_PER_ACTIVE_DAY
            + earned_count * _PTS_PER_BADGE
        ),
        "breakdown": {
            "quiz_attempts": total_quizzes * _PTS_PER_QUIZ,
            "correct": correct * _PTS_PER_CORRECT,
            "mastered": len(mastered_kp) * _PTS_PER_MASTERED,
            "active_days": streak["active_days"] * _PTS_PER_ACTIVE_DAY,
            "badges": earned_count * _PTS_PER_BADGE,
        },
    }

    return {
        "has_data": has_data,
        "streak": streak,
        "points": points,
        "badges": badges,
    }


def _build_badges(**kw: Any) -> list[dict[str, Any]]:
    def b(bid: str, earned: bool, progress: float, earned_at: float | None) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": bid,
            "earned": earned,
            "progress": round(min(1.0, max(0.0, progress)), 3),
        }
        if earned_at is not None:
            item["earned_at"] = earned_at
        return item

    tq = kw["total_quizzes"]
    mc = kw["mastered_count"]
    mt = kw["mastered_types"]
    mr = kw["max_run"]
    ls = kw["longest_streak"]
    ad = kw["active_days"]
    eg = kw["error_graduated"]

    return [
        b("first_quiz", tq >= 1, tq / 1, kw["first_quiz_ts"] if tq >= 1 else None),
        b("first_mastery", mc >= 1, mc / 1, kw["mastery_ref_ts"] if mc >= 1 else None),
        b("quiz_run_5", mr >= 5, mr / 5, kw["run_end_ts"] if mr >= 5 else None),
        b("streak_3", ls >= 3, ls / 3, kw["last_active_ts"] if ls >= 3 else None),
        b("streak_7", ls >= 7, ls / 7, kw["last_active_ts"] if ls >= 7 else None),
        b("streak_30", ls >= 30, ls / 30, kw["last_active_ts"] if ls >= 30 else None),
        b("mastery_10", mc >= 10, mc / 10, kw["mastery_ref_ts"] if mc >= 10 else None),
        b("mastery_50", mc >= 50, mc / 50, kw["mastery_ref_ts"] if mc >= 50 else None),
        b("mastery_100", mc >= 100, mc / 100, kw["mastery_ref_ts"] if mc >= 100 else None),
        b("error_graduate", eg, 1.0 if eg else 0.0, kw["graduated_ts"] if eg else None),
        b(
            "all_types",
            len(mt) >= 4,
            len(mt) / 4,
            kw["mastery_ref_ts"] if len(mt) >= 4 else None,
        ),
        b("active_10", ad >= 10, ad / 10, kw["last_active_ts"] if ad >= 10 else None),
    ]
