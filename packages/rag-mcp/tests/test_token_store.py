"""token_store 单测：本地存取 / 环境变量优先 / login 契约（全离线）。"""

from rag_mcp import token_store


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.delenv(token_store.ENV_TOKEN, raising=False)
    monkeypatch.setenv(token_store.ENV_TOKEN_FILE, str(tmp_path / "t.json"))
    token_store.save_token("abc123", base_url="http://svc")
    assert token_store.load_token() == "abc123"


def test_env_token_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv(token_store.ENV_TOKEN_FILE, str(tmp_path / "t.json"))
    token_store.save_token("from-file")
    monkeypatch.setenv(token_store.ENV_TOKEN, "from-env")
    assert token_store.load_token() == "from-env"  # 环境变量优先于文件


def test_load_missing_file_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv(token_store.ENV_TOKEN, raising=False)
    monkeypatch.setenv(token_store.ENV_TOKEN_FILE, str(tmp_path / "absent.json"))
    assert token_store.load_token() is None


def test_load_corrupt_file_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv(token_store.ENV_TOKEN, raising=False)
    p = tmp_path / "t.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(token_store.ENV_TOKEN_FILE, str(p))
    assert token_store.load_token() is None


def test_clear_token(monkeypatch, tmp_path):
    monkeypatch.delenv(token_store.ENV_TOKEN, raising=False)
    monkeypatch.setenv(token_store.ENV_TOKEN_FILE, str(tmp_path / "t.json"))
    token_store.save_token("x")
    assert token_store.clear_token() is True
    assert token_store.load_token() is None
    assert token_store.clear_token() is False  # 再删已不存在


def test_token_file_path_env_override(monkeypatch):
    monkeypatch.setenv(token_store.ENV_TOKEN_FILE, "/custom/path/token.json")
    p = token_store.token_file_path()
    assert p.name == "token.json"
    assert "custom" in p.parts and "path" in p.parts


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResp(self._payload)


def test_login_posts_phone_code_and_returns_payload():
    http = _FakeHttp({"token": "T", "expires_at": 999})
    out = token_store.login("http://biz/login", "138", "1234", timeout=5, client=http)
    assert out["token"] == "T"
    assert http.calls[0]["json"] == {"phone": "138", "code": "1234"}
    assert http.calls[0]["url"] == "http://biz/login"
    assert http.calls[0]["timeout"] == 5
