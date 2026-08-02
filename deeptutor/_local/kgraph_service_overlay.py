"""Post-grade hook: track consecutive wrong answers for the fallback trigger.

Registered into ``deeptutor.learning.service`` via ``register_post_grade_hook``
when imported (see ``deeptutor/_local/__init__.py``). Correct answers reset the
counter; wrong answers increment it. The counter is cleared on
``replace_modules`` so a fresh path never inherits stale state.
"""

from deeptutor.learning.service import register_post_grade_hook


def _update_consecutive_wrong(progress, kp_id: str, correct: bool) -> None:
    if correct:
        progress.consecutive_wrong.pop(kp_id, None)
    else:
        progress.consecutive_wrong[kp_id] = progress.consecutive_wrong.get(kp_id, 0) + 1


# [KGRAPH-EXT] self-register on import so the hook activates at startup.
register_post_grade_hook(_update_consecutive_wrong)
