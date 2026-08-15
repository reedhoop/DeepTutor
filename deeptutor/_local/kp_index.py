"""Fast lookups over LearningProgress knowledge points (KGraph mastery bridge).

The upstream deeptutor.learning.policy.find_knowledge_point is an O(M*N) linear
scan over progress.modules -> module.knowledge_points. The mastery error-book
and the topology-aware selector call it inside per-KP loops, which turns into
O(K*M*N) per turn. This module builds the kp_id -> (kp, module_id, module_name)
index on demand and serves O(1) lookups after a single O(total-KPs) build.

This is our own overlay code — it never patches the upstream function, so
git rebase upstream/main stays conflict-free.
"""

from __future__ import annotations

from deeptutor.learning.models import KnowledgePoint, LearningProgress


def find_knowledge_point_fast(
    progress: LearningProgress, kp_id: str
) -> tuple[KnowledgePoint | None, str, str]:
    """O(total-KPs) equivalent of find_knowledge_point.

    Rebuilds the index on every call. This is deliberately NOT cached: a global
    cache keyed by id(progress) was unsafe — CPython reuses object addresses
    after GC, and an in-place replace_modules never invalidates a cached entry —
    so a later LearningProgress could hit a stale entry and receive another
    path's KPs, corrupting error-book attribution. Path sizes are small, so the
    rebuild cost is negligible; callers that look up many KPs in one loop should
    build the index once via build_kp_index and reuse it.
    """
    return build_kp_index(progress).get(kp_id, (None, "", ""))


def build_kp_index(
    progress: LearningProgress,
) -> dict[str, tuple[KnowledgePoint, str, str]]:
    """One-shot index build for callers that look up many KPs in a loop."""
    idx: dict[str, tuple[KnowledgePoint, str, str]] = {}
    for module in progress.modules:
        for kp in module.knowledge_points:
            idx.setdefault(kp.id, (kp, module.id, module.name))
    return idx
