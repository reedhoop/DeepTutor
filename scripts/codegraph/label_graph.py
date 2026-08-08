"""Post-label a Graphify graph.json with DeepTutor fork semantics.

Graphify (and every other code-graph tool) has no concept of "this is OUR fork's
custom layer vs upstream". This script:

  1. Adds a ``fork_layer`` field to every node in graph.json, derived from the
     node's ``source_file`` (local | fork_modified | upstream).
  2. Extracts a small *focus subgraph* = all local + fork_modified nodes plus
     their 1-hop upstream neighbors, written to custom_layer.json. This is the
     actually-useful view for fork maintenance (the full 22k-node graph is
     mostly upstream noise).

Run AFTER `graphify extract` / `graphify cluster-only` so the ``community``
field (if present) is preserved.
"""

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))  # scripts/codegraph -> DeepTutor
GRAPH_JSON = os.path.join(REPO, "reports", "codegraph", "graphify-out", "graph.json")
CUSTOM_JSON = os.path.join(REPO, "reports", "codegraph", "custom_layer.json")

sys.path.insert(0, HERE)
from fork_marker import classify  # noqa: E402


def main():
    with open(GRAPH_JSON, encoding="utf-8") as f:
        g = json.load(f)

    nodes = g.get("nodes", [])
    edges = g.get("edges", [])

    # 1) label every node
    counts = {"local": 0, "fork_modified": 0, "upstream": 0}
    node_by_id = {}
    for n in nodes:
        sf = n.get("source_file", "") or ""
        layer = classify(sf)
        n["fork_layer"] = layer
        counts[layer] += 1
        node_by_id[n["id"]] = n

    # 2) focus subgraph = ego network of the fork core.
    #    Keep every node that is local/fork_modified, PLUS the upstream nodes
    #    they touch, PLUS every edge that touches the core (this is what shows
    #    the blast radius / what upstream our custom layer depends on).
    core_ids = {n["id"] for n in nodes if n["fork_layer"] in ("local", "fork_modified")}
    focus_ids = set(core_ids)
    focus_edges = []
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in core_ids or t in core_ids:
            focus_edges.append(e)
            if s in node_by_id:
                focus_ids.add(s)
            if t in node_by_id:
                focus_ids.add(t)

    focus_nodes = [node_by_id[i] for i in focus_ids if i in node_by_id]

    custom = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "graphify extract (AST) + fork labeling",
            "totals": {
                "graph_nodes": len(nodes),
                "graph_edges": len(edges),
                "focus_nodes": len(focus_nodes),
                "focus_edges": len(focus_edges),
            },
            "fork_layer_counts": counts,
        },
        "nodes": focus_nodes,
        "edges": focus_edges,
    }

    # write back labeled full graph (in place, preserves community field)
    with open(GRAPH_JSON, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False)

    with open(CUSTOM_JSON, "w", encoding="utf-8") as f:
        json.dump(custom, f, ensure_ascii=False)

    print("labeled graph.json: nodes=%d  fork_layer=%s" % (len(nodes), counts))
    print("custom_layer.json:  focus_nodes=%d  focus_edges=%d" %
          (len(focus_nodes), len(focus_edges)))
    # show the core (local + fork_modified) files aggregated
    core = [n for n in focus_nodes if n["fork_layer"] in ("local", "fork_modified")]
    from collections import Counter
    by_file = Counter(n["source_file"] for n in core)
    print("\ncore (local + fork_modified) files: %d  symbols: %d" %
          (len(by_file), len(core)))
    for f, c in sorted(by_file.items(), key=lambda x: (-x[1], x[0])):
        print("  %4d  %s" % (c, f))


if __name__ == "__main__":
    main()
