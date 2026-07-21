"""Qdrant 向量库封装。收敛 vectorize.init_qdrant/upsert/delete 与 search.qdrant_search。

`search` 预留 `query_filter` 参数供 RBAC（D7）注入；本层来源无关，返回原始 payload，
字段映射（→ ChunkPayload/facets）与附件富化交给上层（rag-pipeline / rag-search）。
"""

from __future__ import annotations

import logging
from typing import Any

from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

__all__ = ["VectorStore", "make_point"]


def make_point(point_id: str, vector: list[float], payload: dict[str, Any]):
    """构造 Qdrant PointStruct（延迟 import qdrant_client）。"""
    from qdrant_client.models import PointStruct

    return PointStruct(id=point_id, vector=vector, payload=payload)


class VectorStore:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: Any | None = None,
        collection: str | None = None,
    ):
        s = (settings or get_settings()).qdrant
        self.collection = collection or s.collection
        self._url = s.url
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self._url, timeout=15)
        return self._client

    def ensure_collection(self, vector_dim: int, *, recreate: bool = False) -> bool:
        """不存在则创建 collection（COSINE）。返回是否新建/重建。"""
        from qdrant_client.models import Distance, VectorParams

        names = [c.name for c in self.client.get_collections().collections]
        if self.collection in names:
            if not recreate:
                logger.info("Collection '%s' already exists", self.collection)
                return False
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
        )
        logger.info("Collection '%s' created (dim=%d)", self.collection, vector_dim)
        return True

    def ensure_payload_indexes(self, fields: dict[str, str]) -> None:
        """为过滤字段建 payload index（RBAC 前置）。

        fields: ``{字段名: 'keyword'|'integer'|...}``。幂等（已存在则跳过）。
        """
        for field_name, schema in fields.items():
            try:
                self.client.create_payload_index(
                    collection_name=self.collection, field_name=field_name, field_schema=schema
                )
            except Exception as e:  # 已存在等
                logger.debug("create_payload_index(%s) skipped: %s", field_name, e)

    def upsert(self, points: list, *, batch_size: int = 10) -> None:
        """批量 upsert（wait=True）。"""
        for i in range(0, len(points), batch_size):
            self.client.upsert(
                collection_name=self.collection, points=points[i : i + batch_size], wait=True
            )

    def delete(self, point_ids: list) -> None:
        if not point_ids:
            return
        from qdrant_client.models import PointIdsList

        self.client.delete(
            collection_name=self.collection, points_selector=PointIdsList(points=list(point_ids))
        )

    def search(
        self, query_vec: list[float], *, limit: int = 50, query_filter: Any | None = None
    ) -> list[dict[str, Any]]:
        """向量召回，返回 [{id, score, payload}]。query_filter 供 RBAC 注入。"""
        res = self.client.query_points(
            collection_name=self.collection,
            query=query_vec,
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        ).points
        return [
            {"id": r.id, "score": r.score, "payload": dict(r.payload or {})} for r in res
        ]
