"""connectors/base.py 单测：detect_changes 纯逻辑 + DTO + ABC 契约。"""

import pytest

from rag_core.contracts import DocFacets
from rag_pipeline.connectors import base
from rag_pipeline.connectors.base import (
    AssetAuth,
    ChangeSet,
    DocDetail,
    DocRef,
    SourceConnector,
    SourceScope,
    detect_changes,
    normalize_version,
)

# ---------- normalize_version ----------

def test_normalize_version_datetime_variants():
    # T ↔ 空格、去亚秒，两种写法归一化后相等
    assert normalize_version("2026-07-21T10:00:00.123Z") == "2026-07-21 10:00:00"
    assert normalize_version("2026-07-21 10:00:00") == "2026-07-21 10:00:00"
    assert normalize_version("2026-07-21T10:00:00") == "2026-07-21 10:00:00"


def test_normalize_version_edge():
    assert normalize_version(None) == ""
    assert normalize_version("  ") == ""
    # 不含 T/空格的普通令牌（hash）原样保留，不被 '.' 截断
    assert normalize_version("abc123") == "abc123"


# ---------- detect_changes ----------

def _ref(doc_id, ver):
    return DocRef(doc_id=doc_id, source_version=ver)


def test_detect_changes_new_and_unchanged_and_changed():
    refs = [_ref(1, "v1"), _ref(2, "v2new"), _ref(3, "v3")]
    known = {1: "v1", 2: "v2old"}  # 1 未变，2 变更，3 新增
    cs = detect_changes(refs, known)
    assert {r.doc_id for r in cs.unchanged} == {1}
    assert {r.doc_id for r in cs.to_fetch} == {2, 3}
    assert cs.deleted == []
    assert cs.counts == {"to_fetch": 2, "unchanged": 1, "deleted": 0}


def test_detect_changes_deletion_diff():
    refs = [_ref(1, "v1")]
    known = {1: "v1", 2: "v2", 3: "v3"}  # 2、3 来源已无
    cs = detect_changes(refs, known)
    assert cs.deleted == [2, 3]  # 排序输出
    assert {r.doc_id for r in cs.unchanged} == {1}


def test_detect_changes_remote_incomplete_suppresses_deletion():
    # 抓取残缺时绝不误删：deleted 必为空，仍照常算增量
    refs = [_ref(1, "v1new")]
    known = {1: "v1old", 2: "v2", 3: "v3"}
    cs = detect_changes(refs, known, remote_complete=False)
    assert cs.deleted == []
    assert {r.doc_id for r in cs.to_fetch} == {1}


def test_detect_changes_version_normalized_across_formats():
    # DB 存 datetime、来源给 ISO+亚秒，归一化后判为未变（不重复抓取）
    refs = [_ref(10, "2026-07-21T10:00:00.500Z")]
    known = {10: "2026-07-21 10:00:00"}
    cs = detect_changes(refs, known)
    assert {r.doc_id for r in cs.unchanged} == {10}
    assert cs.to_fetch == []


def test_detect_changes_empty_remote_version_forces_fetch():
    # 来源令牌为空 → 无法判定未变 → 保守重抓
    refs = [_ref(5, "")]
    known = {5: "v5"}
    cs = detect_changes(refs, known)
    assert {r.doc_id for r in cs.to_fetch} == {5}
    assert cs.unchanged == []


def test_detect_changes_known_key_type_coercion():
    # DB 的 doc_id 可能是字符串，比较时按 int 归一
    refs = [_ref(7, "v7")]
    cs = detect_changes(refs, {"7": "v7"})
    assert {r.doc_id for r in cs.unchanged} == {7}
    assert cs.deleted == []


# ---------- SourceScope ----------

def test_scope_dir_name():
    s = SourceScope(scope_id="123", facets=DocFacets(collection_slug="kb", collection_id="123"))
    assert s.dir_name() == "kb_123"


def test_scope_dir_name_without_slug_falls_back():
    s = SourceScope(scope_id="123")
    assert s.dir_name() == "123"


# ---------- ABC 契约 ----------

def test_source_connector_is_abstract():
    with pytest.raises(TypeError):
        SourceConnector()  # 未实现抽象方法不可实例化


class _FakeConnector(SourceConnector):
    source = "fake"

    def scopes(self):
        return [SourceScope(scope_id="s1", facets=DocFacets(collection_id="s1"))]

    def list_docs(self, scope):
        return [_ref(1, "v1"), _ref(2, "v2")]

    def fetch(self, scope, ref):
        return DocDetail(
            doc_id=ref.doc_id, title="t", body="# body", source_version=ref.source_version
        )

    def asset_auth(self, scope):
        return AssetAuth(headers={"X-Auth-Token": "t"})

    def build_source_url(self, scope, detail):
        return f"http://fake/{detail.doc_id}"


def test_fake_connector_default_detect_changes_delegates():
    c = _FakeConnector()
    assert c.source == "fake"
    refs = c.list_docs(c.scopes()[0])
    cs = c.detect_changes(refs, {1: "v1"})
    assert isinstance(cs, ChangeSet)
    assert {r.doc_id for r in cs.unchanged} == {1}
    assert {r.doc_id for r in cs.to_fetch} == {2}


def test_module_and_method_detect_changes_agree():
    c = _FakeConnector()
    refs = c.list_docs(c.scopes()[0])
    known = {2: "v_old"}
    assert base.detect_changes(refs, known).counts == c.detect_changes(refs, known).counts
