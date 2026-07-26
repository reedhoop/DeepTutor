"""Socratic tutoring capability — guided learning by questioning.

This is the dispatched entry point (selected from the chat capability
picker as ``capability="socratic_tutor"``). It marks the turn as a Socratic
session and reuses the standard chat agent loop. The actual guardrail prompt
is injected by :class:`~deeptutor.capabilities.socratic.loop.SocraticLoopCapability`,
which the loop consults via ``LOOP_CAPABILITIES``.

Design notes
------------
- Like ``MasteryPathCapability``, this is a thin entry wrapper: it sets a
  metadata flag and runs ``AgenticChatPipeline``. The tutoring behaviour lives
  in the loop capability, not here.
- This is a proper first-class capability (registered in
  ``builtin_capabilities.py``), so it scopes the Socratic guardrails to the
  sessions that opt into it — partners, deep-solve, and plain chat are
  untouched.
"""

from __future__ import annotations

import os

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus


def _socratic_enabled() -> bool:
    """Global kill-switch, mirroring the other tutoring capabilities."""
    return os.environ.get("DEEPTUTOR_SOCRATIC_GUARDRAILS", "1").strip() not in (
        "0",
        "false",
        "False",
        "no",
    )


class SocraticTutorCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="socratic_tutor",
        description=(
            "Socratic tutoring: guide the student by questioning instead of "
            "handing over the answer."
        ),
        stages=["responding"],
        tools_used=[],
        cli_aliases=["socratic"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        if _socratic_enabled():
            context.metadata["socratic_mode"] = True
        pipeline = AgenticChatPipeline(language=context.language)
        await pipeline.run(context, stream)


__all__ = ["SocraticTutorCapability"]
