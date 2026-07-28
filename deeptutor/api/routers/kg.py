"""K12-KGraph curriculum knowledge browser API.

Read-only endpoints that back the frontend "课程知识图谱" (KG) viewer tab:
search a concept by name, fetch its full card (definition / aliases /
importance / examples / prerequisites / learning path / textbook evidence).

All data comes from the in-memory index in ``deeptutor.services.kgraph``
(``get_kg()``), which is the same index that powers the ``curriculum_knowledge``
tool — so the browser and the tutor stay perfectly in sync. No writes, no
external calls.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.kgraph import get_kg, is_available

router = APIRouter()

_auth = [Depends(require_auth)]

_SUBJECT_RE = r"^(math|physics|chemistry|biology)$"


def _require_kg():
    """Return the index, or 404 when the dataset isn't present on disk."""
    if not is_available():
        raise HTTPException(status_code=404, detail="K12-KGraph index not available")
    return get_kg()


@router.get("/available")
async def kg_available():
    """Whether the K12-KGraph dataset is mounted, plus node count."""
    if not is_available():
        return {"available": False, "node_count": 0}
    kg = get_kg()
    return {"available": True, "node_count": len(kg.nodes)}


@router.get("/search")
async def kg_search(
    q: str = Query(..., min_length=1, description="Concept name to resolve"),
    subject: str | None = Query(None, pattern=_SUBJECT_RE, description="Subject filter"),
    top_k: int = Query(5, ge=1, le=20),
):
    """Resolve a free-text concept name to ranked candidate nodes.

    Uses the same cascade matcher as the ``curriculum_knowledge`` tool
    (exact → substring → fuzzy → semantic), so a student's paraphrase
    ("直角三角形两边平方和等于第三边平方") still lands on 勾股定理.
    """
    if not is_available():
        return {
            "query": q,
            "subject": subject,
            "available": False,
            "candidates": [],
        }
    kg = get_kg()
    cands = await kg.resolve(q, top_k=top_k, subject=subject)
    return {
        "query": q,
        "subject": subject,
        "available": True,
        "candidates": [
            {
                "id": c["id"],
                "name": c["name"],
                "label": (kg.get_node(c["id"]) or {}).get("label", ""),
                "score": c["score"],
                "method": c["method"],
            }
            for c in cands
        ],
    }


@router.get("/concept/{node_id}")
async def kg_concept(node_id: str):
    """Full curriculum card for one node.

    Assembles definition / aliases / importance / examples (from the merged
    node), prerequisites (one hop up ``prerequisites_for``), the curriculum
    location breadcrumb (``appears_in`` + upward ``is_part_of``), and the
    aggregated textbook evidence (P0-1: evidence lives on subject edges).
    """
    kg = _require_kg()
    node = kg.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Concept not found: {node_id}")

    dd = kg.definition_data(node_id)
    prereqs = kg.prerequisites_data(node_id, levels=1)
    path = kg.path_data(node_id)
    ev = kg.evidence_data(node_id)

    return {
        "id": node_id,
        "name": dd["name"],
        "label": dd["label"],
        "available": True,
        "definition": dd["definition"],
        "aliases": dd["aliases"],
        "importance": dd["importance"],
        "examples": dd["examples"],
        "prerequisites": [
            {"id": p["id"], "name": p["name"], "label": p["label"]} for p in prereqs
        ],
        "path": path,
        "evidence": {
            "evidences": ev.get("evidences", []),
            "relations": ev.get("relations", []),
        },
    }
