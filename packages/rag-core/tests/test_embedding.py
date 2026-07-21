import pytest
import requests

import rag_core.embedding as emb
from rag_core.embedding import EmbeddingClient, EmbeddingError
from rag_core.settings import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 8


class FakeResp:
    def __init__(self, embedding=None, status=200, text=""):
        self._embedding = [0.1, 0.2, 0.3] if embedding is None else embedding
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return {"data": {"embedding": self._embedding}}


def _capturing_post(store):
    def post(url, headers=None, json=None, timeout=None):
        store["url"] = url
        store["headers"] = headers
        store["json"] = json
        store["timeout"] = timeout
        return FakeResp()

    return post


def test_embed_text_success(monkeypatch):
    monkeypatch.setattr(emb.requests, "post", lambda *a, **k: FakeResp([1.0, 2.0]))
    assert EmbeddingClient(Settings()).embed_text("hi") == [1.0, 2.0]


def test_embed_text_payload_and_auth(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING__MODEL_ENDPOINT", "ep-x")
    monkeypatch.setenv("RAG_EMBEDDING__API_KEY", "key123")
    store = {}
    monkeypatch.setattr(emb.requests, "post", _capturing_post(store))
    EmbeddingClient(Settings()).embed_text("你好")
    assert store["json"]["model"] == "ep-x"
    assert store["json"]["input"] == [{"type": "text", "text": "你好"}]
    assert store["json"]["encoding_format"] == "float"
    assert store["headers"]["Authorization"] == "Bearer key123"


def test_embed_query_requires_input(monkeypatch):
    monkeypatch.setattr(emb.requests, "post", lambda *a, **k: FakeResp())
    with pytest.raises(ValueError):
        EmbeddingClient(Settings()).embed_query()


def test_embed_query_image_url(monkeypatch):
    store = {}
    monkeypatch.setattr(emb.requests, "post", _capturing_post(store))
    EmbeddingClient(Settings()).embed_query(image_url="http://x/a.png")
    assert store["json"]["input"] == [{"type": "image_url", "image_url": {"url": "http://x/a.png"}}]


def test_embed_multimodal_includes_image(tmp_path, monkeypatch):
    png = tmp_path / "i.png"
    png.write_bytes(PNG)
    store = {}
    monkeypatch.setattr(emb.requests, "post", _capturing_post(store))
    EmbeddingClient(Settings()).embed_multimodal("desc", [str(png)])
    items = store["json"]["input"]
    assert items[0] == {"type": "text", "text": "desc"}
    assert items[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_embed_multimodal_skips_unsupported_mime(tmp_path, monkeypatch):
    gif = tmp_path / "i.gif"
    gif.write_bytes(GIF)  # gif 不在 SUPPORTED_IMAGE_MIMES
    store = {}
    monkeypatch.setattr(emb.requests, "post", _capturing_post(store))
    EmbeddingClient(Settings()).embed_multimodal("desc", [str(gif)])
    assert store["json"]["input"] == [{"type": "text", "text": "desc"}]


def test_retry_on_timeout_then_success(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.Timeout("t")
        return FakeResp([9.0])

    monkeypatch.setattr(emb.requests, "post", flaky)
    monkeypatch.setattr(emb.time, "sleep", lambda s: None)
    assert EmbeddingClient(Settings()).embed_text("x") == [9.0]
    assert calls["n"] == 2


def test_retry_exhausted_raises(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("c")

    monkeypatch.setattr(emb.requests, "post", boom)
    monkeypatch.setattr(emb.time, "sleep", lambda s: None)
    with pytest.raises(EmbeddingError):
        EmbeddingClient(Settings()).embed_text("x")


def test_http_429_retried(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        return FakeResp(status=429, text="rate") if calls["n"] == 1 else FakeResp([5.0])

    monkeypatch.setattr(emb.requests, "post", flaky)
    monkeypatch.setattr(emb.time, "sleep", lambda s: None)
    assert EmbeddingClient(Settings()).embed_text("x") == [5.0]
    assert calls["n"] == 2


def test_http_400_not_retried(monkeypatch):
    calls = {"n": 0}

    def bad(*a, **k):
        calls["n"] += 1
        return FakeResp(status=400, text="bad")

    monkeypatch.setattr(emb.requests, "post", bad)
    monkeypatch.setattr(emb.time, "sleep", lambda s: None)
    with pytest.raises(EmbeddingError):
        EmbeddingClient(Settings()).embed_text("x")
    assert calls["n"] == 1


def test_detect_vector_dim_from_settings(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING__VECTOR_DIM", "2048")
    monkeypatch.setattr(
        emb.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用 API"))
    )
    assert EmbeddingClient(Settings()).detect_vector_dim() == 2048


def test_detect_vector_dim_probes_when_zero(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING__VECTOR_DIM", "0")
    monkeypatch.setattr(emb.requests, "post", lambda *a, **k: FakeResp([0.0] * 7))
    assert EmbeddingClient(Settings()).detect_vector_dim() == 7
