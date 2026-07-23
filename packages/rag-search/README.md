# rag-search

在线检索服务（在线面），独立部署。FastAPI + 向量/BM25/标题 RRF 混合检索 + Redis 缓存 + RBAC 过滤。

```bash
rag-search serve [--host 0.0.0.0] [--port 8090]
```

端点：`POST /search`、`POST /image`、`POST /multimodal`、`GET /health`。

| 模块 | 职责 |
|------|------|
| `app.py` | FastAPI 端点 + 依赖注入（embedder/store/cache/db）+ 查询日志 + RBAC 接线 |
| `retrieve.py` | 纯排序 `retrieve()`（剥离 FastAPI/Redis/log，供 eval 直接 import） |
| `cache.py` | Redis 缓存（随机 TTL 防雪崩，cache key 叠 `scope_sig` 防串权限） |
| `auth.py` | RBAC：`resolve_identity`（introspection，token→role_ids）→ `resolve_scope`（role_ids→collection/doc ∪ 公共库）→ `build_query_filter`（Qdrant filter） |

RBAC 默认关（`RAG_RBAC__ENABLED=false` = 旧行为）。两跳解析、introspection 契约、开关说明见[顶层 README](../../README.md#权限过滤rbacp1)。

- **用户 token** → `Authorization: Bearer`（供 introspection）
- **服务令牌** → `X-Service-Token`（挡内网直连，可选）
- **离线/调试** → `INTROSPECT_URL` 留空时直接信 `X-Role-Ids` 头
