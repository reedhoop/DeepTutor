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
    assert "OCR" in resp.body.decode()


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


# ---------------------------------------------------------------------------
# POST /review/diagnose — level-diagnosis aggregation
# ---------------------------------------------------------------------------


def _diag_item(kp_id: str = "", error_type: str = "", is_correct: bool = False):
    return mod.DiagnoseItem(kp_id=kp_id, error_type=error_type, is_correct=is_correct)


class _DiagnoseStore:
    """LearningStore stand-in returning a fixed progress."""

    def __init__(self, progress: LearningProgress | None) -> None:
        self._progress = progress

    def load(self, book_id: str) -> LearningProgress | None:
        return self._progress


class _FakeKg:
    def __init__(self) -> None:
        self.nodes = {
            "kp1": {"name": "勾股定理"},
            "kp2": {"name": "方程求解"},
        }


@pytest.mark.asyncio
async def test_diagnose_empty():
    store = _DiagnoseStore(None)
    with mock.patch.object(mod, "LearningStore", return_value=store), \
         mock.patch("deeptutor.services.kgraph.get_kg", return_value=_FakeKg()), \
         mock.patch.object(mod, "_append_diagnosis"):
        out = await mod.diagnose_review(mod.DiagnoseRequest(book_id="b", questions=[]))
    assert out.total == 0 and out.accuracy == 0.0
    assert out.error_types == [] and out.weak_kps == [] and out.suggestions == []


@pytest.mark.asyncio
async def test_diagnose_accuracy_and_cause_distribution():
    store = _DiagnoseStore(None)
    questions = [
        _diag_item(kp_id="kp1", is_correct=True),
        _diag_item(kp_id="kp1", error_type="application", is_correct=False),
        _diag_item(kp_id="kp2", error_type="structural", is_correct=False),
        _diag_item(kp_id="kp2", error_type="application", is_correct=False),
        _diag_item(kp_id="", error_type="", is_correct=False),
    ]
    with mock.patch.object(mod, "LearningStore", return_value=store), \
         mock.patch("deeptutor.services.kgraph.get_kg", return_value=_FakeKg()), \
         mock.patch.object(mod, "_append_diagnosis"):
        out = await mod.diagnose_review(mod.DiagnoseRequest(book_id="b", questions=questions))

    assert out.total == 5 and out.correct == 1 and out.wrong == 4
    assert out.accuracy == pytest.approx(0.2)
    # Cause distribution: application ×2 (first), structural ×1, uncategorized ×1.
    assert [(et.type, et.count) for et in out.error_types] == [
        ("application", 2), ("structural", 1), ("", 1),
    ]
    assert out.error_types[0].name == "应用错误"


@pytest.mark.asyncio
async def test_diagnose_weak_kps_with_mastery():
    progress = LearningProgress(book_id="b")
    progress.mastery_levels = {"kp1": 0.9, "kp2": 0.3}
    store = _DiagnoseStore(progress)
    questions = [
        _diag_item(kp_id="kp1", is_correct=False),
        _diag_item(kp_id="kp1", is_correct=False),
        _diag_item(kp_id="kp2", is_correct=False),
    ]
    with mock.patch.object(mod, "LearningStore", return_value=store), \
         mock.patch("deeptutor.services.kgraph.get_kg", return_value=_FakeKg()), \
         mock.patch.object(mod, "_append_diagnosis"):
        out = await mod.diagnose_review(mod.DiagnoseRequest(book_id="b", questions=questions))

    # Weak kps sorted by wrong count: kp1 (2) first, then kp2 (1).
    assert [(w.kp_id, w.wrong_count) for w in out.weak_kps] == [("kp1", 2), ("kp2", 1)]
    assert out.weak_kps[0].name == "勾股定理"
    assert out.weak_kps[0].mastery == pytest.approx(0.9)
    assert "巩固" in out.weak_kps[0].suggestion  # mastery ≥ 0.8 branch
    assert out.weak_kps[1].name == "方程求解"
    assert out.weak_kps[1].mastery == pytest.approx(0.3)
    assert "偏低" in out.weak_kps[1].suggestion
    # Suggestions reference the top weak kp.
    assert "勾股定理" in "".join(out.suggestions)


@pytest.mark.asyncio
async def test_diagnose_unknown_kp_name_falls_back_to_id():
    store = _DiagnoseStore(None)
    questions = [_diag_item(kp_id="nope", is_correct=False)]
    with mock.patch.object(mod, "LearningStore", return_value=store), \
         mock.patch("deeptutor.services.kgraph.get_kg", return_value=_FakeKg()), \
         mock.patch.object(mod, "_append_diagnosis"):
        out = await mod.diagnose_review(mod.DiagnoseRequest(book_id="b", questions=questions))
    assert out.weak_kps[0].name == "nope"
    assert "尚未建立掌握度记录" in out.weak_kps[0].suggestion


# ---------------------------------------------------------------------------
# diagnosis persistence + history list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnose_persists_record(tmp_path):
    store = _DiagnoseStore(None)
    written: dict = {}

    def fake_append(record):
        written.update(record)

    with mock.patch.object(mod, "LearningStore", return_value=store), \
         mock.patch("deeptutor.services.kgraph.get_kg", return_value=_FakeKg()), \
         mock.patch.object(mod, "_append_diagnosis", side_effect=fake_append):
        out = await mod.diagnose_review(
            mod.DiagnoseRequest(
                book_id="b",
                questions=[_diag_item(kp_id="kp1", error_type="application", is_correct=False)],
            )
        )

    assert out.diagnosis_id  # returned id links the report to the record
    assert written["id"] == out.diagnosis_id
    assert written["accuracy"] == 0.0
    assert written["weak_kps"][0]["kp_id"] == "kp1"


def test_diagnoses_path_under_workspace(tmp_path, monkeypatch):
    from deeptutor.services import path_service as ps

    class _Fake:
        def get_workspace_dir(self):
            return tmp_path

    monkeypatch.setattr(ps, "get_path_service", lambda: _Fake())
    path = mod._diagnoses_path()
    assert path == tmp_path / "study" / "diagnoses.json"


def test_append_and_load_roundtrip(tmp_path, monkeypatch):
    from deeptutor.services import path_service as ps

    class _Fake:
        def get_workspace_dir(self):
            return tmp_path

    monkeypatch.setattr(ps, "get_path_service", lambda: _Fake())
    mod._append_diagnosis({"id": "d1", "accuracy": 0.5})
    mod._append_diagnosis({"id": "d2", "accuracy": 0.8})
    records = mod._load_diagnoses()
    assert [r["id"] for r in records] == ["d1", "d2"]


def test_load_diagnoses_tolerates_corrupt_file(tmp_path, monkeypatch):
    from deeptutor.services import path_service as ps

    class _Fake:
        def get_workspace_dir(self):
            return tmp_path

    monkeypatch.setattr(ps, "get_path_service", lambda: _Fake())
    path = tmp_path / "study" / "diagnoses.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken json", encoding="utf-8")
    assert mod._load_diagnoses() == []


@pytest.mark.asyncio
async def test_list_diagnoses_newest_first(tmp_path, monkeypatch):
    from deeptutor.services import path_service as ps

    class _Fake:
        def get_workspace_dir(self):
            return tmp_path

    monkeypatch.setattr(ps, "get_path_service", lambda: _Fake())
    mod._append_diagnosis({"id": "old", "created_at": 100})
    mod._append_diagnosis({"id": "new", "created_at": 200})
    out = await mod.list_diagnoses(limit=10)
    assert out["total"] == 2
    assert [d["id"] for d in out["diagnoses"]] == ["new", "old"]


@pytest.mark.asyncio
async def test_diagnose_empty_skips_persistence():
    """Empty diagnoses (total=0) carry no signal — the endpoint must NOT write."""
    store = _DiagnoseStore(None)
    appended = mock.MagicMock()
    with mock.patch.object(mod, "LearningStore", return_value=store), \
         mock.patch("deeptutor.services.kgraph.get_kg", return_value=_FakeKg()), \
         mock.patch.object(mod, "_append_diagnosis", appended):
        out = await mod.diagnose_review(mod.DiagnoseRequest(book_id="b", questions=[]))
    assert out.total == 0
    appended.assert_not_called()


@pytest.mark.asyncio
async def test_diagnose_persists_only_non_empty():
    store = _DiagnoseStore(None)
    appended = mock.MagicMock()
    with mock.patch.object(mod, "LearningStore", return_value=store), \
         mock.patch("deeptutor.services.kgraph.get_kg", return_value=_FakeKg()), \
         mock.patch.object(mod, "_append_diagnosis", appended):
        await mod.diagnose_review(
            mod.DiagnoseRequest(
                book_id="b",
                questions=[_diag_item(kp_id="kp1", is_correct=False)],
            )
        )
    appended.assert_called_once()
    record = appended.call_args.args[0]
    assert record["total"] == 1


# ---------------------------------------------------------------------------
# _auto_tag_kp_ids — auto-associate knowledge points via KGraph resolve
# ---------------------------------------------------------------------------


class _FakeKgResolve:
    def __init__(self, cands):
        self._cands = cands
        self.queries = []

    async def resolve(self, concept, top_k=5, subject=None):
        self.queries.append(concept)
        return self._cands


@pytest.mark.asyncio
async def test_auto_tag_confident_match():
    kg = _FakeKgResolve([{"id": "kp1", "name": "勾股定理", "score": 1.0, "method": "exact"}])
    q = mod.ReviewQuestionIn(stem="勾股定理的应用", kp_id="")
    with mock.patch("deeptutor.services.kgraph.get_kg", return_value=kg):
        tagged = await mod._auto_tag_kp_ids([q])
    assert tagged == 1
    assert q.kp_id == "kp1"
    assert kg.queries == ["勾股定理的应用"]


@pytest.mark.asyncio
async def test_auto_tag_not_confident_leaves_empty():
    kg = _FakeKgResolve([{"id": "kp1", "name": "x", "score": 0.5, "method": "fuzzy"}])
    q = mod.ReviewQuestionIn(stem="模糊题干", kp_id="")
    with mock.patch("deeptutor.services.kgraph.get_kg", return_value=kg):
        tagged = await mod._auto_tag_kp_ids([q])
    assert tagged == 0
    assert q.kp_id == ""


@pytest.mark.asyncio
async def test_auto_tag_does_not_overwrite_existing():
    kg = _FakeKgResolve([{"id": "other", "name": "x", "score": 1.0, "method": "exact"}])
    q = mod.ReviewQuestionIn(stem="题干", kp_id="kp_keep")
    with mock.patch("deeptutor.services.kgraph.get_kg", return_value=kg):
        tagged = await mod._auto_tag_kp_ids([q])
    assert tagged == 0
    assert q.kp_id == "kp_keep"


@pytest.mark.asyncio
async def test_auto_tag_skips_empty_stem_and_kgraph_missing():
    q = mod.ReviewQuestionIn(stem="   ", kp_id="")
    with mock.patch("deeptutor.services.kgraph.get_kg", return_value=None):
        assert await mod._auto_tag_kp_ids([q]) == 0

    def _boom():
        raise RuntimeError("no kgraph")
    with mock.patch("deeptutor.services.kgraph.get_kg", side_effect=_boom):
        assert await mod._auto_tag_kp_ids([mod.ReviewQuestionIn(stem="题", kp_id="")]) == 0


def test_candidate_queries_short_head_first():
    q = mod._candidate_queries("勾股定理：直角三角形两直角边的平方和等于斜边的平方")
    assert q[0] == "勾股定理"  # leading fragment before the colon


def test_candidate_queries_prefix_truncation_when_no_punct():
    q = mod._candidate_queries("解一元二次方程x平方减5x加6等于0")
    assert q[0] == "解一元二次方程x平方减5x加6等于0"  # full stem (no punct)
    assert q[1] == "解一元二次方程x平方减5x加6等"  # s[:16] fallback
    assert q[-1] == "解一元二次方程x"  # s[:8] fallback


def test_candidate_queries_dedup_and_cap():
    q = mod._candidate_queries("一元二次方程")
    assert q == ["一元二次方程"]  # all truncations collapse to the same fragment
    assert len(mod._candidate_queries("很长的一段话" * 10)) <= 5
