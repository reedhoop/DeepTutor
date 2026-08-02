"""KGraph ``Exercise`` nodes -> ``mastery_quiz`` parameters, plus variant lookup.

Pure functions over the (already-loaded) KG index — no LLM calls, no I/O.

Two things the design doc got wrong about the real dataset, corrected here:

1. Exercise nodes DO carry a ``type`` property (Chinese question-type label,
   present on 1,168 of 1,174 nodes) and an integer ``difficulty`` (1–4). So the
   question type is *mapped*, not keyword-guessed; keyword inference is only a
   fallback for the 6 nodes without properties.
2. ``tests_concept`` is sparse: 1,313 of 1,482 covered concepts have exactly
   ONE exercise. A single-source lookup can therefore never satisfy "return
   >= 2 variants". :func:`variant_exercises` widens through three ordered
   tiers (direct -> same section -> neighbouring concepts) instead.

Real answers are messy — "D（幼虫、成虫）", "√（植物也进行呼吸…）",
"（1）×（2）×（3）√" — so every structured mapping is guarded and degrades to a
plain short/open question rather than producing an ungradable choice.
"""

from __future__ import annotations

import re
from typing import Any

from deeptutor.services.kgraph import get_kg, is_available

# Chinese question-type label -> baseline mastery_quiz question_type.
# "judge" is an internal marker: true/false questions become two-option choices
# when the answer resolves to a single verdict, else they degrade.
_TYPE_BASELINE: dict[str, str] = {
    "选择题": "choice",
    "判断题": "judge",
    "填空题": "short",
    "计算题": "short",
    "简答题": "open",
    "应用题": "open",
    "证明题": "open",
    "操作题": "open",
    "作图题": "open",
    "读图题": "open",
}

DIFFICULTY_LABELS: dict[int, str] = {1: "基础", 2: "常规", 3: "进阶", 4: "挑战"}
_LABEL_TO_DIFFICULTY: dict[str, int] = {v: k for k, v in DIFFICULTY_LABELS.items()}

# Answers this short are a single term — keyword-overlap grading ("open") would
# be looser than fuzzy string matching, so prefer "short".
_SHORT_ANSWER_MAX = 12
# Beyond this an answer is prose; exact/fuzzy matching can never pass it.
_OPEN_ANSWER_MIN = 50

_TRUE_TOKENS = ("√", "正确", "对", "true", "yes")
_FALSE_TOKENS = ("×", "✗", "错", "false", "no")
# Checked before the affirmative tokens: "不正确" contains "正确".
_NEGATED_TOKENS = ("不正确", "不对", "不是", "非")

# Option labels at a line start or after a separator / closing bracket:
# "A. body", "A、body", "A) body", "A：body", "（ ）A. body". A bare "A" with no
# delimiter is not an option marker.
_OPTION_RE = re.compile(r"(?:^|[\s;；,，、\n)）])\s*([A-H])\s*[.．、)）:：]\s*")
# "正确答案：B、D。" -> "B、D。"
_ANSWER_PREFIX_RE = re.compile(r"^\s*(?:正确)?答案\s*[:：是]?\s*")
_SUBQUESTION_RE = re.compile(r"[(（]\s*\d+\s*[)）]")


def exercise_to_quiz(exercise_node: dict[str, Any], kp_id: str) -> dict[str, Any]:
    """Convert one KGraph ``Exercise`` node into ``mastery_quiz`` parameters.

    Always returns a usable question: when the structured mapping cannot be
    trusted (options unextractable, answer covering several sub-questions) the
    result degrades to ``short``/``open`` rather than an unanswerable choice.
    """
    props = exercise_node.get("properties") or {}
    stem = str(props.get("stem") or exercise_node.get("name") or "").strip()
    answer = _ANSWER_PREFIX_RE.sub("", str(props.get("answer") or "").strip())
    raw_type = str(props.get("type") or "").strip()
    difficulty = _coerce_difficulty(props.get("difficulty"))

    baseline = _TYPE_BASELINE.get(raw_type) or _infer_baseline(stem, answer)
    q_type, expected, options = _resolve(baseline, stem, answer)

    return {
        "knowledge_point_id": kp_id,
        "exercise_id": str(exercise_node.get("id") or ""),
        "question": stem,
        "expected_answer": expected,
        "question_type": q_type,
        "options": options,
        "difficulty": difficulty,
        "difficulty_label": DIFFICULTY_LABELS.get(difficulty or 0, ""),
        "source_type": raw_type,
        "analysis": str(props.get("analysis") or "").strip(),
    }


def variant_exercises(
    concept_id: str,
    *,
    count: int = 3,
    difficulty: int | str | None = None,
    exclude: tuple[str, ...] | list[str] = (),
) -> list[dict[str, Any]]:
    """Return up to *count* practice variants for *concept_id*, widening by tier.

    Tier 1 ``tests_concept`` edges (the exercise written for this very concept),
    tier 2 other exercises in the same section, tier 3 exercises of directly
    neighbouring concepts (prerequisites and successors). Each result carries
    ``source`` = ``direct`` / ``section`` / ``neighbor`` so the tutor can say
    where a variant came from. Within a tier, easier exercises come first.

    Raises ``RuntimeError`` when the K12-KGraph dataset is absent.
    """
    if not is_available():
        raise RuntimeError(
            "K12-KGraph dataset not found — set K12_KGRAPH_DATA_DIR and retry"
        )
    kg = get_kg()
    if count <= 0:
        return []

    want = _coerce_difficulty(difficulty)
    skip = set(exclude)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for source, ids in (
        ("direct", _direct_exercises(kg, concept_id)),
        ("section", _section_exercises(kg, concept_id)),
        ("neighbor", _neighbor_exercises(kg, concept_id)),
        ("chapter", _chapter_exercises(kg, concept_id)),
    ):
        tier: list[dict[str, Any]] = []
        for eid in ids:
            if eid in seen or eid in skip:
                continue
            node = kg.get_node(eid)
            if not node or node.get("label") != "Exercise":
                continue
            seen.add(eid)
            quiz = exercise_to_quiz(node, concept_id)
            # A handful of Exercise nodes carry no properties at all — an
            # unanswerable question is worse than one fewer variant.
            if not quiz["question"] or not quiz["expected_answer"]:
                continue
            if want is not None and quiz["difficulty"] != want:
                continue
            quiz["source"] = source
            tier.append(quiz)
        tier.sort(key=lambda q: (q["difficulty"] or 99, q["exercise_id"]))
        out.extend(tier)
        if len(out) >= count:
            break
    return out[:count]


# ── exercise pools, one per tier ──────────────────────────────────────────


def _direct_exercises(kg: Any, concept_id: str) -> list[str]:
    return list(kg.adj_rev.get("tests_concept", {}).get(concept_id, []))


def _section_of(kg: Any, nid: str) -> str | None:
    for edge in ("appears_in", "is_part_of"):
        for parent in kg.adj.get(edge, {}).get(nid, []):
            node = kg.get_node(parent)
            if node and node.get("label") in ("Section", "Chapter"):
                return parent
    return None


def _section_exercises(kg: Any, concept_id: str) -> list[str]:
    section = _section_of(kg, concept_id)
    return _exercises_under(kg, section) if section else []


def _chapter_exercises(kg: Any, concept_id: str) -> list[str]:
    """Exercises anywhere in the enclosing chapter (weakest tier, widest net).

    Only reached when the three targeted tiers came up short — true for ~16% of
    concepts, of which this rescues all but one.
    """
    section = _section_of(kg, concept_id)
    if not section:
        return []
    found: list[str] = []
    for parent in [
        *kg.adj.get("is_part_of", {}).get(section, []),
        *kg.adj.get("appears_in", {}).get(section, []),
    ]:
        node = kg.get_node(parent)
        if not node or node.get("label") not in ("Chapter", "Section"):
            continue
        for edge in ("appears_in", "is_part_of"):
            for child in kg.adj_rev.get(edge, {}).get(parent, []):
                child_node = kg.get_node(child)
                label = child_node.get("label") if child_node else None
                if label == "Exercise":
                    found.append(child)
                elif label == "Section":
                    found.extend(_exercises_under(kg, child))
    return found


def _exercises_under(kg: Any, parent_id: str) -> list[str]:
    found: list[str] = []
    for edge in ("appears_in", "is_part_of"):
        for child in kg.adj_rev.get(edge, {}).get(parent_id, []):
            node = kg.get_node(child)
            if node and node.get("label") == "Exercise":
                found.append(child)
    return found


def _neighbor_exercises(kg: Any, concept_id: str) -> list[str]:
    """Exercises of concepts one PREREQ hop away (either direction)."""
    prereq = kg.adj_rev.get("prerequisites_for", {}).get(concept_id, [])
    successors = kg.adj.get("prerequisites_for", {}).get(concept_id, [])
    found: list[str] = []
    for neighbour in [*prereq, *successors]:
        found.extend(_direct_exercises(kg, neighbour))
    return found


# ── question-type resolution ──────────────────────────────────────────────


def _resolve(baseline: str, stem: str, answer: str) -> tuple[str, str, list[str]]:
    """Return ``(question_type, expected_answer, options)`` for one exercise."""
    if baseline == "choice":
        options = extract_options(stem)
        label = _single_option_label(answer, options)
        if options and label:
            return "choice", label, options
        return _degrade(answer), answer, []

    if baseline == "judge":
        verdict = _single_verdict(answer, stem)
        if verdict:
            return "choice", verdict, ["A: 正确（√）", "B: 错误（×）"]
        return _degrade(answer), answer, []

    if baseline == "short" and len(answer) > _OPEN_ANSWER_MIN:
        return "open", answer, []
    if baseline == "open" and 0 < len(answer) <= _SHORT_ANSWER_MAX:
        return "short", answer, []
    return baseline, answer, []


def _degrade(answer: str) -> str:
    """Fallback type for an exercise whose structured mapping failed."""
    return "open" if len(answer) > _SHORT_ANSWER_MAX else "short"


def _infer_baseline(stem: str, answer: str) -> str:
    """Keyword inference for the handful of nodes with no ``type`` property."""
    if extract_options(stem):
        return "choice"
    if any(tok in stem for tok in ("判断", "正确的画", "对错")):
        return "judge"
    if len(answer) > _OPEN_ANSWER_MIN:
        return "open"
    return "short"


def extract_options(stem: str) -> list[str]:
    """Extract ``["A: body", "B: body", ...]`` from a multiple-choice stem.

    Keeps the longest run of labels starting at ``A`` and stepping by one, so
    letters that merely occur in the prose ("下列关于 F、Cl、Br、I 的比较…")
    can't shift or break the real option block. Fewer than two options means
    the stem has none.
    """
    matches = list(_OPTION_RE.finditer(stem))
    if len(matches) < 2:
        return []
    labels = [m.group(1) for m in matches]

    start, run = -1, 0
    for i, label in enumerate(labels):
        if label != "A":
            continue
        length = 1
        while i + length < len(labels) and labels[i + length] == chr(ord("A") + length):
            length += 1
        if length > run:
            start, run = i, length
    if run < 2:
        return []

    block = matches[start : start + run]
    tail = matches[start + run].start() if start + run < len(matches) else len(stem)
    options: list[str] = []
    for i, m in enumerate(block):
        end = block[i + 1].start() if i + 1 < len(block) else tail
        body = stem[m.end() : end].strip().strip(";；,，、。")
        if not body:
            return []
        options.append(f"{m.group(1)}: {body}")
    return options


def _single_option_label(answer: str, options: list[str]) -> str:
    """Resolve a messy answer such as ``"D（幼虫、成虫）"`` to the label ``"D"``.

    Returns ``""`` when the answer names several options (a multi-part
    exercise), which must not be graded as a single choice.
    """
    if not answer or not options:
        return ""
    valid = {opt.split(":", 1)[0] for opt in options}
    named = {ch for ch in answer.upper() if ch in valid}
    head = answer.strip().upper()[:1]
    if head in valid and named <= {head}:
        return head
    return next(iter(named)) if len(named) == 1 else ""


def _single_verdict(answer: str, stem: str) -> str:
    """Map a true/false answer to option label ``A`` (true) / ``B`` (false).

    Returns ``""`` for multi-part judgements — "（1）×（2）√" or a stem listing
    several numbered statements — so they degrade to a free-text answer.
    """
    if not answer:
        return ""
    if len(_SUBQUESTION_RE.findall(stem)) > 1 or len(_SUBQUESTION_RE.findall(answer)) > 0:
        return ""
    lowered = answer.lower()
    if any(tok in lowered for tok in _NEGATED_TOKENS):
        return "B"
    true_hit = any(tok in lowered for tok in _TRUE_TOKENS)
    false_hit = any(tok in lowered for tok in _FALSE_TOKENS) or lowered.startswith(("x", "否"))
    if true_hit and not false_hit:
        return "A"
    if false_hit and not true_hit:
        return "B"
    return ""


def _coerce_difficulty(value: Any) -> int | None:
    """Accept ``2``, ``"2"`` or ``"常规"``; anything else is unknown (``None``)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 4 else None
    text = str(value).strip()
    if text in _LABEL_TO_DIFFICULTY:
        return _LABEL_TO_DIFFICULTY[text]
    try:
        num = int(text)
    except ValueError:
        return None
    return num if 1 <= num <= 4 else None


__all__ = [
    "DIFFICULTY_LABELS",
    "exercise_to_quiz",
    "extract_options",
    "variant_exercises",
]
