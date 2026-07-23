# rag-core

共享底座库，入库端（pipeline）与查询端（search）都依赖它，以保证 embedding 模型 / 向量维度 / payload 字段的**单一契约**。不独立部署。

| 模块 | 职责 |
|------|------|
| `settings.py` | pydantic-settings 单一配置源（`RAG_` 前缀 + `SecretStr`） |
| `db.py` / `repository.py` | MySQL 连接 + `rag_doc_meta/rag_resource/rag_chunk_record` CRUD（表名集中常量）+ RBAC 数据层（`get_role_resource_ids` / `get_public_collection_ids`） |
| `contracts.py` | `DocFacets` / `ChunkPayload` 共享契约（消除三处 payload 漂移） |
| `embedding.py` / `vectorstore.py` | 豆包多模态 embedding client + Qdrant 封装（`search` 预留 `query_filter` 供 RBAC） |
| `cleaning.py` / `chunking.py` / `placeholders.py` | 纯清洗 + 段落分块 + 占位符协议 |
| `media.py` / `download_util.py` / `extract/` | mime/base64、资源下载、附件文本提取（pdf/office/ocr，重依赖走 optional extras） |
| `hashing.py` / `logging.py` | md5 增量判断 / 日志装配 |

重依赖按需装：`pip install rag-core[pdf,office,ocr]`；`[win]` 仅 Windows 装 pywin32（Linux 下 `.doc` 走 antiword/LibreOffice 兜底）。
