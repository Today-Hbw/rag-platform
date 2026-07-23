"""metrics 单测：钉死已知取值，防指标实现漂移。"""

import math

from eval import metrics as m


def test_hit_rate():
    assert m.hit_rate_at_k([1, 2, 3], {3}, 3) == 1.0
    assert m.hit_rate_at_k([1, 2, 3], {3}, 2) == 0.0  # 3 在第 3 位，top-2 未命中
    assert m.hit_rate_at_k([1, 2], {9}, 5) == 0.0
    assert m.hit_rate_at_k([1], set(), 5) == 0.0  # 无相关 → 0


def test_recall():
    assert m.recall_at_k([1, 2, 3, 4], {2, 4, 9}, 4) == 2 / 3  # 命中 2/4，相关共 3
    assert m.recall_at_k([1, 2], {1, 2}, 5) == 1.0
    assert m.recall_at_k([1, 2], {9}, 5) == 0.0


def test_precision():
    assert m.precision_at_k([1, 2, 3, 4], {1, 3}, 4) == 0.5  # 分母固定 k=4
    assert m.precision_at_k([1, 2], {1}, 1) == 1.0
    assert m.precision_at_k([1], {1}, 0) == 0.0


def test_mrr():
    assert m.mrr_at_k([9, 8, 3], {3}, 3) == 1 / 3  # 首个相关在第 3 位
    assert m.mrr_at_k([3, 9], {3}, 3) == 1.0
    assert m.mrr_at_k([9, 8, 3], {3}, 2) == 0.0  # 限 top-2，未及第 3 位
    assert m.mrr_at_k([1], {9}, 5) == 0.0


def test_ndcg_perfect_and_partial():
    # 完美排序：相关项都在最前 → 1.0
    assert m.ndcg_at_k([1, 2, 9], {1, 2}, 3) == 1.0
    # 单个相关项在第 2 位：dcg=1/log2(3)，idcg=1/log2(2)=1
    got = m.ndcg_at_k([9, 1, 8], {1}, 3)
    assert math.isclose(got, (1 / math.log2(3)) / 1.0)
    assert m.ndcg_at_k([1, 2], set(), 3) == 0.0


def test_evaluate_case_keys_and_aggregate():
    c1 = m.evaluate_case([1, 2, 3], {1}, ks=(1, 3))
    assert set(c1) == {
        "hit_rate@1", "hit_rate@3", "recall@1", "recall@3",
        "precision@1", "precision@3", "mrr@1", "mrr@3", "ndcg@1", "ndcg@3",
    }
    assert c1["hit_rate@1"] == 1.0
    c2 = m.evaluate_case([9, 9, 1], {1}, ks=(1, 3))  # hit_rate@1 = 0
    agg = m.aggregate([c1, c2])
    assert agg["hit_rate@1"] == 0.5  # (1 + 0) / 2


def test_aggregate_empty():
    assert m.aggregate([]) == {}
