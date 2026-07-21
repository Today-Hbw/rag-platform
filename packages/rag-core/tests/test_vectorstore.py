import pytest

from rag_core.settings import Settings
from rag_core.vectorstore import VectorStore, make_point

ID1 = "11111111-1111-1111-1111-111111111111"
ID2 = "22222222-2222-2222-2222-222222222222"


def _store():
    qc = pytest.importorskip("qdrant_client")
    client = qc.QdrantClient(location=":memory:")
    return VectorStore(Settings(), client=client, collection="test_col")


def test_ensure_collection_idempotent():
    vs = _store()
    assert vs.ensure_collection(4) is True
    assert vs.ensure_collection(4) is False  # 已存在


def test_upsert_search_delete_roundtrip():
    vs = _store()
    vs.ensure_collection(4)
    pts = [
        make_point(ID1, [1.0, 0.0, 0.0, 0.0], {"doc_id": 1, "chunk_text": "a"}),
        make_point(ID2, [0.0, 1.0, 0.0, 0.0], {"doc_id": 2, "chunk_text": "b"}),
    ]
    vs.upsert(pts, batch_size=1)

    res = vs.search([1.0, 0.0, 0.0, 0.0], limit=2)
    assert len(res) == 2
    assert res[0]["payload"]["doc_id"] == 1  # 与 query 最近
    assert "score" in res[0] and "id" in res[0]

    vs.delete([ID1, ID2])
    assert vs.search([1.0, 0.0, 0.0, 0.0], limit=2) == []


def test_delete_empty_is_noop():
    vs = _store()
    vs.ensure_collection(2)
    vs.delete([])  # 不应报错
