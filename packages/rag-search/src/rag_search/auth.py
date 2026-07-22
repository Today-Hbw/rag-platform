"""RBAC 权限解析（阶段 5）：role_ids → 可见范围 → Qdrant filter。

边界：RAG 不认证用户、不认识人;只接受业务系统传来的 ``X-Role-Ids``,查
``system_role_permission`` 得到可见的 collection/doc,构造 Qdrant filter。

resource_id 约定（D7）：``book:<collection_id>`` / ``doc:<doc_id>`` / ``*``(超管全放行)。

坑（REFACTOR_PLAN §5.2）：payload ``doc_id`` 是 **int**,``MatchAny`` 不强转 int
会静默匹配不中 → doc 级授权全失效且无报错。这里显式 int() 化。

灰度：``rbac.enabled`` 关 = 全量可见(旧行为);开 = fail-closed(无角色/无授权 → 看不到)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rag_core import repository

__all__ = ["Scope", "parse_role_ids", "resolve_scope", "build_query_filter", "scope_sig"]


@dataclass
class Scope:
    """一次请求的可见范围。"""

    allow_all: bool = False
    collection_ids: set[str] = field(default_factory=set)
    doc_ids: set[int] = field(default_factory=set)

    @property
    def denies_all(self) -> bool:
        """既非超管、又无任何可见 collection/doc → 什么都看不到。"""
        return not self.allow_all and not self.collection_ids and not self.doc_ids


def parse_role_ids(header_value: str | None) -> list[str]:
    """解析 ``X-Role-Ids`` 头(逗号分隔),去空白与空项。"""
    if not header_value:
        return []
    return [p.strip() for p in header_value.split(",") if p.strip()]


def resolve_scope(conn, role_ids: list[str]) -> Scope:
    """role_ids → Scope。查 system_role_permission,按 resource_id 前缀归类。"""
    scope = Scope()
    for rid in repository.get_role_resource_ids(conn, role_ids):
        if rid == "*":
            scope.allow_all = True
        elif rid.startswith("book:"):
            scope.collection_ids.add(rid[len("book:"):])
        elif rid.startswith("doc:"):
            try:
                scope.doc_ids.add(int(rid[len("doc:"):]))
            except ValueError:
                continue
    return scope


def build_query_filter(scope: Scope) -> Any | None:
    """Scope → Qdrant Filter。超管返回 None(不过滤);否则 collection_id/doc_id 取并集(OR)。

    denies_all 的情况调用方应提前短路(直接空结果),不必到这里。
    """
    if scope.allow_all:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    should: list[Any] = []
    if scope.collection_ids:
        should.append(
            FieldCondition(key="collection_id", match=MatchAny(any=sorted(scope.collection_ids)))
        )
    if scope.doc_ids:
        # doc_id 是 int：显式 int 化,否则 MatchAny 静默匹配不中
        should.append(
            FieldCondition(key="doc_id", match=MatchAny(any=sorted(int(d) for d in scope.doc_ids)))
        )
    return Filter(should=should) if should else None


def scope_sig(role_ids: list[str]) -> str:
    """缓存 key 的权限签名：排序去重的 role_ids。

    相同 role_ids ⇒ 相同可见集合,故按 role_ids 缓存正确;不同权限用户 key 不同,
    杜绝串缓存拿到越权结果(REFACTOR_PLAN §5.2 铁律 2)。
    """
    return "roles:" + ",".join(sorted(set(role_ids)))
