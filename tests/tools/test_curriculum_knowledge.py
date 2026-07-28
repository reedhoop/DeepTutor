"""Tests for the ``curriculum_knowledge`` on-demand tool (Phase 2 + Phase 3).

These pin the tool's contract: it resolves against the real K12-KGraph index,
dispatches by ``query_type``, never crashes on unknown/ambiguous input, and
respects the subject disambiguation switch.
"""
from __future__ import annotations

import pytest

from deeptutor.tools.builtin import CurriculumKnowledgeTool

pytestmark = pytest.mark.asyncio


@pytest.fixture
def tool():
    return CurriculumKnowledgeTool()


async def test_definition_matched(tool):
    r = await tool.execute(concept="勾股定理", query_type="definition")
    assert r.success is True
    assert r.metadata["status"] == "matched"
    assert "a²" in r.content or "勾股定理" in r.content
    assert r.sources and r.sources[0]["type"] == "k12_kg"


async def test_prerequisites_matched(tool):
    r = await tool.execute(concept="一次函数", query_type="prerequisites")
    assert r.metadata["status"] == "matched"
    prereqs = r.metadata["data"]["prerequisites"]
    ids = {p["id"] for p in prereqs}
    assert "math_8b_rjb_cpt48" in ids


async def test_path_matched(tool):
    r = await tool.execute(concept="勾股定理", query_type="path")
    assert r.metadata["status"] == "matched"
    assert r.metadata["data"]["path"]  # chapter breadcrumb non-empty


async def test_evidence_matched(tool):
    r = await tool.execute(concept="勾股定理", query_type="evidence")
    assert r.metadata["status"] == "matched"
    ev = r.metadata["data"]
    assert ev.get("evidences") or ev.get("relations")


async def test_unknown_concept_no_crash(tool):
    r = await tool.execute(concept="zzz不存在的概念qwerty", query_type="definition")
    assert r.success is True
    # Never auto-answers from a non-match — ambiguous (weak) or no_match only.
    assert r.metadata["status"] in {"no_match", "ambiguous"}


async def test_unknown_concept_no_match_branch(tool, monkeypatch):
    # Disable the semantic fallback so the gibberish query has zero candidates
    # and deterministically exercises the no_match branch.
    import deeptutor.services.kgraph as kgmod

    async def _fake_vectors(self):
        return {}

    monkeypatch.setattr(kgmod.KGIndex, "_ensure_vectors", _fake_vectors)
    r = await tool.execute(concept="zzz不存在的概念qwerty", query_type="definition")
    assert r.success is True
    assert r.metadata["status"] == "no_match"


async def test_ambiguous_returns_candidates(tool):
    # 三角形内角和 is ambiguous in the index (no confident winner).
    r = await tool.execute(concept="三角形内角和", query_type="definition")
    assert r.metadata["status"] == "ambiguous"
    assert r.metadata["candidates"]


async def test_subject_disambiguation(tool):
    # 函数 under physics -> no math concept matches -> no_match.
    r = await tool.execute(concept="函数", subject="physics", query_type="definition")
    assert r.metadata["status"] == "no_match"
    # ...but under math it resolves.
    r2 = await tool.execute(concept="函数", subject="math", query_type="definition")
    assert r2.metadata["status"] == "matched"
    assert r2.metadata["match"]["id"].startswith("math_")
