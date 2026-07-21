"""rag-mcp CLI 入口（骨架）。

迁移 mcp_search/cli.py 后落地：`rag-mcp -s <server_url> [--token ...]`。
注意迁移时修复：--timeout 死参数、命名三重不一致、README 内部域名。
"""

import sys


def main() -> int:
    print("rag-mcp: CLI 尚未实现（见 REFACTOR_PLAN.md 阶段 5 / mcp 迁移）。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
