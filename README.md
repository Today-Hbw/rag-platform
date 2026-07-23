# rag-platform

> 企业知识库 RAG 平台：多源接入 → 清洗 → 多模态向量化 → 混合检索（向量 + BM25 + RRF），支持 MCP 与基于角色的权限过滤。

`rag-platform` 把「数据源接入 → 内容清洗 → 多模态向量化入库 → 在线混合检索」拆成边界清晰的模块：数据源通过可插拔的 connector 接入（首个实现为语雀，可扩展 Confluence / Notion / 本地文件等），检索侧提供向量 + BM25 + 标题的 RRF 混合排序、Redis 缓存、基于角色的权限过滤（RBAC），并以 FastAPI 服务和 MCP 客户端两种方式对外提供能力。

## 架构

monorepo + [uv](https://docs.astral.sh/uv/) workspace，按**部署单元**拆分为 4 个包：

| 包 | 职责 | 独立部署 |
|----|------|:---:|
| [`rag-core`](packages/rag-core) | 共享底座：配置、DB、embedding、向量库、清洗/分块、契约、RBAC 数据层 | 否 |
| [`rag-pipeline`](packages/rag-pipeline) | 离线批处理：connector + 下载 / 清洗 / 向量化 | 是（离线面） |
| [`rag-search`](packages/rag-search) | 在线检索服务：FastAPI + 混合检索 + 缓存 + RBAC 过滤 | 是（在线面） |
| [`rag-mcp`](packages/rag-mcp) | MCP 客户端（HTTP 调 rag-search，零 core 依赖） | 是 |

`pipeline`（离线）与 `search`（在线）可部署在不同服务器：仓库合一是为共享 embedding client 与向量 payload 契约（入库端与查询端必须一致，否则检索静默失效），部署分离靠分包镜像。

```
数据源 ──connector──▶ rag-pipeline (下载/清洗/向量化) ──▶ MySQL(元数据) + Qdrant(向量)
                                                              │
用户 ──▶ rag-mcp / web 后端 ──▶ rag-search (混合检索 + RBAC 过滤) ─┘
```

## 状态

分阶段重构中，**阶段 0–5 主体已落地**，全量单测绿。完整现状分析、迁移映射、分阶段计划与待决策项见根目录 **[REFACTOR_PLAN.md](../REFACTOR_PLAN.md)**。

| 阶段 | 内容 | 状态 |
|------|------|------|
| 0 | 密钥止血（gitignore / gitleaks / 轮换清单） | ✅（凭据轮换待用户） |
| 1 | monorepo 骨架 + uv workspace + 4 包 | ✅ |
| 2 | 抽 rag-core（settings/db/repository/embedding/vectorstore/cleaning…） | ✅（等价对拍待内网） |
| 4 | connector 多源抽象（yuque + local stub + `rag-pipeline sync`） | ✅（等价对拍待内网） |
| 5 | RBAC 权限过滤（P1 两跳 + introspection + 公共库 + rag-mcp login） | ✅ 代码（灰度待内网） |
| 3 | 测试 + CI（paths-filter + 4 包 matrix + ruff/mypy/coverage + gitleaks） | ✅（CI 待首跑） |
| 6 / 7 | 检索评估 eval / Docker 分包 + 调度 | ⏳ 待做 |

## 快速开始

```bash
uv sync --all-extras --dev          # 安装 workspace 全部依赖
cp .env.example .env                # 填入真实配置（密钥不入库）
```

### 离线：同步数据 → 向量入库（rag-pipeline）

```bash
rag-pipeline sync --source yuque [--scope <库>] [--full] [--date YYYYMMDD] [--dry-run]
rag-pipeline clean                  # downloaded → cleaned
rag-pipeline vectorize [--recreate] # cleaned → imported（--recreate 重建 collection，慎用）
```

`--dry-run` 只报告将抓 / 将删，不写盘不改 DB；新增数据源只需实现一个 connector，下游编排零改动。

### 在线：启动检索服务（rag-search）

```bash
rag-search serve [--host 0.0.0.0] [--port 8090]
```

端点：`POST /search`、`POST /image`、`POST /multimodal`、`GET /health`。

### MCP 客户端（rag-mcp）

```bash
rag-mcp login --login-url <业务登录接口>   # 带外换 token，存本地（不经模型）
rag-mcp -s http://<search-host>:8090        # 启动 MCP stdio server
```

## 权限过滤（RBAC，P1）

默认**全关**（`RAG_RBAC__ENABLED=false` = 旧行为，全量可见）；开启后按角色过滤检索结果。设计详见 [REFACTOR_PLAN.md §5.2](../REFACTOR_PLAN.md)。

**颗粒度**：知识库（collection）级 + 文档（doc）级例外 + 公共库人人可见；超管（`allow_all`）不过滤。

**两跳解析（均带缓存）**：

```
调用方带 Authorization: Bearer <user token>
  ① token → role_ids   : rag-search 调业务 introspection 接口（可配 URL）      [业务侧]
  ② role_ids → 资源     : 查本地 system_role_permission → collection/doc 集     [RAG 侧]
  ③ 可见集 = 资源 ∪ 公共库(rag_collection.is_public)；allow_all → 不过滤
  ④ Qdrant filter: should=[collection_id MatchAny, doc_id MatchAny]
```

**introspection 接口契约**（业务侧按此实现）：

```
POST <RAG_RBAC__INTROSPECT_URL>   头 Authorization: Bearer <token>（+ 可选 X-Service-Token）
→ 200 {"valid": true, "role_ids": [12,34], "allow_all": false}
  无效 token → HTTP 401 或 {"valid": false}
```

- **离线 / 调试模式**：`INTROSPECT_URL` 为空（默认）→ 不调远程，直接信 `X-Role-Ids` 头（逗号分隔）；`RAG_RBAC__DEFAULT_ROLE_IDS` 可给静态默认角色。**生产配 URL，离线留空，切换只改配置。**
- **服务令牌**（可选第二道）：`RAG_RBAC__SERVICE_TOKEN` 常量时间比对，挡内网直连；调用方置于 `X-Service-Token` 头（与用户 token 的 `Authorization` 头分开）。
- **身份铁律**：token 走传输层，**绝不做成 MCP 工具参数**；登录换 token 走带外（`rag-mcp login`，验证码用 `getpass` 收），不经模型。缓存 key 叠加权限签名，杜绝不同权限用户串缓存。

数据表：`system_role_permission`（角色→资源，`resource_id = book:<collection_id> / doc:<doc_id> / *`）、`rag_collection`（库属性，`is_public=1` 人人可见）。schema 见 [`deploy/migrations/`](deploy/migrations)。

## 配置

全部走环境变量（`RAG_` 前缀 + `__` 分隔嵌套，密钥用 `SecretStr`），见 [`.env.example`](.env.example)。**密钥不入库**（`.gitignore` + gitleaks 双保险）。rag-mcp 为独立客户端，用自己的 `RAG_MCP_*` 进程环境变量（不读本 `.env`）。

## 开发

```bash
uv run ruff check .           # lint
uv run pytest                 # 全量单测（离线，:memory: Qdrant / respx / fakeredis / mock MySQL）
```
