-- rag_collection：知识库自身属性表（RBAC 阶段5 增量②）。
-- 与 system_role_permission（角色→资源策略）职责分离：这里只描述"库是什么"，
-- 其中 is_public=1 的库人人可见（无 token 也能看），RAG 无条件并入可见集。

CREATE TABLE IF NOT EXISTS rag_collection (
    collection_id   VARCHAR(64)  NOT NULL PRIMARY KEY COMMENT '知识库ID（对齐 rag_doc_meta.collection_id）',
    source          VARCHAR(32)  NOT NULL DEFAULT 'yuque' COMMENT '数据源标识',
    name            VARCHAR(256) DEFAULT NULL COMMENT '库显示名',
    is_public       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=公共库，人人可见',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_public (is_public),
    INDEX idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库属性（含公共库标记）';
