"""app.py 单测：FastAPI 端点（TestClient + 注入 fake 依赖，全离线）。"""

import fakeredis
from fastapi.testclient import TestClient

from rag_core.contracts import ChunkPayload, DocFacets
from rag_core.settings import Settings
from rag_search import auth
from rag_search.app import SearchService, create_app
from rag_search.cache import SearchCache


class FakeEmbedder:
    def embed_query(self, text=None, image_path=None, image_url=None, image_b64=None):
        return [0.1, 0.2, 0.3]


class FakeStore:
    def __init__(self, hits):
        self._hits = hits
        self.last_filter = "unset"

    def search(self, query_vec, *, limit=50, query_filter=None):
        self.last_filter = query_filter
        return list(self._hits)


def _hit(doc_id, title, text, score):
    payload = ChunkPayload(
        source="yuque", doc_id=doc_id, doc_title=title, chunk_index=0, chunk_text=text,
        facets=DocFacets(collection_id="42", collection_slug="kb", doc_key="d1"),
        source_url="http://x/1", has_image=False,
    ).to_payload()
    return {"id": f"p{doc_id}", "score": score, "payload": payload}


def _client(hits, tmp_path, *, rbac=False, service_token=""):
    settings = Settings()
    settings.paths.data_root = str(tmp_path)
    settings.rbac.enabled = rbac
    if service_token:
        from pydantic import SecretStr

        settings.rbac.service_token = SecretStr(service_token)
    store = FakeStore(hits)
    svc = SearchService(
        settings=settings,
        embedder=FakeEmbedder(),
        store=store,
        cache=SearchCache(fakeredis.FakeStrictRedis(decode_responses=True), settings),
        conn_factory=lambda: None,
    )
    return TestClient(create_app(svc)), store


def test_health(tmp_path):
    client, _ = _client([], tmp_path)
    assert client.get("/health").json() == {"status": "ok"}


def test_search_maps_generalized_to_compat_fields(tmp_path):
    client, _ = _client([_hit(1, "社保补缴", "社保补缴流程", 0.9)], tmp_path)
    resp = client.post("/search", json={"query": "社保", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_results"] == 1
    item = body["results"][0]
    assert item["doc_title"] == "社保补缴"
    assert item["book_slug"] == "kb"  # 向后兼容 = collection_slug
    assert item["doc_slug"] == "d1"  # = doc_key
    assert item["source"] == "yuque"  # 新增泛化字段
    assert item["rank"] == 1


def test_search_uses_cache_on_second_call(tmp_path):
    client, _ = _client([_hit(1, "t", "正文内容", 0.9)], tmp_path)
    first = client.post("/search", json={"query": "正文"}).json()
    assert first["from_cache"] is False
    second = client.post("/search", json={"query": "正文"}).json()
    assert second["from_cache"] is True  # 命中缓存


def test_search_refresh_bypasses_cache(tmp_path):
    client, _ = _client([_hit(1, "t", "正文", 0.9)], tmp_path)
    client.post("/search", json={"query": "正文"})
    refreshed = client.post("/search", json={"query": "正文", "refresh": True}).json()
    assert refreshed["from_cache"] is False


def test_search_empty_results(tmp_path):
    client, _ = _client([], tmp_path)
    body = client.post("/search", json={"query": "无结果"}).json()
    assert body["total_results"] == 0 and body["results"] == []


def test_image_requires_input(tmp_path):
    client, _ = _client([], tmp_path)
    assert client.post("/image", json={"top_k": 5}).status_code == 400


def test_multimodal_requires_input(tmp_path):
    client, _ = _client([], tmp_path)
    assert client.post("/multimodal", json={"top_k": 5}).status_code == 400


def test_query_log_written(tmp_path):
    client, _ = _client([_hit(1, "标题", "正文", 0.9)], tmp_path)
    client.post("/search", json={"query": "正文"})
    logs = list((tmp_path / "logs").glob("*.jsonl"))
    assert logs and logs[0].read_text(encoding="utf-8").strip()


# ---------- 服务令牌 ----------

def test_service_token_missing_rejected(tmp_path):
    client, _ = _client([_hit(1, "t", "x", 0.9)], tmp_path, service_token="SEKRET")
    resp = client.post("/search", json={"query": "x"})  # 无 Authorization
    assert resp.status_code == 401


def test_service_token_wrong_rejected(tmp_path):
    client, _ = _client([_hit(1, "t", "x", 0.9)], tmp_path, service_token="SEKRET")
    resp = client.post(
        "/search", json={"query": "x"}, headers={"Authorization": "Bearer WRONG"}
    )
    assert resp.status_code == 401


def test_service_token_correct_passes(tmp_path):
    client, _ = _client([_hit(1, "t", "x", 0.9)], tmp_path, service_token="SEKRET")
    resp = client.post(
        "/search", json={"query": "x"}, headers={"Authorization": "Bearer SEKRET"}
    )
    assert resp.status_code == 200


def test_no_token_configured_allows_all(tmp_path):
    # 未配置令牌 → 不校验(兼容现状)
    client, _ = _client([_hit(1, "t", "x", 0.9)], tmp_path)
    assert client.post("/search", json={"query": "x"}).status_code == 200


# ---------- RBAC 过滤 ----------

def test_rbac_denies_all_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: [])
    client, store = _client([_hit(1, "t", "x", 0.9)], tmp_path, rbac=True)
    body = client.post("/search", json={"query": "x"}, headers={"X-Role-Ids": "99"}).json()
    assert body["total_results"] == 0  # 无授权 → 空
    assert store.last_filter == "unset"  # 短路，未查向量库


def test_rbac_allow_all_no_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: ["*"])
    client, store = _client([_hit(1, "t", "x", 0.9)], tmp_path, rbac=True)
    body = client.post("/search", json={"query": "x"}, headers={"X-Role-Ids": "1"}).json()
    assert body["total_results"] == 1
    assert store.last_filter is None  # 超管不加 filter


def test_rbac_scoped_passes_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: ["book:42"])
    client, store = _client([_hit(1, "t", "x", 0.9)], tmp_path, rbac=True)
    client.post("/search", json={"query": "x"}, headers={"X-Role-Ids": "7"})
    assert store.last_filter is not None  # 传了 Qdrant filter
    assert store.last_filter.should[0].key == "collection_id"


def test_rbac_cache_isolated_by_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: ["*"])
    client, _ = _client([_hit(1, "t", "x", 0.9)], tmp_path, rbac=True)
    a1 = client.post("/search", json={"query": "x"}, headers={"X-Role-Ids": "1"}).json()
    a2 = client.post("/search", json={"query": "x"}, headers={"X-Role-Ids": "1"}).json()
    b1 = client.post("/search", json={"query": "x"}, headers={"X-Role-Ids": "2"}).json()
    assert a1["from_cache"] is False
    assert a2["from_cache"] is True   # 同角色 → 命中
    assert b1["from_cache"] is False  # 不同角色 → 独立缓存，不串权限
