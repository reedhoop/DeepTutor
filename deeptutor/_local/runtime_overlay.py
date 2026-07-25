"""Local overlay — applies our engine defaults into upstream runtime_settings.

Called once at the end of ``runtime_settings.py`` with the module namespace:
``apply_runtime_overlay(globals())``. It only *adds* to upstream structures
(the engine-id frozenset and the default settings dict), so a rebase onto
upstream never has to merge into the literals we no longer touch.
"""

from __future__ import annotations

from typing import Any, Dict

from deeptutor._local import engine_defaults as _ld


def apply_runtime_overlay(ns: Dict[str, Any]) -> None:
    # Union our engine ids into the upstream frozenset.
    ns["_DOCUMENT_PARSING_ENGINES"] = ns["_DOCUMENT_PARSING_ENGINES"] | _ld.EXTERNAL_ENGINE_IDS
    # Merge our default per-engine slices into the upstream defaults dict.
    ns["DEFAULT_DOCUMENT_PARSING_SETTINGS"]["engines"].update(
        _ld.DEFAULT_EXTERNAL_ENGINE_SLICES
    )
