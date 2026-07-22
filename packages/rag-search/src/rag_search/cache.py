"""检索结果的 Redis 缓存。移植自旧 app.py 的 cache_* + make_cache_key。

client 可注入（测试用 fakeredis）；连接失败降级为无缓存。TTL 在 [ttl_min, ttl_max]
随机，避免缓存雪崩。⚠️ 阶段 5 接 RBAC 后，cache key 必须叠加 scope_sig（可见集合签名），
否则不同权限用户会命中彼此缓存拿到越权结果——见 REFACTOR_PLAN §5.2 铁律 2。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from typing import Any

from rag_core.settings import Settings, get_settings

logger = logging.getLogger("rag-search.cache")

__all__ = ["make_cache_key", "SearchCache"]

CACHE_PREFIX = "search:"


def make_cache_key(
    query_text: str,
    *,
    image_b64: str | None = None,
    image_url: str | None = None,
    top_k: int = 10,
    scope_sig: str = "",
) -> str:
    """hash(查询内容 + top_k + scope_sig)。scope_sig 为 RBAC 可见集合签名（默认空）。"""
    parts = [
        query_text or "",
        (image_b64 or "")[:200],
        image_url or "",
        str(top_k),
        scope_sig,
    ]
    h = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
    return f"{CACHE_PREFIX}{h}"


class SearchCache:
    """Redis 缓存封装。client=None 时禁用（降级为直查）。"""

    def __init__(self, client: Any | None, settings: Settings | None = None):
        self._client = client
        s = (settings or get_settings()).redis
        self._ttl_min = s.cache_ttl_min
        self._ttl_max = s.cache_ttl_max

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SearchCache:
        """按配置建 Redis 连接；失败则降级为无缓存。"""
        s = (settings or get_settings()).redis
        client = None
        try:
            import redis

            client = redis.Redis(
                host=s.host, port=s.port, password=s.password.get_secret_value() or None,
                db=s.db, decode_responses=True, socket_timeout=3, socket_connect_timeout=3,
            )
            client.ping()
            logger.info("Redis connected: %s:%s", s.host, s.port)
        except Exception as e:  # noqa: BLE001 - 缓存不可用不应阻断检索
            logger.warning("Redis 不可用，缓存禁用：%s", e)
            client = None
        return cls(client, settings)

    def get(self, key: str) -> dict | None:
        if self._client is None:
            return None
        try:
            data = self._client.get(key)
            return json.loads(data) if data else None
        except Exception as e:  # noqa: BLE001
            logger.warning("cache get error: %s", e)
            return None

    def set(self, key: str, value: dict) -> None:
        if self._client is None:
            return
        ttl = random.randint(self._ttl_min, self._ttl_max)
        try:
            self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception as e:  # noqa: BLE001
            logger.warning("cache set error: %s", e)
