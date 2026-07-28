"""Tests for the swappable course-KB seed strategy (Phase 1 + P2-4 kill-switch).

These guarantee:
* the active strategy is the K12-KGraph one and is the single swap point,
* the runtime kill-switch (``DEEPTUTOR_COURSE_KB_SEED_ENABLED``) works without
  deleting the index,
* ``available()`` reflects both data presence and the kill-switch,
* ``build_seed`` is empty for unknown concepts and non-empty for confident ones.
"""
from __future__ import annotations

import pytest

from deeptutor.services import course_kb_seed as cks
from deeptutor.services.course_kb_seed import (
    K12KGraphSeedStrategy,
    get_active_course_kb_seed_strategy,
)


def test_active_strategy_is_k12kgraph():
    strat = get_active_course_kb_seed_strategy()
    assert isinstance(strat, K12KGraphSeedStrategy)
    assert strat.display_name()  # human-readable header


def test_seed_enabled_default(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_COURSE_KB_SEED_ENABLED", raising=False)
    assert cks._seed_enabled() is True


def test_seed_enabled_off_switch(monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_COURSE_KB_SEED_ENABLED", "0")
    assert cks._seed_enabled() is False
    monkeypatch.setenv("DEEPTUTOR_COURSE_KB_SEED_ENABLED", "no")
    assert cks._seed_enabled() is False


def test_active_strategy_present_when_enabled(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_COURSE_KB_SEED_ENABLED", raising=False)
    strat = cks.get_active_course_kb_seed_strategy()
    assert strat is not None
    assert strat.available() is True


def test_active_strategy_none_when_disabled(monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_COURSE_KB_SEED_ENABLED", "false")
    # SWAP POINT returns None when every strategy reports unavailable (kill-switch).
    assert cks.get_active_course_kb_seed_strategy() is None


@pytest.mark.asyncio
async def test_build_seed_known_concept(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_COURSE_KB_SEED_ENABLED", raising=False)
    strat = get_active_course_kb_seed_strategy()
    seed = await strat.build_seed("勾股定理", max_chars=4000)
    assert seed.strip(), "confident concept should yield a non-empty seed"
    assert "勾股定理" in seed


@pytest.mark.asyncio
async def test_build_seed_unknown_concept_is_empty(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_COURSE_KB_SEED_ENABLED", raising=False)
    strat = get_active_course_kb_seed_strategy()
    seed = await strat.build_seed("zzz不存在的概念qwerty", max_chars=4000)
    assert seed == ""
