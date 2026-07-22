"""语雀 connector：把语雀知识库变成源无关的 DocRef/DocDetail。

从旧 ``download.py`` 搬入（只搬不改行为）：
- REST 分页列举 ``/repos/{book_id}/docs``（limit/offset）；
- 详情 ``/repos/{book_id}/docs/{doc_id}``，取 ``data.body`` 归一化 markdown；
- ``content_updated_at`` → 归一化 ``source_version``（增量令牌）；
- ``X-Auth-Token`` header 鉴权，附件下载额外用浏览器 Cookie（见 ``asset_auth``）；
- 资源清单从 markdown 解析，复用 rag-core ``download_util``。

配置分层（D2/密钥出库）：books 列表（非密钥：book_id/book_slug/namespace）由调用方
传入，token/cookie（密钥）来自 ``rag_core.settings.YuqueSettings``。source_url 模板
可配（默认占位，部署侧按自己的语雀空间设置以与旧产出对齐）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from rag_core.contracts import DocFacets
from rag_core.download_util import (
    extract_attachment_urls,
    extract_image_urls,
    parse_cookie_string,
)
from rag_pipeline.connectors.base import (
    AssetAuth,
    DocDetail,
    DocRef,
    ResourceRef,
    SourceConnector,
    SourceScope,
    normalize_version,
)

logger = logging.getLogger(__name__)

__all__ = ["YuqueBook", "YuqueConnector"]

DEFAULT_API_BASE = "https://www.yuque.com/api/v2"
# 部署侧按自己的语雀空间覆盖（如 https://<space>.yuque.com/{namespace}/{collection_slug}/{doc_key}）。
DEFAULT_URL_TEMPLATE = "https://www.yuque.com/{namespace}/{collection_slug}/{doc_key}"


@dataclass
class YuqueBook:
    """一个语雀知识库的非密钥配置。"""

    book_id: str
    book_slug: str = ""
    namespace: str = ""  # 原 team_code（正确值，可空；D5：权限不锚它）
    title: str = ""
    token: str = ""  # 可选 per-book token 覆盖全局


class YuqueConnector(SourceConnector):
    """语雀数据源接入。

    Args:
        books: 知识库配置列表。
        token: 全局 X-Auth-Token（book 未单独配 token 时用）。
        cookie: 浏览器 Cookie 字符串（附件下载用），可空。
        url_template: source_url 模板，占位符 ``{namespace}/{collection_slug}/{doc_key}``。
        api_base: 语雀 API 根，便于测试注入。
        page_size: 列举分页大小（旧代码 100）。
        session: 可注入的 ``requests.Session``（测试用 mock），默认新建。
    """

    source = "yuque"

    def __init__(
        self,
        books: list[YuqueBook],
        token: str = "",
        cookie: str = "",
        *,
        url_template: str = DEFAULT_URL_TEMPLATE,
        api_base: str = DEFAULT_API_BASE,
        page_size: int = 100,
        session: requests.Session | None = None,
    ) -> None:
        self.books = books
        self.token = token
        self.cookie = cookie
        self.url_template = url_template
        self.api_base = api_base.rstrip("/")
        self.page_size = page_size
        self.session = session or requests.Session()

    # ---------- helpers ----------

    def _token_for(self, scope: SourceScope) -> str:
        return scope.extra.get("token") or self.token

    def _headers(self, scope: SourceScope) -> dict[str, str]:
        return {"X-Auth-Token": self._token_for(scope)}

    def _docs_url(self, book_id: str) -> str:
        return f"{self.api_base}/repos/{book_id}/docs"

    # ---------- SourceConnector ----------

    def scopes(self) -> list[SourceScope]:
        out = []
        for b in self.books:
            facets = DocFacets(
                namespace=b.namespace,
                collection_id=str(b.book_id),
                collection_slug=b.book_slug,
            )
            extra: dict[str, Any] = {}
            if b.token:
                extra["token"] = b.token
            out.append(
                SourceScope(scope_id=str(b.book_id), facets=facets, title=b.title, extra=extra)
            )
        return out

    def list_docs(self, scope: SourceScope) -> list[DocRef]:
        """分页列举 scope 下全部文档的变更令牌（不取正文）。"""
        url = self._docs_url(scope.scope_id)
        headers = self._headers(scope)
        refs: list[DocRef] = []
        offset = 0
        while True:
            resp = self.session.get(
                url, headers=headers, params={"limit": self.page_size, "offset": offset}
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            for doc in data:
                refs.append(
                    DocRef(
                        doc_id=int(doc["id"]),
                        source_version=normalize_version(doc.get("content_updated_at", "")),
                        title=doc.get("title", ""),
                        doc_key=doc.get("slug", ""),
                    )
                )
            if len(data) < self.page_size:
                break
            offset += self.page_size
        return refs

    def fetch(self, scope: SourceScope, ref: DocRef) -> DocDetail:
        """取单篇详情：归一化 markdown + 资源清单 + facets + source_url。"""
        url = f"{self._docs_url(scope.scope_id)}/{ref.doc_id}"
        resp = self.session.get(url, headers=self._headers(scope))
        resp.raise_for_status()
        detail = resp.json()
        data = detail.get("data", {})
        body = data.get("body", "") or ""
        slug = data.get("slug", "") or ref.doc_key
        book_slug = (data.get("book") or {}).get("slug") or scope.facets.collection_slug
        title = data.get("title") or ref.title

        facets = DocFacets(
            namespace=scope.facets.namespace,
            collection_id=scope.facets.collection_id,
            collection_slug=book_slug,
            doc_key=slug,
        )
        result = DocDetail(
            doc_id=int(ref.doc_id),
            title=title,
            body=body,
            source_version=normalize_version(data.get("content_updated_at", ref.source_version)),
            facets=facets,
            resources=self._resources_from_body(body),
            raw=detail,
        )
        result.source_url = self.build_source_url(scope, result)
        return result

    def asset_auth(self, scope: SourceScope) -> AssetAuth:
        """图片走 X-Auth-Token header，附件额外需浏览器 Cookie。"""
        return AssetAuth(
            headers=self._headers(scope),
            cookies=parse_cookie_string(self.cookie),
        )

    def build_source_url(self, scope: SourceScope, detail: DocDetail) -> str:
        """按模板拼原文 URL。缺 doc_key 时返回空串（与旧行为一致）。"""
        if not detail.facets.doc_key:
            return ""
        return self.url_template.format(
            namespace=detail.facets.namespace,
            collection_slug=detail.facets.collection_slug,
            doc_key=detail.facets.doc_key,
        )

    # ---------- internal ----------

    @staticmethod
    def _resources_from_body(body: str) -> list[ResourceRef]:
        """从 markdown 正文解析图片 + 附件引用（源自 download_util 的白名单规则）。"""
        resources: list[ResourceRef] = []
        for i, u in enumerate(extract_image_urls(body)):
            resources.append(ResourceRef(kind="image", index=i, url=u))
        for i, att in enumerate(extract_attachment_urls(body)):
            resources.append(
                ResourceRef(
                    kind="attachment", index=i, url=att["url"], filename=att["filename"]
                )
            )
        return resources
