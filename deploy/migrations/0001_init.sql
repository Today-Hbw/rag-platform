-- rag-platform 初始 schema（通用多源版，决策 D2=A / D3=改表名）。
-- 全新安装执行本文件；从旧 qdrant_yuque_kb_* 迁移见 0002_migrate_from_legacy.sql。

-- ============================================
-- 文档元数据
-- ============================================
CREATE TABLE IF NOT EXISTS rag_doc_meta (
    doc_id              BIGINT       NOT NULL PRIMARY KEY COMMENT '来源原生文档ID',
    source              VARCHAR(32)  NOT NULL DEFAULT 'yuque' COMMENT '数据源标识',
    namespace           VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '团队/空间/租户（原 team_code）',
    collection_id       VARCHAR(64)  NOT NULL COMMENT '知识库/空间/库（原 book_id；RBAC 过滤锚点）',
    collection_slug     VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '库别名（原 book_slug）',
    doc_key             VARCHAR(256) DEFAULT NULL COMMENT '来源内文档别名（原 doc_slug）',
    doc_title           VARCHAR(512) DEFAULT NULL COMMENT '文档标题',
    source_url          VARCHAR(1024) DEFAULT NULL COMMENT '原文链接（由 connector 产出）',
    source_file         VARCHAR(1024) DEFAULT NULL COMMENT '本地文件相对 data_root 路径',
    source_version      VARCHAR(64)  DEFAULT NULL COMMENT '变更令牌（语雀=content_updated_at 归一化）',
    source_dims         JSON         DEFAULT NULL COMMENT '来源特有维度',
    md_hash             CHAR(32)     DEFAULT NULL COMMENT 'md 文件 MD5（清洗增量判断）',
    file_hash           CHAR(32)     DEFAULT NULL COMMENT 'md_clean MD5（向量化增量判断）',
    chunk_count         INT          DEFAULT 0 COMMENT '向量分块数',
    image_count         INT          DEFAULT 0 COMMENT '图片数',
    attachment_count    INT          DEFAULT 0 COMMENT '附件数',
    status              VARCHAR(16)  DEFAULT 'new' COMMENT 'downloaded/cleaned/imported/vec_skipped/vec_failed/deleted',
    error_message       VARCHAR(512) DEFAULT NULL,
    download_time       DATETIME     DEFAULT NULL,
    clean_time          DATETIME     DEFAULT NULL,
    last_vec_time       DATETIME     DEFAULT NULL,
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_source (source),
    INDEX idx_namespace (namespace),
    INDEX idx_collection (source, collection_id),
    INDEX idx_collection_slug (collection_slug),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档元数据（多源通用）';

-- ============================================
-- 文档资源（图片 + 附件）
-- ============================================
CREATE TABLE IF NOT EXISTS rag_resource (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    doc_id          BIGINT       NOT NULL COMMENT '关联 rag_doc_meta.doc_id',
    resource_type   VARCHAR(16)  NOT NULL DEFAULT 'attachment' COMMENT 'image/attachment',
    res_index       INT          NOT NULL COMMENT '资源序号',
    filename        VARCHAR(512) DEFAULT NULL,
    file_type       VARCHAR(16)  DEFAULT NULL COMMENT '扩展名（附件）或 MIME（图片）',
    url             VARCHAR(1024) DEFAULT NULL COMMENT '原始 URL',
    local_file      VARCHAR(1024) DEFAULT NULL COMMENT '本地文件相对路径',
    served_url      VARCHAR(1024) DEFAULT NULL COMMENT '服务路径（图片）',
    size_bytes      INT          DEFAULT 0,
    extracted_text  VARCHAR(1024) DEFAULT NULL COMMENT '提取文本文件路径（附件）',
    text_chars      INT          DEFAULT 0,
    status          VARCHAR(16)  DEFAULT 'ok' COMMENT 'ok/failed',
    error_message   VARCHAR(512) DEFAULT NULL,
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_doc_res (doc_id, resource_type, res_index),
    INDEX idx_doc (doc_id),
    INDEX idx_doc_type (doc_id, resource_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档资源（图片+附件）';

-- ============================================
-- 向量分块记录（Qdrant point 映射）
-- ============================================
CREATE TABLE IF NOT EXISTS rag_chunk_record (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    doc_id        BIGINT      NOT NULL COMMENT '关联 rag_doc_meta.doc_id',
    chunk_index   INT         NOT NULL,
    point_id      VARCHAR(64) NOT NULL COMMENT 'Qdrant point UUID',
    chunk_hash    CHAR(32)    NOT NULL COMMENT 'chunk 内容 MD5',
    status        VARCHAR(16) DEFAULT 'active' COMMENT 'active/deleted',
    created_at    DATETIME    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_doc_chunk (doc_id, chunk_index),
    INDEX idx_point (point_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='向量分块记录';

-- ============================================
-- 角色资源权限（RBAC，D7：resource_id = book:<collection_id> / doc:<doc_id>）
-- ============================================
CREATE TABLE IF NOT EXISTS system_role_permission (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    role_id         BIGINT NOT NULL COMMENT '角色ID',
    resource_table  VARCHAR(64) NOT NULL DEFAULT 'rag_doc_meta' COMMENT '资源表名',
    resource_id     VARCHAR(64) NOT NULL COMMENT 'book:<collection_id> / doc:<doc_id> / *',
    permission      VARCHAR(16) DEFAULT 'view' COMMENT 'view/edit/admin',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_role_resource (role_id, resource_table, resource_id),
    INDEX idx_role (role_id),
    INDEX idx_resource (resource_table, resource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='角色资源权限';




-- 业务系统关联表
-- system_user
-- system_user_role
