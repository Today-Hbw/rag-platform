"""retrievers 单测：chunk→doc 折叠 + make_retriever（fake store/embed，离线）。"""

from eval.retrievers import fold_to_doc_ids, make_retriever


def test_fold_preserves_first_occurrence_order():
    results = [
        {"doc_id": 5, "chunk_index": 0},
        {"doc_id": 5, "chunk_index": 3},  # 同 doc 的次 chunk → 丢
        {"doc_id": 2, "chunk_index": 1},
        {"doc_id": None},                  # 无 doc_id → 丢
        {"doc_id": 5, "chunk_index": 9},
    ]
    assert fold_to_doc_ids(results) == [5, 2]


class FakeStore:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query_vec, *, limit=50, query_filter=None):
        return list(self._hits)


def _payload(doc_id, chunk_index, text):
    from rag_core.contracts import ChunkPayload, DocFacets

    return ChunkPayload(
        source="yuque", doc_id=doc_id, doc_title=f"t{doc_id}",
        chunk_index=chunk_index, chunk_text=text,
        facets=DocFacets(collection_id="1", collection_slug="k", doc_key="d"),
        source_url="http://x", has_image=False,
    ).to_payload()


def test_make_retriever_returns_ranked_doc_ids():
    hits = [
        {"id": "a", "score": 0.9, "payload": _payload(7, 0, "社保 补缴 流程")},
        {"id": "b", "score": 0.8, "payload": _payload(7, 1, "另一段 社保")},
        {"id": "c", "score": 0.5, "payload": _payload(3, 0, "报销")},
    ]
    r = make_retriever(store=FakeStore(hits), embed_fn=lambda q: [0.1, 0.2], pool=50)
    doc_ids = r("社保")
    assert set(doc_ids) == {7, 3}
    assert doc_ids[0] == 7  # doc 7 两个 chunk 命中，排前
