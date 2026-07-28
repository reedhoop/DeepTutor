"""Parametrized regression over the curated K12-KGraph eval set.

The eval cases live in ``eval/k12bench/cases.jsonl`` (the single source of
truth, also run by ``eval/k12bench/run.py``). This wrapper makes the eval set
part of the normal ``pytest`` run so it can never silently rot.

Deterministic + offline: no LLM, no network, no embedding.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.kgraph import get_kg, is_confident as _is_confident

CASES_PATH = Path(__file__).resolve().parents[2] / "eval" / "k12bench" / "cases.jsonl"

pytestmark = pytest.mark.asyncio


def _load_cases():
    cases = []
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


CASES = _load_cases()
IDS = [c["id"] for c in CASES]


@pytest.fixture(scope="module")
def kg():
    return get_kg()


@pytest.mark.parametrize("case", CASES, ids=IDS)
async def test_eval_case(case, kg):
    expect = case.get("expect", {})
    subject = case.get("subject") or None
    cands = await kg.resolve(case["query"], top_k=5, subject=subject)
    confident = bool(cands) and _is_confident(cands)
    top = cands[0] if cands else None
    cid = top["id"] if top else None

    if expect.get("confident") is True:
        assert confident, f"{case['id']}: expected confident, got {len(cands)} cands"
    if expect.get("confident") is False:
        assert not confident, f"{case['id']}: expected ambiguous, got {cid}"

    want_cid = expect.get("concept_id")
    if want_cid is not None:
        assert cid == want_cid, f"{case['id']}: id {cid} != {want_cid}"

    want_prefix = expect.get("subject_prefix")
    if want_prefix and cid is not None:
        assert cid.startswith(want_prefix + "_"), f"{case['id']}: {cid} !prefix {want_prefix}_"

    prereq_subset = expect.get("prereqs_subset") or []
    if prereq_subset and confident and cid:
        have = {p["id"] for p in kg.prerequisites_data(cid)}
        missing = [p for p in prereq_subset if p not in have]
        assert not missing, f"{case['id']}: prereqs missing {missing}"
