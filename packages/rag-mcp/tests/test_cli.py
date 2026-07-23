"""rag-mcp CLI 单测：参数解析（含 timeout 透传修复）。"""

import pytest

from rag_mcp import cli
from rag_mcp.server import DEFAULT_TIMEOUT


def test_parse_requires_server():
    with pytest.raises(SystemExit):
        cli._parse_args([])  # 缺 --server


def test_parse_defaults():
    args = cli._parse_args(["-s", "http://svc:8090"])
    assert args.server == "http://svc:8090"
    assert args.timeout == DEFAULT_TIMEOUT
    assert args.verbose is False


def test_parse_timeout_and_verbose():
    args = cli._parse_args(["-s", "http://svc", "--timeout", "5", "-v"])
    assert args.timeout == 5  # 透传（旧版死参数已修复）
    assert args.verbose is True


def test_timeout_passed_to_client(monkeypatch):
    """--timeout / token 真正传到 RemoteSearchClient（回归旧死参数 bug）。"""
    captured = {}

    async def fake_run(server_url, timeout, *, token=None, service_token=None):
        captured.update(
            server_url=server_url, timeout=timeout,
            token=token, service_token=service_token,
        )

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setenv("RAG_MCP_TOKEN", "tok-abc")
    monkeypatch.setenv("RAG_MCP_SERVICE_TOKEN", "svc-xyz")
    rc = cli.main(["-s", "http://svc", "--timeout", "7"])
    assert rc == 0
    assert captured == {
        "server_url": "http://svc", "timeout": 7,
        "token": "tok-abc", "service_token": "svc-xyz",
    }


def test_cli_flag_token_overrides_env(monkeypatch):
    captured = {}

    async def fake_run(server_url, timeout, *, token=None, service_token=None):
        captured["token"] = token

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setenv("RAG_MCP_TOKEN", "from-env")
    cli.main(["-s", "http://svc", "--token", "from-flag"])
    assert captured["token"] == "from-flag"  # 显式 flag 优先于环境变量


def test_login_requires_url(monkeypatch):
    monkeypatch.delenv("RAG_MCP_LOGIN_URL", raising=False)
    assert cli.main(["login", "--phone", "138", "--code", "1234"]) == 2  # 缺 login-url


def test_login_saves_token(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MCP_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(
        cli.token_store, "login",
        lambda url, phone, code, timeout=10.0: {"token": "logged-in-tok"},
    )
    rc = cli.main([
        "login", "--login-url", "http://biz/login", "--phone", "138", "--code", "1234",
    ])
    assert rc == 0
    assert cli.token_store.load_token() == "logged-in-tok"


def test_login_missing_token_in_response(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MCP_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(
        cli.token_store, "login", lambda url, phone, code, timeout=10.0: {"nope": 1}
    )
    rc = cli.main(
        ["login", "--login-url", "http://biz/login", "--phone", "1", "--code", "2"]
    )
    assert rc == 1  # 响应无 token 字段
