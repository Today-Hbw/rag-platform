"""RBAC 权限解析（阶段 5）：role_ids → 可见范围 → Qdrant filter。

边界：RAG 不认证用户、不认识人;只接受业务系统传来的 ``X-Role-Ids``,查
``system_role_permission`` 得到可见的 collection/doc,构造 Qdrant filter。

resource_id 约定（D7）：``book:<collection_id>`` / ``doc:<doc_id>`` / ``*``(超管全放行)。

坑（REFACTOR_PLAN §5.2）：payload ``doc_id`` 是 **int**,``MatchAny`` 不强转 int
会静默匹配不中 → doc 级授权全失效且无报错。这里显式 int() 化。

灰度：``rbac.enabled`` 关 = 全量可见(旧行为);开 = fail-closed(无角色/无授权 → 看不到)。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from rag_core import repository

logger = logging.getLogger(__name__)

__all__ = [
    "Scope",
    "Identity",
    "parse_role_ids",
    "resolve_identity",
    "introspect",
    "resolve_scope",
    "build_query_filter",
    "scope_sig",
]


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


# ==================== 身份内省（token → role_ids，增量①）====================


@dataclass
class Identity:
    """一次请求的身份解析结果（第①跳产物：token → role_ids）。

    valid=False 表示 token 无效/内省失败 → 上层视为无角色（fail-closed，仅公共库可见）。
    allow_all=True 表示超管（老板），下游不加 Qdrant 过滤。
    """

    valid: bool = False
    role_ids: list[str] = field(default_factory=list)
    allow_all: bool = False


class _TTLCache:
    """极简进程内 TTL 缓存（token → Identity）。单进程/单 worker 足够；
    多 worker 各自缓存，TTL 短，可接受。key 为 token（已在内存，不额外落盘）。"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Identity]] = {}

    def get(self, key: str) -> Identity | None:
        item = self._store.get(key)
        if item is None:
            return None
        expire_at, value = item
        if time.monotonic() >= expire_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Identity, ttl: int) -> None:
        if ttl <= 0:
            return
        self._store[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._store.clear()


_identity_cache = _TTLCache()


def introspect(cfg, token: str, *, session=None) -> Identity:
    """调业务 introspection 接口把用户 token 换成 role_ids（不缓存，缓存在 resolve_identity）。

    契约（REFACTOR_PLAN §5.2）：``POST <introspect_url>``，头 ``Authorization: Bearer <token>``
    (可选 ``X-Service-Token``)；200 → ``{"valid":bool,"role_ids":[...],"allow_all":bool}``。
    401 / valid=false / 任何异常 → ``Identity(valid=False)``（fail-closed，绝不放行）。
    """
    import requests

    headers = {"Authorization": f"Bearer {token}"}
    svc_token = cfg.introspect_service_token.get_secret_value()
    if svc_token:
        headers["X-Service-Token"] = svc_token
    try:
        client = session or requests
        resp = client.post(cfg.introspect_url, headers=headers, timeout=cfg.introspect_timeout)
    except Exception as e:  # noqa: BLE001 - 网络异常一律按无效身份处理
        logger.warning("introspection 请求失败: %s", e)
        return Identity(valid=False)
    if resp.status_code == 401:
        return Identity(valid=False)
    if resp.status_code != 200:
        logger.warning("introspection 返回非预期状态码: %s", resp.status_code)
        return Identity(valid=False)
    try:
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("introspection 响应非 JSON: %s", e)
        return Identity(valid=False)
    if not data.get("valid"):
        return Identity(valid=False)
    role_ids = [str(r) for r in (data.get("role_ids") or [])]
    return Identity(valid=True, role_ids=role_ids, allow_all=bool(data.get("allow_all")))


def resolve_identity(
    cfg, *, token: str | None = None, roles_header_value: str | None = None, session=None
) -> Identity:
    """身份解析总入口（第①跳）。两种模式由 ``introspect_url`` 是否配置决定：

    - **离线/调试（默认，url 为空）**：直接信 ``X-Role-Ids`` 头；缺失则用
      ``default_role_ids`` 兜底。等价 bda10ab 旧行为，不发任何网络请求。
    - **在线（url 有值）**：拿用户 token 调 introspection，结果按 token 缓存（TTL）。
      无 token → valid=False（fail-closed）。

    切换只改配置，代码零改动。
    """
    if not cfg.introspect_url:
        role_ids = parse_role_ids(roles_header_value) or [str(r) for r in cfg.default_role_ids]
        return Identity(valid=True, role_ids=role_ids, allow_all=False)

    if not token:
        return Identity(valid=False)
    cached = _identity_cache.get(token)
    if cached is not None:
        return cached
    identity = introspect(cfg, token, session=session)
    if identity.valid:
        _identity_cache.set(token, identity, cfg.scope_cache_ttl)
    return identity


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


def scope_sig(role_ids: list[str], allow_all: bool = False) -> str:
    """缓存 key 的权限签名：排序去重的 role_ids（allow_all 单独一档）。

    相同 role_ids ⇒ 相同可见集合,故按 role_ids 缓存正确;不同权限用户 key 不同,
    杜绝串缓存拿到越权结果(REFACTOR_PLAN §5.2 铁律 2)。allow_all(超管)看到的是
    全量、无过滤,与任何受限角色结果不同,故必须独占一档签名。
    """
    if allow_all:
        return "roles:__all__"
    return "roles:" + ",".join(sorted(set(role_ids)))
