"""Built-in loop-capability registry."""

from __future__ import annotations

from deeptutor.capabilities.explore_context import ExploreContextCapability
from deeptutor.capabilities.mastery import MasteryLoopCapability
from deeptutor.capabilities.socratic import SocraticLoopCapability
from deeptutor.capabilities.obsidian import ObsidianCapability
from deeptutor.capabilities.protocol import LoopCapability
from deeptutor.capabilities.solve import SolveLoopCapability
from deeptutor.capabilities.subagent import SubagentCapability
from deeptutor.core.context import UnifiedContext

LOOP_CAPABILITIES: tuple[LoopCapability, ...] = (
    MasteryLoopCapability(),
    SolveLoopCapability(),
    ObsidianCapability(),
    SubagentCapability(),
    ExploreContextCapability(),
    SocraticLoopCapability(),
)


def active_loop_capabilities(context: UnifiedContext) -> tuple[LoopCapability, ...]:
    """Return the loop capabilities active for this turn in stable registry order."""
    return tuple(cap for cap in LOOP_CAPABILITIES if cap.is_active(context))


def any_exclusive_capability_active(context: UnifiedContext) -> bool:
    return any(
        getattr(extension, "exclusive_tools", False)
        for extension in active_loop_capabilities(context)
    )


def capability_tool_owners() -> dict[str, str]:
    """Map each capability-owned tool name to its owning capability name.

    Static (independent of any turn) so the settings UI can group capability
    tools under their owner. Built-in/system tools are absent from the map.
    """
    return {name: cap.name for cap in LOOP_CAPABILITIES for name in cap.owned_tools}


__all__ = [
    "EXTENSIONS_GROUP",
    "BUILTIN_LOOP_CAPABILITY_SPECS",
    "LOOP_CAPABILITIES",
    "active_loop_capabilities",
    "all_loop_capabilities",
    "any_exclusive_capability_active",
    "capability_tool_owners",
]
