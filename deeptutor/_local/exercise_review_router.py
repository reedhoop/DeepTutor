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

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from deeptutor.learning.models import ErrorType, LearningProgress, QuizAttempt
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.settings.interface_settings import get_response_language

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_BOOK_ID = "exercise_review"

# Diagnostic records live in the user workspace so the growth archive and
# motivation layers can consume them later (append-only, read-only elsewhere).
_DIAGNOSES_FILENAME = "diagnoses.json"


def _diagnoses_path() -> Path:
    from deeptutor.services.path_service import get_path_service

    return get_path_service().get_workspace_dir() / "study" / _DIAGNOSES_FILENAME


def _load_diagnoses() -> list[dict[str, Any]]:
    path = _diagnoses_path()
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — corrupt file must not break API
        logger.warning("failed to read diagnoses: %s", exc)
    return []


# read-modify-write of diagnoses.json is guarded so concurrent diagnoses
# (FastAPI handles requests concurrently) don't clobber each other's records.
_DIAGNOSES_LOCK = threading.Lock()


def _append_diagnosis(record: dict[str, Any]) -> None:
    path = _diagnoses_path()
    with _DIAGNOSES_LOCK:
        records = _load_diagnoses()
        records.append(record)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            logger.warning("failed to persist diagnosis: %s", exc)


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
# Level-diagnosis schema (ER-12.2: 上传试卷 → 水平诊断)
# ---------------------------------------------------------------------------


class DiagnoseItem(BaseModel):
    """One reviewed question's outcome, used to aggregate a level report."""

    id: str = ""
    kp_id: str = ""
    error_type: str = ""
    is_correct: bool = False


class DiagnoseRequest(BaseModel):
    book_id: str = DEFAULT_BOOK_ID
    questions: list[DiagnoseItem] = Field(default_factory=list)


class ErrorTypeStat(BaseModel):
    type: str
    name: str
    count: int


class WeakKpStat(BaseModel):
    kp_id: str
    name: str
    wrong_count: int
    mastery: float
    suggestion: str


class DiagnoseResponse(BaseModel):
    book_id: str
    diagnosis_id: str = ""
    total: int
    correct: int
    wrong: int
    accuracy: float
    error_types: list[ErrorTypeStat] = Field(default_factory=list)
    weak_kps: list[WeakKpStat] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# Error-cause display labels, per response language. Keys mirror the ErrorType
# enum ``.value`` ("structural" / "deviation" / "application" / "metacognitive").
_ERROR_TYPE_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "structural": "知识结构性",
        "deviation": "理解偏差型",
        "application": "应用错误",
        "metacognitive": "元认知型",
    },
    "en": {
        "structural": "Structural gap",
        "deviation": "Misconception",
        "application": "Application error",
        "metacognitive": "Metacognitive",
    },
}


def _error_type_name(value: str, lang: str) -> str:
    table = _ERROR_TYPE_LABELS.get(lang, _ERROR_TYPE_LABELS["en"])
    return table.get(value, "未分类" if lang == "zh" else "Uncategorized")


def _L(lang: str, zh: str, en: str) -> str:
    """Pick the reader-facing string for the given response language."""
    return zh if lang == "zh" else en


def _kp_display_name(kg: Any, kp_id: str) -> str:
    try:
        node = kg.nodes.get(kp_id)
        return str(node.get("name") or kp_id) if node else kp_id
    except Exception:  # noqa: BLE001 — kgraph may be absent
        return kp_id


@router.post("/review/diagnose")
async def diagnose_review(body: DiagnoseRequest) -> DiagnoseResponse:
    """Aggregate a reviewed exercise page into a level-diagnosis report.

    Pure read-only derivation from the questions the frontend already holds
    (no dependency on error-book persistence): overall accuracy, error-cause
    distribution, weak knowledge points (with mastery from the book's
    LearningProgress when available) and concrete study suggestions.
    """
    book_id = body.book_id.strip() or DEFAULT_BOOK_ID
    lang = get_response_language()
    items = body.questions
    total = len(items)
    correct = sum(1 for q in items if q.is_correct)
    wrong = total - correct
    accuracy = round(correct / total, 3) if total else 0.0

    # Error-cause distribution (only wrong answers carry a cause).
    error_counts: dict[str, int] = {}
    for q in items:
        if q.is_correct:
            continue
        key = _coerce_error_type(q.error_type)
        label = key.value if key is not None else ""
        error_counts[label] = error_counts.get(label, 0) + 1
    error_types = [
        ErrorTypeStat(
            type=t,
            name=_error_type_name(t, lang),
            count=c,
        )
        for t, c in sorted(error_counts.items(), key=lambda kv: -kv[1])
    ]

    # Weak knowledge points: wrong questions grouped by kp.
    kp_wrong: dict[str, int] = {}
    for q in items:
        if q.is_correct or not q.kp_id:
            continue
        kp_wrong[q.kp_id] = kp_wrong.get(q.kp_id, 0) + 1

    mastery_map: dict[str, float] = {}
    try:
        progress = await asyncio.to_thread(LearningStore().load, book_id)
        mastery_map = dict(progress.mastery_levels) if progress else {}
    except Exception:  # noqa: BLE001 — reading mastery is best-effort
        logger.debug("diagnose: no progress for %r", book_id)

    kg = None
    try:
        from deeptutor.services.kgraph import get_kg

        kg = await asyncio.to_thread(get_kg)
    except Exception:  # noqa: BLE001 — kgraph optional
        pass

    weak_kps: list[WeakKpStat] = []
    for kp_id, count in sorted(kp_wrong.items(), key=lambda kv: -kv[1]):
        mastery = round(mastery_map.get(kp_id, 0.0), 3)
        name = _kp_display_name(kg, kp_id)
        if mastery >= 0.8:
            suggestion = _L(
                lang,
                f"「{name}」掌握度尚可但仍有错题——建议做 2~3 道变式题巩固，"
                "并注意粗心/审题类错误。",
                f"Good mastery on 「{name}」 but there are still mistakes — do "
                "2-3 variant exercises and watch for careless/reading errors.",
            )
        elif mastery > 0:
            suggestion = _L(
                lang,
                f"「{name}」掌握度 {mastery:.0%} 偏低——建议先回看前置知识点，"
                "再通过变式题专项练习。",
                f"Mastery on 「{name}」 is low ({mastery:.0%}) — review the "
                "prerequisites first, then practice with variant exercises.",
            )
        else:
            suggestion = _L(
                lang,
                f"「{name}」尚未建立掌握度记录——建议从知识脉络图回看该点，"
                "再练一组变式题建立基线。",
                f"No mastery record for 「{name}」 yet — review it on the "
                "knowledge map, then practice a set of variants to establish a baseline.",
            )
        weak_kps.append(
            WeakKpStat(
                kp_id=kp_id, name=name, wrong_count=count,
                mastery=mastery, suggestion=suggestion,
            )
        )

    suggestions: list[str] = []
    if wrong and weak_kps:
        suggestions.append(
            _L(
                lang,
                f"共 {wrong} 道错题，集中在 {len(weak_kps)} 个知识点——优先攻克错题数"
                f"最多的「{weak_kps[0].name}」。",
                f"{wrong} wrong answers across {len(weak_kps)} knowledge points — "
                f"tackle 「{weak_kps[0].name}」 (the most frequent) first.",
            )
        )
    elif wrong:
        suggestions.append(
            _L(
                lang,
                "存在错题但未关联知识点，建议在题目中补充 kp_id 以获得专项建议。",
                "There are wrong answers not linked to a knowledge point — add "
                "a kp_id to each question for targeted advice.",
            )
        )
    if error_types and error_types[0].count > 0:
        top_cause = error_types[0]
        suggestions.append(
            _L(
                lang,
                f"主要错因类型为「{top_cause.name}」（{top_cause.count} 题）"
                + ("——建议放慢步骤、检验每一步的依据。" if top_cause.type == "metacognitive"
                   else "——建议对照解析重建解题路径。"),
                f"Main error type: 「{top_cause.name}」 ({top_cause.count} questions)"
                + (" — slow down and verify each step." if top_cause.type == "metacognitive"
                   else " — reconstruct the solution path from the analysis."),
            )
        )
    if correct and total:
        suggestions.append(
            _L(
                lang,
                f"正确率 {accuracy:.0%}，继续保持当前节奏。",
                f"Accuracy {accuracy:.0%} — keep up the current pace.",
            )
        )

    diagnosis_id = uuid.uuid4().hex[:12]
    record = {
        "id": diagnosis_id,
        "book_id": book_id,
        "created_at": time.time(),
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "accuracy": accuracy,
        "error_types": [et.model_dump() for et in error_types],
        "weak_kps": [wk.model_dump() for wk in weak_kps],
        "suggestions": suggestions,
    }
    # Persist for the growth-archive / motivation consumers (append-only,
    # best-effort — a failed write must not fail the request). Empty
    # diagnoses carry no signal and would only spam the history.
    if total > 0:
        await asyncio.to_thread(_append_diagnosis, record)

    return DiagnoseResponse(
        book_id=book_id,
        diagnosis_id=diagnosis_id,
        total=total,
        correct=correct,
        wrong=wrong,
        accuracy=accuracy,
        error_types=error_types,
        weak_kps=weak_kps,
        suggestions=suggestions,
    )


@router.get("/diagnoses")
async def list_diagnoses(limit: int = 20) -> dict[str, Any]:
    """Recent level-diagnosis records, newest first.

    Read-only — consumed by the growth archive (accuracy trend) and the
    motivation layer (diagnosis-derived badges later). Cap at *limit* to keep
    responses small.
    """
    records = await asyncio.to_thread(_load_diagnoses)
    records.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return {"total": len(records), "diagnoses": records[: max(0, min(limit, 200))]}


# ---------------------------------------------------------------------------
# Pluggable question splitter (phase-1: unconfigured)
# ---------------------------------------------------------------------------


def _split_questions_from_image(image_base64: str) -> Optional[list[dict[str, Any]]]:
    """Split a whole-page exercise image into question dicts.

    Wired to :func:`deeptutor._local.question_splitter.split_questions` —
    an OCR-first (PP-StructureV3/PaddleOCR) splitter with zero LLM
    dependency. Returns ``None`` when the image can't be decoded or OCR'd,
    and the endpoint answers 400 with a hint so callers fall back to
    supplying ``questions`` directly.
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

        # ``user_answer`` is typed Any on the wire (choice ids, numbers, JSON
        # arrays…). ``infer_error_type`` expects a str — coerce defensively so a
        # non-str answer can't raise and silently fall back to APPLICATION.
        return infer_error_type(progress, item.kp_id or "", str(item.user_answer or ""))
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


_HEAD_SPLIT_RE = re.compile(r"[：:，,。；;？?！!\s]+")


def _candidate_queries(stem: str) -> list[str]:
    """Short query fragments from a question stem, most-likely-first.

    ``resolve`` matches concept *names*, so a full sentence ranks poorly (its
    substring ratio falls below the acceptance floor and semantic search
    returns a near-tie). The knowledge-point name usually sits at the head of
    the stem, so we try the leading punctuation-split fragments, then
    short prefix truncations.
    """
    s = stem.strip()
    candidates: list[str] = []
    seen: set[str] = set()

    def add(c: str) -> None:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            candidates.append(c)

    for frag in _HEAD_SPLIT_RE.split(s):
        if frag:
            add(frag)
        if len(candidates) >= 3:
            break
    add(s[:16])
    add(s[:12])
    add(s[:8])
    return candidates[:5]


async def _auto_tag_kp_ids(questions: list[ReviewQuestionIn]) -> int:
    """Auto-fill empty ``kp_id`` fields via KGraph concept resolution.

    The OCR splitter produces plain-text stems with no knowledge-point tag, so
    the downstream diagnosis (weak-point analysis) and variant retrieval would
    have nothing to key on. For every question that lacks a ``kp_id``, resolve
    short head fragments of its stem against the KGraph and tag it when the
    match is *confident* (reuses :func:`deeptutor.services.kgraph.is_confident`
    — the single source of truth, never a local copy). Best-effort: any
    failure just leaves the field empty so the existing fallbacks keep working.
    """
    try:
        from deeptutor.services.kgraph import get_kg, is_confident

        kg = get_kg()
    except Exception:  # noqa: BLE001 — kgraph optional
        return 0
    if kg is None:
        return 0
    tagged = 0
    for q in questions:
        if q.kp_id or not q.stem.strip():
            continue
        for query in _candidate_queries(q.stem):
            try:
                cands = await kg.resolve(query, top_k=3)
            except Exception:  # noqa: BLE001 — embedding endpoint may be down
                continue
            if is_confident(cands):
                q.kp_id = cands[0]["id"]
                tagged += 1
                break
    return tagged


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
        split = await asyncio.to_thread(
            _split_questions_from_image, body.image_base64
        )
        if split is None:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        "自动切分暂不可用：OCR 未能从图片中提取出题目（请确认是 "
                        "清晰的印刷体试卷照片），或本地 PaddleOCR 引擎不可用。"
                        "也可以直接提供 questions（由任意视觉 LLM 抽取后粘贴 "
                        "JSON），稍后再试。"
                    )
                }
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
    tagged = await _auto_tag_kp_ids(questions)
    if tagged:
        logger.info("auto-tagged %d question(s) with kp_id via KGraph", tagged)
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
    progress = await asyncio.to_thread(store.load, book_id)
    if progress is None:
        progress = LearningProgress(book_id=book_id)
    service = LearningService(store)

    added = 0
    for idx, item in enumerate(body.errors):
        try:
            service.record_quiz_attempt(
                progress,
                QuizAttempt(
                    question_id=item.question_id or f"q_{uuid.uuid4().hex[:8]}",
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

    await asyncio.to_thread(store.save, progress)
    return ReviewErrorsResponse(book_id=book_id, added=added)


__all__ = ["router"]
