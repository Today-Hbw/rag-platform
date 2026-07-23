"""MCP server：把远程 rag-search 服务封装成 MCP 工具。零 rag-core 依赖。

迁自旧 mcp_search/cli.py，迁移时修复：
- ``timeout`` 透传到 RemoteSearchClient（旧版是死参数，从未生效）；
- 命名去语雀化（工具名 search_knowledge_base / check_service_health，源无关）；
- 端点默认 ``/search`` ``/health``（对齐 rag-search app），可配以适配网关前缀。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool

logger = logging.getLogger("rag-mcp")

__all__ = ["RemoteSearchClient", "format_results", "create_mcp_server"]

DEFAULT_TIMEOUT = 30


class RemoteSearchClient:
    """远程检索服务 HTTP 客户端。

    ``token``（带外登录得到的用户 token）经 ``Authorization: Bearer`` 逐请求透传给
    rag-search，供其做 introspection/RBAC——**它由客户端持有，不是 MCP 工具参数，
    模型看不到**（REFACTOR_PLAN §5.2 铁律 3）。``service_token`` 经 ``X-Service-Token``
    透传，证明调用方是可信客户端（rag-search 侧可选校验）。
    """

    def __init__(
        self,
        base_url: str,
        timeout: int = DEFAULT_TIMEOUT,
        *,
        search_path: str = "/search",
        health_path: str = "/health",
        token: str | None = None,
        service_token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.search_path = search_path
        self.health_path = health_path
        self.token = token
        self.service_token = service_token

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.service_token:
            headers["X-Service-Token"] = self.service_token
        return headers

    async def search(self, query: str, top_k: int = 10) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}{self.search_path}",
                json={"query": query, "top_k": top_k},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}{self.health_path}")
                return resp.status_code == 200
        except Exception:  # noqa: BLE001 - 健康检查失败即视为不健康
            return False


def format_results(result: dict[str, Any], query: str, top_k: int) -> str:
    """把检索响应格式化为 markdown（纯函数，便于单测）。"""
    total = result.get("total_results", 0)
    elapsed = result.get("elapsed_ms", 0)
    lines = [
        f"## 搜索结果：'{query}'",
        f"**找到 {total} 条结果**（显示前 {min(top_k, total)} 条）",
        f"**耗时:** {elapsed} 毫秒\n",
    ]
    for i, item in enumerate(result.get("results", [])):
        lines += [
            f"### 结果 {i + 1}",
            f"**标题:** {item.get('doc_title', 'N/A')}",
            f"**混合评分:** {item.get('hybrid_score', 0):.4f} "
            f"(向量: {item.get('vector_score', 0):.4f}, BM25: {item.get('bm25_score', 0):.4f})",
            f"**原文链接:** {item.get('source_url', 'N/A')}",
            "**内容:**",
            item.get("chunk_text", "")[:500],
            "...\n",
        ]
    return "\n".join(lines)


def create_mcp_server(client: RemoteSearchClient) -> Server:
    """构造 MCP server，暴露 search_knowledge_base / check_service_health 两个工具。"""
    app: Server = Server("rag-knowledge-base")

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_knowledge_base",
                description="搜索知识库：向量相似度 + BM25 关键词 + 标题增强的混合检索。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询字符串"},
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量，默认 10，范围 1-50",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="check_service_health",
                description="检查知识库检索服务的健康状态",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search_knowledge_base":
            return await _handle_search(client, arguments)
        if name == "check_service_health":
            return await _handle_health(client)
        return [TextContent(type="text", text=f"未知工具: {name}")]

    return app


async def _handle_search(client: RemoteSearchClient, arguments: dict) -> list[TextContent]:
    query = (arguments.get("query") or "").strip()
    if not query:
        return [TextContent(type="text", text="错误：搜索查询不能为空")]
    top_k = max(1, min(50, arguments.get("top_k", 10)))
    try:
        logger.info("搜索请求: %s, top_k: %s", query, top_k)
        result = await client.search(query, top_k)
        return [TextContent(type="text", text=format_results(result, query, top_k))]
    except httpx.HTTPStatusError as e:
        return [TextContent(
            type="text",
            text=f"错误：远程服务器返回 HTTP {e.response.status_code}\n{e.response.text}",
        )]
    except httpx.ConnectError:
        return [TextContent(
            type="text",
            text=f"错误：无法连接到远程服务器 {client.base_url}。请检查地址/网络/防火墙。",
        )]
    except Exception as e:  # noqa: BLE001
        logger.exception("搜索失败")
        return [TextContent(type="text", text=f"错误：{e}")]


async def _handle_health(client: RemoteSearchClient) -> list[TextContent]:
    ok = await client.health()
    mark = "✅ 服务正常" if ok else "❌ 服务异常"
    return [TextContent(type="text", text=f"{mark}\n服务器地址: {client.base_url}")]
