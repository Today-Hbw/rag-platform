"""auth.py 单测：role_ids 解析 / scope 归类 / Qdrant filter / 缓存签名 / introspection。"""

import pytest

from rag_core.settings import RbacSettings
from rag_search import auth


def test_parse_role_ids():
    assert auth.parse_role_ids("12, 34 ,56") == ["12", "34", "56"]
    assert auth.parse_role_ids("") == []
    assert auth.parse_role_ids(None) == []
    assert auth.parse_role_ids(" , ,7") == ["7"]  # 空项剔除


def _no_public(monkeypatch):
    monkeypatch.setattr(auth.repository, "get_public_collection_ids", lambda conn: [])


def test_resolve_scope_classifies(monkeypatch):
    _no_public(monkeypatch)
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
    # allow_all 时不应查公共库（超管看全部）——故意让 public 抛错来证明未被调用
    monkeypatch.setattr(
        auth.repository, "get_public_collection_ids",
        lambda conn: (_ for _ in ()).throw(AssertionError("allow_all 不应查公共库")),
    )
    scope = auth.resolve_scope(object(), ["1"])
    assert scope.allow_all is True
    assert scope.denies_all is False


def test_resolve_scope_denies_all_when_no_grant(monkeypatch):
    _no_public(monkeypatch)
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: [])
    scope = auth.resolve_scope(object(), ["99"])
    assert scope.denies_all is True  # 无授权且无公共库 → 什么都看不到(fail-closed)


def test_resolve_scope_unions_public_collections(monkeypatch):
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: ["book:42"])
    monkeypatch.setattr(auth.repository, "get_public_collection_ids", lambda conn: ["9", "10"])
    scope = auth.resolve_scope(object(), ["7"])
    assert scope.collection_ids == {"42", "9", "10"}  # 角色库 ∪ 公共库


def test_resolve_scope_public_visible_without_roles(monkeypatch):
    # 无角色/无 token，但有公共库 → 仍可见公共库（denies_all=False）
    monkeypatch.setattr(auth.repository, "get_role_resource_ids", lambda conn, rids: [])
    monkeypatch.setattr(auth.repository, "get_public_collection_ids", lambda conn: ["9"])
    scope = auth.resolve_scope(object(), [])
    assert scope.collection_ids == {"9"}
    assert scope.denies_all is False


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


def test_scope_sig_allow_all_is_distinct():
    # 超管全量、无过滤 → 独占一档，不与任何受限角色串缓存
    assert auth.scope_sig([], allow_all=True) == "roles:__all__"
    assert auth.scope_sig(["1"], allow_all=True) == "roles:__all__"
    assert auth.scope_sig(["1"], allow_all=True) != auth.scope_sig(["1"])


# ==================== introspection（增量①）====================


class _FakeResp:
    def __init__(self, status_code, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    """记录调用并返回预置响应；post 抛异常可模拟网络故障。"""

    def __init__(self, resp=None, boom=False):
        self._resp = resp
        self._boom = boom
        self.calls = []

    def post(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if self._boom:
            raise ConnectionError("network down")
        return self._resp


@pytest.fixture(autouse=True)
def _clear_identity_cache():
    auth._identity_cache.clear()
    yield
    auth._identity_cache.clear()


def test_resolve_identity_offline_reads_role_header():
    # introspect_url 空 → 离线模式：直接信 X-Role-Ids，不发网络请求
    cfg = RbacSettings()
    ident = auth.resolve_identity(cfg, token="ignored", roles_header_value="12, 34")
    assert ident.valid is True
    assert ident.role_ids == ["12", "34"]
    assert ident.allow_all is False


def test_resolve_identity_offline_falls_back_to_defaults():
    cfg = RbacSettings(default_role_ids=["7", "8"])
    ident = auth.resolve_identity(cfg, roles_header_value=None)
    assert ident.role_ids == ["7", "8"]  # 头缺失 → 静态默认兜底


def test_resolve_identity_online_no_token_is_invalid():
    cfg = RbacSettings(introspect_url="http://biz/introspect")
    ident = auth.resolve_identity(cfg, token=None, roles_header_value="12")
    assert ident.valid is False  # 在线模式无 token → fail-closed（X-Role-Ids 不再被信任）


def test_resolve_identity_online_calls_and_caches():
    cfg = RbacSettings(introspect_url="http://biz/introspect", scope_cache_ttl=300)
    sess = _FakeSession(_FakeResp(200, {"valid": True, "role_ids": [12, 34], "allow_all": False}))
    a = auth.resolve_identity(cfg, token="tok-1", session=sess)
    assert a.valid and a.role_ids == ["12", "34"]  # int → str 归一
    b = auth.resolve_identity(cfg, token="tok-1", session=sess)
    assert b.role_ids == ["12", "34"]
    assert len(sess.calls) == 1  # 第二次命中缓存，不再请求
    assert sess.calls[0]["headers"]["Authorization"] == "Bearer tok-1"


def test_resolve_identity_online_allow_all():
    cfg = RbacSettings(introspect_url="http://biz/introspect")
    sess = _FakeSession(_FakeResp(200, {"valid": True, "role_ids": [], "allow_all": True}))
    ident = auth.resolve_identity(cfg, token="boss", session=sess)
    assert ident.allow_all is True


def test_introspect_sends_service_token_header():
    from pydantic import SecretStr

    cfg = RbacSettings(
        introspect_url="http://biz/introspect",
        introspect_service_token=SecretStr("svc-secret"),
    )
    sess = _FakeSession(_FakeResp(200, {"valid": True, "role_ids": [1]}))
    auth.introspect(cfg, "tok", session=sess)
    assert sess.calls[0]["headers"]["X-Service-Token"] == "svc-secret"


def test_introspect_401_is_invalid():
    cfg = RbacSettings(introspect_url="http://biz/introspect")
    ident = auth.introspect(cfg, "tok", session=_FakeSession(_FakeResp(401)))
    assert ident.valid is False


def test_introspect_valid_false_is_invalid():
    cfg = RbacSettings(introspect_url="http://biz/introspect")
    sess = _FakeSession(_FakeResp(200, {"valid": False}))
    assert auth.introspect(cfg, "tok", session=sess).valid is False


def test_introspect_network_error_is_invalid():
    cfg = RbacSettings(introspect_url="http://biz/introspect")
    ident = auth.introspect(cfg, "tok", session=_FakeSession(boom=True))
    assert ident.valid is False  # 网络故障 → fail-closed


def test_introspect_bad_json_is_invalid():
    cfg = RbacSettings(introspect_url="http://biz/introspect")
    sess = _FakeSession(_FakeResp(200, raise_json=True))
    assert auth.introspect(cfg, "tok", session=sess).valid is False


def test_invalid_identity_not_cached():
    cfg = RbacSettings(introspect_url="http://biz/introspect")
    sess = _FakeSession(_FakeResp(401))
    auth.resolve_identity(cfg, token="tok", session=sess)
    auth.resolve_identity(cfg, token="tok", session=sess)
    assert len(sess.calls) == 2  # 无效身份不缓存 → 每次都重试
