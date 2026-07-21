import pymysql

import rag_core.db as db
from rag_core.settings import Settings


def test_get_connection_unwraps_secret_and_passes_params(monkeypatch):
    captured = {}

    def fake_connect(**kw):
        captured.update(kw)
        return "CONN"

    monkeypatch.setattr(db.pymysql, "connect", fake_connect)
    monkeypatch.setenv("RAG_MYSQL__HOST", "h1")
    monkeypatch.setenv("RAG_MYSQL__PORT", "3307")
    monkeypatch.setenv("RAG_MYSQL__PASSWORD", "pw123")

    conn = db.get_connection(Settings())

    assert conn == "CONN"
    assert captured["host"] == "h1"
    assert captured["port"] == 3307
    assert captured["password"] == "pw123"  # SecretStr 已解包
    assert captured["cursorclass"] is pymysql.cursors.DictCursor
