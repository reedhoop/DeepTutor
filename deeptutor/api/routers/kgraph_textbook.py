"""K12 textbook navigation API.

Read-only endpoints that expose the K12-KGraph curriculum hierarchy
(``Book`` → ``Chapter`` → ``Section``) so the frontend can render a
textbook navigator. A ``Section`` is the leaf the learner clicks to start a
mastery path (it is fed to ``POST /api/v1/learning/progress/{book_id}/from-kgraph``).

The graph is the single source of truth: there is no separate textbook model.
Subject / edition labels are derived from the node id conventions
(``{subject}_{grade}_{edition}``, e.g. ``math_8b_rjb``) with a Chinese-name table
and a safe raw-token fallback, so an unseen subject never crashes the endpoint.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException

from deeptutor.services.kgraph import IS_PART_OF, get_kg, is_available

logger = logging.getLogger(__name__)

router = APIRouter()

# ── id → human label tables (graceful fallback to the raw token) ──────────────

_SUBJECT_NAMES: dict[str, str] = {
    "math": "数学",
    "chinese": "语文",
    "english": "英语",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
    "history": "历史",
    "geography": "地理",
    "politics": "道德与法治",
    "science": "科学",
    "it": "信息技术",
    "art": "美术",
    "music": "音乐",
    "pe": "体育与健康",
}

_EDITION_NAMES: dict[str, str] = {
    "rjb": "人教版",
    "bjs": "北师大版",
    "sh": "沪教版",
    "yj": "译林版",
    "zj": "浙教版",
    "js": "苏教版",
    "xd": "新世纪版",
    "bs": "北师版",
    "jx": "冀教版",
    "hn": "华南版",
    "qm": "青岛版",
    "wn": "外研版",
    "bj": "北京版",
}

_CH_RE = re.compile(r"_ch(\d+)")
_SEC_RE = re.compile(r"_s(\d+)")

# ── stage (学段) grouping ────────────────────────────────────────────────────
# KGraph models every book as a direct child of its subject — 八年级上册 and
# 必修一 are both plain ``Book`` nodes with no 初中/高中 grouping node. The
# frontend needs a stage layer for a correct K12 hierarchy (subject → stage →
# book → chapter), so we derive it from the book id conventions instead of
# changing the upstream dataset: the grade token (2nd segment, e.g. ``8a`` /
# ``bx1`` / ``xzxbx2``) encodes the stage.
_STAGE_ORDER = ["primary", "junior", "senior"]
_STAGE_NAMES = {"primary": "小学", "junior": "初中", "senior": "高中"}


def _stage_id_for_book(book_id: str) -> str | None:
    """Map a book id onto its stage id ("primary"/"junior"/"senior").

    ``必修`` / ``选择性必修`` tokens (``bx1``, ``xzxbx1``, …) always carry
    ``bx`` and are senior-high; otherwise the leading grade number decides
    (≤6 primary, 7–9 junior). Unknown shapes return ``None`` and the book
    stays ungrouped (the frontend falls back to the flat list).
    """
    parts = book_id.split("_")
    if len(parts) < 2:
        return None
    grade_token = parts[1]
    if "bx" in grade_token:
        return "senior"
    # Grade token must START with a digit (``8a``/``9``/``1a``) — a leading
    # letter like ``vol1``/``part2`` is a volume number, not a grade.
    m = re.match(r"(\d+)", grade_token)
    if not m:
        return None
    grade = int(m.group(1))
    if grade <= 6:
        return "primary"
    if grade <= 9:
        return "junior"
    return None


def _subject_name(code: str) -> str:
    return _SUBJECT_NAMES.get(code, code)


def _edition_name(token: str) -> str:
    return _EDITION_NAMES.get(token, token)


def _ch_num(chapter_id: str) -> int:
    m = _CH_RE.search(chapter_id)
    return int(m.group(1)) if m else 9_999


def _sec_num(section_id: str) -> int:
    m = _SEC_RE.search(section_id)
    return int(m.group(1)) if m else 9_999


def _node_name(kg: Any, nid: str) -> str:
    node = kg.nodes.get(nid)
    return node.get("name", "") if node else nid


# KGraph is a process-wide singleton, so the built hierarchy is stable for the
# lifetime of the process. Cache it keyed by the kg object identity to avoid
# rebuilding the whole subject→book→chapter→section tree on every request.
_TREE_CACHE: dict[int, dict[str, Any]] = {}


def _build_tree() -> dict[str, Any]:
    """Build the subject → book → chapter → section hierarchy from KGraph."""
    kg = get_kg()
    cached = _TREE_CACHE.get(id(kg))
    if cached is not None:
        return cached
    children_of = kg.adj_rev.get(IS_PART_OF, {})

    subjects: dict[str, dict[str, Any]] = {}

    for nid, node in kg.nodes.items():
        if node.get("label") != "Book":
            continue
        parts = nid.split("_")
        subject_code = parts[0] if parts else nid
        # edition is the last token when the id has at least 3 segments
        edition_token = parts[-1] if len(parts) >= 3 else ""

        subject = subjects.setdefault(
            subject_code,
            {"id": subject_code, "name": _subject_name(subject_code), "books": []},
        )

        chapters = []
        for ch_id in sorted(children_of.get(nid, []), key=_ch_num):
            sections = [
                {"id": s_id, "name": _node_name(kg, s_id)}
                for s_id in sorted(children_of.get(ch_id, []), key=_sec_num)
            ]
            chapters.append(
                {
                    "id": ch_id,
                    "name": _node_name(kg, ch_id),
                    "sections": sections,
                }
            )

        # Only surface books that actually have chapters/sections to navigate.
        if not chapters:
            continue

        subject["books"].append(
            {
                "id": nid,
                "name": _node_name(kg, nid) or nid,
                "edition": _edition_name(edition_token) if edition_token else "",
                "chapters": chapters,
            }
        )

    # Drop subjects with no usable books, sort books by id for stable order.
    result = [s for s in subjects.values() if s["books"]]
    for s in result:
        s["books"].sort(key=lambda b: b["id"])
        # Stage grouping metadata (book_ids only — the flat ``books`` list is
        # kept for backward compatibility). Stable order: 小学 → 初中 → 高中.
        grouped: dict[str, list[str]] = {}
        for b in s["books"]:
            sid = _stage_id_for_book(b["id"])
            if sid:
                grouped.setdefault(sid, []).append(b["id"])
        s["stages"] = [
            {"id": sid, "name": _STAGE_NAMES[sid], "book_ids": grouped[sid]}
            for sid in _STAGE_ORDER
            if sid in grouped
        ]
    result.sort(key=lambda s: s["id"])
    tree = {"subjects": result}
    _TREE_CACHE[id(kg)] = tree
    return tree


@router.get("/textbook-tree")
async def textbook_tree() -> dict[str, Any]:
    """Return the full K12 curriculum tree for the textbook navigator.

    Shape::

        {
          "subjects": [
            {
              "id": "math", "name": "数学",
              "books": [
                {
                  "id": "math_8b_rjb", "name": "八年级下册", "edition": "人教版",
                  "chapters": [ { "id", "name", "sections": [ {"id", "name"} ] } ]
                }
              ]
            }
          ]
        }
    """
    if not is_available():
        raise HTTPException(
            status_code=404,
            detail="K12-KGraph dataset is not available on this server",
        )
    try:
        return _build_tree()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"textbook_tree failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to build textbook tree")
