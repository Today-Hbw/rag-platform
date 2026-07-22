"""connector 注册表 + yuque 装配（load_books / from_settings）单测。"""

import json

import pytest

from rag_core.settings import Settings, YuqueSettings
from rag_pipeline.connectors import registry
from rag_pipeline.connectors.base import SourceConnector
from rag_pipeline.connectors.yuque import YuqueConnector, load_books


def test_yuque_registered_and_resolvable():
    assert "yuque" in registry.available_connectors()


def test_get_unknown_raises_with_available():
    with pytest.raises(KeyError) as ei:
        registry.get_connector("nope")
    assert "yuque" in str(ei.value)


def test_register_and_get_roundtrip():
    class Dummy(SourceConnector):
        source = "dummy"

        def scopes(self):
            return []

        def list_docs(self, scope):
            return []

        def fetch(self, scope, ref):
            raise NotImplementedError

        def asset_auth(self, scope):
            raise NotImplementedError

        def build_source_url(self, scope, detail):
            return ""

    registry.register_connector("dummy", lambda s: Dummy())
    try:
        c = registry.get_connector("dummy")
        assert isinstance(c, Dummy)
    finally:
        registry._REGISTRY.pop("dummy", None)


# ---------- load_books ----------

def test_load_books_missing_file_returns_empty(tmp_path):
    assert load_books(tmp_path / "nope.json") == []


def test_load_books_accepts_wrapped_and_bare(tmp_path):
    wrapped = tmp_path / "w.json"
    wrapped.write_text(
        json.dumps({"books": [{"book_id": 123, "book_slug": "kb"}]}), encoding="utf-8"
    )
    bare = tmp_path / "b.json"
    bare.write_text(json.dumps([{"book_id": "9", "book_slug": "x"}]), encoding="utf-8")
    bw = load_books(wrapped)
    assert bw[0].book_id == "123" and bw[0].book_slug == "kb"  # book_id 统一 str
    assert load_books(bare)[0].book_id == "9"


def test_load_books_filters_unknown_keys(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps([{"book_id": "1", "bogus": "x", "namespace": "n"}]), encoding="utf-8")
    b = load_books(p)[0]
    assert b.book_id == "1" and b.namespace == "n"  # bogus 被丢弃，未报错


# ---------- from_settings ----------

def test_from_settings_wires_secrets_and_books(tmp_path):
    cfg = tmp_path / "yuque.json"
    cfg.write_text(json.dumps({"books": [{"book_id": "42", "book_slug": "kb"}]}), encoding="utf-8")
    settings = Settings(
        yuque=YuqueSettings(
            token="TT", cookie="a=1", books_config=str(cfg),
            url_template="https://s/{namespace}/{collection_slug}/{doc_key}",
        )
    )
    c = YuqueConnector.from_settings(settings)
    assert isinstance(c, YuqueConnector)
    assert c.token == "TT" and c.cookie == "a=1"
    assert c.url_template == "https://s/{namespace}/{collection_slug}/{doc_key}"
    scopes = c.scopes()
    assert scopes[0].scope_id == "42"
