"""Strip Exercise nodes that were mis-admitted as knowledge points.

``kgraph_bridge.TEACHABLE`` used to include ``Exercise``, so every path built
before that fix carries objectives whose *name* is a whole question stem.
This removes them and every reference that pointed at them.

Run with ``--apply`` to write; default is a dry run.

    PYTHONPATH=. .venv/Scripts/python.exe reports/clean_exercise_kps.py [--apply]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# MUST run before importing deeptutor: when executed as a script, sys.path[0] is
# reports/, which makes `import deeptutor` resolve to the stale non-editable copy
# in .venv/Lib/site-packages (v1.5.4) instead of this repo's source tree.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) in sys.path:
    sys.path.remove(str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT))

from deeptutor.capabilities.mastery.kgraph_bridge import TEACHABLE  # noqa: E402
from deeptutor.services.kgraph import get_kg, is_available  # noqa: E402

PATHS_DIR = Path("data/user/workspace/learning")

# Progress fields keyed by knowledge-point id.
_KP_KEYED_DICTS = ("mastery_levels", "consecutive_wrong", "review_schedule")
_KP_KEYED_LISTS = ("quiz_attempts", "error_records")


def main(apply: bool) -> int:
    if not is_available():
        print("K12-KGraph dataset unavailable — cannot classify nodes.")
        return 1
    kg = get_kg()

    files = sorted(PATHS_DIR.glob("kgraph_*.json"))
    if not files:
        print(f"no kgraph paths under {PATHS_DIR}")
        return 0

    total_removed = 0
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))

        doomed: set[str] = set()
        for module in data.get("modules", []):
            for kp in module.get("knowledge_points", []):
                node = kg.get_node(kp["id"])
                if node and node.get("label") not in TEACHABLE:
                    doomed.add(kp["id"])
        if not doomed:
            print(f"{path.name}: clean")
            continue

        # 1) drop the objectives themselves
        for module in data.get("modules", []):
            module["knowledge_points"] = [
                kp for kp in module.get("knowledge_points", [])
                if kp["id"] not in doomed
            ]

        # 2) drop dangling prerequisite edges (both as key and as value)
        dep_map = data.get("dep_map") or {}
        data["dep_map"] = {
            kid: [d for d in deps if d not in doomed]
            for kid, deps in dep_map.items()
            if kid not in doomed
        }

        # 3) drop per-KP state and history (should be empty, but be exact)
        orphan_state = 0
        for field in _KP_KEYED_DICTS:
            bucket = data.get(field)
            if isinstance(bucket, dict):
                hits = [k for k in bucket if k in doomed]
                orphan_state += len(hits)
                for k in hits:
                    bucket.pop(k)
        for field in _KP_KEYED_LISTS:
            bucket = data.get(field)
            if isinstance(bucket, list):
                before = len(bucket)
                data[field] = [
                    r for r in bucket
                    if r.get("knowledge_point_id") not in doomed
                ]
                orphan_state += before - len(data[field])

        # 4) a pending question aimed at a removed objective would deadlock
        #    ``next_objective`` on an id that no longer exists.
        pending = data.get("pending_question")
        if isinstance(pending, dict) and pending.get("knowledge_point_id") in doomed:
            data["pending_question"] = None
            orphan_state += 1

        total_removed += len(doomed)
        print(
            f"{path.name}: removing {len(doomed)} exercise KP(s)"
            f"{f', {orphan_state} orphan state entries' if orphan_state else ''}"
        )
        for nid in sorted(doomed):
            name = (kg.get_node(nid) or {}).get("name", "")
            print(f"    - {nid}  {name[:56]}")

        if apply:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    verb = "removed" if apply else "would remove"
    print(f"\n{verb} {total_removed} exercise KP(s) across {len(files)} path(s)")
    if not apply and total_removed:
        print("dry run — re-run with --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
