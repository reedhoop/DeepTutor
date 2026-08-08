"""Distill a compact, agent-facing project map from the Graphify graph.

Output (both into reports/codegraph/):
  - AGENT_MAP.json : machine-readable, small enough to load into agent context
  - AGENT_MAP.md   : human/agent-readable summary

Goal: an AI coding agent (CodeBuddy / future sessions) can read this in a few
seconds and know (1) what the god-node hubs are (don't touch casually),
(2) exactly which files are OUR fork (the 19 custom files), and (3) the
registration SEAMS where new features must plug in (not reinvent).
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))  # scripts/codegraph -> DeepTutor
GRAPH = os.path.join(REPO, "reports/codegraph/graphify-out/graph.json")
CUSTOM = os.path.join(REPO, "reports/codegraph/custom_layer.json")
OUT_DIR = os.path.join(REPO, "reports/codegraph")

# --- Role map for our 19 custom files (from fork knowledge) -------------------
ROLE = {
    "deeptutor/_local/__init__.py": "Overlay bootstrap: apply_kgraph_overlay() registers 4 post-grade hooks at import-time. Entry point of all _local wiring.",
    "deeptutor/_local/kgraph_service_overlay.py": "MUST load before errorbook overlay; maintains consecutive_wrong counter used by error attribution.",
    "deeptutor/_local/kgraph_errorbook_overlay.py": "Post-grade hook: structural error attribution + backfill ordering. Order-dependent on service_overlay.",
    "deeptutor/_local/kgraph_policy_overlay.py": "KGraph policy overlay (scoping / gating of knowledge tools).",
    "deeptutor/_local/engine_defaults.py": "DEFAULT_ENGINE_DEFINITIONS + readiness_ttl/scan_ttl constants + normalize_routing().",
    "deeptutor/_local/engine_router.py": "resolve_engine() with readiness cache + TTL; auto/manual routing of 8 parsing engines.",
    "deeptutor/_local/runtime_overlay.py": "apply_runtime_overlay(globals()) injects new keys into DEFAULT_DOCUMENT_PARSING_SETTINGS.",
    "deeptutor/_local/kp_index.py": "O(1) find_knowledge_point_fast() index keyed by id(progress).",
    "deeptutor/_local/engines_registry.py": "ENGINE_REGISTRY + readiness probe definitions: lists the 8 parsing engines and their readiness checks.",
    "deeptutor/_local/kgraph_context_overlay.py": "KGraph context overlay: injects KGraph knowledge context into prompts (knowledge-grounding hook).",
    "deeptutor/api/routers/kgraph_textbook.py": "REST: KGraph textbook browser endpoints.",
    "deeptutor/api/routers/mastery_path.py": "get_learning_service() -> workspace-keyed cached singleton (multi-user safe).",
    "deeptutor/capabilities/mastery/error_book.py": "Stage-3 error book: cause inference, weak-point ranking, root-cause backfill.",
    "deeptutor/services/kgraph.py": "K12 KGraph service: prerequisites_data(), numpy semantic retrieval, node_vectors cache.",
    "deeptutor/services/parsing/engines/ovisocr2/backend.py": "VLM backend (ovisocr2) — loop-safe calls.",
    "deeptutor/services/parsing/engines/paddleocr_vl/backend.py": "VLM backend (paddleocr_vl) — loop-safe calls.",
    "deeptutor/tools/builtin/__init__.py": "Builtin tool registry (96 symbols). New tools register here.",
    "tests/test_local_overlay.py": "Tests for router scan tiers, resolve fallback, TTL, normalize_routing.",
    "web/app/(workspace)/textbook/page.tsx": "Textbook browser UI (tree view; candidate for markmap brain-map, ER-2).",
}

# --- Registration SEAMS: where new features MUST plug in -----------------------
SEAMS = [
    {
        "name": "post-grade hook registry",
        "file": "deeptutor/_local/__init__.py",
        "symbol": "apply_kgraph_overlay()",
        "use_when": "You need code to run AFTER an answer is graded (e.g. error-book, analytics).",
        "rule": "Register via apply_kgraph_overlay(). service_overlay MUST be ordered before errorbook_overlay (hook order is load-bearing).",
    },
    {
        "name": "builtin tool registry",
        "file": "deeptutor/tools/builtin/__init__.py",
        "symbol": "register_tool() / TOOL_REGISTRY",
        "use_when": "You need a new callable tool for the tutor agent (e.g. kgraph_visualize).",
        "rule": "Follow the variant_exercise registration pattern in deeptutor/capabilities/mastery/tools.py.",
    },
    {
        "name": "settings pipeline",
        "file": "deeptutor/_local/runtime_overlay.py",
        "symbol": "apply_runtime_overlay(globals())",
        "use_when": "You add a new config key consumed by parsing/engines.",
        "rule": "setdefault the default in DEFAULT_DOCUMENT_PARSING_SETTINGS; load_document_parsing_settings() re-normalizes every call (no cache).",
    },
    {
        "name": "engine router",
        "file": "deeptutor/_local/engine_router.py",
        "symbol": "resolve_engine()",
        "use_when": "You add a new document-parsing engine or change routing.",
        "rule": "Readiness TTL is now hoisted once per resolve_engine call; do NOT re-read settings inside _engine_ready hot path.",
    },
    {
        "name": "learning service accessor",
        "file": "deeptutor/api/routers/mastery_path.py",
        "symbol": "get_learning_service()",
        "use_when": "You need LearningService in a route/handler.",
        "rule": "Use this accessor (workspace-keyed cached singleton). Do NOT construct LearningStore() per call or as a global.",
    },
]

MAIN_FLOW = [
    "User message -> AgenticChatPipeline (upstream orchestrator)",
    "-> MessageBus / StreamBus (hub, ~341 edges) fan-out",
    "-> tool dispatch via TOOL_REGISTRY (deeptutor/tools/builtin/__init__.py)",
    "-> _local overlays hook in: kgraph_service_overlay -> kgraph_errorbook_overlay (post-grade)",
    "-> services: kgraph (K12 graph), parsing/engines (8 VLM), mastery (error_book, exercise_adapter)",
    "-> response streamed back via StreamBus -> frontend (Next.js, web/app)",
]

# --- Compute god-nodes by total degree ----------------------------------------
def main():
    g = json.load(open(GRAPH, encoding="utf-8"))
    nodes = g["nodes"]
    edges = g.get("edges", [])
    deg = {}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        deg[s] = deg.get(s, 0) + 1
        deg[t] = deg.get(t, 0) + 1
    by_id = {n["id"]: n for n in nodes}
    top = sorted(deg.items(), key=lambda x: -x[1])[:20]
    god = []
    for nid, d in top:
        n = by_id.get(nid, {})
        god.append({
            "id": nid,
            "file": n.get("source_file", ""),
            "degree": d,
            "name": n.get("label", nid),
        })

    # fork boundary from custom_layer.json
    c = json.load(open(CUSTOM, encoding="utf-8"))
    seen = {}
    for n in c["nodes"]:
        sf = n.get("source_file", "")
        layer = n.get("fork_layer", "upstream")
        if layer in ("local", "fork_modified") and sf not in seen:
            seen[sf] = layer
    boundary = []
    for sf, layer in sorted(seen.items()):
        boundary.append({
            "file": sf,
            "layer": layer,
            "role": ROLE.get(sf, "fork-modified file (role not yet documented)"),
        })

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_graph": "reports/codegraph/graphify-out/graph.json",
        "tool": "graphifyy v0.9.34 (offline AST + Leiden clustering)",
        "note": "Static snapshot of commit facab3ff. Regenerate after each feature batch.",
    }

    out = {
        "meta": meta,
        "god_nodes": god,
        "fork_boundary": boundary,
        "registration_seams": SEAMS,
        "main_flow": MAIN_FLOW,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "AGENT_MAP.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # markdown
    md = []
    md.append("# DeepTutor — Project Map for AI Agents\n")
    md.append(f"_Generated {meta['generated_at']} from {meta['tool']}._\n")
    md.append("\n## TL;DR for the agent\n")
    md.append("- This is a **fork** of HKUDS/DeepTutor. 90%+ is upstream you should NOT modify.")
    md.append("- All custom value lives in **19 files** (see Fork Boundary). Read those first.")
    md.append("- New features plug into **registration seams** — do NOT reinvent them.\n")

    md.append("\n## God-nodes (architectural hubs — don't touch casually)\n")
    for n in god[:12]:
        md.append(f"- **{n.get('name', n['id'])}** (`{n['file']}`) — degree {n['degree']}")
    md.append("\n> Our `_local/` code hangs off these hubs as leaf subsystems via post-grade hooks.\n")

    md.append("\n## Fork Boundary — the 19 custom files\n")
    for b in boundary:
        tag = "LOCAL" if b["layer"] == "local" else "FORK"
        md.append(f"### [{tag}] {b['file']}\n{b['role']}\n")

    md.append("\n## Registration Seams — where features plug in\n")
    for s in SEAMS:
        md.append(f"### {s['name']}\n- File: `{s['file']}` → `{s['symbol']}`")
        md.append(f"- Use when: {s['use_when']}")
        md.append(f"- Rule: {s['rule']}\n")

    md.append("\n## Main request flow (what you didn't write, but must understand)\n")
    for i, step in enumerate(MAIN_FLOW, 1):
        md.append(f"{i}. {step}")

    with open(os.path.join(OUT_DIR, "AGENT_MAP.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print("god_nodes:", len(god), "| fork_boundary:", len(boundary),
          "| seams:", len(SEAMS))
    print("wrote AGENT_MAP.json + AGENT_MAP.md")

if __name__ == "__main__":
    main()
