"""Topology-aware KP selector for the mastery engine (KGraph bridge).

Registered into ``deeptutor.learning.policy`` via ``register_kp_selector`` when
this module is imported (see ``deeptutor/_local/__init__.py``). When a path
carries no KGraph dependency map, it degrades to the original linear scan, so
hand-built paths behave exactly as before.
"""

from deeptutor.learning.models import KnowledgePoint, LearningModule, LearningProgress
from deeptutor.learning.policy import (
    is_mastered,
    register_kp_selector,
)
from deeptutor._local.kp_index import find_knowledge_point_fast

# Consecutive wrong answers on a KP before we push the learner back to a
# prerequisite they have not yet mastered.
WRONG_THRESHOLD = 2


def topo_aware_kp_selector(
    progress: LearningProgress, module: LearningModule
) -> KnowledgePoint | None:
    """Dependency-aware replacement for the linear scan.

    Returns the next ``KnowledgePoint`` to work on, or ``None`` to fall through
    to the original logic (e.g. nothing overrides this module).
    """
    # No KGraph dependency map => nothing to topologically override. Degrade to
    # the original linear scan so hand-built paths behave exactly as upstream.
    if not progress.dep_map:
        return None
    # Real-time fallback: if the learner is stuck on a KP, revisit an unmastered
    # prerequisite first.
    fallback = _check_wrong_trigger(progress, module)
    if fallback is not None:
        return fallback
    return _first_available_kp(progress, module)


def _first_available_kp(progress: LearningProgress, module: LearningModule):
    """First KP whose in-path prerequisites are all already mastered."""
    dep_map = progress.dep_map
    for kp in module.knowledge_points:
        if is_mastered(progress, kp):
            continue
        prereqs = dep_map.get(kp.id, [])
        if prereqs and not all(
            _is_prereq_satisfied(progress, pid) for pid in prereqs
        ):
            continue
        return kp
    return None


def _is_prereq_satisfied(progress: LearningProgress, prereq_id: str) -> bool:
    """A prerequisite is satisfied if it is already mastered, or it lives
    outside the current path (external prerequisites are assumed known)."""
    kp, _, _ = find_knowledge_point_fast(progress, prereq_id)
    if kp is None:
        return True
    return is_mastered(progress, kp)


def _check_wrong_trigger(progress: LearningProgress, module: LearningModule):
    """If a KP has >= WRONG_THRESHOLD consecutive wrong answers and a
    prerequisite is still unmastered, return that prerequisite to revisit."""
    for kp in module.knowledge_points:
        if progress.consecutive_wrong.get(kp.id, 0) < WRONG_THRESHOLD:
            continue
        if is_mastered(progress, kp):
            continue
        for pid in progress.dep_map.get(kp.id, []):
            pkp, _, _ = find_knowledge_point_fast(progress, pid)
            if pkp is not None and not is_mastered(progress, pkp):
                return pkp
    return None


# [KGRAPH-EXT] self-register on import so the overlay activates at startup.
register_kp_selector(topo_aware_kp_selector)
