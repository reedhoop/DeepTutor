"""Stage 3 end-to-end seed + in-process proof.

Drives the REAL production flow (``LearningService.grade_and_record`` -> post
grade hook ``refine_latest_error``) to create varied error records on the
existing ``kgraph_math_8b_rjb_ch17_s1`` path, then prints the error-book
summary and a variant lookup to prove the closed loop against the real K12-KGraph
data. Idempotent: resets the path's error/attempt/mastery state first.

Run with the project venv:
    .venv/Scripts/python.exe reports/seed_errorbook_e2e.py
"""

from __future__ import annotations

import json

# Importing the overlay self-registers the post-grade hooks (consecutive-wrong
# counter + error-book refiner) in the same order the running backend uses.
import deeptutor._local  # noqa: F401
from deeptutor.learning import models as lm
from deeptutor.learning.service import LearningService, LearningStore
from deeptutor.capabilities.mastery import error_book as eb
from deeptutor.capabilities.mastery.exercise_adapter import variant_exercises

BOOK_ID = "kgraph_math_8b_rjb_ch17_s1"
MODULE_ID = BOOK_ID

# (kp_id, expected_answer, user_answer, question_type, repetitions)
# A blank user_answer -> METACOGNITIVE; a concept KP -> UNDERSTANDING_DEVIATION;
# a procedure KP -> APPLICATION_ERROR; 3x wrong -> METACOGNITIVE (streak);
# a KP whose prerequisite is unmastered -> KNOWLEDGE_STRUCTURAL.
SCENARIOS = [
    ("math_8b_rjb_cpt11", "c=5", "c=3", "short", 1),          # concept -> understanding deviation
    ("math_8b_rjb_cpt13", "S=25", "S=16", "short", 1),         # concept, prereq cpt11 unmastered -> structural
    ("math_8b_rjb_skl4", "x=13", "x=5", "short", 1),           # procedure -> application error
    ("math_8b_rjb_skl5", "√2≈1.414", "", "short", 1),          # blank -> metacognitive
    ("math_8b_rjb_cpt12", "yes", "no", "short", 3),            # concept x3 -> metacognitive (streak)
]


def main() -> None:
    store = LearningStore()
    service = LearningService(store)
    progress = store.load(BOOK_ID)
    if progress is None:
        raise SystemExit(f"path {BOOK_ID!r} not found — start it from the textbook navigator first")

    # Reset error/attempt/mastery state for a clean, repeatable E2E.
    progress.error_records = []
    progress.quiz_attempts = []
    progress.consecutive_wrong = {}
    progress.mastery_levels = {}
    progress.qualitative_mastery = {}

    for kp_id, expected, user_answer, qtype, reps in SCENARIOS:
        kp = next(
            (k for m in progress.modules for k in m.knowledge_points if k.id == kp_id),
            None,
        )
        if kp is None:
            print(f"  ! skip {kp_id!r}: not in path")
            continue
        for i in range(reps):
            service.grade_and_record(
                progress,
                question_id=f"e2e_{kp_id}_{i}",
                knowledge_point_id=kp_id,
                module_id=MODULE_ID,
                user_answer=user_answer,
                expected_answer=expected,
                question_type=qtype,
            )
    service.save(progress)

    # ── In-process proof (same functions the REST layer calls) ──
    summary = eb.summarize(progress, top_k=10)
    print("\n=== error-book summary (live path) ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:2400])

    print("\n=== variant lookup for 勾股定理 (math_8b_rjb_cpt11) ===")
    variants = variant_exercises("math_8b_rjb_cpt11", count=4)
    for v in variants:
        print(
            f"  [{v['source']}] {v['source_type']}/{v['difficulty_label']} "
            f"q={v['question'][:28]!r} a={v['expected_answer'][:18]!r}"
        )
    print(f"  -> {len(variants)} variants returned")


if __name__ == "__main__":
    main()
