"""Unit tests for the ER-12 exercise-review overlay
(``deeptutor._local.exercise_review_router``).

Covers the pure helpers (error-type coercion/resolution, variant enrichment)
and both endpoints with mocked storage so no KGraph dataset or file I/O is
touched. The auto-split hook stays unconfigured in these tests, mirroring the
phase-1 sandbox state.
"""

from __future__ import annotations

from unittest import mock

import pytest

from deeptutor._local import exercise_review_router as mod
from deeptutor.learning.models import ErrorType, LearningProgress


# ---------------------------------------------------------------------------
# _coerce_error_type
# ---------------------------------------------------------------------------


def test_coerce_error_type_accepts_enum_values():
    assert mod._coerce_error_type("structural") is ErrorType.KNOWLEDGE_STRUCTURAL
    assert mod._coerce_error_type("deviation") is ErrorType.UNDERSTANDING_DEVIATION
    assert mod._coerce_error_type("application") is ErrorType.APPLICATION_ERROR
    assert mod._coerce_error_type("metacognitive") is ErrorType.METACOGNITIVE


def test_coerce_error_type_accepts_legacy_chinese_labels():
    # ErrorType._missing_ maps the pre-rename Chinese labels onto the enum.
    assert mod._coerce_error_type("知识结构性") is ErrorType.KNOWLEDGE_STRUCTURAL
    assert mod._coerce_error_type("理解偏差型") is ErrorType.UNDERSTANDING_DEVIATION
    assert mod._coerce_error_type("应用错误") is ErrorType.APPLICATION_ERROR
    assert mod._coerce_error_type("元认知型") is ErrorType.METACOGNITIVE


def test_coerce_error_type_rejects_unknown_and_empty():
    assert mod._coerce_error_type("") is None
    assert mod._coerce_error_type("bogus") is None
    assert mod._coerce_error_type(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _resolve_error_type
# ---------------------------------------------------------------------------


def _item(error_type: str = "", user_answer: object = "x"):
    return mod.ReviewErrorItem(
        question_id="q1", stem="s", kp_id="kp1", error_type=error_type,
        user_answer=user_answer,
    )


def test_resolve_error_type_prefers_explicit_value():
    progress = LearningProgress(book_id="b")
    assert (
        mod._resolve_error_type(progress, _item(error_type="structural"))
        is ErrorType.KNOWLEDGE_STRUCTURAL
    )
    # Legacy Chinese labels go through the same path.
    assert (
        mod._resolve_error_type(progress, _item(error_type="应用错误"))
        is ErrorType.APPLICATION_ERROR
    )


def test_resolve_error_type_uses_inference_for_unknown():
    progress = LearningProgress(book_id="b")
    with mock.patch(
        "deeptutor.capabilities.mastery.error_book.infer_error_type",
        return_value=ErrorType.METACOGNITIVE,
    ) as infer:
        assert mod._resolve_error_type(progress, _item(error_type="junk")) is ErrorType.METACOGNITIVE
    infer.assert_called_once_with(progress, "kp1", "x")


def test_resolve_error_type_coerces_non_str_user_answer():
    """A list/dict/number answer must not blow up ``infer_error_type``."""
    progress = LearningProgress(book_id="b")
    for answer in ([1, 2, 3], {"choice": "B"}, 42, None):
        with mock.patch(
            "deeptutor.capabilities.mastery.error_book.infer_error_type",
            return_value=ErrorType.UNDERSTANDING_DEVIATION,
        ) as infer:
            out = mod._resolve_error_type(progress, _item(user_answer=answer))
        assert out is ErrorType.UNDERSTANDING_DEVIATION
        # The coerced string reached the inference call.
        assert isinstance(infer.call_args.args[2], str)


def test_resolve_error_type_falls_back_when_inference_raises():
    progress = LearningProgress(book_id="b")
    with mock.patch(
        "deeptutor.capabilities.mastery.error_book.infer_error_type",
        side_effect=RuntimeError("boom"),
    ):
        assert (
            mod._resolve_error_type(progress, _item(error_type="junk"))
            is ErrorType.APPLICATION_ERROR
        )


# ---------------------------------------------------------------------------
# _enrich_variants
# ---------------------------------------------------------------------------


def test_enrich_variants_passthrough_without_kp():
    q = mod.ReviewQuestionIn(stem="1+1=?")
    out = mod._enrich_variants(q)
    assert out.variant == [] and out.variant_note == ""
    assert out.stem == "1+1=?"


def test_enrich_variants_attaches_variants():
    q = mod.ReviewQuestionIn(id="q1", stem="s", kp_id="kp1")
    with mock.patch(
        "deeptutor.capabilities.mastery.exercise_adapter.variant_exercises",
        return_value=[{"id": "v1"}, {"id": "v2"}, {"id": "v3"}, {"id": "v4"}],
    ) as ve:
        out = mod._enrich_variants(q)
    ve.assert_called_once_with("kp1", count=3, exclude=("q1",))
    assert [v["id"] for v in out.variant] == ["v1", "v2", "v3"]


def test_enrich_variants_note_when_empty():
    q = mod.ReviewQuestionIn(stem="s", kp_id="kp1")
    with mock.patch(
        "deeptutor.capabilities.mastery.exercise_adapter.variant_exercises",
        return_value=[],
    ):
        out = mod._enrich_variants(q)
    assert out.variant == []
    assert "未检索到" in out.variant_note


def test_enrich_variants_note_when_dataset_absent():
    q = mod.ReviewQuestionIn(stem="s", kp_id="kp1")
    with mock.patch(
        "deeptutor.capabilities.mastery.exercise_adapter.variant_exercises",
        side_effect=RuntimeError("no kgraph"),
    ):
        out = mod._enrich_variants(q)
    assert out.variant == []
    assert "不可用" in out.variant_note


# ---------------------------------------------------------------------------
# POST /review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_requires_questions_or_autosplit():
    resp = await mod.review_exercise_page(
        mod.ReviewRequest(questions=[], auto_split=False)
    )
    assert resp.status_code == 400
    assert "questions" in resp.body.decode()


@pytest.mark.asyncio
async def test_review_autosplit_requires_image():
    resp = await mod.review_exercise_page(
        mod.ReviewRequest(questions=[], auto_split=True, image_base64="")
    )
    assert resp.status_code == 400
    assert "image_base64" in resp.body.decode()


@pytest.mark.asyncio
async def test_review_autosplit_unconfigured_hint():
    with mock.patch.object(mod, "_split_questions_from_image", return_value=None):
        resp = await mod.review_exercise_page(
            mod.ReviewRequest(
                questions=[], auto_split=True, image_base64="aGVsbG8="
            )
        )
    assert resp.status_code == 400
    assert "切分器" in resp.body.decode()


@pytest.mark.asyncio
async def test_review_enriches_questions():
    with mock.patch(
        "deeptutor.capabilities.mastery.exercise_adapter.variant_exercises",
        return_value=[{"id": "v1"}],
    ):
        resp = await mod.review_exercise_page(
            mod.ReviewRequest(
                book_id=" b1 ",
                questions=[
                    mod.ReviewQuestionIn(id="q1", stem="x", kp_id="kp1"),
                    mod.ReviewQuestionIn(id="q2", stem="y"),
                ],
            )
        )
    # The success branch returns a ReviewResponse model directly (400s are
    # JSONResponse) — assert on the model fields.
    assert isinstance(resp, mod.ReviewResponse)
    assert resp.book_id == "b1"  # stripped
    assert len(resp.questions) == 2
    assert resp.questions[0].variant[0]["id"] == "v1"
    assert resp.questions[1].variant == []


# ---------------------------------------------------------------------------
# POST /review/errors
# ---------------------------------------------------------------------------


class _FakeStore:
    """In-memory LearningStore stand-in recording saves."""

    def __init__(self, progress: LearningProgress | None = None) -> None:
        self._progress = progress
        self.saved: list[LearningProgress] = []

    def load(self, book_id: str) -> LearningProgress | None:
        return self._progress

    def save(self, progress: LearningProgress) -> None:
        self.saved.append(progress)


def _patch_store(progress: LearningProgress | None = None):
    store = _FakeStore(progress)
    patcher = mock.patch.object(mod, "LearningStore", return_value=store)
    patcher.start()
    return store


@pytest.mark.asyncio
async def test_record_errors_empty_returns_zero():
    store = _patch_store()
    try:
        resp = await mod.record_review_errors(
            mod.ReviewErrorsRequest(book_id="b", errors=[])
        )
    finally:
        mock.patch.stopall()
    assert resp.added == 0
    assert store.saved == []  # nothing loaded/saved


@pytest.mark.asyncio
async def test_record_errors_writes_progress_and_saves():
    progress = LearningProgress(book_id="b")
    store = _patch_store(progress)
    try:
        resp = await mod.record_review_errors(
            mod.ReviewErrorsRequest(
                book_id="b",
                errors=[
                    mod.ReviewErrorItem(
                        question_id="q1", stem="s", kp_id="kp1",
                        error_type="structural", user_answer="A",
                    ),
                    mod.ReviewErrorItem(
                        question_id="", stem="s2", kp_id="kp2",
                        error_type="", user_answer="B",
                    ),
                ],
            )
        )
    finally:
        mock.patch.stopall()

    assert resp.added == 2
    assert len(progress.quiz_attempts) == 2
    assert len(progress.error_records) == 2
    assert progress.error_records[0].error_type is ErrorType.KNOWLEDGE_STRUCTURAL
    # Auto-generated question ids are unique even when the caller omits them.
    assert progress.quiz_attempts[1].question_id == "q_1"
    assert store.saved == [progress]


@pytest.mark.asyncio
async def test_record_errors_survives_non_str_user_answer():
    progress = LearningProgress(book_id="b")
    _patch_store(progress)
    try:
        resp = await mod.record_review_errors(
            mod.ReviewErrorsRequest(
                book_id="b",
                errors=[
                    mod.ReviewErrorItem(
                        question_id="q1", stem="s", kp_id="kp1",
                        error_type="", user_answer=["A", "B"],  # multi-select
                    ),
                ],
            )
        )
    finally:
        mock.patch.stopall()

    assert resp.added == 1
    assert len(progress.error_records) == 1
    assert progress.error_records[0].error_type is not None


@pytest.mark.asyncio
async def test_record_errors_keeps_going_on_item_failure():
    progress = LearningProgress(book_id="b")
    store = _patch_store(progress)
    try:
        with mock.patch.object(
            mod.LearningService, "record_quiz_attempt", side_effect=[None, RuntimeError("x")]
        ):
            resp = await mod.record_review_errors(
                mod.ReviewErrorsRequest(
                    book_id="b",
                    errors=[
                        mod.ReviewErrorItem(question_id="q1", stem="s"),
                        mod.ReviewErrorItem(question_id="q2", stem="s2"),
                    ],
                )
            )
    finally:
        mock.patch.stopall()

    assert resp.added == 1  # second item failed, first counted
    assert store.saved == [progress]
