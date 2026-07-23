"""查询向量磁盘缓存：key = md5(model_endpoint + query)。

改融合层/chunk 逻辑时向量可复用，跑分秒级且确定；换 embedding 模型（endpoint 变）时
key 自动变化 → 缓存失效并重算，隔离「这次到底改了什么」（REFACTOR_PLAN §5.3）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

__all__ = ["EmbedCache"]


class EmbedCache:
    def __init__(self, cache_dir: str | Path, model_endpoint: str):
        self.cache_dir = Path(cache_dir)
        self.model_endpoint = model_endpoint
        self.hits = 0
        self.misses = 0

    def _key(self, query: str) -> str:
        raw = f"{self.model_endpoint}\x00{query}".encode()
        return hashlib.md5(raw).hexdigest()

    def _path(self, query: str) -> Path:
        return self.cache_dir / f"{self._key(query)}.json"

    def get(self, query: str) -> list[float] | None:
        p = self._path(query)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, query: str, vec: list[float]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._path(query).write_text(json.dumps(vec), encoding="utf-8")

    def embed(self, query: str, embed_fn: Callable[[str], list[float]]) -> list[float]:
        """命中则直接返回；否则调 ``embed_fn`` 计算并落盘。"""
        cached = self.get(query)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        vec = embed_fn(query)
        self.put(query, vec)
        return vec
