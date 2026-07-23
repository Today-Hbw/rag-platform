"""检索评估指标（全纯函数，无 I/O，是重点单测对象）。

评估单元 = ``doc_id``：预测为「排序去重的 doc_id 列表」，标注为「相关 doc_id 集合」
（REFACTOR_PLAN §5.3）。所有 @k 指标对单条查询计算，``aggregate`` 求均值。

二值相关性（相关/不相关）；如需分级相关性，ndcg 的 gain 可后续扩展。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

__all__ = [
    "DEFAULT_KS",
    "hit_rate_at_k",
    "recall_at_k",
    "precision_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "METRICS",
    "evaluate_case",
    "aggregate",
]

DEFAULT_KS = (1, 3, 5, 10)


def _topk(ranked: Sequence, k: int) -> list:
    if k <= 0:
        return []
    return list(ranked[:k])


def hit_rate_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """top-k 内是否命中任一相关 doc（0/1）。"""
    rel = set(relevant)
    if not rel:
        return 0.0
    return 1.0 if any(d in rel for d in _topk(ranked, k)) else 0.0


def recall_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """top-k 命中的相关 doc 占全部相关 doc 的比例。"""
    rel = set(relevant)
    if not rel:
        return 0.0
    hits = sum(1 for d in _topk(ranked, k) if d in rel)
    return hits / len(rel)


def precision_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """top-k 内相关 doc 的比例（分母固定为 k）。"""
    if k <= 0:
        return 0.0
    rel = set(relevant)
    hits = sum(1 for d in _topk(ranked, k) if d in rel)
    return hits / k


def mrr_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """首个相关 doc 的倒数排名（限 top-k 内）；无命中为 0。"""
    rel = set(relevant)
    for i, d in enumerate(_topk(ranked, k), 1):
        if d in rel:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """二值相关性的归一化折损累积增益。"""
    rel = set(relevant)
    if not rel:
        return 0.0
    dcg = 0.0
    for i, d in enumerate(_topk(ranked, k), 1):
        if d in rel:
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


METRICS = {
    "hit_rate": hit_rate_at_k,
    "recall": recall_at_k,
    "precision": precision_at_k,
    "mrr": mrr_at_k,
    "ndcg": ndcg_at_k,
}


def evaluate_case(
    ranked: Sequence, relevant: Iterable, ks: Sequence[int] = DEFAULT_KS
) -> dict[str, float]:
    """单条查询 → ``{"<metric>@<k>": value}``。"""
    rel = set(relevant)
    out: dict[str, float] = {}
    for name, fn in METRICS.items():
        for k in ks:
            out[f"{name}@{k}"] = fn(ranked, rel, k)
    return out


def aggregate(per_case: Sequence[dict[str, float]]) -> dict[str, float]:
    """多条查询的逐指标均值。空输入返回空 dict。"""
    if not per_case:
        return {}
    keys = per_case[0].keys()
    n = len(per_case)
    return {key: sum(c.get(key, 0.0) for c in per_case) / n for key in keys}
