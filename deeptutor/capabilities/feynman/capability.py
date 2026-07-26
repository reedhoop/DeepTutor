"""Feynman tutoring capability — learn by explaining in your own words.

This is the dispatched entry point (selected from the chat capability
picker as ``capability="feynman_tutor"``). It marks the turn as a Feynman
session and reuses the standard chat agent loop. The actual behaviour —
require the learner to explain the concept in their own words, then assess
it for clarity, key omissions, and misunderstandings — is injected by
:class:`~deeptutor.capabilities.feynman.loop.FeynmanLoopCapability`, which the
loop consults via ``LOOP_CAPABILITIES``.

Design notes
------------
- Like ``SocraticTutorCapability``/``MasteryPathCapability``, this is a thin
  entry wrapper: it sets a metadata flag and runs ``AgenticChatPipeline``.
  The tutoring behaviour lives in the loop capability, not here.
- This is a proper first-class capability (registered in
  ``builtin_capabilities.py``), so the Feynman mode is scoped to the
  sessions that opt into it — partners, deep-solve, and plain chat are
  untouched.

The Feynman check itself already exists inside the Mastery Path flow
(``learning/prompts`` ``feynman.system``: judge an explanation on simple
language / key omissions / misunderstandings). This capability lifts that
same "explain-it-back" pattern into a standalone, pick-from-the-selector
mode for any topic the learner chooses.
"""

from __future__ import annotations

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus


class FeynmanTutorCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="feynman_tutor",
        description=(
            "Feynman tutoring: learn by explaining in your own words; the tutor "
            "checks for clarity, gaps, and misunderstandings."
        ),
        stages=["responding"],
        tools_used=[],
        cli_aliases=["feynman"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        context.metadata["feynman_mode"] = True
        pipeline = AgenticChatPipeline(language=context.language)
        await pipeline.run(context, stream)


__all__ = ["FeynmanTutorCapability"]
