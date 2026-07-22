"""stages/download.py 单测：源无关编排 + 删除守卫，全离线（monkeypatch 下载/提取/DB）。"""

import pytest

from rag_core.contracts import DocFacets
from rag_pipeline.connectors.base import (
    AssetAuth,
    DocDetail,
    DocRef,
    ResourceRef,
    SourceConnector,
    SourceScope,
)
from rag_pipeline.stages import download as dl
from rag_pipeline.workspace import Workspace

# ---------- 假 connector ----------

class FakeConnector(SourceConnector):
    source = "fake"

    def __init__(self, refs, details, deleted_known=None):
        self._refs = refs
        self._details = details  # doc_id -> DocDetail

    def scopes(self):
        facets = DocFacets(collection_id="42", collection_slug="kb")
        return [SourceScope(scope_id="42", facets=facets)]

    def list_docs(self, scope):
        return list(self._refs)

    def fetch(self, scope, ref):
        return self._details[ref.doc_id]

    def asset_auth(self, scope):
        return AssetAuth(headers={"X-Auth-Token": "t"}, cookies={"c": "1"})

    def build_source_url(self, scope, detail):
        return f"http://x/{detail.doc_id}"


# ---------- 假 DB：记录 repository 调用 ----------

class RepoSpy:
    def __init__(self, known):
        self.known = known
        self.upserts = []
        self.resources = []
        self.deleted = []

    def get_scope_versions(self, conn, source, collection_id):
        return dict(self.known)

    def upsert_doc_meta(self, conn, record):
        self.upserts.append(record)

    def save_resources(self, conn, doc_id, rtype, resources):
        self.resources.append((doc_id, rtype, resources))

    def mark_docs_deleted(self, conn, doc_ids):
        self.deleted.extend(doc_ids)


@pytest.fixture
def patched(monkeypatch):
    """monkeypatch 下载/提取，下载会真的写文件以便 size/exists 成立。"""

    def fake_dl(url, save_path, headers=None, cookies=None, max_retries=3, label=""):
        import os
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(b"DATA")
        return 4

    monkeypatch.setattr(dl.du, "download_with_retry", fake_dl)
    monkeypatch.setattr(dl, "extract_text_from_file", lambda p, ft, settings=None: "TXT")
    monkeypatch.setattr(dl.media, "detect_mime_from_file", lambda p: "image/png")


def _detail(doc_id, body="# b", resources=None, version="v1"):
    return DocDetail(
        doc_id=doc_id,
        title=f"t{doc_id}",
        body=body,
        source_version=version,
        facets=DocFacets(collection_id="42", collection_slug="kb", doc_key=f"d{doc_id}"),
        source_url=f"http://x/{doc_id}",
        resources=resources or [],
    )


def _run(monkeypatch, tmp_path, refs, details, known):
    spy = RepoSpy(known)
    monkeypatch.setattr(dl, "repository", spy)
    conn = object()
    conn_c = FakeConnector(refs, details)
    ws = Workspace(tmp_path, "20260722")
    stats = dl.sync_scope(conn, conn_c, conn_c.scopes()[0], ws)
    return spy, stats, ws


def test_incremental_only_fetches_changed(monkeypatch, tmp_path, patched):
    refs = [DocRef(doc_id=1, source_version="v1"), DocRef(doc_id=2, source_version="v2new")]
    details = {2: _detail(2, version="v2new")}
    spy, stats, _ = _run(monkeypatch, tmp_path, refs, details, known={1: "v1", 2: "v2old"})
    assert stats.downloaded == 1  # 只抓变更的 2
    assert stats.skipped == 1  # 1 未变
    assert [u["doc_id"] for u in spy.upserts] == [2]
    assert spy.upserts[0]["source"] == "fake"
    assert spy.upserts[0]["collection_id"] == "42"
    assert spy.upserts[0]["status"] == "downloaded"


def test_deletion_diff_marks_deleted(monkeypatch, tmp_path, patched):
    refs = [DocRef(doc_id=1, source_version="v1")]
    spy, stats, _ = _run(monkeypatch, tmp_path, refs, {}, known={1: "v1", 9: "vx"})
    assert stats.deleted == 1
    assert spy.deleted == [9]


def test_empty_listing_with_known_suppresses_deletion(monkeypatch, tmp_path, patched):
    # 列举回 0 篇但 DB 有存量 → 判为抓取残缺，绝不删
    spy, stats, _ = _run(monkeypatch, tmp_path, [], {}, known={1: "v1", 2: "v2"})
    assert stats.deleted == 0
    assert spy.deleted == []


def test_downloads_assets_and_writes_md(monkeypatch, tmp_path, patched):
    resources = [
        ResourceRef(kind="image", index=0, url="http://cdn/a.png"),
        ResourceRef(kind="attachment", index=0, url="http://x/r.pdf", filename="r.pdf"),
    ]
    refs = [DocRef(doc_id=5, source_version="v1")]
    details = {5: _detail(5, resources=resources)}
    spy, stats, ws = _run(monkeypatch, tmp_path, refs, details, known={})
    assert stats.downloaded == 1
    assert stats.images == 1
    assert stats.attachments == 1
    # md 写盘
    assert (tmp_path / "20260722" / "kb_42" / "md" / "5_t5.md").exists()
    # resource 记录：image + attachment 各一批
    rtypes = {r[1] for r in spy.resources}
    assert rtypes == {"image", "attachment"}
    img_batch = next(r[2] for r in spy.resources if r[1] == "image")
    assert img_batch[0]["status"] == "ok"
    assert img_batch[0]["served_url"].startswith("/assets/20260722/kb_42/")
    att_batch = next(r[2] for r in spy.resources if r[1] == "attachment")
    assert att_batch[0]["text_chars"] == 3  # "TXT"
    assert att_batch[0]["status"] == "ok"


def test_asset_download_failure_recorded_not_fatal(monkeypatch, tmp_path, patched):
    def boom(url, save_path, headers=None, cookies=None, max_retries=3, label=""):
        raise RuntimeError("net")

    monkeypatch.setattr(dl.du, "download_with_retry", boom)
    resources = [ResourceRef(kind="image", index=0, url="http://cdn/a.png")]
    refs = [DocRef(doc_id=5, source_version="v1")]
    details = {5: _detail(5, resources=resources)}
    spy, stats, _ = _run(monkeypatch, tmp_path, refs, details, known={})
    assert stats.downloaded == 1  # 整篇仍算成功
    assert stats.images == 0  # 但图片失败不计
    img_batch = next(r[2] for r in spy.resources if r[1] == "image")
    assert img_batch[0]["status"] == "failed"
    assert "net" in img_batch[0]["error"]


def test_full_mode_refetches_all(monkeypatch, tmp_path, patched):
    refs = [DocRef(doc_id=1, source_version="v1"), DocRef(doc_id=2, source_version="v2")]
    details = {1: _detail(1), 2: _detail(2)}
    spy = RepoSpy(known={1: "v1", 2: "v2"})
    monkeypatch.setattr(dl, "repository", spy)
    ws = Workspace(tmp_path, "20260722")
    c = FakeConnector(refs, details)
    stats = dl.sync_scope(object(), c, c.scopes()[0], ws, full=True)
    assert stats.downloaded == 2  # full 忽略增量，全抓
    assert stats.skipped == 0


def test_fetch_failure_counted_and_isolated(monkeypatch, tmp_path, patched):
    refs = [DocRef(doc_id=1, source_version="v1"), DocRef(doc_id=2, source_version="v2")]
    details = {1: _detail(1)}  # 2 缺失 → fetch KeyError

    spy = RepoSpy(known={})
    monkeypatch.setattr(dl, "repository", spy)
    ws = Workspace(tmp_path, "20260722")
    c = FakeConnector(refs, details)
    stats = dl.sync_scope(object(), c, c.scopes()[0], ws)
    assert stats.downloaded == 1
    assert stats.failed == 1
    assert stats.failures[0]["doc_id"] == 2


def test_sync_isolates_scope_listing_failure(monkeypatch, tmp_path, patched):
    class BoomConnector(FakeConnector):
        def list_docs(self, scope):
            raise RuntimeError("list failed")

    spy = RepoSpy(known={})
    monkeypatch.setattr(dl, "repository", spy)
    ws = Workspace(tmp_path, "20260722")
    c = BoomConnector([], {})
    results = dl.sync(object(), c, ws)
    assert len(results) == 1
    assert results[0].failed == 1
    assert spy.deleted == []  # 列举失败绝不触发删除
