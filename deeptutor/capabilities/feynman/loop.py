"""Feynman loop-capability hooks — injects the Feynman-style tutoring block.

Reuses the full chat tool surface (the same built-ins a plain chat turn
sees, under the user's composer toggles) and contributes only a system-prompt
block that reframes the tutor as a Feynman-style guide: the learner must
explain the concept in their own words, and the tutor assesses it for
clarity, key omissions, and misunderstandings, asking for a re-explanation
when the bar isn't met.

It is active only when the turn opted into Feynman tutoring
(``context.metadata["feynman_mode"]`` is set by
:class:`~deeptutor.capabilities.feynman.capability.FeynmanTutorCapability`).
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext


class FeynmanLoopCapability:
    """Turn-scoped integration for Feynman tutoring."""

    name = "feynman"
    owned_tools: tuple[str, ...] = ()

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("feynman_mode"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        override = _prompt_text(prompts, ("feynman", "system"))
        content = override or _load_system_prompt(language)
        return PromptBlock("feynman_tutor", content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        _ = (tool_name, context)
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["FeynmanLoopCapability"]
