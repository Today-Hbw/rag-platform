"""rag-pipeline CLI 入口（骨架）。

阶段 4 落地：`rag-pipeline sync --source yuque [--scope ...] [--stage ...]
[--full] [--date YYYYMMDD] [--dry-run]`。
"""

import sys


def main() -> int:
    print("rag-pipeline: CLI 尚未实现（见 REFACTOR_PLAN.md 阶段 4）。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
