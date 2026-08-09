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

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.kgraph import get_kg, is_available

logger = logging.getLogger(__name__)

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
    location breadcrumb (``appears_in`` + upward ``is_part_of``), the
    teachable ``knowledge_points`` that belong to this node (via ``appears_in``
    + ``is_part_of`` reverse edges — the same set ``section_to_module`` turns
    into a mastery path), and the aggregated textbook evidence (P0-1: evidence
    lives on subject edges).
    """
    kg = _require_kg()
    node = kg.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Concept not found: {node_id}")

    dd = kg.definition_data(node_id)
    prereqs = kg.prerequisites_data(node_id, levels=1)
    path = kg.path_data(node_id)
    ev = kg.evidence_data(node_id)
    knowledge_points = kg.knowledge_points_data(node_id)

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
        "knowledge_points": knowledge_points,
        "path": path,
        "evidence": {
            "evidences": ev.get("evidences", []),
            "relations": ev.get("relations", []),
        },
    }


@router.get("/visualize")
async def kg_visualize(
    node_id: str | None = Query(None, description="Center KGraph concept id to diagram"),
    path_id: str | None = Query(None, description="Mastery path id; diagram its objectives' KGraph"),
    levels: int = Query(2, ge=1, le=4, description="Upward prerequisite depth (node mode)"),
    successor_levels: int = Query(1, ge=0, le=3, description="Downward successor depth (node mode)"),
):
    """Render a KGraph subgraph as a Mermaid ``graph TD`` string (ER-1).

    Two modes, selected by which query param is supplied:

    * ``node_id`` — a single concept plus its prerequisite / successor hops.
    * ``path_id`` — a mastery path's objectives, connected by the
      ``prerequisites_for`` edges that exist *between* them, coloured by the
      learner's mastery bucket.

    The heavy lifting lives in ``deeptutor._local.kgraph_mermaid_overlay`` so
    it stays rebase-safe; this handler only owns HTTP concerns. When the KGraph
    dataset isn't mounted we return ``available: false`` (not a 404) so the
    frontend can show a friendly fallback.
    """
    if not is_available():
        return {"available": False, "reason": "K12-KGraph index not available"}
    if not node_id and not path_id:
        raise HTTPException(
            status_code=400, detail="Provide node_id or path_id"
        )
    try:
        from deeptutor._local.kgraph_mermaid_overlay import build_kgraph_mermaid

        result = build_kgraph_mermaid(
            node_id=node_id,
            path_id=path_id,
            levels=levels,
            successor_levels=successor_levels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # unknown node, KG hiccup, etc.
        logger.warning("kg_visualize failed: %s", exc)
        return {
            "available": True,
            "error": str(exc),
            "mermaid": "",
            "nodes": [],
            "edges": [],
        }
    result["available"] = True
    return result
