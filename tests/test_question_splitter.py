"""Unit tests for the ER-12 question splitter (``_local.question_splitter``).

Covers the pure text-splitting logic (question-number regex across the common
printed-paper formats, noise-line filtering, block shaping) and base64
decoding. OCR itself (PaddleOCR) is exercised by the integration smoke, not
here — it needs model weights and is slow.
"""

from __future__ import annotations

import pytest

from deeptutor._local import question_splitter as qs


# ---------------------------------------------------------------------------
# _decode_image
# ---------------------------------------------------------------------------


def test_decode_image_plain_base64():
    import base64

    payload = base64.b64encode(b"PNGDATA").decode()
    assert qs._decode_image(payload) == b"PNGDATA"


def test_decode_image_with_data_url_prefix():
    import base64

    payload = base64.b64encode(b"PNGDATA").decode()
    assert qs._decode_image(f"data:image/png;base64,{payload}") == b"PNGDATA"


def test_decode_image_invalid_returns_none():
    assert qs._decode_image("!!!not-base64!!!") is None
    assert qs._decode_image("") is None
    assert qs._decode_image(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _split_by_question — question-number formats
# ---------------------------------------------------------------------------


SAMPLE = """1. What is the value of x?
A. 1
B. 2
C. 3
D. 4
2、求方程的解
3．计算下列各式
(4) 附加题：证明勾股定理
第5题 请写出推理过程
"""


def test_split_recognizes_number_formats():
    blocks = qs._split_by_question(SAMPLE)
    # 1. / 2、 / 3． / (4) / 第5题 → 5 blocks
    assert len(blocks) == 5
    assert blocks[0].startswith("1.")
    assert blocks[1].startswith("2、")
    assert blocks[2].startswith("3．")
    assert blocks[3].startswith("(4)")
    assert blocks[4].startswith("第5题")


def test_split_keeps_option_lines_with_question():
    blocks = qs._split_by_question(SAMPLE)
    assert "A. 1" in blocks[0]
    assert "D. 4" in blocks[0]


def test_split_drops_noise_lines():
    text = """姓名：张三    得分：98
密封线
1. 第一题内容
班级：初二3班
A. 选项甲
B. 选项乙
评卷人签字
2. 第二题
"""
    blocks = qs._split_by_question(text)
    assert len(blocks) == 2
    assert "姓名" not in blocks[0]
    assert "密封线" not in blocks[0]
    assert "得分" not in blocks[0]
    assert "班级" not in blocks[0]
    assert "评卷人" not in blocks[0]


def test_split_empty_text():
    assert qs._split_by_question("") == []
    assert qs._split_by_question("\n\n  \n") == []


def test_split_no_question_numbers_returns_single_block():
    blocks = qs._split_by_question("这里是一段没有编号的文字，只有一行。")
    assert len(blocks) == 1
    assert "这里是一段" in blocks[0]


# ---------------------------------------------------------------------------
# _to_question_dicts — ReviewQuestionIn-shaped output
# ---------------------------------------------------------------------------


def test_to_question_dicts_shapes_fields():
    blocks = ["1. 题干一\nA. x", "2、题干二"]
    out = qs._to_question_dicts(blocks)
    assert len(out) == 2
    q1, q2 = out
    assert q1["id"] == "q1"
    assert "题干一" in q1["stem"]
    assert "A. x" in q1["stem"]
    assert q1["options"] == [] and q1["answer"] == ""
    assert q1["analysis"] == "" and q1["error_type"] == "" and q1["kp_id"] == ""
    assert q2["id"] == "q2"


def test_to_question_dicts_drops_noise_inside_block():
    blocks = ["1. 题干\n得分：____\n答案写在答题卡上"]
    out = qs._to_question_dicts(blocks)
    stem = out[0]["stem"]
    assert "得分" not in stem
    assert "答案写" not in stem
    assert "题干" in stem


def test_to_question_dicts_empty_blocks_skipped():
    assert qs._to_question_dicts([]) == []
    assert qs._to_question_dicts(["", "  ", "得分：__"]) == []
