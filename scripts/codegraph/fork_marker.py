"""Fork-semantics marker for DeepTutor code-graph tooling.

DeepTutor is a *fork* of HKUDS/DeepTutor. Almost all of the ~264k lines in the
repo are upstream code we do not own or modify. The only parts that are *ours*
are:

  1. Everything under ``deeptutor/_local/`` (the overlay "命门").
  2. The 15 files touched by our last optimization commit
     (``facab3ff``) -- fork-modified upstream files.

No off-the-shelf code-graph tool (Graphify / GitNexus / CodeGraph / ...) knows
this distinction. So after generating a graph we post-label nodes/files with
``local`` / ``fork_modified`` so the custom layer is visible at a glance.

This module is the single source of truth for that distinction.
"""

# Files modified in optimization commit facab3ff (the "ours" set outside _local/).
FORK_MODIFIED = {
    "deeptutor/_local/engine_defaults.py",
    "deeptutor/_local/engine_router.py",
    "deeptutor/_local/kgraph_errorbook_overlay.py",
    "deeptutor/_local/kgraph_policy_overlay.py",
    "deeptutor/_local/runtime_overlay.py",
    "deeptutor/_local/kp_index.py",
    "deeptutor/api/routers/kgraph_textbook.py",
    "deeptutor/api/routers/mastery_path.py",
    "deeptutor/capabilities/mastery/error_book.py",
    "deeptutor/services/kgraph.py",
    "deeptutor/services/parsing/engines/ovisocr2/backend.py",
    "deeptutor/services/parsing/engines/paddleocr_vl/backend.py",
    "deeptutor/tools/builtin/__init__.py",
    "tests/test_local_overlay.py",
    "web/app/(workspace)/textbook/page.tsx",
}

# Directory prefixes that are entirely "ours".
LOCAL_PREFIXES = ("deeptutor/_local/",)


def label_for(path: str) -> dict:
    """Return fork-semantics tags for a repo-relative path."""
    p = path.replace("\\", "/")
    tags = {"local": False, "fork_modified": False}
    if any(p.startswith(pre) for pre in LOCAL_PREFIXES):
        tags["local"] = True
    if p in FORK_MODIFIED:
        tags["fork_modified"] = True
    return tags


def classify(path: str) -> str:
    """Coarse bucket: 'local' | 'fork_modified' | 'upstream'."""
    t = label_for(path)
    if t["local"]:
        return "local"
    if t["fork_modified"]:
        return "fork_modified"
    return "upstream"
