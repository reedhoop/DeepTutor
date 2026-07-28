"""Regression for D2: the passive course-KB seed is suppressed under Socratic.

Phase 3 weaves curriculum depth into Socratic via the *on-demand*
``curriculum_knowledge`` tool. The passive ``course_kb`` seed must NOT also be
injected there (it would hand the answer to the student). This test locks the
capability gate that enforces that boundary, plus the tool's auto-mount flag.
"""
from __future__ import annotations

import types

import pytest

from deeptutor.agents.chat import agentic_pipeline as ap
from deeptutor.core.context import UnifiedContext


class _FakeCap:
    def __init__(self, name: str):
        self.name = name


def _ctx() -> UnifiedContext:
    return UnifiedContext(session_id="t", user_message="x", language="zh")


def test_seed_blocked_under_socratic(monkeypatch):
    monkeypatch.setattr(
        ap,
        "active_loop_capabilities",
        lambda ctx: [_FakeCap("socratic_tutor")],
    )
    assert ap.AgenticChatPipeline._course_kb_seed_blocked_by_capability(_ctx()) is True


def test_seed_blocked_under_socratic_cli_name(monkeypatch):
    monkeypatch.setattr(
        ap,
        "active_loop_capabilities",
        lambda ctx: [_FakeCap("socratic")],
    )
    assert ap.AgenticChatPipeline._course_kb_seed_blocked_by_capability(_ctx()) is True


def test_seed_not_blocked_for_chat(monkeypatch):
    monkeypatch.setattr(
        ap,
        "active_loop_capabilities",
        lambda ctx: [_FakeCap("chat")],
    )
    assert ap.AgenticChatPipeline._course_kb_seed_blocked_by_capability(_ctx()) is False


def test_curriculum_tool_mount_flag():
    # The tool is auto-mounted by the has_curriculum_kb flag (data present),
    # capability-independent — so Socratic gets the tool, not the seed.
    from deeptutor.agents._shared.tool_composition import (
        _CONDITIONAL_MOUNT_FLAGS,
    )

    assert _CONDITIONAL_MOUNT_FLAGS.get("curriculum_knowledge") == "has_curriculum_kb"
