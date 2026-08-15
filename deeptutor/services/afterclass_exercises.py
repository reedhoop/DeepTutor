"""afterclass_exercises — curated, analysis-rich textbook exercises.

Loads ``K12-KGraph/afterclass_exercises/*.json`` and indexes every question by
the KG concept/skill ids its ``links.concept_names`` / ``links.skill_names``
resolve to (via the KG name index). This is **complementary** to the KG
``Exercise`` nodes already consumed by :mod:`exercise_adapter`:

* different id scheme (``math_7a_rjb_ch1_s1_t1`` vs ``math_7a_rjb_exe1``);
* carries a worked ``analysis`` field the KG ``Exercise`` nodes largely lack;
* currently covers 数学 + 化学 only (no biology/physics files upstream).

Exposes :func:`get_afterclass` (lazy singleton) and
:meth:`AfterclassIndex.questions_for`, which the variant pipeline turns into
``exercise_to_quiz``-shaped dicts tagged ``source="afterclass"``.

Pure JSON — no I/O after load, no LLM. The dir is resolved with the same
"in-repo priority, sibling fallback" convention as :mod:`kgraph`.
"""

from __future__ import annotations

import glob
import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.kgraph import DATA_DIR, _norm, get_kg, is_available

logger = logging.getLogger(__name__)

_SUFFIX = "afterclass_exercises"


class AfterclassIndex:
    """In-memory index over the afterclass_exercises dataset."""

    def __init__(self) -> None:
        # KG node id -> list of raw question dicts linked to that concept/skill.
        self.by_concept: dict[str, list[dict[str, Any]]] = {}
        self.subjects: set[str] = set()
        self.total = 0
        self.loaded = False

    # -- loading ---------------------------------------------------------- #
    def load(self) -> "AfterclassIndex":
        if self.loaded:
            return self
        root = self._resolve_dir()
        if not root or not root.is_dir():
            logger.warning(
                "afterclass_exercises not found (looked under %s); "
                "variant_exercises will skip this source.",
                DATA_DIR / "K12-KGraph" / _SUFFIX,
            )
            self.loaded = True
            return self

        kg = get_kg()  # ensures name_index is populated
        for fp in sorted(glob.glob(str(root / "*.json"))):
            try:
                with open(fp, encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:  # noqa: BLE001 - skip a corrupt file
                logger.warning("afterclass_exercises: failed to load %s: %s", fp, exc)
                continue
            if not isinstance(data, dict):
                continue
            subject = str(data.get("subject") or "")
            if subject:
                self.subjects.add(subject)
            for q in data.get("questions", []) or []:
                self._index_question(q, kg)

        self.loaded = True
        logger.info(
            "afterclass_exercises loaded: %d questions, %d concepts/skills indexed, "
            "subjects=%s",
            self.total,
            len(self.by_concept),
            sorted(self.subjects),
        )
        return self

    def _index_question(self, q: dict[str, Any], kg: Any) -> None:
        qid = q.get("id")
        if not qid:
            return
        self.total += 1
        links = q.get("links") or {}
        names = [
            *((links.get("concept_names") or [])),
            *((links.get("skill_names") or [])),
        ]
        seen_ids: set[str] = set()
        for nm in names:
            if not nm:
                continue
            nid = kg.name_index.get(_norm(nm))
            if not nid or nid in seen_ids:
                continue
            seen_ids.add(nid)
            self.by_concept.setdefault(nid, []).append(q)

    def _resolve_dir(self) -> Path | None:
        """Same convention as ``kgraph._default_data_dir``: in-repo copy first,
        then the sibling clone at ``<parent-of-repo>/K12-KGraph-data``."""
        in_repo = DATA_DIR / "K12-KGraph" / _SUFFIX
        if in_repo.is_dir():
            return in_repo
        sibling = DATA_DIR.parent.parent / "K12-KGraph-data" / "K12-KGraph" / _SUFFIX
        if sibling.is_dir():
            return sibling
        return None

    # -- queries ---------------------------------------------------------- #
    def questions_for(self, concept_id: str) -> list[dict[str, Any]]:
        """Raw afterclass questions linked (by resolved name) to *concept_id*."""
        return self.by_concept.get(concept_id, [])

    def stats(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "indexed_concepts": len(self.by_concept),
            "subjects": sorted(self.subjects),
            "available": self.loaded and bool(self.by_concept),
        }


_index: AfterclassIndex | None = None


def get_afterclass() -> AfterclassIndex:
    """Lazily load + return the singleton afterclass index."""
    global _index
    if _index is None:
        _index = AfterclassIndex().load()
    return _index


def is_available_afterclass() -> bool:
    """True when afterclass_exercises data is present and resolvable."""
    if not is_available():
        return False
    idx = get_afterclass()
    return idx.loaded and bool(idx.by_concept)


__all__ = ["AfterclassIndex", "get_afterclass", "is_available_afterclass"]
