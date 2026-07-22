"""下载阶段：源无关编排。

流程（对每个 scope）：``list_docs`` → ``get_scope_versions`` → ``detect_changes``
→ 逐篇 ``fetch`` → 写 md + 下载资产（图片/附件）+ 提取附件文本 → ``upsert_doc_meta``
+ ``save_resources``；最后按删除差集 ``mark_docs_deleted``。

移植自旧 download.py 的 ``process_doc``/``process_assets``/``download_book``，去掉语雀
专有逻辑（改由 connector 提供），路径基准由 :class:`Workspace` 提供。

⚠️ 删除安全（NEXT_SESSION 提示的破坏性风险）：删除差集来自 ``detect_changes``，仅当
列举**完整**才据此软删。本阶段守卫：列举成功但返回 0 篇而 DB 有存量时，判为抓取残缺
（``remote_complete=False``），不删任何文档——宁漏删不误删。
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rag_core import download_util as du
from rag_core import media, repository
from rag_core.extract import extract_text_from_file
from rag_core.hashing import text_md5
from rag_core.settings import Settings
from rag_pipeline.connectors.base import AssetAuth, DocDetail, SourceConnector, SourceScope
from rag_pipeline.workspace import Workspace

logger = logging.getLogger(__name__)

__all__ = ["DownloadStats", "sync_scope", "sync"]


@dataclass
class DownloadStats:
    scope_id: str
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0
    images: int = 0
    attachments: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)


# ==================== 资产下载 ====================

def _download_images(
    detail: DocDetail, scope: SourceScope, workspace: Workspace, auth: AssetAuth
) -> list[dict[str, Any]]:
    """下载文档图片，返回 rag_resource 记录列表（含失败项，保留 url/local 供追溯）。"""
    out: list[dict[str, Any]] = []
    images_dir = workspace.images_dir(scope, detail.doc_id)
    for res in (r for r in detail.resources if r.kind == "image"):
        clean_url = res.url.split("?")[0]
        ext = os.path.splitext(clean_url)[1].lower() or ".png"
        mime = media.guess_mime_from_ext(ext)
        url_hash = hashlib.md5(res.url.encode()).hexdigest()[:10]
        local = images_dir / f"{res.index}_{url_hash}{ext}"
        rel = workspace.rel(local)
        try:
            size = du.download_with_retry(
                res.url, str(local), headers=auth.headers, label=f"IMG {res.index}"
            )
            real_mime = media.detect_mime_from_file(local)
            if real_mime:
                mime = real_mime
            out.append(
                {
                    "index": res.index,
                    "url": res.url,
                    "mime": mime,
                    "local_path": rel,
                    "served_url": workspace.served_url(rel),
                    "size_bytes": size,
                    "status": "ok",
                }
            )
        except Exception as e:  # noqa: BLE001 - 单图失败不应中断整篇
            logger.warning("[IMG %s] download failed: %s", res.index, e)
            out.append(
                {
                    "index": res.index,
                    "url": res.url,
                    "mime": mime,
                    "local_path": rel,
                    "size_bytes": 0,
                    "status": "failed",
                    "error": str(e),
                }
            )
    return out


def _download_attachments(
    detail: DocDetail,
    scope: SourceScope,
    workspace: Workspace,
    auth: AssetAuth,
    settings: Settings | None,
) -> list[dict[str, Any]]:
    """下载附件并提取文本，返回 rag_resource 记录列表。"""
    out: list[dict[str, Any]] = []
    files_dir = workspace.files_dir(scope, detail.doc_id)
    texts_dir = workspace.texts_dir(scope, detail.doc_id)
    for res in (r for r in detail.resources if r.kind == "attachment"):
        ext = os.path.splitext(res.url.split("?")[0])[1].lower()
        file_type = ext.lstrip(".")
        local = files_dir / f"{res.index}_{res.filename}"
        rel = workspace.rel(local)
        try:
            du.download_with_retry(
                res.url,
                str(local),
                headers=auth.headers,
                cookies=auth.cookies,
                label=f"ATT {res.index}",
            )
            text_rel = ""
            text_chars = 0
            extracted = extract_text_from_file(str(local), file_type, settings=settings)
            if extracted:
                texts_dir.mkdir(parents=True, exist_ok=True)
                stem = os.path.splitext(res.filename)[0]
                text_file = texts_dir / f"{res.index}_{stem}.txt"
                text_file.write_text(extracted, encoding="utf-8")
                text_rel = workspace.rel(text_file)
                text_chars = len(extracted)
            size = local.stat().st_size if local.exists() else 0
            out.append(
                {
                    "index": res.index,
                    "filename": res.filename,
                    "url": res.url,
                    "file_type": file_type,
                    "local_file": rel,
                    "size_bytes": size,
                    "extracted_text": text_rel,
                    "text_chars": text_chars,
                    "status": "ok",
                }
            )
        except Exception as e:  # noqa: BLE001 - 单附件失败不应中断整篇
            logger.warning("[ATT %s] failed: %s", res.index, e)
            out.append(
                {
                    "index": res.index,
                    "filename": res.filename,
                    "url": res.url,
                    "file_type": file_type,
                    "local_file": rel,
                    "status": "failed",
                    "error": str(e),
                }
            )
    return out


# ==================== 单篇持久化 ====================

def _meta_record(source: str, detail: DocDetail, md_rel: str, image_count: int,
                 attachment_count: int) -> dict[str, Any]:
    """DocDetail → rag_doc_meta 通用列记录（D2=A）。"""
    f = detail.facets
    return {
        "doc_id": detail.doc_id,
        "source": source,
        "namespace": f.namespace,
        "collection_id": f.collection_id,
        "collection_slug": f.collection_slug,
        "doc_key": f.doc_key,
        "doc_title": detail.title,
        "source_url": detail.source_url,
        "source_file": md_rel,
        "source_version": detail.source_version,
        "source_dims": None,
        "md_hash": text_md5(detail.body),
        "file_hash": "",
        "chunk_count": 0,
        "image_count": image_count,
        "attachment_count": attachment_count,
        "status": "downloaded",
        "download_time": datetime.now(),
    }


def _persist_doc(
    conn,
    connector: SourceConnector,
    scope: SourceScope,
    detail: DocDetail,
    workspace: Workspace,
    settings: Settings | None,
) -> tuple[int, int]:
    """写 md + 资产 + DB。返回 (成功图片数, 成功附件数)。"""
    md_rel = workspace.write_md(scope, detail.doc_id, detail.title, detail.body)
    auth = connector.asset_auth(scope)
    images = _download_images(detail, scope, workspace, auth)
    attachments = _download_attachments(detail, scope, workspace, auth, settings)
    image_count = sum(1 for i in images if i["status"] == "ok")
    attachment_count = sum(1 for a in attachments if a["status"] == "ok")

    repository.upsert_doc_meta(
        conn, _meta_record(connector.source, detail, md_rel, image_count, attachment_count)
    )
    repository.save_resources(conn, detail.doc_id, "image", images)
    repository.save_resources(conn, detail.doc_id, "attachment", attachments)
    return image_count, attachment_count


# ==================== scope / 全量编排 ====================

def sync_scope(
    conn,
    connector: SourceConnector,
    scope: SourceScope,
    workspace: Workspace,
    *,
    settings: Settings | None = None,
    full: bool = False,
) -> DownloadStats:
    """同步单个 scope。``full=True`` 忽略增量、全量重下（删除差集仍照常处理）。"""
    stats = DownloadStats(scope_id=scope.scope_id)

    refs = connector.list_docs(scope)  # 列举失败会抛出 → 整个 scope 中止，不做删除
    known = repository.get_scope_versions(conn, connector.source, scope.facets.collection_id)

    # 完整性守卫：列举回 0 篇但 DB 有存量，判为抓取残缺，禁止删除（宁漏删不误删）
    remote_complete = bool(refs) or not known
    changes = connector.detect_changes(refs, known, remote_complete=remote_complete)

    to_process = refs if full else changes.to_fetch
    stats.skipped = 0 if full else len(changes.unchanged)

    for ref in to_process:
        try:
            detail = connector.fetch(scope, ref)
            img_n, att_n = _persist_doc(conn, connector, scope, detail, workspace, settings)
            stats.downloaded += 1
            stats.images += img_n
            stats.attachments += att_n
        except Exception as e:  # noqa: BLE001 - 单篇失败记录后继续
            logger.error("[%s] fetch/persist failed: %s", ref.doc_id, e)
            stats.failed += 1
            stats.failures.append({"doc_id": ref.doc_id, "error": str(e)})

    if changes.deleted:
        repository.mark_docs_deleted(conn, changes.deleted)
        stats.deleted = len(changes.deleted)
        logger.info("[%s] marked %d docs deleted", scope.scope_id, stats.deleted)

    return stats


def sync(
    conn,
    connector: SourceConnector,
    workspace: Workspace,
    *,
    settings: Settings | None = None,
    full: bool = False,
) -> list[DownloadStats]:
    """同步 connector 的所有 scope，单个 scope 失败不影响其它。"""
    results: list[DownloadStats] = []
    for scope in connector.scopes():
        try:
            results.append(
                sync_scope(conn, connector, scope, workspace, settings=settings, full=full)
            )
        except Exception as e:  # noqa: BLE001 - scope 级列举失败隔离
            logger.error("scope %s failed: %s", scope.scope_id, e)
            results.append(DownloadStats(scope_id=scope.scope_id, failed=1))
    return results
