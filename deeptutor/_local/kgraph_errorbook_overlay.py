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
register_post_grade_hook(refine_latest_error)
