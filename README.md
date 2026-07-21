# rag-platform

> 企业知识库 RAG 平台：多源接入 → 清洗 → 多模态向量化 → 混合检索（向量 + BM25 + RRF），支持 MCP 与权限过滤。

`rag-platform` 是一个可扩展的企业知识库检索增强（RAG）平台。它把「数据源接入 → 内容清洗 → 多模态向量化入库 → 在线混合检索」拆成边界清晰的模块：数据源通过可插拔的 connector 接入（首个实现为语雀，可扩展 Confluence / Notion / 本地文件等），检索侧提供向量 + BM25 + 标题的 RRF 混合排序、Redis 缓存、基于角色的权限过滤，并以 FastAPI 服务和 MCP 客户端两种方式对外提供能力。

## 架构

采用 monorepo + [uv](https://docs.astral.sh/uv/) workspace，按**部署单元**拆分为 4 个包：

| 包 | 职责 | 独立部署 |
|----|------|:---:|
| [`rag-core`](packages/rag-core) | 共享底座：配置、DB、embedding、向量库、契约、权限 | 否 |
| [`rag-pipeline`](packages/rag-pipeline) | 离线批处理：connector + 下载 / 清洗 / 向量化 | 是（离线面） |
| [`rag-search`](packages/rag-search) | 在线检索服务：FastAPI + 混合检索 + 缓存 | 是（在线面） |
| [`rag-mcp`](packages/rag-mcp) | MCP 客户端（HTTP 调 rag-search，零 core 依赖） | 是 |

`pipeline`（离线）与 `search`（在线）可部署在不同服务器：仓库合一是为共享 embedding client 与向量 payload 契约（入库端与查询端必须一致，否则检索静默失效），部署分离靠分包镜像。

## 状态

🚧 **重构中**。当前处于骨架搭建阶段。connector 抽象、RBAC 权限过滤、检索评估等能力尚未落地。
完整的现状分析、迁移映射、分阶段计划与待决策项见根目录 **[REFACTOR_PLAN.md](../REFACTOR_PLAN.md)**。

## 开发

```bash
uv sync --all-extras --dev    # 安装 workspace 全部依赖
uv run ruff check .           # lint
uv run pytest                 # 测试
```

配置走环境变量（`RAG_` 前缀），见 [`.env.example`](.env.example)。**密钥不入库。**
