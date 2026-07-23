# rag-mcp

MCP 客户端，把远程 rag-search 封装成 MCP 工具供 LLM 调用。**零 rag-core 依赖**（保持独立可发布），仅 stdlib + httpx + mcp。

```bash
rag-mcp login --login-url <业务登录接口>   # 带外换 token，存本地文件（不经模型）
rag-mcp -s http://<search-host>:8090        # 启动 MCP stdio server
```

暴露两个工具：`search_knowledge_base`（混合检索）、`check_service_health`。

| 模块 | 职责 |
|------|------|
| `server.py` | `RemoteSearchClient`（HTTP 调 rag-search，逐请求透传 token）+ MCP server 装配 + 结果 markdown 格式化 |
| `cli.py` | `serve`（默认）与 `login` 子命令 |
| `token_store.py` | 带外 token：`login`（手机号+验证码→token）+ 本地文件存取（`0600`）+ env |

## 身份与 token

身份走**传输层可信 token**，**绝不做成 MCP 工具参数**（模型看不到）：

- `rag-mcp login` 带外换 token（验证码用 `getpass` 收，不回显）→ 存本地文件。
- serve 时 token 解析优先级：`--token` > `RAG_MCP_TOKEN` > 本地文件；经 `Authorization: Bearer` 逐请求透传给 rag-search 做 introspection/RBAC。
- 服务令牌 `RAG_MCP_SERVICE_TOKEN` → `X-Service-Token`。

环境变量：`RAG_MCP_TOKEN` / `RAG_MCP_TOKEN_FILE` / `RAG_MCP_LOGIN_URL` / `RAG_MCP_SERVICE_TOKEN`。
