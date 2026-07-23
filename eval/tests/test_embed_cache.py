"""embed_cache 单测：命中/未命中 + endpoint 变更使缓存失效。"""

from eval.embed_cache import EmbedCache


def test_miss_then_hit(tmp_path):
    calls = []

    def embed(q):
        calls.append(q)
        return [1.0, 2.0]

    cache = EmbedCache(tmp_path, "model-v1")
    assert cache.embed("查询", embed) == [1.0, 2.0]  # miss → 计算
    assert cache.embed("查询", embed) == [1.0, 2.0]  # hit → 复用
    assert calls == ["查询"]  # embed_fn 只调一次
    assert cache.hits == 1 and cache.misses == 1


def test_endpoint_change_invalidates(tmp_path):
    c1 = EmbedCache(tmp_path, "model-v1")
    c1.embed("q", lambda _: [1.0])
    c2 = EmbedCache(tmp_path, "model-v2")  # 换模型 endpoint → key 变 → miss
    assert c2.get("q") is None
    hit_path = c1._path("q")
    assert hit_path.exists() and c2._path("q") != hit_path


def test_corrupt_cache_file_is_miss(tmp_path):
    cache = EmbedCache(tmp_path, "m")
    cache.put("q", [1.0])
    cache._path("q").write_text("{bad", encoding="utf-8")
    assert cache.get("q") is None
