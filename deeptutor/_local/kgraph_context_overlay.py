"""Textbook material for the objective the learner is on (KGraph bridge).

Registered into ``deeptutor.learning.policy`` via ``register_kp_enricher`` when
this module is imported (see ``deeptutor/_local/__init__.py``).

Why this exists: the engine describes an objective as
``{id, name, type, status, mastery}``. A name tells the tutor *what* to teach
("勾股定理", "赵爽弦图") but not what the textbook actually says, so the model
falls back on its own priors — fine for universal theorems, wrong for concepts
a specific edition defines its own way. KGraph concept nodes already carry that
material; this overlay hands it to the tutor.

Degrades to ``{}`` when the dataset is absent or the id is not a KG node, so
hand-built (non-KGraph) paths behave exactly as before.
"""

from functools import lru_cache

from deeptutor.learning.policy import register_kp_enricher
from deeptutor.services.kgraph import get_kg, is_available

# Per-field clamp. Definitions run ~50-100 chars; the ceiling only guards
# against a pathological node bloating the tool payload.
_MAX_CHARS = 600
_MAX_LIST_ITEMS = 4

# Concept nodes carry definition/importance/examples/aliases/formula/unit;
# Skill nodes carry a single `description`. Ordered by teaching value.
_TEXT_FIELDS = ("definition", "description", "formula", "unit", "importance")
_LIST_FIELDS = ("aliases", "examples")


def _clip(value: str) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= _MAX_CHARS else text[: _MAX_CHARS - 1] + "…"


@lru_cache(maxsize=4096)
def kp_source_context(kp_id: str) -> dict:
    """Textbook material behind *kp_id*, or ``{}`` when there is none.

    Cached because ``next_objective`` runs on every tutor turn while the
    underlying dataset is a static on-disk snapshot.
    """
    if not kp_id or not is_available():
        return {}
    node = get_kg().get_node(kp_id)
    if not node:
        return {}
    props = node.get("properties") or {}
    out: dict[str, object] = {}

    for key in _TEXT_FIELDS:
        raw = props.get(key)
        if isinstance(raw, str) and raw.strip():
            out[key] = _clip(raw)

    for key in _LIST_FIELDS:
        raw = props.get(key)
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, (list, tuple)):
            items = [_clip(v) for v in raw if isinstance(v, str) and v.strip()]
            if items:
                out[key] = items[:_MAX_LIST_ITEMS]

    if out:
        # Tells the tutor these words are the book's, not its own recollection.
        out["source"] = "K12-KGraph textbook节点"
    return out


# [KGRAPH-EXT] self-register on import so the overlay activates at startup.
register_kp_enricher(kp_source_context)
