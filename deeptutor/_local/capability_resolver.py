"""Fork-specific runtime resolution for non-``llm`` chat models.

The capability-fallback router needs to resolve a model that is *not* the
active ``llm`` slot — the explicit ``vlm`` slot (T1) or a model auto-discovered
elsewhere in the catalog (T2) — through the exact same provider matching the
``llm`` slot gets (default base_url fill, local ``sk-no-key-required``,
gateway detection). Upstream only exposes that matching via
``resolve_llm_runtime_config``, which is hard-wired to the ``llm`` slot.

Rather than rewrite that upstream function (rebase friction), we *stage* the
target ``(profile, model)`` into a synthetic catalog's ``llm`` slot and reuse
the public resolver as-is. The matching is OpenAI-compatible and identical, so
the result is byte-for-byte what ``llm`` resolution would produce for that
profile/model.

No module-top ``deeptutor`` imports beyond the two stable public entry points;
everything else lives in this one self-contained fork module.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from deeptutor.services.config.model_catalog import get_model_catalog_service
from deeptutor.services.config.provider_runtime import (
    ResolvedLLMConfig,
    resolve_llm_runtime_config,
)


def resolve_catalog_pair(
    profile: dict[str, Any] | None,
    model: dict[str, Any] | None,
    catalog: dict[str, Any] | None = None,
) -> ResolvedLLMConfig:
    """Resolve an arbitrary ``(profile, model)`` pair through provider matching.

    Returns the :class:`ResolvedLLMConfig` for a model that is NOT the active
    ``llm`` slot (the explicit ``vlm`` slot, or a model the capability-fallback
    router discovered). Raises ``ValueError`` when the model name is empty —
    unlike the ``llm`` slot there is no implicit default for a hand-picked
    vision model.
    """
    model_name = ((model or {}).get("model") or "").strip()
    if not model_name:
        raise ValueError("No model is configured for this profile.")

    loaded = catalog if catalog is not None else get_model_catalog_service().load()
    # Stage the target pair as the synthetic llm slot so upstream's resolver
    # applies its full matching (default base_url / local key / gateway) to it.
    synth = deepcopy(loaded)
    synth.setdefault("services", {})["llm"] = {
        "active_profile_id": (profile or {}).get("id"),
        "active_model_id": (model or {}).get("id"),
        "profiles": [profile] if profile else [],
    }
    return resolve_llm_runtime_config(catalog=synth)


__all__ = ["resolve_catalog_pair"]
