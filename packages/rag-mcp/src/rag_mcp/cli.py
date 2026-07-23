"""rag-mcp CLI。两种用法：

- ``rag-mcp -s <server_url> [--timeout N] [--token T] [--service-token S] [-v]``
  启动 MCP stdio server，把远程 rag-search 封装为工具供 LLM 调用。
- ``rag-mcp login --login-url <url> [--phone ...] [--code ...] [-s <server_url>]``
  **带外登录**：手机号 + 验证码换 token，存本地文件；serve 时自动加载并逐请求透传。
  登录不经模型（REFACTOR_PLAN §5.2 铁律 3）。

token 解析优先级（serve）：``--token`` > ``RAG_MCP_TOKEN`` 环境变量 > 本地 token 文件。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys

from rag_mcp import token_store
from rag_mcp.server import DEFAULT_TIMEOUT, RemoteSearchClient, create_mcp_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rag-mcp")


async def _run(
    server_url: str,
    timeout: int,
    *,
    token: str | None = None,
    service_token: str | None = None,
) -> None:
    from mcp.server.stdio import stdio_server

    logger.info("启动 rag-mcp，远程服务: %s（token: %s）", server_url, "有" if token else "无")
    client = RemoteSearchClient(
        server_url, timeout=timeout, token=token, service_token=service_token
    )
    app = create_mcp_server(client)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rag-mcp", description="rag-platform 检索服务的 MCP 客户端"
    )
    parser.add_argument("-s", "--server", required=True, help="远程服务地址，如 http://host:8090")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时秒数")
    parser.add_argument("--token", default=None, help="用户 token（覆盖环境变量/本地文件）")
    parser.add_argument(
        "--service-token", default=None, help="服务令牌（默认读 RAG_MCP_SERVICE_TOKEN）"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    return parser.parse_args(argv)


def _parse_login_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rag-mcp login", description="带外登录换取用户 token（不经模型）"
    )
    parser.add_argument(
        "--login-url", default=os.environ.get(token_store.ENV_LOGIN_URL),
        help="业务登录接口 URL（默认读 RAG_MCP_LOGIN_URL）",
    )
    parser.add_argument("--phone", default=None, help="手机号")
    parser.add_argument("--code", default=None, help="验证码")
    parser.add_argument("-s", "--server", default=None, help="远程服务地址（随 token 一并存）")
    parser.add_argument("--timeout", type=float, default=10.0, help="登录请求超时秒数")
    return parser.parse_args(argv)


def _login_main(argv: list[str] | None) -> int:
    args = _parse_login_args(argv)
    if not args.login_url:
        logger.error("缺少 --login-url（或设置 RAG_MCP_LOGIN_URL）")
        return 2
    phone = args.phone or input("手机号: ").strip()
    # 验证码走 getpass 避免回显/落入 shell 历史
    code = args.code or getpass.getpass("验证码: ").strip()
    if not phone or not code:
        logger.error("手机号与验证码均不能为空")
        return 2
    try:
        data = token_store.login(args.login_url, phone, code, timeout=args.timeout)
    except Exception as e:  # noqa: BLE001
        logger.error("登录失败: %s", e)
        return 1
    token = data.get("token")
    if not token:
        logger.error("登录响应缺少 token 字段")
        return 1
    path = token_store.save_token(token, base_url=args.server)
    logger.info("登录成功，token 已保存至 %s", path)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "login":
        return _login_main(argv[1:])

    args = _parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    token = args.token or token_store.load_token()
    service_token = args.service_token or os.environ.get(token_store.ENV_SERVICE_TOKEN)
    try:
        asyncio.run(
            _run(args.server, args.timeout, token=token, service_token=service_token)
        )
    except KeyboardInterrupt:
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error("启动失败: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
