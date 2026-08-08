"""One-command regeneration of the DeepTutor code knowledge graph.

This is the ONLY script you need to re-run after any upstream sync or feature
batch. It reproduces the full pipeline:

    graphify extract  ->  graphify cluster-only  ->  links->edges fix
    ->  label_graph  ->  build_viewer  ->  build_agent_map

The output (graph.json ~27MB + AST cache ~28MB) is a regenerable artifact and
is git-ignored (see repo .gitignore). Only THIS pipeline + .graphifyignore are
version-controlled.

Requirements:
    pip install graphifyy            # the `graphify` CLI + offline AST extractor
    # run with the python that has graphifyy installed:
    python scripts/codegraph/regenerate.py

The script uses sys.executable for every graphify call, so whatever interpreter
you launch it with must be the one that has `graphifyy` installed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))  # scripts/codegraph -> DeepTutor
OUT_DIR = os.path.join(REPO, "reports", "codegraph")
GRAPH_JSON = os.path.join(OUT_DIR, "graphify-out", "graph.json")


def run(cmd):
    print(">>>", " ".join(cmd))
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if r.stdout:
        # keep tail only; graphify is very verbose
        print("\n".join(r.stdout.splitlines()[-25:]))
    if r.returncode != 0:
        print("STDERR:\n", r.stderr[-2000:])
        sys.exit("FAILED: " + " ".join(cmd))
    return r


def links_to_edges(g):
    """cluster-only rewrites graph.json into NetworkX node-link format (links),
    but our downstream scripts + the MCP server expect `edges`. Convert back,
    deduping same-endpoint pairs (the loader collapses these anyway)."""
    if "links" in g and "edges" not in g:
        edges = []
        seen = set()
        for l in g["links"]:
            s = l.get("source")
            t = l.get("target")
            if s is None or t is None:
                continue
            key = (s, t)
            if key in seen:
                continue
            seen.add(key)
            e = {"source": s, "target": t}
            if "type" in l:
                e["type"] = l["type"]
            edges.append(e)
        g["edges"] = edges
        del g["links"]
    return g


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="cg_regen_")
    try:
        # 1) extract (AST, offline). .graphifyignore at repo root excludes
        #    i18n / scripts/codegraph / reports noise so the graph stays clean.
        run([sys.executable, "-m", "graphify", "extract", ".",
             "--code-only", "--no-cluster", "--out", tmp])

        # 2) cluster (Leiden communities); this ALSO rewrites graph.json into
        #    the `links` format (gotcha handled in links_to_edges below).
        run([sys.executable, "-m", "graphify", "cluster-only", tmp,
             "--no-label", "--no-viz"])

        # 3) fix links->edges and install as canonical graph.json
        src = os.path.join(tmp, "graphify-out", "graph.json")
        with open(src, encoding="utf-8") as f:
            g = json.load(f)
        g = links_to_edges(g)
        os.makedirs(os.path.dirname(GRAPH_JSON), exist_ok=True)
        with open(GRAPH_JSON, "w", encoding="utf-8") as f:
            json.dump(g, f, ensure_ascii=False)
        print("installed graph.json: nodes=%d edges=%d" %
              (len(g.get("nodes", [])), len(g.get("edges", []))))

        # 4) downstream generators (stdlib only)
        run([sys.executable, os.path.join(HERE, "label_graph.py")])
        run([sys.executable, os.path.join(HERE, "build_viewer.py")])
        run([sys.executable, os.path.join(HERE, "build_agent_map.py")])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nDONE. Graph regenerated at reports/codegraph/")
    print("  graph.json  -> used by MCP server + viewer")
    print("  index.html  -> open directly (self-contained)")
    print("  AGENT_MAP.* -> agent-readable project map")


if __name__ == "__main__":
    main()
