"""源无关的摄取契约：DTO + ``SourceConnector`` ABC + ``detect_changes`` 纯逻辑。

connector 只负责「把某来源变成统一中间格式」：
``scopes()`` 列同步单元 → ``list_docs()`` 列变更令牌 → ``fetch()`` 取归一化
markdown + 资源清单 + facets + source_url；``asset_auth()`` 给资产下载的凭据。
增量判断（``detect_changes``）、下载编排、删除差集、资产下载、DB 持久化、clean、
vectorize **全部源无关**，不进 connector。

设计约束（见 REFACTOR_PLAN.md §5.1）：
- 不同来源 body 格式差异大（语雀=内嵌 HTML 的 md、Confluence=XHTML、Notion=block
  JSON）。connector 必须把 body 归一化为 **markdown + 占位契约**，否则下游 clean /
  vectorize 无法源无关。
- 契约中读写双方共享的 ``DocFacets`` / ``ChunkPayload`` 放在 ``rag_core.contracts``；
  本模块只放 pipeline 离线侧需要的摄取 DTO（读端不依赖）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rag_core.contracts import DocFacets

__all__ = [
    "SourceScope",
    "DocRef",
    "ResourceRef",
    "DocDetail",
    "AssetAuth",
    "ChangeSet",
    "SourceConnector",
    "normalize_version",
    "detect_changes",
]


@dataclass
class SourceScope:
    """一个来源内的同步单元（语雀=一个知识库 book）。

    ``facets`` 预填 scope 级分类维度（namespace/collection_id/collection_slug），
    ``doc_key`` 留空由每篇文档补。``dir_name`` 取代旧代码硬编码的
    ``{book_slug}_{book_id}`` 目录布局，供 Workspace 定位落盘路径。
    """

    scope_id: str  # 来源内 scope 主键（语雀 book_id）
    facets: DocFacets = field(default_factory=DocFacets)
    title: str = ""  # 人类可读名（日志用），可空
    extra: dict[str, Any] = field(default_factory=dict)  # 来源特有配置（分页/模板等）

    def dir_name(self) -> str:
        """落盘目录名。默认 ``{collection_slug}_{collection_id}``，回退到 scope_id。"""
        slug = self.facets.collection_slug
        cid = self.facets.collection_id or self.scope_id
        return f"{slug}_{cid}" if slug else str(cid)


@dataclass
class DocRef:
    """``list_docs`` 产出的轻量列表项：足够做增量判断，不含正文。

    ``source_version`` 是**已归一化**的变更令牌（语雀=content_updated_at）。
    ``detect_changes`` 按字符串相等比较它，故归一化是 connector 的责任
    （用 :func:`normalize_version` 或来源自定义）。
    """

    doc_id: int
    source_version: str = ""  # 已归一化的变更令牌
    title: str = ""
    doc_key: str = ""  # 来源内文档别名（语雀 slug）
    extra: dict[str, Any] = field(default_factory=dict)  # fetch 需要的来源上下文


@dataclass
class ResourceRef:
    """文档正文引用的一个资产（图片或附件）。URL 源自归一化后的 markdown。"""

    kind: str  # "image" | "attachment"
    index: int
    url: str
    filename: str = ""


@dataclass
class DocDetail:
    """``fetch`` 产出的完整文档：归一化 markdown + 资源清单 + facets + source_url。"""

    doc_id: int
    title: str
    body: str  # 归一化 markdown（下游 clean/chunk 的唯一输入）
    source_version: str = ""  # 与 DocRef 同口径的已归一化令牌
    facets: DocFacets = field(default_factory=DocFacets)
    source_url: str = ""
    resources: list[ResourceRef] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)  # 原始响应（存档/排障用）


@dataclass
class AssetAuth:
    """下载资产（图片/附件）所需的鉴权。语雀图片走 header、附件走浏览器 cookie。"""

    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)


@dataclass
class ChangeSet:
    """``detect_changes`` 的输出：本次要抓取 / 未变 / 已删除的划分。

    ``deleted`` 是 DB 有、来源已无的 doc_id。⚠️ 删除是破坏性动作（会清向量），
    调用方必须先确认 ``remote_complete``（列举无分页失败）才可据此删除。
    """

    to_fetch: list[DocRef] = field(default_factory=list)
    unchanged: list[DocRef] = field(default_factory=list)
    deleted: list[int] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "to_fetch": len(self.to_fetch),
            "unchanged": len(self.unchanged),
            "deleted": len(self.deleted),
        }


def normalize_version(v: Any) -> str:
    """归一化变更令牌用于相等比较。

    处理常见 ISO datetime 抖动：``T`` ↔ 空格、去掉亚秒小数部分与时区尾巴。
    对不含 ``T``/``.`` 的普通字符串（如内容 hash）只做 str + strip，保持原样。
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if "T" in s or " " in s:  # 形似 datetime 才做时间归一化
        s = s.replace("T", " ").split(".")[0].strip()
    return s


def detect_changes(
    refs: list[DocRef],
    known: Mapping[Any, Any],
    *,
    remote_complete: bool = True,
) -> ChangeSet:
    """源无关增量 + 删除差集（纯函数）。

    Args:
        refs: 来源本次列举到的文档（``source_version`` 已归一化）。
        known: DB 已存的 ``{doc_id: source_version}``（值会经 :func:`normalize_version`
            再比较，容忍 DB 里存的 datetime 格式与来源略有差异）。
        remote_complete: 来源列举是否完整（无分页/网络失败）。**为 False 时强制
            ``deleted=[]``**——宁可漏删不可误删，避免抓取残缺时把正常文档判为已删。

    Returns:
        ChangeSet：``to_fetch``（新增或令牌变化）/``unchanged``（令牌一致）/
        ``deleted``（DB 有、来源无；仅在 remote_complete 时非空）。
    """
    known_norm = {int(k): normalize_version(v) for k, v in known.items()}
    seen: set[int] = set()
    to_fetch: list[DocRef] = []
    unchanged: list[DocRef] = []

    for ref in refs:
        did = int(ref.doc_id)
        seen.add(did)
        prev = known_norm.get(did)
        cur = normalize_version(ref.source_version)
        if prev is not None and cur != "" and prev == cur:
            unchanged.append(ref)
        else:
            to_fetch.append(ref)

    deleted: list[int] = []
    if remote_complete:
        deleted = sorted(did for did in known_norm if did not in seen)

    return ChangeSet(to_fetch=to_fetch, unchanged=unchanged, deleted=deleted)


class SourceConnector(ABC):
    """数据源接入契约。子类挂 ``source`` 类属性（如 ``"yuque"``），进注册表并写入
    ``ChunkPayload.source``。

    ``detect_changes`` 已由基类按源无关逻辑实现（委托给模块级 :func:`detect_changes`），
    子类通常无需覆盖；只需实现 scopes/list_docs/fetch/asset_auth/build_source_url。
    """

    source: str = ""

    @abstractmethod
    def scopes(self) -> list[SourceScope]:
        """返回配置的同步单元（语雀=各 book）。"""

    @abstractmethod
    def list_docs(self, scope: SourceScope) -> list[DocRef]:
        """列举 scope 下所有文档的变更令牌（含分页），不取正文。"""

    @abstractmethod
    def fetch(self, scope: SourceScope, ref: DocRef) -> DocDetail:
        """取单篇文档详情：归一化 markdown + 资源清单 + facets + source_url。"""

    @abstractmethod
    def asset_auth(self, scope: SourceScope) -> AssetAuth:
        """返回下载该 scope 资产所需的 header/cookie。"""

    @abstractmethod
    def build_source_url(self, scope: SourceScope, detail: DocDetail) -> str:
        """按来源模板拼人类可读的原文 URL。"""

    def detect_changes(
        self,
        refs: list[DocRef],
        known: Mapping[Any, Any],
        *,
        remote_complete: bool = True,
    ) -> ChangeSet:
        """源无关增量 + 删除差集，见模块级 :func:`detect_changes`。"""
        return detect_changes(refs, known, remote_complete=remote_complete)
