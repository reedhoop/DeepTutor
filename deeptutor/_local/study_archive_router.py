"""Study archive aggregation (ER-13): growth timeline + weak-point digest.

Mounted onto the FastAPI ``app`` at API-startup via ``deeptutor.api.main`` under
the independent prefix ``/api/v1/study`` (NOT on an upstream router, so the
one-way upstream rebase stays clean). The ``_auth`` dependency is attached at
mount time in ``main``.

Mounting here — rather than via a top-level ``apply_*_overlay()`` call inside
``_local/__init__.py`` — is deliberate: importing the router there would trigger
a circular import (``_local`` → ``api.routers`` → ``learning.prompts`` →
``services.config`` while ``config`` is still half-initialised). ``main`` imports
the router only after all core config packages are ready.

Pure read-only derivation from existing ``LearningProgress`` / error-book data —
never writes learning state, so it stays rebase-safe and does not perturb the
mastery serialization or the one-way upstream sync contract.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from deeptutor.capabilities.mastery.error_book import weak_points
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore

router = APIRouter()

_MASTERY_THRESHOLD = 0.8


def _progress_stats(progress: Any) -> dict[str, Any]:
    """Lightweight rollup of one learning path for the archive cards."""
    mastery = progress.mastery_levels or {}
    total = len(mastery) or sum(len(m.knowledge_points) for m in progress.modules)
    mastered = sum(1 for v in mastery.values() if v >= _MASTERY_THRESHOLD)
    avg = (sum(mastery.values()) / total) if total else 0.0
    open_errors = [
        r for r in progress.error_records if r.status in ("active", "retrying")
    ]
    return {
        "kp_count": total,
        "mastered_count": mastered,
        "avg_mastery": round(avg, 4),
        "quiz_count": len(progress.quiz_attempts),
        "error_count": len(open_errors),
    }


@router.get("/archive")
async def study_archive() -> dict[str, Any]:
    """Aggregate every learning path into a student-level growth archive.

    Returns per-book stats (for the card grid + knowledge-map links), an overall
    rollup, a time-ordered ``timeline`` of mastery evolution across sessions, and
    a merged ``weak_points`` digest (top pain points across all books).
    """
    service = LearningService(LearningStore())
    summaries = (service.list_progress().get("summaries", []) or [])
    store = LearningStore()

    books: list[dict[str, Any]] = []
    totals = {"kp": 0, "mastered": 0, "quiz": 0, "error": 0}
    seen_weak: dict[str, dict[str, Any]] = {}

    for s in summaries:
        bid = s.get("book_id")
        if not bid:
            continue
        progress = store.load(bid)
        if progress is None:
            continue
        st = _progress_stats(progress)
        books.append(
            {
                "book_id": bid,
                "name": s.get("name") or bid,
                "updated_at": s.get("updated_at", progress.updated_at),
                "avg_mastery_pct": round(st["avg_mastery"] * 100, 1),
                "mastered_count": st["mastered_count"],
                "kp_count": st["kp_count"],
                "quiz_count": st["quiz_count"],
                "error_count": st["error_count"],
            }
        )
        totals["kp"] += st["kp_count"]
        totals["mastered"] += st["mastered_count"]
        totals["quiz"] += st["quiz_count"]
        totals["error"] += st["error_count"]
        for w in weak_points(progress, top_k=3):
            prev = seen_weak.get(w.knowledge_point_id)
            if prev is None or w.score > prev["score"]:
                seen_weak[w.knowledge_point_id] = {
                    "knowledge_point_id": w.knowledge_point_id,
                    "name": w.name,
                    "module_id": w.module_id,
                    "mastery": w.mastery,
                    "error_count": w.error_count,
                    "score": w.score,
                    "reason": w.reason,
                }

    weak_points_merged = sorted(seen_weak.values(), key=lambda x: -x["score"])[:8]
    timeline = sorted(books, key=lambda b: b["updated_at"], reverse=True)
    overall_avg = (
        round(totals["mastered"] / totals["kp"] * 100, 1) if totals["kp"] else 0.0
    )

    return {
        "books": books,
        "timeline": timeline,
        "weak_points": weak_points_merged,
        "overall": {
            "path_count": len(books),
            "kp_count": totals["kp"],
            "mastered_count": totals["mastered"],
            "avg_mastery_pct": overall_avg,
            "quiz_count": totals["quiz"],
            "error_count": totals["error"],
        },
    }
