"""auth.py 单测：role_ids 解析 / scope 归类 / Qdrant filter / 缓存签名。"""

from rag_search import auth


def test_parse_role_ids():
    assert auth.parse_role_ids("12, 34 ,56") == ["12", "34", "56"]
    assert auth.parse_role_ids("") == []
    assert auth.parse_role_ids(None) == []
    assert auth.parse_role_ids(" , ,7") == ["7"]  # 空项剔除


def test_resolve_scope_classifies(monkeypatch):
    monkeypatch.setattr(
        auth.repository, "get_role_resource_ids",
        lambda conn, rids: ["book:42", "book:43", "doc:100", "doc:xx"],
    )
    scope = auth.resolve_scope(object(), ["12"])
    assert scope.allow_all is False
    assert scope.collection_ids == {"42", "43"}
    assert scope.doc_ids == {100}  # doc:xx 非 int 被丢
    assert scope.denies_all is False


def test_resolve_scope_allow_all(monkeypatch):
    monkeypatch.setattr(
        auth.repository, "get_role_resource_ids", lambda conn, rids: ["*", "book:1"]
    )
    scope = auth.resolve_scope(object(), ["1"])
    assert scope.allow_all is True
    assert scope.denies_all is False


def test_resolve_scope_denies_all_when_no_grant(monkeypatch):
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: [])
    scope = auth.resolve_scope(object(), ["99"])
    assert scope.denies_all is True  # 无授权 → 什么都看不到(fail-closed)


def test_build_query_filter_allow_all_is_none():
    assert auth.build_query_filter(auth.Scope(allow_all=True)) is None


def test_build_query_filter_collection_and_doc():
    scope = auth.Scope(collection_ids={"42", "43"}, doc_ids={100, 200})
    f = auth.build_query_filter(scope)
    keys = {c.key for c in f.should}
    assert keys == {"collection_id", "doc_id"}
    doc_cond = next(c for c in f.should if c.key == "doc_id")
    assert doc_cond.match.any == [100, 200]  # int，已排序
    assert all(isinstance(x, int) for x in doc_cond.match.any)  # 强转 int（防静默失配）
    col_cond = next(c for c in f.should if c.key == "collection_id")
    assert col_cond.match.any == ["42", "43"]


def test_build_query_filter_doc_only():
    f = auth.build_query_filter(auth.Scope(doc_ids={5}))
    assert len(f.should) == 1 and f.should[0].key == "doc_id"


def test_scope_sig_stable_and_order_independent():
    assert auth.scope_sig(["34", "12"]) == auth.scope_sig(["12", "34", "12"])
    assert auth.scope_sig(["12"]) != auth.scope_sig(["34"])
    assert auth.scope_sig([]) == "roles:"
