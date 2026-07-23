"""两次 run 的指标对拍 + 回归门禁（``--fail-on-regress``）。

对拍锚定聚合指标（aggregate）。回归 = 某指标下降超过容差 ``tol``（默认 0，即任何下降都算）。
⚠️ 有意义的前提：两次 run 打在**同一冻结快照 collection** 上（D9），否则分不清是算法
变了还是索引变了。
"""

from __future__ import annotations

from dataclasses import dataclass

from .runner import RunResult

__all__ = ["MetricDelta", "compare_runs", "regressions"]


@dataclass
class MetricDelta:
    metric: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


def compare_runs(before: RunResult, after: RunResult) -> list[MetricDelta]:
    """逐聚合指标对比，按指标名排序。缺失指标按 0 计。"""
    keys = sorted(set(before.aggregate) | set(after.aggregate))
    return [
        MetricDelta(k, before.aggregate.get(k, 0.0), after.aggregate.get(k, 0.0))
        for k in keys
    ]


def regressions(deltas: list[MetricDelta], *, tol: float = 0.0) -> list[MetricDelta]:
    """下降超过容差的指标（delta < -tol）。tol=0 → 任何下降都算回归。"""
    return [d for d in deltas if d.delta < -tol]
