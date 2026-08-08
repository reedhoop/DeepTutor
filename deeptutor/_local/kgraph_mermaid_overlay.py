"""KGraph -> Mermaid graph builder (ER-1 local overlay).

Builds a prerequisite / forward-dependency subgraph around a single KGraph
concept (``node_id`` mode) or across a whole mastery path's objectives
(``path_id`` mode), and serialises it as a Mermaid ``graph TD`` string the
frontend renders with ``web/components/Mermaid.tsx``.

This is a *pure builder*: no FastAPI, no auth, no request objects. The REST
seam in :mod:`deeptutor.api.routers.kg` calls :func:`build_kgraph_mermaid` and
owns all HTTP concerns (status codes, auth, errors). Keeping the logic here —
inside ``_local`` — means a future ``git rebase`` onto upstream only has to
re-apply a tiny thin handler in ``kg.py``; the heavy graph logic never
diverges from upstream files.

Two modes:

* ``node_id`` — center node + upward ``prerequisites_for`` hops (``levels``)
  and downward successor hops (``successor_levels``). The center is
  highlighted; prereqs / successors get distinct tints. Capped at
  ``max_nodes`` (kept closest-first) so a dense hub stays readable.
* ``path_id`` — load the mastery progress, take every objective whose id (or
  name) maps to a KGraph node, then draw the ``prerequisites_for`` edges that
  exist *between those objectives*. Nodes are coloured by the learner's
  mastery bucket so the graph doubles as a status view.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.services.kgraph import PREREQ, _norm, get_kg, is_available

logger = logging.getLogger(__name__)

MAX_NODES = 50

# Mastery buckets, matching the four-colour dashboard in the learning page.
_BUCKET_OF = lambda m: (  # noqa: E731
    "proficient" if m >= 0.9 else "good" if m >= 0.7 else "qualified" if m >= 0.4 else "weak"
)


def _escape_label(s: str) -> str:
    """Make a node label safe inside Mermaid ``["..."]`` quoting."""
    return s.replace("\\", "\\\\").replace('"', "'").replace("\n", " ").strip()


def _sanitize_id(nid: str) -> str:
    """Mermaid node ids must be alnum/underscore; collapse everything else."""
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in nid)
    return out or "n"


def _name_of(kg: Any, nid: str) -> str:
    return (kg.definition_data(nid) or {}).get("name") or nid


def build_kgraph_mermaid(
    *,
    node_id: str | None = None,
    path_id: str | None = None,
    levels: int = 2,
    successor_levels: int = 1,
    max_nodes: int = MAX_NODES,
) -> dict[str, Any]:
    """Return ``{"mermaid": str, "nodes": [...], "edges": [...], "mode": ...}``.

    Raises ``RuntimeError`` when the KGraph index is absent, ``ValueError`` when
    neither id is supplied or the center node is unknown.
    """
    if not is_available():
        raise RuntimeError("K12-KGraph index not available")
    kg = get_kg()
    if node_id:
        return _build_node_graph(kg, node_id, levels, successor_levels, max_nodes)
    if path_id:
        return _build_path_graph(kg, path_id, max_nodes)
    raise ValueError("build_kgraph_mermaid needs node_id or path_id")


def _build_node_graph(
    kg: Any, center: str, levels: int, successor_levels: int, max_nodes: int
) -> dict[str, Any]:
    if not kg.get_node(center):
        raise ValueError(f"Unknown KGraph node: {center}")

    # id -> {"depth": int, "kind": center|prereq|successor}
    nodes: dict[str, dict[str, Any]] = {center: {"depth": 0, "kind": "center"}}
    edges: list[tuple[str, str]] = []

    # Upward: prerequisites of `cur` are nodes that have `cur` as a prerequisite.
    frontier = [(center, 0)]
    for _ in range(max(levels, 0)):
        nxt: list[tuple[str, int]] = []
        for cur, d in frontier:
            for p in kg.adj_rev[PREREQ].get(cur, []):
                if p in nodes:
                    continue
                nodes[p] = {"depth": d + 1, "kind": "prereq"}
                edges.append((p, cur))
                nxt.append((p, d + 1))
        frontier = nxt

    # Downward: successors of `cur` are nodes for which `cur` is a prerequisite.
    frontier = [(center, 0)]
    for _ in range(max(successor_levels, 0)):
        nxt = []
        for cur, d in frontier:
            for s in kg.adj[PREREQ].get(cur, []):
                if s in nodes:
                    continue
                nodes[s] = {"depth": d + 1, "kind": "successor"}
                edges.append((cur, s))
                nxt.append((s, d + 1))
        frontier = nxt

    nodes, edges = _cap(nodes, edges, center, max_nodes)
    mermaid = _render(kg, nodes, edges, center, kind_styled=True)
    return {
        "mermaid": mermaid,
        "mode": "node",
        "center_id": center,
        "nodes": [
            {"id": nid, "name": _name_of(kg, nid), "kind": meta["kind"]}
            for nid, meta in nodes.items()
        ],
        "edges": [{"from": s, "to": t} for s, t in edges],
    }


def _build_path_graph(kg: Any, path_id: str, max_nodes: int) -> dict[str, Any]:
    """Draw prerequisite edges among a mastery path's KGraph-mapped objectives."""
    from deeptutor.learning.service import LearningService
    from deeptutor.learning.storage import LearningStore

    progress = LearningService(LearningStore()).get_or_create(path_id)

    # Map each objective to a KGraph node id (by id, else by normalised name).
    kp_to_kg: dict[str, str] = {}
    kg_to_kp: dict[str, str] = {}
    for module in progress.modules:
        for kp in module.knowledge_points:
            gid = None
            if kg.get_node(kp.id):
                gid = kp.id
            else:
                gid = kg.name_index.get(_norm(kp.name))
            if gid and gid not in kg_to_kp:
                kp_to_kg[kp.id] = gid
                kg_to_kp[gid] = kp.id

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str]] = []
    for kp in (
        kp_
        for module in progress.modules
        for kp_ in module.knowledge_points
    ):
        gid = kp_to_kg.get(kp.id)
        if not gid:
            continue
        bucket = _BUCKET_OF(progress.mastery_levels.get(kp.id, 0.0))
        nodes[gid] = {"kind": "path", "bucket": bucket, "label": kp.name}

    # Edges: prerequisites / successors that BOTH land in the path's kg set.
    for gid in list(nodes.keys()):
        for p in kg.adj_rev[PREREQ].get(gid, []):
            if p in nodes and (p, gid) not in edges:
                edges.append((p, gid))
        for s in kg.adj[PREREQ].get(gid, []):
            if s in nodes and (gid, s) not in edges:
                edges.append((gid, s))

    if not nodes:
        return {
            "mermaid": "",
            "mode": "path",
            "center_id": None,
            "nodes": [],
            "edges": [],
            "note": "no_path_nodes_mapped",
        }

    # Path graphs stay small; cap defensively.
    if len(nodes) > max_nodes:
        keep = list(nodes.keys())[:max_nodes]
        nodes = {k: nodes[k] for k in keep}
        edges = [(s, t) for s, t in edges if s in nodes and t in nodes]

    mermaid = _render_path(nodes, edges)
    return {
        "mermaid": mermaid,
        "mode": "path",
        "center_id": None,
        "nodes": [
            {"id": nid, "name": meta.get("label") or _name_of(kg, nid), "bucket": meta["bucket"]}
            for nid, meta in nodes.items()
        ],
        "edges": [{"from": s, "to": t} for s, t in edges],
    }


def _cap(nodes, edges, center, max_nodes):
    """Keep the center plus closest nodes when the graph exceeds the cap."""
    if len(nodes) <= max_nodes:
        return nodes, edges
    priority = {"center": 0, "prereq": 1, "successor": 2}
    ordered = sorted(
        nodes.items(),
        key=lambda kv: (priority.get(kv[1]["kind"], 3), kv[1].get("depth", 9)),
    )
    keep = {center}
    kept_nodes: dict[str, dict[str, Any]] = {center: nodes[center]}
    for nid, meta in ordered:
        if nid == center:
            continue
        if len(kept_nodes) >= max_nodes:
            break
        keep.add(nid)
        kept_nodes[nid] = meta
    kept_edges = [(s, t) for s, t in edges if s in keep and t in keep]
    return kept_nodes, kept_edges


def _render(kg, nodes, edges, center, kind_styled: bool) -> str:
    lines = ["graph TD"]
    for nid, meta in nodes.items():
        mid = _sanitize_id(nid)
        label = _escape_label(_name_of(kg, nid))
        lines.append(f'    {mid}["{label}"]')
    for s, t in edges:
        lines.append(f"    {_sanitize_id(s)} --> {_sanitize_id(t)}")
    if kind_styled:
        lines.append("    classDef center fill:#6366f1,stroke:#4338ca,color:#fff;")
        lines.append("    classDef prereq fill:#e0f2fe,stroke:#0284c7;")
        lines.append("    classDef successor fill:#dcfce7,stroke:#16a34a;")
        lines.append(f"    class {_sanitize_id(center)} center;")
        for nid, meta in nodes.items():
            if nid == center:
                continue
            cls = "prereq" if meta["kind"] == "prereq" else "successor"
            lines.append(f"    class {_sanitize_id(nid)} {cls};")
    return "\n".join(lines)


def _render_path(nodes, edges) -> str:
    lines = ["graph TD"]
    for nid, meta in nodes.items():
        mid = _sanitize_id(nid)
        label = _escape_label(meta.get("label") or nid)
        lines.append(f'    {mid}["{label}"]')
    for s, t in edges:
        lines.append(f"    {_sanitize_id(s)} --> {_sanitize_id(t)}")
    lines.append("    classDef weak fill:#fee2e2,stroke:#ef4444;")
    lines.append("    classDef qualified fill:#fef9c3,stroke:#eab308;")
    lines.append("    classDef good fill:#e0f2fe,stroke:#0ea5e9;")
    lines.append("    classDef proficient fill:#dcfce7,stroke:#22c55e;")
    for nid, meta in nodes.items():
        lines.append(f"    class {_sanitize_id(nid)} {meta['bucket']};")
    return "\n".join(lines)
