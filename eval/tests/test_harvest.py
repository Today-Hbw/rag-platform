"""harvest 单测：从日志 pooling 候选 + 频次过滤 + 模板生成。"""

import json

from eval.harvest import harvest_from_logs, to_case_templates


def _write_logs(tmp_path, entries):
    d = tmp_path / "logs"
    d.mkdir()
    with open(d / "2026-07-23.jsonl", "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return d


def test_harvest_aggregates_freq_and_pools_candidates(tmp_path):
    logs = _write_logs(tmp_path, [
        {"query": "社保", "doc_ids": [1, 2]},
        {"query": "社保", "doc_ids": [2, 3]},   # 并集 pooling → [1,2,3]
        {"query": "报销", "doc_ids": [9]},
        {"query": "(image)", "doc_ids": [7]},    # 图片查询跳过
        {"query": "  ", "doc_ids": [8]},          # 空查询跳过
    ])
    rows = harvest_from_logs(logs)
    by_q = {r["query"]: r for r in rows}
    assert by_q["社保"]["freq"] == 2
    assert by_q["社保"]["candidate_doc_ids"] == [1, 2, 3]
    assert "(image)" not in by_q and "  " not in by_q
    assert rows[0]["query"] == "社保"  # 频次降序


def test_min_freq_filter(tmp_path):
    logs = _write_logs(tmp_path, [
        {"query": "a", "doc_ids": []},
        {"query": "a", "doc_ids": []},
        {"query": "b", "doc_ids": []},
    ])
    rows = harvest_from_logs(logs, min_freq=2)
    assert [r["query"] for r in rows] == ["a"]


def test_max_candidates_truncates(tmp_path):
    logs = _write_logs(tmp_path, [{"query": "a", "doc_ids": list(range(100))}])
    rows = harvest_from_logs(logs, max_candidates=5)
    assert rows[0]["candidate_doc_ids"] == [0, 1, 2, 3, 4]


def test_to_case_templates_leaves_relevant_empty():
    rows = [{"query": "社保", "freq": 3, "candidate_doc_ids": [1, 2]}]
    tpl = to_case_templates(rows)
    assert tpl[0]["id"] == "q1"
    assert tpl[0]["relevant_doc_ids"] == []  # 待人工打标
    assert "candidates=[1, 2]" in tpl[0]["note"]
