"""cli 单测：compare 门禁 + harvest 端到端（离线；run 需内网，不测真实路径）。"""

import json

from eval import cli
from eval.runner import RunResult, save_run


def _save(tmp_path, name, agg):
    p = tmp_path / f"{name}.json"
    save_run(RunResult(name=name, ks=[1], per_case={}, aggregate=agg), p)
    return str(p)


def test_compare_passes_without_regression(tmp_path, capsys):
    before = _save(tmp_path, "before", {"recall@1": 0.5})
    after = _save(tmp_path, "after", {"recall@1": 0.7})
    rc = cli.main(["compare", "--before", before, "--after", after, "--fail-on-regress"])
    assert rc == 0
    assert "无回归" in capsys.readouterr().out


def test_compare_fails_on_regression(tmp_path):
    before = _save(tmp_path, "before", {"recall@1": 0.7})
    after = _save(tmp_path, "after", {"recall@1": 0.5})
    rc = cli.main(["compare", "--before", before, "--after", after, "--fail-on-regress"])
    assert rc == 1  # 门禁失败


def test_compare_regression_without_gate_is_zero(tmp_path):
    before = _save(tmp_path, "before", {"recall@1": 0.7})
    after = _save(tmp_path, "after", {"recall@1": 0.5})
    rc = cli.main(["compare", "--before", before, "--after", after])  # 无 --fail-on-regress
    assert rc == 0


def test_harvest_writes_templates(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "d.jsonl").write_text(
        json.dumps({"query": "社保", "doc_ids": [1, 2]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "candidates.jsonl"
    rc = cli.main(["harvest", "--logs-dir", str(logs), "--out", str(out)])
    assert rc == 0
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["query"] == "社保" and rows[0]["relevant_doc_ids"] == []
