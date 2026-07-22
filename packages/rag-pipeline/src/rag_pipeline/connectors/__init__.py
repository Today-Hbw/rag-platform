"""数据源 connector 包。

`base` 定义源无关的摄取契约（DTO + `SourceConnector` ABC + `detect_changes` 纯逻辑）；
具体来源实现（如 `yuque`）只负责“把某来源变成统一中间格式”，下载编排 / 增量 /
删除差集 / 资产下载 / 持久化 / clean / vectorize 全部源无关。
"""

from __future__ import annotations

from rag_pipeline.connectors.base import (
    AssetAuth,
    ChangeSet,
    DocDetail,
    DocRef,
    ResourceRef,
    SourceConnector,
    SourceScope,
    detect_changes,
    normalize_version,
)
from rag_pipeline.connectors.registry import (
    available_connectors,
    get_connector,
    register_connector,
)

__all__ = [
    "AssetAuth",
    "ChangeSet",
    "DocDetail",
    "DocRef",
    "ResourceRef",
    "SourceConnector",
    "SourceScope",
    "detect_changes",
    "normalize_version",
    "available_connectors",
    "get_connector",
    "register_connector",
]
