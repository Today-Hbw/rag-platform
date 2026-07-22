"""rag-mcp CLI：``rag-mcp -s <server_url> [--timeout N] [-v]`` 启动 MCP stdio server。

把远程 rag-search 服务封装为 MCP 工具供 LLM 调用。timeout 已透传（修复旧死参数）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from rag_mcp.server import DEFAULT_TIMEOUT, RemoteSearchClient, create_mcp_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rag-mcp")


async def _run(server_url: str, timeout: int) -> None:
    from mcp.server.stdio import stdio_server

    logger.info("启动 rag-mcp，远程服务: %s", server_url)
    app = create_mcp_server(RemoteSearchClient(server_url, timeout=timeout))
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rag-mcp", description="rag-platform 检索服务的 MCP 客户端"
    )
    parser.add_argument("-s", "--server", required=True, help="远程服务地址，如 http://host:8090")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时秒数")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        asyncio.run(_run(args.server, args.timeout))
    except KeyboardInterrupt:
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error("启动失败: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
