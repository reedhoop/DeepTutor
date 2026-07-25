"""Local customization overlay for DeepTutor.

Everything in this package is *ours*. The upstream ``factory.py`` and
``runtime_settings.py`` only append a tiny stable hook (a single call to one
of the ``apply_*`` functions below) so that rebasing onto the active upstream
never collides with our custom-engine additions.

See ``engines_registry.py`` and ``engine_defaults.py`` for the actual logic.
"""

from deeptutor._local.engines_registry import apply_factory_overlay
from deeptutor._local.runtime_overlay import apply_runtime_overlay

__all__ = ["apply_factory_overlay", "apply_runtime_overlay"]
