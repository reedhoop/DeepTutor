"""Post-grade hook: re-file the error record with a structure-aware cause.

Registered into ``deeptutor.learning.service`` via ``register_post_grade_hook``
when imported (see ``deeptutor/_local/__init__.py``). Must be registered AFTER
``kgraph_service_overlay`` — that hook updates ``consecutive_wrong``, which the
refinement reads to tell a one-off slip from a stuck streak.

Upstream's ``classify_error`` only distinguishes a blank answer from everything
else; this upgrades the record in place using the dependency map and knowledge
type. No upstream file changes.
"""

from deeptutor.capabilities.mastery.error_book import refine_latest_error
from deeptutor.learning.service import register_post_grade_hook

# [KGRAPH-EXT] self-register on import so the hook activates at startup.
# Import-order assertion: this hook reads ``progress.consecutive_wrong`` that the
# ``kgraph_service_overlay`` hook maintains, so that overlay MUST be imported
# first. ``apply_kgraph_overlay()`` orders them correctly; this guard fails fast
# (instead of silently mis-ordering the post-grade hooks) if someone imports
# this module directly out of order.
import sys as _sys

if "deeptutor._local.kgraph_service_overlay" not in _sys.modules:
    raise RuntimeError(
        "kgraph_errorbook_overlay imported before kgraph_service_overlay; "
        "the post-grade hook order is load-bearing. Import it via "
        "deeptutor._local.apply_kgraph_overlay() (which orders them correctly)."
    )

register_post_grade_hook(refine_latest_error)
