"""Unit tests for the KGraph textbook-tree stage (学段) grouping.

Regression for the "必修一 与 九年级同级" issue: KGraph models every book as a
flat child of its subject with no 初中/高中 grouping node. The API derives a
stage layer from book-id conventions instead (grade token ``8a``/``9`` →
junior, ``bx1``/``xzxbx2`` → senior) so the frontend can render
subject → stage → book → chapter.
"""

from __future__ import annotations

from unittest import mock

import pytest

from deeptutor.api.routers import kgraph_textbook as mod
from deeptutor.services.kgraph import IS_PART_OF


# ---------------------------------------------------------------------------
# _stage_id_for_book — pure id → stage mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("book_id", "expected"),
    [
        ("physics_8a_rjb", "junior"),
        ("physics_8b_rjb", "junior"),
        ("physics_9_rjb", "junior"),
        ("math_7a_rjb", "junior"),
        ("math_9a_rjb", "junior"),
        ("chemistry_9a_rjb", "junior"),
        ("biology_7a_rjb", "junior"),
        ("math_1a_rjb", "primary"),
        ("math_6b_rjb", "primary"),
        ("physics_bx1_rjb", "senior"),
        ("physics_bx2_rjb", "senior"),
        ("physics_bx3_rjb", "senior"),
        ("physics_xzxbx1_rjb", "senior"),
        ("math_bx1_rjb", "senior"),
    ],
)
def test_stage_id_for_book_known_shapes(book_id: str, expected: str) -> None:
    assert mod._stage_id_for_book(book_id) == expected


@pytest.mark.parametrize(
    "book_id",
    [
        "physics",  # single segment, no grade token
        "physics_grade_x",  # no digit, no bx
        "custom_vol1",  # leading letter → volume number, not a grade
        "custom_part2",
        "",
    ],
)
def test_stage_id_for_book_unknown_returns_none(book_id: str) -> None:
    assert mod._stage_id_for_book(book_id) is None


# ---------------------------------------------------------------------------
# _build_tree — stages metadata attached per subject (fake kg)
# ---------------------------------------------------------------------------


def _node(name: str, label: str) -> dict[str, str]:
    return {"name": name, "label": label}


class _FakeKg:
    def __init__(self, nodes: dict, children_of: dict) -> None:
        self.nodes = nodes
        self.adj_rev = {IS_PART_OF: children_of}


def _physics_kg() -> _FakeKg:
    """Flat physics graph: 3 junior + 3 senior books, one chapter each."""
    nodes: dict[str, dict] = {}
    children_of: dict[str, list[str]] = {}
    for bid in (
        "physics_8a_rjb", "physics_8b_rjb", "physics_9_rjb",
        "physics_bx1_rjb", "physics_bx2_rjb", "physics_xzxbx1_rjb",
    ):
        nodes[bid] = _node(
            {"physics_8a_rjb": "八年级上册", "physics_8b_rjb": "八年级下册",
             "physics_9_rjb": "九年级", "physics_bx1_rjb": "必修一",
             "physics_bx2_rjb": "必修二", "physics_xzxbx1_rjb": "选择性必修一"}[bid],
            "Book",
        )
        ch = f"{bid}_ch1"
        nodes[ch] = _node("第一章", "Chapter")
        nodes[f"{ch}_s1"] = _node("第一节", "Section")
        children_of[bid] = [ch]
        children_of[ch] = [f"{ch}_s1"]
    return _FakeKg(nodes, children_of)


@pytest.mark.asyncio
async def test_build_tree_attaches_stages_in_order():
    kg = _physics_kg()
    with mock.patch.object(mod, "get_kg", return_value=kg), \
         mock.patch.object(mod, "is_available", return_value=True):
        tree = mod._build_tree()

    physics = next(s for s in tree["subjects"] if s["id"] == "physics")
    # Flat books list kept for backward compatibility.
    assert len(physics["books"]) == 6
    # Stage groups in fixed order: 初中 → 高中.
    assert [s["id"] for s in physics["stages"]] == ["junior", "senior"]
    junior, senior = physics["stages"]
    assert junior["name"] == "初中"
    assert set(junior["book_ids"]) == {"physics_8a_rjb", "physics_8b_rjb", "physics_9_rjb"}
    assert set(senior["book_ids"]) == {"physics_bx1_rjb", "physics_bx2_rjb", "physics_xzxbx1_rjb"}


@pytest.mark.asyncio
async def test_build_tree_unknown_book_stays_ungrouped():
    kg = _physics_kg()
    kg.nodes["physics_custom_x"] = _node("自编教材", "Book")
    kg.nodes["physics_custom_x_ch1"] = _node("第一章", "Chapter")
    kg.nodes["physics_custom_x_ch1_s1"] = _node("第一节", "Section")
    kg.adj_rev[IS_PART_OF]["physics_custom_x"] = ["physics_custom_x_ch1"]
    kg.adj_rev[IS_PART_OF]["physics_custom_x_ch1"] = ["physics_custom_x_ch1_s1"]

    with mock.patch.object(mod, "get_kg", return_value=kg), \
         mock.patch.object(mod, "is_available", return_value=True):
        tree = mod._build_tree()

    physics = next(s for s in tree["subjects"] if s["id"] == "physics")
    # Ungrouped book stays in the flat list but in no stage group.
    assert len(physics["books"]) == 7
    assert all(
        "physics_custom_x" not in stage["book_ids"]
        for stage in physics["stages"]
    )


@pytest.mark.asyncio
async def test_build_tree_subject_without_stages():
    # A subject whose books carry no recognizable grade tokens → stages empty.
    kg = _FakeKg(
        {
            "custom_a": _node("教材A", "Book"),
            "custom_a_ch1": _node("第一章", "Chapter"),
        },
        {
            "custom_a": ["custom_a_ch1"],
            "custom_a_ch1": [],
        },
    )
    with mock.patch.object(mod, "get_kg", return_value=kg), \
         mock.patch.object(mod, "is_available", return_value=True):
        tree = mod._build_tree()
    subj = tree["subjects"][0]
    assert subj["stages"] == []
