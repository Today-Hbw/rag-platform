-- 旧 qdrant_yuque_kb_* → 新 rag_* 数据迁移（决策 D2=A / D3=改表名）。
--
-- ⚠️⚠️ 草案，须在你的 MySQL 上人工审阅 + 全库备份后执行。此处无法测试。 ⚠️⚠️
-- 前提：已执行 0001_init.sql 建好空的 rag_* 表。
-- 策略：非破坏——先灌入新表，核对行数/抽样无误后，再手动 DROP 旧表。
--
-- 注意 D5：旧 `team_code` 列实际存的是 book_slug（历史 bug），此处**照搬进 namespace 不修正**，
--        以维持数据连续性；新代码与权限一律不依赖 namespace，只用 collection_id/doc_id。
-- 注意 source_version：由旧 content_updated_at 归一化为 ISO 字符串；需与 yuque connector
--        （阶段 4）产出的变更令牌格式一致，否则首轮增量会全部判为“已变更”而重跑（安全但耗时）。

START TRANSACTION;

INSERT INTO rag_doc_meta
    (doc_id, source, namespace, collection_id, collection_slug, doc_key,
     doc_title, source_url, source_file, source_version,
     md_hash, file_hash, chunk_count, image_count, attachment_count,
     status, error_message, download_time, clean_time, last_vec_time, created_at, updated_at)
SELECT
    doc_id, 'yuque', team_code, book_id, book_slug, doc_slug,
    doc_title, source_url, source_file,
    DATE_FORMAT(content_updated_at, '%Y-%m-%dT%H:%i:%sZ'),
    md_hash, file_hash, chunk_count, image_count, attachment_count,
    status, error_message, download_time, clean_time, last_vec_time, created_at, updated_at
FROM qdrant_yuque_kb_doc_meta;

INSERT INTO rag_resource
    (id, doc_id, resource_type, res_index, filename, file_type, url, local_file,
     served_url, size_bytes, extracted_text, text_chars, status, error_message, created_at)
SELECT
    id, doc_id, resource_type, res_index, filename, file_type, url, local_file,
    served_url, size_bytes, extracted_text, text_chars, status, error_message, created_at
FROM qdrant_yuque_kb_resource;

INSERT INTO rag_chunk_record
    (id, doc_id, chunk_index, point_id, chunk_hash, status, created_at)
SELECT
    id, doc_id, chunk_index, point_id, chunk_hash, status, created_at
FROM qdrant_yuque_kb_chunk_record;

UPDATE system_role_permission
   SET resource_table = 'rag_doc_meta'
 WHERE resource_table = 'qdrant_yuque_kb_doc_meta';

-- 核对：下面两组应一致，确认后再 COMMIT。
-- SELECT (SELECT COUNT(*) FROM qdrant_yuque_kb_doc_meta) AS old_meta, (SELECT COUNT(*) FROM rag_doc_meta) AS new_meta;

COMMIT;

-- 验证无误后再执行（不可逆）：
-- DROP TABLE qdrant_yuque_kb_chunk_record, qdrant_yuque_kb_resource, qdrant_yuque_kb_doc_meta;
