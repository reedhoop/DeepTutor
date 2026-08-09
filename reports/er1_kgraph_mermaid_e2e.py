"""ER-1 backend regression/e2e: KGraph -> Mermaid overlay + kgraph_visualize tool.

Run with the project venv from the repo root:
    .venv/Scripts/python.exe reports/er1_kgraph_mermaid_e2e.py

Inserts the repo root at sys.path[0] FIRST so `import deeptutor` resolves to the
repository source, not the stale non-editable copy in the venv site-packages
(the classic `ModelCatalogService has no attribute update` trap).
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    # --- tool registration (no KGraph data needed) ---
    from deeptutor.capabilities.mastery.tools import (
        KGraphVisualizeTool,
        MASTERY_TOOL_NAMES,
        MASTERY_TOOL_TYPES,
    )

    assert "kgraph_visualize" in MASTERY_TOOL_NAMES, "tool name not registered"
    assert KGraphVisualizeTool in MASTERY_TOOL_TYPES, "tool class not registered"
    print("[ok] kgraph_visualize registered in mastery tool set")

    tool = KGraphVisualizeTool()
    no_path = asyncio.run(tool.execute())
    assert no_path.success is False, "no-path call should fail gracefully"
    print("[ok] tool graceful when no mastery path active")

    # --- builder end-to-end (needs the K12-KGraph dataset) ---
    from deeptutor._local.kgraph_mermaid_overlay import build_kgraph_mermaid
    from deeptutor.services.kgraph import get_kg, is_available

    if not is_available():
        print("SKIP: K12-KGraph dataset not mounted; builder not exercised.")
        return 0

    kg = get_kg()
    adj_fwd = kg.adj.get("prerequisites_for", {})
    nid = next(iter(adj_fwd.keys()), None) or next(iter(kg.name_index.values()), None)
    assert nid, "KGraph has no nodes"
    print(f"[info] sample KGraph node: {nid}")

    res = build_kgraph_mermaid(node_id=nid, levels=2, successor_levels=1)
    mermaid = res["mermaid"]
    assert mermaid.startswith("graph TD"), f"unexpected mermaid head: {mermaid[:40]!r}"
    assert "classDef" in mermaid, "node styling missing"
    if res["edges"]:
        assert "-->" in mermaid, "edges not rendered"
    assert len(res["nodes"]) >= 1, "no nodes produced"
    print(
        f"[ok] node-mode mermaid built: {len(res['nodes'])} nodes, "
        f"{len(res['edges'])} edges, {len(mermaid)} chars"
    )

    # path mode: empty / unmapped path must not raise
    empty = build_kgraph_mermaid(path_id="__no_such_path__")
    assert empty["mode"] == "path"
    print("[ok] path-mode on unknown path returns empty (no crash)")

    # unknown node -> ValueError
    try:
        build_kgraph_mermaid(node_id="__definitely_not_a_node__", levels=1, successor_levels=0)
        raise AssertionError("expected ValueError for unknown node")
    except ValueError:
        print("[ok] unknown node raises ValueError")

    # --- REST handler (the FastAPI /api/v1/kg/visualize seam) ---
    # The frontend KGraphMermaid component hits this endpoint; verify the
    # handler returns the exact shape it consumes (available/mermaid/nodes/edges)
    # and fails with 400 on bad input.
    from fastapi import HTTPException
    from deeptutor.api.routers.kg import kg_visualize

    # NOTE: calling the route directly bypasses FastAPI, so we must pass the
    # Query-defaulted ints explicitly (production FastAPI injects 2 / 1).
    r = asyncio.run(kg_visualize(node_id=nid, levels=2, successor_levels=1))
    assert r.get("available") is True, "handler must set available=True"
    assert isinstance(r.get("mermaid"), str) and r["mermaid"].startswith("graph TD"), \
        f"handler mermaid shape mismatch: {r.get('mermaid', '')[:40]!r}"
    assert r["mode"] == "node"
    for k in ("available", "mermaid", "nodes", "edges"):
        assert k in r, f"handler response missing {k!r}"
    print(f"[ok] REST kg_visualize(node_id) -> mode={r['mode']} nodes={len(r['nodes'])}")

    try:
        asyncio.run(kg_visualize(node_id=None, path_id=None, levels=2, successor_levels=1))
        raise AssertionError("expected 400 when no id supplied")
    except HTTPException as e:
        assert e.status_code == 400, f"expected 400, got {e.status_code}"

    try:
        asyncio.run(kg_visualize(node_id="__definitely_not_a_node__", levels=2, successor_levels=1))
        raise AssertionError("expected 400 for unknown node")
    except HTTPException as e:
        assert e.status_code == 400
    print("[ok] REST handler raises 400 on missing / unknown id")

    print("ALL ER-1 BACKEND CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
