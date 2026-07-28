"""Course-KB seed strategy for the chat loop (Phase 1 RAG).

WHAT THIS FILE IS
-----------------
Phase 1 of the K12-KGraph → DeepTutor integration. In Phase 0 we built the
in-memory curriculum index; in Phase 2 we exposed it as an *on-demand* tool
(``curriculum_knowledge``). This file closes the loop: it lets the **course
knowledge graph be proactively seeded** into the chat model's context for the
current question, *alongside* (and coexisting with) the user's own attached
knowledge bases, without the student having to call a tool.

WHY A STRATEGY ABSTRACTION (the user's explicit requirement)
-----------------------------------------------------------
The user asked that this retrieval behaviour be **clearly annotated / isolated**
so that *if the strategy ever needs to change, a better strategy can be swapped
in*. Concretely:

  * The *what* (how to turn "what is the student asking about" into a coherent
    chunk of curriculum context) lives entirely behind ``CourseKBSeedStrategy``.
  * The *when / whether* (capability gating such as excluding the Socratic
    tutor) stays in the chat pipeline, which owns capability knowledge. The
    strategy itself is capability-agnostic.
  * To **swap in a better strategy**, you only touch ONE place:
    ``get_active_course_kb_seed_strategy()`` (search that name — it is the single
    swap point, documented again right above the function). You may either
    return a different registered instance, or append a new class that
    implements ``CourseKBSeedStrategy`` and register it first in ``_STRATEGIES``.
    Nothing else in the codebase needs to change.

STRATEGY CONTRACT
-----------------
A ``CourseKBSeedStrategy`` must provide:
  * ``available() -> bool``        — is the backing data / service present?
  * ``display_name() -> str``      — human label used as the seed section header.
  * ``async build_seed(query, max_chars) -> str``
        Given the student's current question and a hard character budget,
        return the curriculum-context text to inject, or ``""`` when there is
        nothing confident to seed (e.g. the question names no known concept).
        The returned text must already be truncated to ``max_chars``.

The current (and default) strategy is ``K12KGraphSeedStrategy``, which reuses
the same Strategy-B confidence gate as the ``curriculum_knowledge`` tool so the
seed and the tool never disagree about what counts as a confident match.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from deeptutor.services.kgraph import is_confident

logger = logging.getLogger(__name__)


def _seed_enabled() -> bool:
    """P2-4: runtime kill-switch for the passive course-KB seed.

    The course-KB seed injects up to ``KB_SEED_CHARS_PER_KB`` of curriculum
    context into the user message. On small/free models a 4k-char injection can
    crowd out reasoning budget, so we expose a no-delete off-switch: set
    ``DEEPTUTOR_COURSE_KB_SEED_ENABLED=0`` (or false/no/off) to disable the
    seed without touching the dataset or the on-demand tool.
    """
    val = os.environ.get("DEEPTUTOR_COURSE_KB_SEED_ENABLED", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


# --------------------------------------------------------------------------- #
# Strategy contract
# --------------------------------------------------------------------------- #
class CourseKBSeedStrategy(Protocol):
    """Swappable contract for building the course-KB seed text.

    Implement this to add a new course-knowledge source. See the module
    docstring for the full contract and the single swap point.
    """

    def available(self) -> bool:
        """Return True when the backing data / service is usable."""
        ...

    def display_name(self) -> str:
        """Human-readable label, used as the seed section header."""
        ...

    async def build_seed(self, query: str, max_chars: int) -> str:
        """Build the curriculum-context seed for ``query``.

        Return ``""`` when there is nothing confident to seed. The result must
        already be truncated to ``max_chars`` characters.
        """
        ...


# --------------------------------------------------------------------------- #
# Confidence gate
# --------------------------------------------------------------------------- #
# The confidence gate is the single source ``is_confident`` in
# ``deeptutor.services.kgraph`` (imported above). The passive seed and the
# on-demand tool therefore always agree on what counts as a confident match —
# no copy-coupling.


# --------------------------------------------------------------------------- #
# Default strategy: K12-KGraph
# --------------------------------------------------------------------------- #
class K12KGraphSeedStrategy:
    """Seed the chat context from the bundled K12-KGraph curriculum index.

    Uses the same lexical-cascade + semantic-fallback resolution
    (``KGIndex.resolve``) and the same confidence gate as the on-demand
    ``curriculum_knowledge`` tool, then assembles a compact, structured
    curriculum context: definition, curriculum location, prerequisites, and the
    textbook evidence (when present). The result is meant as *grounding
    material for the tutor*, never as a ready-made answer.
    """

    def available(self) -> bool:
        from deeptutor.services.kgraph import is_available

        return is_available() and _seed_enabled()

    def display_name(self) -> str:
        return "课程知识图谱（K12-KGraph）"

    async def build_seed(self, query: str, max_chars: int, subject: str | None = None) -> str:
        from deeptutor.services.kgraph import get_kg

        query = (query or "").strip()
        self._matched_concepts: list[str] = []
        self._matched_node_ids: list[str] = []
        if not query:
            return ""

        kg = get_kg()
        cands = await kg.resolve(query, top_k=5, subject=subject)
        if not cands or not is_confident(cands):
            # Never seed an ambiguous or weak match — let the tutor ask,
            # or let the student invoke the curriculum_knowledge tool.
            return ""

        top = cands[0]
        nid = top["id"]
        parts: list[str] = []

        # 1) Definition (the core grounding fact).
        d = kg.definition_data(nid)
        parts.append(f"概念：{d.get('name', '')}")
        definition = (d.get("definition") or "").strip()
        if definition:
            parts.append(f"定义：{definition}")
        aliases = d.get("aliases") or []
        if aliases:
            parts.append("别名：" + "、".join(aliases))

        # 2) Curriculum location (helps the tutor situate the concept).
        chain = kg.path_data(nid)
        if chain:
            crumbs: list[str] = []
            seen_crumb: set[str] = set()
            for c in chain:
                name = c.get("name", "")
                cid = c.get("id", "")
                if name and cid not in seen_crumb:
                    seen_crumb.add(cid)
                    crumbs.append(name)
            if crumbs:
                parts.append("课程位置：" + " > ".join(crumbs))

        # 3) Prerequisites (what the student is expected to already know).
        prereqs = kg.prerequisites_data(nid, levels=1)
        prereq_names = [p.get("name", "") for p in prereqs if p.get("name")]
        if prereq_names:
            parts.append("前置基础：" + "、".join(prereq_names))

        # 4) Textbook evidence (authoritative source, when available).
        ev = kg.evidence_data(nid)
        evidence = (ev.get("evidence") or "").strip()
        if evidence:
            parts.append("教材依据：" + evidence)

        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n...[truncated]"
        # Track matched concepts + node_ids for observability (so a caller can
        # see *which* K12-KGraph concepts were seeded into the turn; not part
        # of the strategy contract).
        self._matched_concepts = [n for n in ([d.get("name", "")] + list(aliases)) if n]
        self._matched_node_ids.append(nid)
        return text

    def matched_concepts(self) -> list[str]:
        """Concepts matched by the most recent :meth:`build_seed` call.

        Used for observability only; not part of the ``CourseKBSeedStrategy``
        contract.
        """
        return list(self._matched_concepts)

    def matched_node_ids(self) -> list[str]:
        """Node IDs matched by the most recent :meth:`build_seed` call.

        Used for observability only; not part of the ``CourseKBSeedStrategy``
        contract.  Callers can feed these into :func:`grade_info_of_id` to
        surface the grade/semester in trace panels.
        """
        return list(self._matched_node_ids)


# --------------------------------------------------------------------------- #
# Registry + single swap point
# --------------------------------------------------------------------------- #
# Registration order = preference order. ``get_active_course_kb_seed_strategy``
# returns the first strategy whose ``available()`` is True.
_STRATEGIES: list[CourseKBSeedStrategy] = [
    K12KGraphSeedStrategy(),
]


def get_active_course_kb_seed_strategy() -> CourseKBSeedStrategy | None:
    """SWAP POINT — return the course-KB seed strategy currently in effect.

    ┌─────────────────────────────────────────────────────────────────────┐
    │  TO USE A BETTER STRATEGY: either change what this function returns,  │
    │  or implement a new class conforming to ``CourseKBSeedStrategy`` and  │
    │  register it first in ``_STRATEGIES`` above. No other code changes.   │
    └─────────────────────────────────────────────────────────────────────┘
    """
    for strategy in _STRATEGIES:
        try:
            if strategy.available():
                return strategy
        except Exception as exc:  # noqa: BLE001
            logger.warning("course-KB seed strategy %s unavailable: %s", type(strategy).__name__, exc)
    return None
