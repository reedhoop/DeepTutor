"""KGraph -> Mastery bridge: turn a K12-KGraph section subtree into a mastery path.

Pure functions — no LLM calls, no I/O beyond reading the (already-loaded) KG
index. The topology-aware *ordering* of objectives lives in
``deeptutor._local.kgraph_policy_overlay``, which registers a KP selector via
``register_kp_selector``; this module only produces the data the engine
consumes (a ``LearningModule`` plus a ``dep_map`` of in-path prerequisites).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule
from deeptutor.services.kgraph import get_kg, is_available

# Concepts and Skills are teachable objectives. Experiments are demonstrations
# (not independently gradable).
#
# Exercises are deliberately excluded: they are *assessment material*, not
# learning goals. An Exercise node's ``name`` is the whole question stem, so
# admitting them made objectives read like
# "如图，在Rt△ABC与Rt△A′B′C′中…证明△ABC≌△A′B′C′" — and double-booked one node
# as both the goal and the probe that tests it. Exercises reach the learner
# through ``variant_exercise`` (see :mod:`..exercise_adapter`), which walks
# ``tests_concept`` edges to pull practice items for a *concept*.
TEACHABLE = frozenset({"Concept", "Skill"})

_LABEL_TO_TYPE: dict[str, KnowledgeType] = {
    "Concept": KnowledgeType.CONCEPT,   # qualitative gate (Feynman judged)
    "Skill": KnowledgeType.PROCEDURE,   # quantitative gate (recency-weighted >= 0.9)
}


@dataclass(frozen=True)
class BridgeResult:
    module: LearningModule
    dep_map: dict[str, list[str]]      # KP.id -> [prereq KP.id within the module]
    source_section_id: str
    stats: dict[str, int]


def section_to_module(
    section_id: str,
    module_order: int = 0,
    prereq_levels: int = 2,
) -> BridgeResult:
    """Build a mastery ``LearningModule`` from one KGraph section subtree.

    Raises ``RuntimeError`` when the K12-KGraph dataset is not on disk (the
    caller should surface this as a 4xx). ``get_kg()`` is a lazy singleton that
    always returns a loaded index, so a ``None`` guard is unnecessary.
    """
    if not is_available():
        raise RuntimeError(
            "K12-KGraph dataset not found — set K12_KGRAPH_DATA_DIR and retry"
        )
    kg = get_kg()

    # 1) Collect teachable nodes under the section (two edge types, merged).
    kids_set = set(kg.adj_rev.get("appears_in", {}).get(section_id, []))
    kids_set |= set(kg.adj_rev.get("is_part_of", {}).get(section_id, []))
    kids = [
        nid
        for nid in kids_set
        if (node := kg.get_node(nid)) and node.get("label") in TEACHABLE
    ]

    # 2) Build KPs + dep_map (only prerequisites that stay inside the module).
    module_id = f"kgraph_{section_id}"
    kid_set = set(kids)
    kps: list[KnowledgePoint] = []
    dep_map: dict[str, list[str]] = {}
    for nid in kids:
        node = kg.get_node(nid)
        kps.append(
            KnowledgePoint(
                id=nid,
                name=node.get("name", nid),
                type=_LABEL_TO_TYPE[node["label"]],
                module_id=module_id,
            )
        )
        prereqs = kg.prerequisites_data(nid, levels=prereq_levels)
        dep_map[nid] = [p["id"] for p in prereqs if p["id"] in kid_set]

    # 3) Topological order (Kahn + cycle demotion).
    ordered, cycles = _topo_sort(kps, dep_map)

    section_name = (kg.get_node(section_id) or {}).get("name", section_id)
    module = LearningModule(
        id=module_id,
        name=section_name,
        order=module_order,
        knowledge_points=ordered,
    )
    return BridgeResult(
        module=module,
        dep_map=dep_map,
        source_section_id=section_id,
        stats={
            "total_kps": len(kps),
            "with_prereqs": sum(1 for v in dep_map.values() if v),
            "cycles_skipped": cycles,
        },
    )


def _topo_sort(
    kps: list[KnowledgePoint], dep_map: dict[str, list[str]]
) -> tuple[list[KnowledgePoint], int]:
    """Return ``(ordered KPs, count of nodes in cycles)``.

    Cycle members are appended at the end in their original order (demoted,
    never dropped) so a malformed prerequisite cycle degrades to a stable
    linear order instead of crashing.
    """
    id_to_kp = {kp.id: kp for kp in kps}
    in_degree = {kp.id: 0 for kp in kps}
    successors: dict[str, list[str]] = {}
    for nid, deps in dep_map.items():
        for d in deps:
            if d in id_to_kp:
                in_degree[nid] += 1
                successors.setdefault(d, []).append(nid)

    queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
    ordered_ids: list[str] = []
    while queue:
        nid = queue.popleft()
        ordered_ids.append(nid)
        for succ in successors.get(nid, []):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    cycle_ids = [kp.id for kp in kps if kp.id not in set(ordered_ids)]
    ordered_ids.extend(cycle_ids)
    return [id_to_kp[nid] for nid in ordered_ids], len(cycle_ids)
