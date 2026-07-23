"""compare 单测：delta 计算 + 回归检出 + 容差。"""

from eval.compare import compare_runs, regressions
from eval.runner import RunResult


def _run(agg):
    return RunResult(name="r", ks=[1], per_case={}, aggregate=agg)


def test_compare_deltas():
    before = _run({"recall@1": 0.5, "mrr@1": 0.4})
    after = _run({"recall@1": 0.7, "mrr@1": 0.3})
    deltas = {d.metric: d for d in compare_runs(before, after)}
    assert round(deltas["recall@1"].delta, 4) == 0.2
    assert round(deltas["mrr@1"].delta, 4) == -0.1


def test_regressions_respects_tolerance():
    before = _run({"a": 1.0, "b": 1.0})
    after = _run({"a": 0.95, "b": 0.80})
    all_deltas = compare_runs(before, after)
    assert {d.metric for d in regressions(all_deltas, tol=0.0)} == {"a", "b"}
    # 容差 0.1 → a 的 -0.05 不算回归，b 的 -0.20 算
    assert {d.metric for d in regressions(all_deltas, tol=0.1)} == {"b"}


def test_missing_metric_defaults_zero():
    deltas = {d.metric: d for d in compare_runs(_run({"x": 0.5}), _run({}))}
    assert deltas["x"].after == 0.0 and deltas["x"].delta == -0.5
