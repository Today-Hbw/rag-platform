"""MySQL 数据访问层（rag_doc_meta / rag_resource / rag_chunk_record）。

收敛原 download/clean_md/vectorize 三处各写一份的 SQL；表名集中为模块常量。
按 D2=A 使用通用列名（source/namespace/collection_id/collection_slug/doc_key/source_version）。

约定：所有函数第一参数为 pymysql 连接（DictCursor）；写操作自行 commit。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = [
    "TABLE_DOC_META",
    "TABLE_RESOURCE",
    "TABLE_CHUNK",
    "TABLE_ROLE_PERM",
    "get_role_resource_ids",
    "get_doc_meta",
    "get_scope_versions",
    "upsert_doc_meta",
    "mark_docs_deleted",
    "get_docs_to_clean",
    "get_docs_to_vectorize",
    "get_docs_to_delete",
    "update_clean_status",
    "update_vec_status",
    "update_vec_error",
    "mark_doc_fully_deleted",
    "save_resources",
    "get_resources",
    "get_attachments_by_doc_ids",
    "delete_resources_for_docs",
    "build_manifest",
    "get_chunk_point_ids",
    "replace_chunk_records",
]

TABLE_DOC_META = "rag_doc_meta"
TABLE_RESOURCE = "rag_resource"
TABLE_CHUNK = "rag_chunk_record"
TABLE_ROLE_PERM = "system_role_permission"


# ==================== 权限（RBAC） ====================

def get_role_resource_ids(
    conn, role_ids: list, resource_table: str = TABLE_DOC_META
) -> list[str]:
    """查这批角色被授权的 resource_id（``book:<collection_id>`` / ``doc:<doc_id>`` / ``*``）。

    role_id 非 int 的忽略。空角色返回 []（由上层判为无权限）。仅取 view 及以上，
    这里不区分权限级别（检索只关心"能否看到"）。
    """
    ids = []
    for r in role_ids:
        try:
            ids.append(int(r))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    placeholders = ",".join(["%s"] * len(ids))
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT resource_id FROM {TABLE_ROLE_PERM}
            WHERE resource_table = %s AND role_id IN ({placeholders})
            """,
            (resource_table, *ids),
        )
        return [row["resource_id"] for row in cursor.fetchall()]


# ==================== doc_meta ====================

def get_doc_meta(conn, doc_id) -> dict | None:
    """按 doc_id 取增量判断所需字段。"""
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT source_version, md_hash, file_hash FROM {TABLE_DOC_META} WHERE doc_id = %s",
            (doc_id,),
        )
        return cursor.fetchone()


def get_scope_versions(conn, source: str, collection_id) -> dict[int, str]:
    """取某 scope 下未删文档的 ``{doc_id: source_version}``，供 detect_changes 增量判断。"""
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT doc_id, source_version FROM {TABLE_DOC_META}
            WHERE source = %s AND collection_id = %s AND status != 'deleted'
            """,
            (source, str(collection_id)),
        )
        return {int(row["doc_id"]): (row.get("source_version") or "") for row in cursor.fetchall()}


def upsert_doc_meta(conn, record: dict[str, Any]) -> None:
    """插入或更新文档元数据。record 需含通用列键。"""
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {TABLE_DOC_META}
                (doc_id, source, namespace, collection_id, collection_slug, doc_key,
                 doc_title, source_url, source_file, source_version, source_dims,
                 md_hash, file_hash, chunk_count, image_count, attachment_count,
                 status, download_time)
            VALUES
                (%(doc_id)s, %(source)s, %(namespace)s, %(collection_id)s,
                 %(collection_slug)s, %(doc_key)s,
                 %(doc_title)s, %(source_url)s, %(source_file)s,
                 %(source_version)s, %(source_dims)s,
                 %(md_hash)s, %(file_hash)s, %(chunk_count)s, %(image_count)s,
                 %(attachment_count)s, %(status)s, %(download_time)s)
            ON DUPLICATE KEY UPDATE
                source_version = VALUES(source_version),
                md_hash = VALUES(md_hash),
                source_file = VALUES(source_file),
                doc_title = VALUES(doc_title),
                doc_key = VALUES(doc_key),
                source_url = VALUES(source_url),
                source_dims = VALUES(source_dims),
                image_count = VALUES(image_count),
                attachment_count = VALUES(attachment_count),
                download_time = VALUES(download_time),
                status = VALUES(status)
            """,
            record,
        )
    conn.commit()


def mark_docs_deleted(conn, doc_ids: list) -> None:
    """软删除：doc_meta + chunk_record 标 status='deleted'，并清 resource 记录。

    向量的物理清理留给 vectorize（读 :func:`get_docs_to_delete` → 删 Qdrant point →
    :func:`mark_doc_fully_deleted`）。移植自旧 download_book 的删除差集处理。
    """
    if not doc_ids:
        return
    ids = tuple(int(d) for d in doc_ids)
    placeholders = ",".join(["%s"] * len(ids))
    with conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE {TABLE_DOC_META} SET status = 'deleted' WHERE doc_id IN ({placeholders})",
            ids,
        )
        cursor.execute(
            f"UPDATE {TABLE_CHUNK} SET status = 'deleted' WHERE doc_id IN ({placeholders})",
            ids,
        )
    delete_resources_for_docs(conn, list(ids))
    conn.commit()


def get_docs_to_clean(conn) -> list[dict]:
    """status='downloaded' 待清洗文档。"""
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT doc_id, source, namespace, collection_id, source_file
            FROM {TABLE_DOC_META}
            WHERE status = 'downloaded'
            """
        )
        return list(cursor.fetchall())


def get_docs_to_vectorize(conn) -> list[dict]:
    """status='cleaned' 待向量化文档；带出 source_url（消除 vectorize 重建模板）。"""
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT doc_id, source, namespace, collection_id, collection_slug, doc_key,
                   doc_title, source_url, source_file
            FROM {TABLE_DOC_META}
            WHERE status = 'cleaned'
            """
        )
        return list(cursor.fetchall())


def get_docs_to_delete(conn) -> list[str]:
    """status='deleted' 待清理 Qdrant 的 doc_id（字符串）。"""
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT doc_id FROM {TABLE_DOC_META} WHERE status = 'deleted'")
        return [str(row["doc_id"]) for row in cursor.fetchall()]


def update_clean_status(conn, doc_id, md_hash, md_clean_path) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {TABLE_DOC_META}
            SET status = 'cleaned', md_hash = %s, clean_time = %s, source_file = %s
            WHERE doc_id = %s
            """,
            (md_hash, datetime.now(), md_clean_path, doc_id),
        )
    conn.commit()


def update_vec_status(conn, doc_id, file_hash, chunk_count) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {TABLE_DOC_META}
            SET status = 'imported', file_hash = %s, chunk_count = %s, last_vec_time = %s,
                error_message = NULL
            WHERE doc_id = %s
            """,
            (file_hash, chunk_count, datetime.now(), doc_id),
        )
    conn.commit()


def update_vec_error(conn, doc_id, status, error_message) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE {TABLE_DOC_META} SET status = %s, error_message = %s WHERE doc_id = %s",
            (status, error_message, doc_id),
        )
    conn.commit()


def mark_doc_fully_deleted(conn, doc_id) -> None:
    """硬删除该 doc 的 chunk_record + resource + doc_meta 三表行。"""
    with conn.cursor() as cursor:
        cursor.execute(f"DELETE FROM {TABLE_CHUNK} WHERE doc_id = %s", (doc_id,))
        cursor.execute(f"DELETE FROM {TABLE_RESOURCE} WHERE doc_id = %s", (doc_id,))
        cursor.execute(f"DELETE FROM {TABLE_DOC_META} WHERE doc_id = %s", (doc_id,))
    conn.commit()


# ==================== resource ====================

def save_resources(conn, doc_id, resource_type: str, resources: list[dict]) -> None:
    """全量替换某 doc 的 image/attachment 资源记录。"""
    with conn.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {TABLE_RESOURCE} WHERE doc_id = %s AND resource_type = %s",
            (doc_id, resource_type),
        )
        for res in resources:
            cursor.execute(
                f"""
                INSERT INTO {TABLE_RESOURCE}
                    (doc_id, resource_type, res_index, filename, file_type, url,
                     local_file, served_url, size_bytes, extracted_text, text_chars,
                     status, error_message)
                VALUES
                    (%(doc_id)s, %(resource_type)s, %(res_index)s, %(filename)s, %(file_type)s,
                     %(url)s, %(local_file)s, %(served_url)s, %(size_bytes)s,
                     %(extracted_text)s, %(text_chars)s, %(status)s, %(error_message)s)
                """,
                {
                    "doc_id": doc_id,
                    "resource_type": resource_type,
                    "res_index": res.get("index", 0),
                    "filename": res.get("filename", ""),
                    "file_type": res.get("file_type") or res.get("mime", ""),
                    "url": res.get("url", ""),
                    "local_file": res.get("local_path") or res.get("local_file", ""),
                    "served_url": res.get("served_url", ""),
                    "size_bytes": res.get("size_bytes", 0),
                    "extracted_text": res.get("extracted_text", ""),
                    "text_chars": res.get("text_chars", 0),
                    "status": res.get("status", "ok"),
                    "error_message": res.get("error"),
                },
            )
    conn.commit()


def get_resources(conn, doc_id, resource_type: str | None = None) -> list[dict]:
    """取某 doc 的资源记录，可按类型过滤。"""
    with conn.cursor() as cursor:
        if resource_type:
            cursor.execute(
                f"SELECT * FROM {TABLE_RESOURCE} WHERE doc_id = %s AND resource_type = %s "
                f"ORDER BY res_index",
                (doc_id, resource_type),
            )
        else:
            cursor.execute(
                f"SELECT * FROM {TABLE_RESOURCE} WHERE doc_id = %s "
                f"ORDER BY resource_type, res_index",
                (doc_id,),
            )
        return list(cursor.fetchall())


def get_attachments_by_doc_ids(conn, doc_ids: list) -> dict[int, list[dict]]:
    """批量查多篇文档的 ok 附件，返回 ``{doc_id: [att_info]}``（检索结果富化用）。

    served_url 优先用 DB 值，缺失则由 local_file 拼 ``/assets/<rel>``（data_root 即服务根）。
    """
    if not doc_ids:
        return {}
    ids = tuple(int(d) for d in doc_ids)
    placeholders = ",".join(["%s"] * len(ids))
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT doc_id, filename, file_type, local_file, served_url, text_chars
            FROM {TABLE_RESOURCE}
            WHERE doc_id IN ({placeholders}) AND resource_type = 'attachment' AND status = 'ok'
            ORDER BY res_index
            """,
            ids,
        )
        rows = cursor.fetchall()
    result: dict[int, list[dict]] = {}
    for row in rows:
        local_file = row.get("local_file", "") or ""
        served_url = row.get("served_url", "") or ""
        if not served_url and local_file:
            served_url = "/assets/" + local_file.replace("\\", "/").lstrip("/")
        result.setdefault(int(row["doc_id"]), []).append(
            {
                "filename": row.get("filename", ""),
                "file_type": row.get("file_type", ""),
                "local_path": local_file,
                "served_url": served_url,
                "text_chars": row.get("text_chars", 0),
            }
        )
    return result


def delete_resources_for_docs(conn, doc_ids: list) -> None:
    if not doc_ids:
        return
    with conn.cursor() as cursor:
        placeholders = ",".join(["%s"] * len(doc_ids))
        cursor.execute(
            f"DELETE FROM {TABLE_RESOURCE} WHERE doc_id IN ({placeholders})",
            tuple(int(d) for d in doc_ids),
        )
    conn.commit()


def build_manifest(conn, doc_id) -> dict[str, list[dict]]:
    """从 resource 表组装 {images, attachments}（取代已废弃的 manifest.json）。"""
    images = [
        {
            "url": row.get("url", ""),
            "index": row.get("res_index", 0),
            "local_path": row.get("local_file", ""),
            "mime": row.get("file_type", ""),
            "size_bytes": row.get("size_bytes", 0),
            "status": row.get("status", "ok"),
        }
        for row in get_resources(conn, doc_id, "image")
    ]
    attachments = [
        {
            "url": row.get("url", ""),
            "index": row.get("res_index", 0),
            "filename": row.get("filename", ""),
            "file_type": row.get("file_type", ""),
            "local_file": row.get("local_file", ""),
            "served_url": row.get("served_url", ""),
            "extracted_text": row.get("extracted_text", ""),
            "text_chars": row.get("text_chars", 0),
            "status": row.get("status", "ok"),
            "error": row.get("error_message"),
        }
        for row in get_resources(conn, doc_id, "attachment")
    ]
    return {"images": images, "attachments": attachments}


# ==================== chunk_record ====================

def get_chunk_point_ids(conn, doc_id) -> list[str]:
    """取某 doc 的 active point_id（删旧点用）。"""
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT point_id FROM {TABLE_CHUNK} WHERE doc_id = %s AND status = 'active'",
            (doc_id,),
        )
        return [row["point_id"] for row in cursor.fetchall()]


def replace_chunk_records(conn, doc_id, chunks_data: list[tuple]) -> None:
    """全删重插 chunk_record。chunks_data: [(chunk_index, point_id, chunk_hash), ...]。"""
    with conn.cursor() as cursor:
        cursor.execute(f"DELETE FROM {TABLE_CHUNK} WHERE doc_id = %s", (doc_id,))
        for chunk_index, point_id, chunk_hash in chunks_data:
            cursor.execute(
                f"""
                INSERT INTO {TABLE_CHUNK} (doc_id, chunk_index, point_id, chunk_hash, status)
                VALUES (%s, %s, %s, %s, 'active')
                """,
                (doc_id, chunk_index, point_id, chunk_hash),
            )
    conn.commit()
