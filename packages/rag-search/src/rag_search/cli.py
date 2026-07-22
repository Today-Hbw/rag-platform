"""rag-search CLI：``rag-search serve [--host H] [--port P]`` 启动检索服务。"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag-search")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="启动 FastAPI 检索服务")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8090)
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from rag_search.app import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
