"""Qdrant payload 与来源无关 taxonomy 的共享契约。

消除原三处漂移：vectorize.py:654（写）/ search/search.py:262（读）/ search/app.py:172（响应）。
按决策 D2=A 泛化：语雀专有列 team_code/book_id/book_slug/doc_slug → 来源无关四元组
namespace/collection_id/collection_slug/doc_key + source + source_dims。

payload 采用**扁平**结构（facets 展开为顶层键），便于 Qdrant 建 payload index 与过滤
（RBAC 按 collection_id/doc_id 过滤，见 D7）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["DocFacets", "ChunkPayload"]


@dataclass
class DocFacets:
    """来源无关的文档分类维度（taxonomy）。字段后注释为语雀映射。"""

    namespace: str = ""  # 原 team_code：团队/空间/租户
    collection_id: str = ""  # 原 book_id：知识库/空间/库（RBAC 过滤锚点）
    collection_slug: str = ""  # 原 book_slug
    doc_key: str = ""  # 原 doc_slug：来源内文档别名
    dims: dict[str, str] = field(default_factory=dict)  # 来源特有维度


@dataclass
class ChunkPayload:
    """写入 Qdrant point 的 payload。"""

    source: str  # 数据源标识，如 "yuque"
    doc_id: int  # 来源原生文档 ID（RBAC + eval 主键）
    doc_title: str
    chunk_index: int
    chunk_text: str
    facets: DocFacets = field(default_factory=DocFacets)
    source_url: str = ""
    source_file: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    has_image: bool = False
    has_attachment: bool = False
    attachment_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        """转为写入 Qdrant 的扁平 dict（facets 展开为顶层键，便于过滤/建索引）。"""
        payload: dict[str, Any] = {
            "source": self.source,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "namespace": self.facets.namespace,
            "collection_id": self.facets.collection_id,
            "collection_slug": self.facets.collection_slug,
            "doc_key": self.facets.doc_key,
            "images": self.images,
            "has_image": self.has_image,
            "has_attachment": self.has_attachment,
            "attachment_count": self.attachment_count,
        }
        if self.facets.dims:
            payload["source_dims"] = dict(self.facets.dims)
        return payload

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> ChunkPayload:
        """从 Qdrant 读回的扁平 payload 重建，忽略未知键、缺失键用默认值。"""
        facets = DocFacets(
            namespace=data.get("namespace", ""),
            collection_id=data.get("collection_id", ""),
            collection_slug=data.get("collection_slug", ""),
            doc_key=data.get("doc_key", ""),
            dims=dict(data.get("source_dims") or {}),
        )
        return cls(
            source=data.get("source", ""),
            doc_id=data.get("doc_id"),
            doc_title=data.get("doc_title", ""),
            chunk_index=data.get("chunk_index"),
            chunk_text=data.get("chunk_text", ""),
            facets=facets,
            source_url=data.get("source_url", ""),
            source_file=data.get("source_file", ""),
            images=list(data.get("images") or []),
            has_image=bool(data.get("has_image", False)),
            has_attachment=bool(data.get("has_attachment", False)),
            attachment_count=int(data.get("attachment_count", 0) or 0),
        )
