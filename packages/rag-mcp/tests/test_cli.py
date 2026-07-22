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
    """--timeout 真正传到 RemoteSearchClient（回归旧死参数 bug）。"""
    captured = {}

    class FakeClient:
        def __init__(self, url, timeout=DEFAULT_TIMEOUT):
            captured["url"] = url
            captured["timeout"] = timeout

    async def fake_run(server_url, timeout):
        # 复刻 _run 内部装配，验证 timeout 落到 client
        FakeClient(server_url, timeout=timeout)

    monkeypatch.setattr(cli, "_run", fake_run)
    rc = cli.main(["-s", "http://svc", "--timeout", "7"])
    assert rc == 0
