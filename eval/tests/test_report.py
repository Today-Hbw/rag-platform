"""report 单测：渲染输出含关键字段（纯字符串）。"""

from eval.compare import compare_runs
from eval.report import format_comparison, format_run
from eval.runner import RunResult


def test_format_run():
    run = RunResult(
        name="baseline", ks=[1, 3], per_case={"q1": {}},
        aggregate={"recall@1": 0.5}, meta={"collection": "snap1"},
    )
    out = format_run(run)
    assert "baseline" in out and "recall@1" in out and "0.5000" in out
    assert "snap1" in out


def test_format_comparison_marks_regression():
    before = RunResult(name="a", ks=[1], per_case={}, aggregate={"recall@1": 0.8})
    after = RunResult(name="b", ks=[1], per_case={}, aggregate={"recall@1": 0.6})
    deltas = compare_runs(before, after)
    from eval.compare import regressions

    out = format_comparison(deltas, regressions(deltas))
    assert "REGRESS" in out and "-0.2000" in out


def test_format_comparison_no_regression():
    before = RunResult(name="a", ks=[1], per_case={}, aggregate={"recall@1": 0.6})
    after = RunResult(name="b", ks=[1], per_case={}, aggregate={"recall@1": 0.8})
    out = format_comparison(compare_runs(before, after), [])
    assert "无回归" in out
