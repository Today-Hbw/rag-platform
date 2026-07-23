"""schema 单测：数据集读写 / 类型归一 / 重复 id 报错。"""

import pytest
from eval.schema import EvalCase, load_dataset, save_dataset


def test_roundtrip(tmp_path):
    cases = [
        EvalCase(id="q1", query="社保补缴", relevant_doc_ids=[1, 2], note="hr"),
        EvalCase(id="q2", query="报销流程", relevant_doc_ids=[3]),
    ]
    p = tmp_path / "ds.jsonl"
    save_dataset(cases, p)
    got = load_dataset(p)
    assert [c.id for c in got] == ["q1", "q2"]
    assert got[0].relevant_doc_ids == [1, 2]
    assert got[1].note == ""


def test_load_coerces_int_and_skips_blank(tmp_path):
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"id": 1, "query": "q", "relevant_doc_ids": ["10", "20"]}\n\n',
        encoding="utf-8",
    )
    got = load_dataset(p)
    assert len(got) == 1
    assert got[0].id == "1" and got[0].relevant_doc_ids == [10, 20]


def test_duplicate_id_raises(tmp_path):
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"id": "q1", "query": "a"}\n{"id": "q1", "query": "b"}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="重复 case id"):
        load_dataset(p)


def test_malformed_line_raises(tmp_path):
    p = tmp_path / "ds.jsonl"
    p.write_text('{"id": "q1"}\n', encoding="utf-8")  # 缺 query
    with pytest.raises(ValueError):
        load_dataset(p)
