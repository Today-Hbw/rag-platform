"""把 run 结果 / 对拍结果渲染为可读文本（纯函数）。"""

from __future__ import annotations

from .compare import MetricDelta
from .runner import RunResult

__all__ = ["format_run", "format_comparison"]


def format_run(run: RunResult) -> str:
    lines = [f"# eval run: {run.name}", f"cases: {len(run.per_case)}  ks: {run.ks}"]
    if run.meta:
        lines.append(f"meta: {run.meta}")
    lines.append("")
    lines.append(f"{'metric':<16} {'value':>8}")
    lines.append("-" * 26)
    for metric in sorted(run.aggregate):
        lines.append(f"{metric:<16} {run.aggregate[metric]:>8.4f}")
    return "\n".join(lines)


def format_comparison(deltas: list[MetricDelta], regressed: list[MetricDelta]) -> str:
    reg_keys = {d.metric for d in regressed}
    lines = [
        f"{'metric':<16} {'before':>8} {'after':>8} {'delta':>8}  flag",
        "-" * 54,
    ]
    for d in deltas:
        flag = "REGRESS" if d.metric in reg_keys else ("+" if d.delta > 0 else "")
        lines.append(
            f"{d.metric:<16} {d.before:>8.4f} {d.after:>8.4f} {d.delta:>+8.4f}  {flag}"
        )
    lines.append("")
    lines.append(
        f"回归指标数: {len(regressed)}" if regressed else "无回归 ✅"
    )
    return "\n".join(lines)
