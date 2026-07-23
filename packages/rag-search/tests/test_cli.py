"""rag-search CLI 单测：serve 子命令装配（mock uvicorn，不真正起服务）。"""

import sys
import types

import pytest

from rag_search import cli


def test_serve_invokes_uvicorn(monkeypatch):
    called = {}
    fake_uvicorn = types.SimpleNamespace(
        run=lambda app, host, port: called.update(host=host, port=port, has_app=app is not None)
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    rc = cli.main(["serve", "--host", "127.0.0.1", "--port", "1234"])
    assert rc == 0
    assert called == {"host": "127.0.0.1", "port": 1234, "has_app": True}


def test_requires_subcommand():
    with pytest.raises(SystemExit):
        cli.main([])  # 缺子命令
