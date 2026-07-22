"""local connector 单测 + 经 download.sync 端到端验证 ABC 不过拟合语雀 REST。"""

from rag_pipeline.connectors import registry
from rag_pipeline.connectors.local import LocalConnector
from rag_pipeline.stages import download as dl
from rag_pipeline.workspace import Workspace


def test_local_registered():
    assert "local" in registry.available_connectors()


def test_scopes_and_list_and_fetch(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("# A\n![](http://cdn/i.png)", encoding="utf-8")
    (tmp_path / "sub" / "b.md").write_text("# B\n[x](http://x/f.pdf)", encoding="utf-8")

    c = LocalConnector(tmp_path, collection_id="docs")
    scope = c.scopes()[0]
    assert scope.scope_id == "docs"

    refs = c.list_docs(scope)
    assert {r.doc_key for r in refs} == {"a.md", "sub/b.md"}
    assert all(r.source_version for r in refs)  # 内容 hash 作版本

    ref_a = next(r for r in refs if r.doc_key == "a.md")
    detail = c.fetch(scope, ref_a)
    assert detail.body.startswith("# A")
    assert detail.facets.collection_id == "docs"
    assert [r.kind for r in detail.resources] == ["image"]
    assert detail.source_url.startswith("file:")


def test_list_docs_missing_root_empty(tmp_path):
    c = LocalConnector(tmp_path / "nope")
    assert c.list_docs(c.scopes()[0]) == []


def test_version_changes_with_content(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("v1", encoding="utf-8")
    c = LocalConnector(tmp_path)
    v1 = c.list_docs(c.scopes()[0])[0].source_version
    f.write_text("v2 changed", encoding="utf-8")
    v2 = c.list_docs(c.scopes()[0])[0].source_version
    assert v1 != v2  # 内容变 → 版本变 → 会被 detect_changes 判为需重抓


class _RepoSpy:
    """download.sync 需要的最小 repository 面。"""

    def __init__(self):
        self.upserts = []
        self.resources = []
        self.deleted = []

    def get_scope_versions(self, conn, source, collection_id):
        return {}

    def upsert_doc_meta(self, conn, record):
        self.upserts.append(record)

    def save_resources(self, conn, doc_id, rtype, resources):
        self.resources.append((doc_id, rtype))

    def mark_docs_deleted(self, conn, doc_ids):
        self.deleted.extend(doc_ids)


def test_local_connector_runs_through_download_sync(monkeypatch, tmp_path):
    """核心验收：同一 stages.sync 编排，换 local connector 无需改任何下游。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("# A\n\n正文", encoding="utf-8")
    (src / "b.md").write_text("# B\n\n正文", encoding="utf-8")

    spy = _RepoSpy()
    monkeypatch.setattr(dl, "repository", spy)
    data_root = tmp_path / "out"
    ws = Workspace(data_root, "20260722")
    c = LocalConnector(src, collection_id="docs")

    results = dl.sync(object(), c, ws, settings=None)
    assert results[0].downloaded == 2
    assert len(spy.upserts) == 2
    assert all(u["source"] == "local" for u in spy.upserts)
    # md 已落盘到 data_root
    assert list((data_root / "20260722").rglob("*.md"))
