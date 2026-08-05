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
