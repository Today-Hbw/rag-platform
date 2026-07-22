"""retrieve.py 单测：tokenize / BM25 / fuse / dedup / retrieve（fake store）。"""

from rag_core.contracts import ChunkPayload, DocFacets
from rag_core.settings import Settings
from rag_search import retrieve as rt


def test_tokenize_cjk_and_words():
    toks = rt.tokenize("社保hello123")
    assert "社" in toks and "保" in toks
    assert "hello123" in toks


def test_bm25_ranks_matching_doc_higher():
    docs = ["社保 补缴 流程", "年假 申请", "社保 缴纳 基数"]
    bm25 = rt.BM25(docs)
    res = bm25.search("社保", top_n=10)
    assert res  # 含“社保”的文档得分>0
    top_idx = res[0][0]
    assert "社保" in docs[top_idx]


def test_fuse_combines_signals_and_sorts():
    hits = [
        {"doc_title": "社保补缴", "chunk_text": "社保补缴流程说明"},
        {"doc_title": "年假", "chunk_text": "年假申请说明"},
    ]
    fused = rt.fuse(hits, "社保", rrf_k=20, title_weight=7)
    assert fused[0]["doc_title"] == "社保补缴"  # 标题+正文都命中，排第一
    assert "hybrid_score" in fused[0] and "bm25_score" in fused[0]


def _hit(doc_id, chunk_index, title, text, score):
    payload = ChunkPayload(
        source="yuque",
        doc_id=doc_id,
        doc_title=title,
        chunk_index=chunk_index,
        chunk_text=text,
        facets=DocFacets(collection_id="42", collection_slug="kb", doc_key="d1"),
        source_url="http://x/1",
    ).to_payload()
    return {"id": f"p{doc_id}-{chunk_index}", "score": score, "payload": payload}


class FakeStore:
    def __init__(self, hits):
        self._hits = hits
        self.last_filter = "unset"

    def search(self, query_vec, *, limit=50, query_filter=None):
        self.last_filter = query_filter
        return list(self._hits)


def test_retrieve_parses_generalized_payload_and_dedups():
    hits = [
        _hit(1, 0, "社保补缴", "社保补缴流程", 0.9),
        _hit(1, 0, "社保补缴", "社保补缴流程", 0.8),  # 同 (doc_id,chunk_index) → 去重
        _hit(2, 0, "年假", "年假申请", 0.7),
    ]
    store = FakeStore(hits)
    out = rt.retrieve([0.1, 0.2], store=store, conn=None, query_text="社保", settings=Settings())
    keys = {(r["doc_id"], r["chunk_index"]) for r in out}
    assert keys == {(1, 0), (2, 0)}  # 去重后 2 条
    r = next(r for r in out if r["doc_id"] == 1)
    assert r["collection_slug"] == "kb" and r["doc_key"] == "d1" and r["source"] == "yuque"
    assert r["attachments"] == []  # conn=None → 不富化


def test_retrieve_empty_when_no_hits():
    assert rt.retrieve([0.1], store=FakeStore([]), settings=Settings()) == []


def test_retrieve_passes_query_filter_through():
    store = FakeStore([_hit(1, 0, "t", "x", 0.5)])
    rt.retrieve([0.1], store=store, query_text="x", settings=Settings(), query_filter={"f": 1})
    assert store.last_filter == {"f": 1}


def test_retrieve_enriches_attachments_via_repository(monkeypatch):
    store = FakeStore([_hit(5, 0, "t", "正文", 0.5)])
    monkeypatch.setattr(
        rt.repository, "get_attachments_by_doc_ids",
        lambda conn, ids: {5: [{"filename": "a.pdf", "served_url": "/assets/a.pdf"}]},
    )
    out = rt.retrieve([0.1], store=store, conn=object(), query_text="正文", settings=Settings())
    assert out[0]["attachments"][0]["filename"] == "a.pdf"
