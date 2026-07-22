"""向量化阶段：把 status='cleaned' 文档切块、多模态编码、写入 Qdrant（源无关）。

流程：先处理删除（get_docs_to_delete → 删 Qdrant point → mark_doc_fully_deleted）；
再对 cleaned 文档：读 md_clean → chunk_with_images → 逐块 embed_multimodal → 用
``ChunkPayload`` 组装扁平 payload（泛化 facets，source_url 直取 doc_meta，不再重建模板）
→ 先 upsert 新点、后删旧点 → update_vec_status + replace_chunk_records。

移植自旧 vectorize.py，payload 从语雀专有列改为 ``ChunkPayload``（D2=A 泛化）。
embedding/vectorstore 通过依赖注入，便于离线单测。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from rag_core import repository
from rag_core.chunking import chunk_with_images
from rag_core.contracts import ChunkPayload, DocFacets
from rag_core.embedding import EmbeddingClient
from rag_core.hashing import file_md5, text_md5
from rag_core.settings import Settings, get_settings
from rag_core.vectorstore import VectorStore, make_point
from rag_pipeline.workspace import Workspace

logger = logging.getLogger(__name__)

__all__ = ["VectorizeStats", "vectorize"]

# RBAC 过滤前置：为这些字段建 payload index（D7 锚 collection_id/doc_id）
PAYLOAD_INDEXES = {"collection_id": "keyword", "doc_id": "integer", "source": "keyword"}


@dataclass
class VectorizeStats:
    vectorized: int = 0
    chunks: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)


def _has_meaningful(text: str) -> bool:
    """至少含一个字母/数字/CJK 才值得向量化（忠实旧逻辑）。"""
    return any(c.isalnum() or "一" <= c <= "鿿" for c in text.strip())


def _process_deletions(conn, store: VectorStore) -> int:
    """删 Qdrant 点并硬删 DB 行。返回删除文档数。"""
    deleted = 0
    for doc_id_str in repository.get_docs_to_delete(conn):
        doc_id = int(doc_id_str)
        old_points = repository.get_chunk_point_ids(conn, doc_id)
        if old_points:
            store.delete(old_points)
        repository.mark_doc_fully_deleted(conn, doc_id)
        deleted += 1
        logger.info("[%s] 已从 Qdrant 删除 %d 点", doc_id, len(old_points))
    return deleted


def _vectorize_doc(
    conn,
    doc: dict,
    workspace: Workspace,
    embedder: EmbeddingClient,
    store: VectorStore,
    settings: Settings,
) -> tuple[str, int]:
    """向量化单篇。返回 (结果, chunk 数)；结果 ∈ ok/skipped/failed。"""
    doc_id = doc["doc_id"]
    clean_abs = workspace.data_root / doc["source_file"]
    if not clean_abs.exists():
        repository.update_vec_error(
            conn, doc_id, "vec_failed", f"md_clean 不存在: {doc['source_file']}"
        )
        return "failed", 0

    text = clean_abs.read_text(encoding="utf-8")
    if not _has_meaningful(text):
        repository.update_vec_error(conn, doc_id, "vec_skipped", "内容为空或无有效字符")
        return "skipped", 0

    manifest = repository.build_manifest(conn, doc_id)
    chunk_pairs = chunk_with_images(
        text, manifest, workspace.data_root,
        settings.pipeline.chunk_size, settings.pipeline.chunk_overlap,
    )
    if not chunk_pairs:
        repository.update_vec_error(conn, doc_id, "vec_skipped", "分块后为空")
        return "skipped", 0

    # 逐块多模态编码；任一块失败则整篇失败（不产生半截向量）
    embeddings: list[list[float]] = []
    for i, (chunk_text_i, img_infos) in enumerate(chunk_pairs):
        img_paths = [str(workspace.data_root / info["local_path"]) for info in img_infos]
        try:
            embeddings.append(
                embedder.embed_multimodal(chunk_text_i, image_paths=img_paths or None)
            )
        except Exception as e:  # noqa: BLE001
            repository.update_vec_error(
                conn, doc_id, "vec_failed", f"chunk {i} embedding 失败: {e}"
            )
            return "failed", 0

    att_count = sum(1 for a in manifest.get("attachments", []) if a.get("status") == "ok")
    facets = DocFacets(
        namespace=doc.get("namespace", ""),
        collection_id=doc.get("collection_id", ""),
        collection_slug=doc.get("collection_slug", ""),
        doc_key=doc.get("doc_key", "") or "",
    )

    points = []
    chunks_data = []
    for i, ((chunk_text_i, img_infos), emb) in enumerate(
        zip(chunk_pairs, embeddings, strict=True)
    ):
        point_id = str(uuid.uuid4())
        payload = ChunkPayload(
            source=doc.get("source", ""),
            doc_id=doc_id,
            doc_title=doc.get("doc_title", ""),
            chunk_index=i,
            chunk_text=chunk_text_i,
            facets=facets,
            source_url=doc.get("source_url", "") or "",
            source_file=doc["source_file"],
            images=img_infos,
            has_image=bool(img_infos),
            has_attachment=att_count > 0,
            attachment_count=att_count,
        ).to_payload()
        points.append(make_point(point_id, emb, payload))
        chunks_data.append((i, point_id, text_md5(chunk_text_i)))

    old_points = repository.get_chunk_point_ids(conn, doc_id)
    store.upsert(points)  # 先写新点
    if old_points:
        store.delete(old_points)  # 确认新点写入后再删旧点
    repository.update_vec_status(conn, doc_id, file_md5(clean_abs), len(chunk_pairs))
    repository.replace_chunk_records(conn, doc_id, chunks_data)
    return "ok", len(chunk_pairs)


def vectorize(
    conn,
    workspace: Workspace,
    *,
    settings: Settings | None = None,
    embedder: EmbeddingClient | None = None,
    store: VectorStore | None = None,
    recreate: bool = False,
) -> VectorizeStats:
    """向量化编排。embedder/store 可注入（离线测试）；缺省从 settings 构造。"""
    settings = settings or get_settings()
    embedder = embedder or EmbeddingClient(settings)
    store = store or VectorStore(settings)

    store.ensure_collection(settings.embedding.vector_dim, recreate=recreate)
    store.ensure_payload_indexes(PAYLOAD_INDEXES)

    stats = VectorizeStats()
    stats.deleted = _process_deletions(conn, store)

    docs = repository.get_docs_to_vectorize(conn)
    logger.info("待向量化 %d 篇", len(docs))
    for doc in docs:
        try:
            result, n = _vectorize_doc(conn, doc, workspace, embedder, store, settings)
        except Exception as e:  # noqa: BLE001 - 单篇失败隔离
            logger.error("[%s] vectorize failed: %s", doc.get("doc_id"), e)
            stats.failed += 1
            stats.failures.append({"doc_id": doc.get("doc_id"), "error": str(e)})
            continue
        if result == "ok":
            stats.vectorized += 1
            stats.chunks += n
        elif result == "skipped":
            stats.skipped += 1
        else:
            stats.failed += 1
    return stats
