"""混合检索排序：向量召回 + 正文 BM25 + 标题 BM25 的加权 RRF 融合（源无关、纯排序）。

从旧 search/search.py 搬入 tokenize/BM25/hybrid_search，并把 ``retrieve`` 从
FastAPI/_run_search 剥离为纯函数（供 eval 直接调用，绕开缓存/日志）：
输入已编码的 query_vec + 注入的 VectorStore/DB 连接，输出排序去重后的结果 dict。

payload 按 ``ChunkPayload`` 泛化字段消费（D2=A），不再读语雀专有 book_slug/doc_slug；
``query_filter`` 透传给向量层，供阶段 5 RBAC 注入（默认 None = 旧行为）。
"""

from __future__ import annotations

import math
import re
from typing import Any

from rag_core import repository
from rag_core.contracts import ChunkPayload
from rag_core.settings import Settings, get_settings
from rag_core.vectorstore import VectorStore

__all__ = ["tokenize", "BM25", "fuse", "retrieve"]

_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """分词：CJK 单字成词 + 连续字母数字成词（忠实旧逻辑）。"""
    if not text:
        return []
    return _CJK_RE.findall(text) + _WORD_RE.findall(text)


def _tokenize_unique(text: str) -> set[str]:
    return set(tokenize(text))


class BM25:
    """经典 BM25（k1=1.5, b=0.75）。移植自旧 search.py，无行为改动。"""

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.n_docs = len(documents)
        self.avg_dl = sum(len(d) for d in documents) / max(self.n_docs, 1)
        df_counts: dict[str, int] = {}
        for doc in documents:
            for tok in _tokenize_unique(doc):
                df_counts[tok] = df_counts.get(tok, 0) + 1
        self.idf = {
            tok: math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for tok, df in df_counts.items()
        }

    def score(self, query_tokens: list[str], doc_text: str) -> float:
        tokens = tokenize(doc_text)
        if not tokens:
            return 0.0
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        dl = len(tokens)
        s = 0.0
        for q in query_tokens:
            idf = self.idf.get(q, 0.0)
            if idf == 0:
                continue
            f = tf.get(q, 0)
            denom = f + self.k1 * (1 - self.b + self.b * dl / self.avg_dl)
            s += idf * (f * (self.k1 + 1)) / denom
        return s

    def search(self, query: str, top_n: int = 10) -> list[tuple[int, float]]:
        q = tokenize(query)
        scored = [(i, self.score(q, doc)) for i, doc in enumerate(self.documents)]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_n]


def fuse(
    qdrant_results: list[dict[str, Any]],
    query: str,
    *,
    rrf_k: int = 20,
    title_weight: int = 7,
) -> list[dict[str, Any]]:
    """三信号加权 RRF：向量 rank + 正文 BM25 rank + 标题 BM25 rank。

    ``score = 1/(k+向量) + 1/(k+正文BM25) + w/(k+标题BM25)``。忠实旧 hybrid_search。
    """
    chunk_texts = [r.get("chunk_text", "") for r in qdrant_results]
    bm25 = BM25(chunk_texts)
    bm25_results = bm25.search(query, top_n=len(chunk_texts))
    bm25_max = max((s for _, s in bm25_results), default=1.0)
    bm25_map = {idx: s / bm25_max for idx, s in bm25_results}
    bm25_rank = {idx: rank for rank, (idx, _) in enumerate(bm25_results, 1)}

    vector_rank = {i: rank for rank, i in enumerate(range(len(qdrant_results)), 1)}

    titles = [r.get("doc_title", "") for r in qdrant_results]
    title_results = BM25(titles).search(query, top_n=len(titles))
    title_rank = {idx: rank for rank, (idx, _) in enumerate(title_results, 1)}

    combined = []
    for i, r in enumerate(qdrant_results):
        rrf = (
            1.0 / (rrf_k + vector_rank.get(i, 999))
            + 1.0 / (rrf_k + bm25_rank.get(i, 999))
            + title_weight / (rrf_k + title_rank.get(i, 999))
        )
        combined.append({**r, "bm25_score": bm25_map.get(i, 0.0), "hybrid_score": rrf})
    combined.sort(key=lambda x: -x["hybrid_score"])
    return combined


def _parse_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Qdrant 命中 → 泛化结果 dict（用 ChunkPayload.from_payload 读扁平 payload）。"""
    p = ChunkPayload.from_payload(hit.get("payload", {}))
    return {
        "doc_id": p.doc_id,
        "doc_title": p.doc_title,
        "source": p.source,
        "collection_id": p.facets.collection_id,
        "collection_slug": p.facets.collection_slug,
        "doc_key": p.facets.doc_key,
        "chunk_index": p.chunk_index,
        "chunk_text": p.chunk_text,
        "source_url": p.source_url,
        "images": p.images,
        "has_image": p.has_image,
        "has_attachment": p.has_attachment,
        "attachment_count": p.attachment_count,
        "score": hit.get("score", 0.0),
    }


def _dedup(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 (doc_id, chunk_index) 去重，保留先出现（hybrid_score 最高）的。"""
    seen = set()
    out = []
    for r in results:
        key = (r["doc_id"], r["chunk_index"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def retrieve(
    query_vec: list[float],
    *,
    store: VectorStore,
    conn=None,
    query_text: str = "",
    top_k: int = 10,
    settings: Settings | None = None,
    query_filter: Any | None = None,
) -> list[dict[str, Any]]:
    """纯排序检索：向量召回 → RRF 融合 → 去重 → 截 top_k → 富化附件。

    ``query_filter`` 透传向量层（RBAC 预留）；``conn`` 提供时按 doc_id 批量补附件详情。
    """
    settings = settings or get_settings()
    recall_limit = settings.search.recall_limit
    hits = store.search(query_vec, limit=recall_limit, query_filter=query_filter)
    if not hits:
        return []

    parsed = [_parse_hit(h) for h in hits]
    fused = fuse(
        parsed, query_text or "",
        rrf_k=settings.search.rrf_k, title_weight=settings.search.title_weight,
    )
    deduped = _dedup(fused)[:top_k]

    if conn is not None:
        att_map = repository.get_attachments_by_doc_ids(conn, list({r["doc_id"] for r in deduped}))
        for r in deduped:
            r["attachments"] = att_map.get(r["doc_id"], [])
    else:
        for r in deduped:
            r["attachments"] = []
    return deduped
