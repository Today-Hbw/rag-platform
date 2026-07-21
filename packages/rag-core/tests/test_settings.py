from rag_core.settings import Settings


def test_defaults():
    s = Settings()
    assert s.mysql.port == 3306
    assert s.qdrant.collection == "knowledge_documents"
    assert s.rbac.enabled is False


def test_env_nested_override(monkeypatch):
    monkeypatch.setenv("RAG_MYSQL__PASSWORD", "secret123")
    monkeypatch.setenv("RAG_MYSQL__HOST", "10.0.0.9")
    monkeypatch.setenv("RAG_SEARCH__RRF_K", "42")
    s = Settings()
    assert s.mysql.host == "10.0.0.9"
    assert s.mysql.password.get_secret_value() == "secret123"
    assert s.search.rrf_k == 42


def test_secret_not_leaked_in_repr(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING__API_KEY", "topsecretkey")
    s = Settings()
    assert "topsecretkey" not in repr(s)
    assert "topsecretkey" not in str(s.embedding)
    assert s.embedding.api_key.get_secret_value() == "topsecretkey"
