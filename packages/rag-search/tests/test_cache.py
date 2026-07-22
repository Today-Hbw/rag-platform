"""cache.py 单测：make_cache_key + SearchCache（fakeredis / 禁用降级）。"""

import fakeredis

from rag_core.settings import Settings
from rag_search.cache import SearchCache, make_cache_key


def test_make_cache_key_varies_with_inputs():
    k1 = make_cache_key("社保", top_k=10)
    k2 = make_cache_key("社保", top_k=20)  # top_k 不同
    k3 = make_cache_key("年假", top_k=10)
    assert k1 != k2 != k3 and k1 != k3
    assert k1.startswith("search:")


def test_make_cache_key_scope_sig_changes_key():
    # RBAC：不同可见集合签名 → 不同 key（防越权命中缓存）
    assert make_cache_key("q", scope_sig="userA") != make_cache_key("q", scope_sig="userB")


def test_cache_roundtrip_with_fakeredis():
    cache = SearchCache(fakeredis.FakeStrictRedis(decode_responses=True), Settings())
    assert cache.get("search:x") is None
    cache.set("search:x", {"query": "q", "total_results": 1})
    assert cache.get("search:x") == {"query": "q", "total_results": 1}


def test_cache_disabled_when_client_none():
    cache = SearchCache(None, Settings())
    cache.set("k", {"a": 1})  # 不报错
    assert cache.get("k") is None
