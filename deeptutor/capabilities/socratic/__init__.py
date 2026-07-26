"""Socratic tutoring capability package.

Only the loop capability is imported here so the package can be loaded while
``deeptutor.capabilities`` initialises (the registry imports this symbol). The
dispatched entry point ``SocraticTutorCapability`` lives in ``capability.py``
and is resolved lazily via its class-path string in
``builtin_capabilities.py`` — importing it at package-load time would pull in
``agentic_pipeline`` and create a circular import.
"""

from deeptutor.capabilities.socratic.loop import SocraticLoopCapability

__all__ = ["SocraticLoopCapability"]
