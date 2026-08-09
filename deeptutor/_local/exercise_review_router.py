"""Exercise review orchestration (ER-12): whole page → per-question review.

Pure orchestration overlay over existing assets:
- Question splitting is a pluggable hook (``_split_questions_from_image``).
  Phase-1 keeps it unconfigured: the endpoint answers 400 with a clear hint so
  callers fall back to supplying ``questions`` directly (any vision-capable LLM
  or VLM engine can be wired in later without touching the endpoint contract).
- Per-question variant retrieval reuses ``variant_exercises`` from the KGraph
  exercise adapter (four-level cascade direct→section→neighbor→chapter).
- "Marked wrong → error book" reuses ``LearningService.record_quiz_attempt`` —
  the single write path that creates/updates ``ErrorRecord`` AND appends a
  ``QuizAttempt`` atomically.

Read-only except for the explicit ``/review/errors`` write. Mounted in
``api/main.py`` at ``/api/v1/study`` (same pattern as ER-13/14).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from deeptutor.learning.models import ErrorType, LearningProgress, QuizAttempt
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_BOOK_ID = "exercise_review"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ReviewQuestionIn(BaseModel):
    """One extracted question. ``id`` is auto-generated when omitted."""

    id: str = ""
    stem: str
    options: list[str] = Field(default_factory=list)
    answer: str = ""
    analysis: str = ""
    error_type: str = ""
    kp_id: str = ""
    module_id: str = ""


class ReviewRequest(BaseModel):
    book_id: str = DEFAULT_BOOK_ID
    questions: list[ReviewQuestionIn] = Field(default_factory=list)
    image_base64: str = ""
    auto_split: bool = False


class ReviewQuestionOut(ReviewQuestionIn):
    """Question enriched with variant exercises (when a kp is mapped)."""

    variant: list[dict[str, Any]] = Field(default_factory=list)
    variant_note: str = ""


class ReviewResponse(BaseModel):
    book_id: str
    questions: list[ReviewQuestionOut] = Field(default_factory=list)


class ReviewErrorItem(BaseModel):
    question_id: str
    stem: str = ""
    kp_id: str = ""
    error_type: str = ""
    module_id: str = ""
    user_answer: Any = None


class ReviewErrorsRequest(BaseModel):
    book_id: str = DEFAULT_BOOK_ID
    errors: list[ReviewErrorItem] = Field(default_factory=list)


class ReviewErrorsResponse(BaseModel):
    book_id: str
    added: int


# ---------------------------------------------------------------------------
# Pluggable question splitter (phase-1: unconfigured)
# ---------------------------------------------------------------------------


def _split_questions_from_image(image_base64: str) -> Optional[list[dict[str, Any]]]:
    """Split a whole-page exercise image into question dicts.

    Phase-1: no splitter is wired in the sandbox (no vision-LLM/VLM guarantee),
    so this returns ``None`` and the endpoint answers with a clear hint.
    A future implementation (vision LLM extraction or VLM layout splitting,
    e.g. reusing ``VisionSolverAgent``) plugs in here without changing the
    endpoint contract.
    """
    try:
        from deeptutor._local.question_splitter import split_questions  # type: ignore

        return split_questions(image_base64)
    except Exception as exc:  # noqa: BLE001 — splitter absent or failed
        logger.debug("question splitter unavailable: %s", exc)
        return None


def _coerce_error_type(value: str) -> ErrorType | None:
    try:
        return ErrorType(value) if value else None
    except ValueError:
        return None


def _resolve_error_type(
    progress: LearningProgress, item: "ReviewErrorItem"
) -> ErrorType:
    """Pick a concrete error type for an error record.

    ``record_quiz_attempt`` only creates an ErrorRecord when ``error_type`` is
    set, so an unknown/omitted type must not silently drop the record. Prefer
    the caller's value, then the existing ``infer_error_type`` heuristic, then
    a safe default.
    """
    coerced = _coerce_error_type(item.error_type)
    if coerced is not None:
        return coerced
    try:
        from deeptutor.capabilities.mastery.error_book import infer_error_type

        return infer_error_type(progress, item.kp_id or "", item.user_answer)
    except Exception as exc:  # noqa: BLE001 — fall back to a legal default
        logger.debug("error-type inference failed for %r: %s", item.question_id, exc)
        return ErrorType.APPLICATION_ERROR


def _enrich_variants(question: ReviewQuestionIn) -> ReviewQuestionOut:
    out = ReviewQuestionOut(**question.model_dump())
    if not question.kp_id:
        return out
    try:
        from deeptutor.capabilities.mastery.exercise_adapter import variant_exercises

        variants = variant_exercises(
            question.kp_id,
            count=3,
            exclude=(question.id,) if question.id else (),
        )
        out.variant = variants[:3]
        if not variants:
            out.variant_note = "未检索到变式题（知识图谱该知识点无配套习题）。"
    except Exception as exc:  # noqa: BLE001 — KGraph dataset may be absent
        logger.debug("variant retrieval failed for %r: %s", question.kp_id, exc)
        out.variant_note = "变式检索暂不可用（知识图谱数据未就绪）。"
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/review")
async def review_exercise_page(body: ReviewRequest) -> Any:
    """Enrich a whole-page exercise extract into a per-question review view.

    Accepts either pre-extracted ``questions`` (the reliable path) or an
    ``image_base64`` + ``auto_split`` attempt (phase-1: requires a configured
    splitter; otherwise a clear 400 hint is returned).
    """
    questions = list(body.questions)
    if not questions and body.auto_split:
        if not body.image_base64:
            return JSONResponse(
                status_code=400,
                content={"detail": "开启 auto_split 时必须提供 image_base64。"},
            )
        split = _split_questions_from_image(body.image_base64)
        if split is None:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        "自动切分暂不可用：尚未配置题目切分器（需要视觉模型或 "
                        "VLM 版面引擎）。请先直接提供 questions（可由任意视觉 "
                        "LLM 抽取后粘贴 JSON），或配置切分器后重试。"
                    )
                },
            )
        questions = [
            ReviewQuestionIn(**item) if isinstance(item, dict) else item
            for item in split
        ]
    if not questions:
        return JSONResponse(
            status_code=400,
            content={"detail": "请提供 questions（题目列表）或开启 auto_split 并上传整页图片。"},
        )

    book_id = body.book_id.strip() or DEFAULT_BOOK_ID
    enriched = [_enrich_variants(q) for q in questions]
    return ReviewResponse(book_id=book_id, questions=enriched)


@router.post("/review/errors")
async def record_review_errors(body: ReviewErrorsRequest) -> ReviewErrorsResponse:
    """Mark reviewed questions as wrong → error book (the ER-12 acceptance core).

    Reuses ``record_quiz_attempt`` so each wrong answer atomically appends a
    QuizAttempt and creates/updates the corresponding ErrorRecord.
    """
    book_id = body.book_id.strip() or DEFAULT_BOOK_ID
    if not body.errors:
        return ReviewErrorsResponse(book_id=book_id, added=0)

    store = LearningStore()
    progress = store.load(book_id)
    if progress is None:
        progress = LearningProgress(book_id=book_id)
    service = LearningService(store)

    added = 0
    for item in body.errors:
        try:
            service.record_quiz_attempt(
                progress,
                QuizAttempt(
                    question_id=item.question_id or f"q_{added}",
                    knowledge_point_id=item.kp_id or "",
                    module_id=item.module_id or "exercise_review",
                    is_correct=False,
                    user_answer=item.user_answer,
                    error_type=_resolve_error_type(progress, item),
                ),
            )
            added += 1
        except Exception as exc:  # noqa: BLE001 — keep going on per-item failure
            logger.warning("failed to record review error %r: %s", item.question_id, exc)

    store.save(progress)
    return ReviewErrorsResponse(book_id=book_id, added=added)


__all__ = ["router"]
