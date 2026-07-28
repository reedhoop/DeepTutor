"""Deterministic tests for the K12-KGraph index service.

These lock the curriculum-grounding layer's *correctness* (the part that is
pure graph traversal / JSON lookup, no LLM, no embedding) so refactors or
dataset swaps surface immediately. They are deterministic and offline.
"""
from __future__ import annotations

import pytest

from deeptutor.services.kgraph import get_kg

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def kg():
    return get_kg()


def test_index_loaded(kg):
    # Plan Phase 0 built the index from 10,685 nodes.
    assert len(kg.nodes) > 10000


async def test_resolve_exact(kg):
    cands = await kg.resolve("勾股定理", top_k=5)
    assert cands and cands[0]["id"] == "math_8b_rjb_cpt11"
    assert cands[0]["method"] == "exact"


async def test_resolve_by_alias(kg):
    # 勾股定理 carries alias 毕达哥拉斯定理 (P0-3: aliases are indexed).
    cands = await kg.resolve("毕达哥拉斯定理", top_k=5)
    assert cands and cands[0]["id"] == "math_8b_rjb_cpt11"
    assert cands[0]["method"] == "exact"


async def test_resolve_subject_filter(kg):
    # 函数 is a math concept; under subject=physics it must be filtered out.
    math_cands = await kg.resolve("函数", subject="math", top_k=5)
    assert math_cands and math_cands[0]["id"].startswith("math_")
    phys_cands = await kg.resolve("函数", subject="physics", top_k=5)
    assert phys_cands == []


async def test_prerequisites_subset(kg):
    prereqs = kg.prerequisites_data("math_8b_rjb_cpt50")  # 一次函数
    ids = {p["id"] for p in prereqs}
    assert "math_8b_rjb_cpt48" in ids
    assert "math_8b_rjb_cpt57" in ids


async def test_evidence_aggregation(kg):
    # P0-1 fix: evidence lives on edges, aggregated into _node_evidence.
    ev = kg.evidence_data("math_8b_rjb_cpt11")
    assert ev["evidences"] or ev["relations"], "no teaching evidence aggregated"


def test_skill_description_fallback(kg):
    # P0-2 fix: Skill nodes carry `description`, not `definition`; the accessor
    # must fall back to `description` when label == "Skill".
    skill_id = None
    for nid, n in kg.nodes.items():
        if n.get("label") == "Skill":
            desc = (n.get("properties", {}) or {}).get("description")
            if desc:
                skill_id = nid
                break
    assert skill_id is not None, "no Skill node with a description in fixture"
    d = kg.definition_data(skill_id)
    assert d["definition"], "Skill description fallback returned empty"
