"""本地文件 connector：把目录树里的 .md 当作文档源。

用途：(1) 验证 ``SourceConnector`` ABC 没过拟合语雀 REST——一个纯文件、无分页无鉴权
的源也能套同一契约；(2) 离线兜底 / 自测数据源。

约定：``doc_id`` 由相对路径 md5 派生（稳定可复现）；``source_version`` = 文件内容 md5
（内容变才重抓）；资源清单从 markdown 解析，与 yuque 一致复用 download_util。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rag_core.contracts import DocFacets
from rag_core.download_util import extract_attachment_urls, extract_image_urls
from rag_core.hashing import text_md5
from rag_pipeline.connectors.base import (
    AssetAuth,
    DocDetail,
    DocRef,
    ResourceRef,
    SourceConnector,
    SourceScope,
)

if TYPE_CHECKING:
    from rag_core.settings import Settings

logger = logging.getLogger(__name__)

__all__ = ["LocalConnector"]


def _doc_id(rel_path: str) -> int:
    """相对路径 → 稳定 48-bit 正整数 doc_id（落 BIGINT）。"""
    return int(hashlib.md5(rel_path.encode("utf-8")).hexdigest()[:12], 16)


class LocalConnector(SourceConnector):
    """从 ``root`` 目录递归读 .md 文件的数据源。"""

    source = "local"

    def __init__(self, root: str | Path, collection_id: str = "local") -> None:
        self.root = Path(root)
        self.collection_id = collection_id

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> LocalConnector:
        from rag_core.settings import get_settings

        s = (settings or get_settings()).local
        return cls(root=s.root, collection_id=s.collection_id)

    def scopes(self) -> list[SourceScope]:
        facets = DocFacets(collection_id=self.collection_id, collection_slug=self.root.name)
        return [SourceScope(scope_id=self.collection_id, facets=facets, title=str(self.root))]

    def list_docs(self, scope: SourceScope) -> list[DocRef]:
        if not self.root.exists():
            logger.warning("local root 不存在：%s", self.root)
            return []
        refs = []
        for path in sorted(self.root.rglob("*.md")):
            rel = path.relative_to(self.root).as_posix()
            body = path.read_text(encoding="utf-8")
            refs.append(
                DocRef(
                    doc_id=_doc_id(rel),
                    source_version=text_md5(body),
                    title=path.stem,
                    doc_key=rel,
                    extra={"path": str(path)},
                )
            )
        return refs

    def fetch(self, scope: SourceScope, ref: DocRef) -> DocDetail:
        path = Path(ref.extra.get("path") or (self.root / ref.doc_key))
        body = path.read_text(encoding="utf-8")
        facets = DocFacets(
            collection_id=scope.facets.collection_id,
            collection_slug=scope.facets.collection_slug,
            doc_key=ref.doc_key,
        )
        resources: list[ResourceRef] = []
        for i, u in enumerate(extract_image_urls(body)):
            resources.append(ResourceRef(kind="image", index=i, url=u))
        for i, att in enumerate(extract_attachment_urls(body)):
            resources.append(
                ResourceRef(kind="attachment", index=i, url=att["url"], filename=att["filename"])
            )
        detail = DocDetail(
            doc_id=ref.doc_id,
            title=ref.title,
            body=body,
            source_version=text_md5(body),
            facets=facets,
            resources=resources,
        )
        detail.source_url = self.build_source_url(scope, detail)
        return detail

    def asset_auth(self, scope: SourceScope) -> AssetAuth:
        return AssetAuth()  # 本地文件无需鉴权

    def build_source_url(self, scope: SourceScope, detail: DocDetail) -> str:
        return (self.root / detail.facets.doc_key).as_uri() if detail.facets.doc_key else ""
