"""检索器封装：把 rag-search 的纯 ``retrieve()`` 适配成「query → 排序去重 doc_id 列表」。

评估单元是 doc，而 ``retrieve()`` 返回 chunk 级结果，故这里按首现顺序折叠到 doc 级
（与 app.py 的 doc 去重口径一致）。检索器对查询召回一个较大的 chunk 池（``pool``），
折叠后返回全部候选 doc_id；@k 截断交给 metrics，避免因 chunk 截断导致 doc 数不足。

``embed_fn``（query→向量）与 ``store`` 均可注入，便于离线单测（无需真打 embedding/Qdrant）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["fold_to_doc_ids", "make_retriever"]

Retriever = Callable[[str], list[int]]


def fold_to_doc_ids(results: list[dict[str, Any]]) -> list[int]:
    """chunk 结果 → 排序去重 doc_id 列表（保留首现 = hybrid_score 最高的那个 chunk）。"""
    seen: set[int] = set()
    out: list[int] = []
    for r in results:
        doc_id = r.get("doc_id")
        if doc_id is None or doc_id in seen:
            continue
        seen.add(doc_id)
        out.append(doc_id)
    return out


def make_retriever(
    *,
    store,
    embed_fn: Callable[[str], list[float]],
    conn=None,
    settings=None,
    pool: int = 50,
) -> Retriever:
    """构造检索器。``pool`` 为召回的 chunk 上限（应 ≥ 期望的最大 @k 对应 doc 数）。"""
    from rag_search.retrieve import retrieve

    def _retrieve(query: str) -> list[int]:
        query_vec = embed_fn(query)
        results = retrieve(
            query_vec, store=store, conn=conn, query_text=query, top_k=pool, settings=settings
        )
        return fold_to_doc_ids(results)

    return _retrieve
