"""评估执行：对数据集逐条跑检索器 → 计算 @k 指标 → 聚合 → 存/取 run 结果。

``run_eval`` 只依赖注入的 ``retriever``（query→doc_id 列表）与纯指标，本身无 I/O，
可完全离线单测。真实跑分时由 CLI 用 embed_cache + 真 store 装配 retriever。

run 结果落盘为 JSON（含指标 + 元信息如快照 collection / 模型 endpoint），供 compare 对拍。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .metrics import DEFAULT_KS, aggregate, evaluate_case
from .schema import EvalCase

__all__ = ["RunResult", "run_eval", "save_run", "load_run"]


@dataclass
class RunResult:
    name: str
    ks: list[int]
    per_case: dict[str, dict[str, float]]  # case id → {metric@k: value}
    aggregate: dict[str, float]
    ranked: dict[str, list[int]] = field(default_factory=dict)  # case id → 检索出的 doc_id
    meta: dict = field(default_factory=dict)  # 快照 collection / 模型 endpoint / 时间戳等

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RunResult:
        return cls(
            name=d["name"],
            ks=list(d.get("ks", DEFAULT_KS)),
            per_case=d.get("per_case", {}),
            aggregate=d.get("aggregate", {}),
            ranked={k: list(v) for k, v in d.get("ranked", {}).items()},
            meta=d.get("meta", {}),
        )


def run_eval(
    cases: Sequence[EvalCase],
    retriever: Callable[[str], list[int]],
    *,
    ks: Sequence[int] = DEFAULT_KS,
    name: str = "run",
    meta: dict | None = None,
) -> RunResult:
    per_case: dict[str, dict[str, float]] = {}
    ranked_map: dict[str, list[int]] = {}
    for case in cases:
        ranked = retriever(case.query)
        ranked_map[case.id] = list(ranked)
        per_case[case.id] = evaluate_case(ranked, case.relevant_doc_ids, ks)
    agg = aggregate(list(per_case.values()))
    return RunResult(
        name=name,
        ks=list(ks),
        per_case=per_case,
        aggregate=agg,
        ranked=ranked_map,
        meta=dict(meta or {}),
    )


def save_run(run: RunResult, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_run(path: str | Path) -> RunResult:
    return RunResult.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
