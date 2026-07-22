"""rag-pipeline CLI 单测：参数解析 + 装配编排（monkeypatch connector/db/sync）。"""

import pytest

from rag_pipeline import cli
from rag_pipeline.stages.download import DownloadStats


class _FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def wired(monkeypatch):
    """把 connector/db/sync 都换成假的，记录 sync 收到的参数。"""
    captured = {}
    conn = _FakeConn()

    monkeypatch.setattr(cli, "get_connection", lambda settings: conn)
    monkeypatch.setattr(cli, "get_connector", lambda source, settings: object())

    def fake_sync(conn_, connector, workspace, *, settings, full, dry_run, scope_ids):
        captured.update(
            full=full, dry_run=dry_run, scope_ids=scope_ids,
            date=workspace.date, data_root=str(workspace.data_root),
        )
        return [DownloadStats(scope_id="42", downloaded=3, skipped=1, images=2)]

    monkeypatch.setattr(cli.download, "sync", fake_sync)
    return captured, conn


def test_sync_basic_returns_zero_and_closes_conn(wired, capsys):
    captured, conn = wired
    rc = cli.main(["sync", "--source", "yuque"])
    assert rc == 0
    assert conn.closed is True
    out = capsys.readouterr().out
    assert "已下载 3" in out and "跳过 1" in out
    assert captured["full"] is False and captured["dry_run"] is False


def test_sync_passes_flags(wired):
    captured, _ = wired
    cli.main([
        "sync", "--source", "yuque", "--full", "--dry-run",
        "--scope", "1", "--scope", "2", "--date", "20260722", "--data-root", "/tmp/dr",
    ])
    assert captured["full"] is True
    assert captured["dry_run"] is True
    assert captured["scope_ids"] == ["1", "2"]
    assert captured["date"] == "20260722"


def test_dry_run_output_uses_planned(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_connection", lambda settings: _FakeConn())
    monkeypatch.setattr(cli, "get_connector", lambda source, settings: object())
    monkeypatch.setattr(
        cli.download, "sync",
        lambda *a, **k: [DownloadStats(scope_id="42", planned_fetch=5, planned_delete=2)],
    )
    rc = cli.main(["sync", "--source", "yuque", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "将抓取 5" in out and "删除 2" in out


def test_unknown_source_returns_2(monkeypatch, capsys):
    def boom(source, settings):
        raise KeyError("未知数据源 'x'；可用：['yuque']")

    monkeypatch.setattr(cli, "get_connector", boom)
    monkeypatch.setattr(cli, "get_connection", lambda settings: _FakeConn())
    rc = cli.main(["sync", "--source", "x"])
    assert rc == 2


def test_failed_docs_return_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_connection", lambda settings: _FakeConn())
    monkeypatch.setattr(cli, "get_connector", lambda source, settings: object())
    monkeypatch.setattr(
        cli.download, "sync",
        lambda *a, **k: [DownloadStats(scope_id="42", downloaded=1, failed=2)],
    )
    rc = cli.main(["sync", "--source", "yuque"])
    assert rc == 1  # 有失败 → 非零退出
