"""Fast lookups over ``LearningProgress`` knowledge points (KGraph mastery bridge).

The upstream ``deeptutor.learning.policy.find_knowledge_point`` is an O(M·N)
linear scan over ``progress.modules`` → ``module.knowledge_points``. The mastery
error-book and the topology-aware selector call it *inside* per-KP loops, which
turns into O(K·M·N) per turn. This module builds the ``kp_id`` →
``(kp, module_id, module_name)`` index once per ``progress`` object and serves
O(1) lookups.

This is our own overlay code — it never patches the upstream function, so
``git rebase upstream/main`` stays conflict-free.
"""

from __future__ import annotations

from typing import Any

from deeptutor.learning.models import KnowledgePoint, LearningModule, LearningProgress

# keyed by id(progress) -> {kp_id: (kp, module_id, module_name)}
_KP_INDEX_CACHE: dict[int, dict[str, tuple[KnowledgePoint, str, str]]] = {}


def reset_kp_index_cache() -> None:
    """Drop cached indexes (e.g. when the progress layer is reloaded in tests)."""
    _KP_INDEX_CACHE.clear()


def find_knowledge_point_fast(
    progress: LearningProgress, kp_id: str
) -> tuple[KnowledgePoint | None, str, str]:
    """O(1) equivalent of ``find_knowledge_point`` for a stable ``progress`` object.

    Builds the index on first use per ``progress`` identity and reuses it. When
    ``progress`` is a fresh object each call (cross-request), the cache misses
    harmlessly and we just rebuild — correctness is never affected.
    """
    key = id(progress)
    idx = _KP_INDEX_CACHE.get(key)
    if idx is None:
        idx = {}
        for module in progress.modules:
            for kp in module.knowledge_points:
                # first occurrence wins, matching upstream linear-scan semantics
                idx.setdefault(kp.id, (kp, module.id, module.name))
        _KP_INDEX_CACHE[key] = idx
        if len(_KP_INDEX_CACHE) > 256:  # bound memory across many distinct progresses
            _KP_INDEX_CACHE.clear()
    return idx.get(kp_id, (None, "", ""))


def build_kp_index(
    progress: LearningProgress,
) -> dict[str, tuple[KnowledgePoint, str, str]]:
    """One-shot index build for callers that look up many KPs in a loop."""
    idx: dict[str, tuple[KnowledgePoint, str, str]] = {}
    for module in progress.modules:
        for kp in module.knowledge_points:
            idx.setdefault(kp.id, (kp, module.id, module.name))
    return idx
