"""Local customization overlay for DeepTutor.

Everything in this package is *ours*. The upstream ``factory.py`` and
``runtime_settings.py`` only append a tiny stable hook (a single call to one
of the ``apply_*`` functions below) so that rebasing onto the active upstream
never collides with our custom-engine additions.

See ``engines_registry.py`` and ``engine_defaults.py`` for the actual logic.

.. note::

   Importing this package **runs the KGraph -> Mastery overlay registration**
   as a side effect (``apply_kgraph_overlay()`` is invoked at the bottom of
   this module). That is deliberate — the API startup chain imports
   ``deeptutor._local`` through ``runtime_settings.py`` / ``factory.py``, so
   the bridge activates with zero extra wiring. If a future change makes any
   of those imports lazy, call ``apply_kgraph_overlay()`` explicitly in the
   entry point; do NOT assume the bridge is up just because the package is
   importable.
"""

from deeptutor._local.engines_registry import apply_factory_overlay
from deeptutor._local.runtime_overlay import apply_runtime_overlay


def apply_kgraph_overlay() -> None:
    """Register the KGraph -> Mastery bridge overlays (idempotent).

    Importing the four overlay modules self-registers the topology-aware KP
    selector, the post-grade hooks, and the textbook-material enricher. Safe
    to call repeatedly (Python caches module imports, so each overlay
    registers exactly once) and safe when the bridge is unused — hand-built
    paths degrade to the original behaviour.

    Import order is load-bearing: ``kgraph_errorbook_overlay`` reads the
    ``consecutive_wrong`` streak that ``kgraph_service_overlay`` maintains, so
    it must be registered after it. ``kgraph_context_overlay`` is
    order-independent (only attaches textbook material to rendered
    objectives).
    """
    from deeptutor._local import kgraph_policy_overlay  # noqa: F401
    from deeptutor._local import kgraph_service_overlay  # noqa: F401
    from deeptutor._local import kgraph_errorbook_overlay  # noqa: F401
    from deeptutor._local import kgraph_context_overlay  # noqa: F401


# Module-load side effect so the API startup chain (which imports this package
# through runtime_settings.py / factory.py) activates the bridge automatically.
apply_kgraph_overlay()

__all__ = [
    "apply_factory_overlay",
    "apply_runtime_overlay",
    "apply_kgraph_overlay",
]
