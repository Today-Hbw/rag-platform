"""connector 注册表：按 ``--source`` 名解析出 connector 实例。

新增数据源只需实现 ``SourceConnector`` 并在此 ``register_connector``，下游 CLI /
stages 无需改动（对应阶段 4 验收：新增 stub connector 不改任何下游）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from rag_pipeline.connectors.base import SourceConnector
from rag_pipeline.connectors.local import LocalConnector
from rag_pipeline.connectors.yuque import YuqueConnector

if TYPE_CHECKING:
    from rag_core.settings import Settings

__all__ = [
    "register_connector",
    "get_connector",
    "available_connectors",
]

# name -> factory(settings) -> SourceConnector
ConnectorFactory = Callable[["Settings | None"], SourceConnector]
_REGISTRY: dict[str, ConnectorFactory] = {}


def register_connector(name: str, factory: ConnectorFactory) -> None:
    """注册数据源工厂。``factory(settings)`` 返回可用的 connector 实例。"""
    _REGISTRY[name] = factory


def get_connector(name: str, settings: Settings | None = None) -> SourceConnector:
    """按名解析 connector。未知名抛 KeyError 并列出可用源。"""
    if name not in _REGISTRY:
        raise KeyError(f"未知数据源 {name!r}；可用：{sorted(_REGISTRY)}")
    return _REGISTRY[name](settings)


def available_connectors() -> list[str]:
    return sorted(_REGISTRY)


# ---- 内置注册 ----
register_connector("yuque", YuqueConnector.from_settings)
register_connector("local", LocalConnector.from_settings)
