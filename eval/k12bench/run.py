"""Deterministic evaluation runner for the K12-KGraph integration.

This is the offline regression harness for Phase 5 (E6 of the integration
plan). It replaces the old manual "does the concept card render?" smoke check
with a reproducible, CI-friendly assertion set:

* loads the same ``K12-KGraph`` index that the backend serves,
* runs every curated query through ``KGIndex.resolve`` + the *real* confidence
  gate (``deeptutor.services.kgraph.is_confident`` — the single source of
  truth shared with the on-demand tool),
* asserts the expected resolution (concept id / subject / prerequisites).

No LLM, no network, no embedding — purely deterministic. The eval cases live
in ``cases.jsonl`` (the single source of truth, also consumed by the pytest
wrapper in ``tests/services/test_k12bench_evalset.py``).

Why offline instead of upstream K12-Bench? The original plan (E6) proposed
reusing the upstream MIT ``eval/`` runner over K12-Bench, but (a) that runner
is not present in this fork and (b) K12-Bench is an external dataset that
cannot be fetched from the sandbox. The deterministic set below captures the
same regression value for *our* curriculum-grounding layer today and can be
extended with an LLM-judged track later (see README).

Usage::

    python eval/k12bench/run.py            # run all cases, exit 1 on failure
    python eval/k12bench/run.py --quiet    # only print failures
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the repo root importable when run as a standalone script.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deeptutor.services.kgraph import get_kg, is_confident as _is_confident  # noqa: E402


CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"


def _load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


async def _evaluate(g, case: dict) -> tuple[bool, list[str]]:
    expect = case.get("expect", {})
    subject = case.get("subject") or None
    cands = await g.resolve(case["query"], top_k=5, subject=subject)
    confident = bool(cands) and _is_confident(cands)
    top = cands[0] if cands else None
    cid = top["id"] if top else None

    errors: list[str] = []

    # 1) confidence match
    if expect.get("confident") is True and not confident:
        errors.append(f"expected confident match, got ambiguous ({len(cands)} cands)")
    if expect.get("confident") is False and confident:
        errors.append(f"expected ambiguous/empty, got confident -> {cid}")

    # 2) exact concept id
    want_cid = expect.get("concept_id")
    if want_cid is not None:
        if cid != want_cid:
            errors.append(f"concept_id expected {want_cid}, got {cid}")

    # 3) subject prefix
    want_prefix = expect.get("subject_prefix")
    if want_prefix and cid is not None:
        if not cid.startswith(want_prefix + "_"):
            errors.append(f"subject_prefix expected {want_prefix}_, got {cid}")

    # 4) prerequisites subset (only meaningful when confident)
    prereq_subset = expect.get("prereqs_subset") or []
    if prereq_subset and confident and cid:
        have = {p["id"] for p in g.prerequisites_data(cid)}
        missing = [p for p in prereq_subset if p not in have]
        if missing:
            errors.append(f"prereqs missing {missing}")

    ok = not errors
    return ok, errors


def main() -> int:
    ap = argparse.ArgumentParser(description="K12-KGraph deterministic eval")
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    ap.add_argument("--cases", type=Path, default=CASES_PATH, help="path to cases.jsonl")
    args = ap.parse_args()

    cases = _load_cases(args.cases)
    g = get_kg()

    import asyncio

    results = asyncio.run(_run_all(g, cases))

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    width = max((len(c["id"]) for c in cases), default=8)

    print(f"\nK12-KGraph eval — {passed}/{total} passed\n")
    print(f"{'CASE':<{width}}  {'QUERY':<14} {'RESULT':<7} DETAIL")
    print("-" * (width + 40))
    for case, (ok, errors) in zip(cases, results):
        if ok and args.quiet:
            continue
        status = "PASS" if ok else "FAIL"
        detail = "" if ok else "; ".join(errors)
        if ok:
            detail = "ok"
        print(f"{case['id']:<{width}}  {case['query']:<14} {status:<7} {detail}")

    fails = total - passed
    print("-" * (width + 40))
    print(f"TOTAL {total}  PASS {passed}  FAIL {fails}\n")
    return 0 if fails == 0 else 1


async def _run_all(g, cases):
    out = []
    for c in cases:
        out.append(await _evaluate(g, c))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
