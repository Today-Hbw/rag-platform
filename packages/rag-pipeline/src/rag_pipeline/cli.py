"""rag-pipeline CLI 入口。

``rag-pipeline sync --source yuque [--scope ID ...] [--full] [--date YYYYMMDD]
[--data-root DIR] [--dry-run]``

装配：settings → registry.get_connector(source) → db 连接 → Workspace → stages.sync。
仅 download 阶段落地（clean/vectorize 待后续阶段）。
"""

from __future__ import annotations

import argparse
import logging
import sys

from rag_core.db import get_connection
from rag_core.settings import get_settings
from rag_pipeline.connectors.registry import available_connectors, get_connector
from rag_pipeline.stages import download
from rag_pipeline.workspace import Workspace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sync", help="从数据源同步（下载阶段）")
    p.add_argument("--source", required=True, help=f"数据源，可用：{available_connectors()}")
    p.add_argument("--scope", action="append", default=None, help="只同步指定 scope（可多次）")
    p.add_argument("--full", action="store_true", help="忽略增量，全量重下")
    p.add_argument("--date", default=None, help="落盘日期目录 YYYYMMDD，缺省今天")
    p.add_argument("--data-root", default=None, help="覆盖 settings.paths.data_root")
    p.add_argument("--dry-run", action="store_true", help="只报告将抓/将删，不写盘不改 DB")
    return parser


def _run_sync(args) -> int:
    settings = get_settings()
    try:
        connector = get_connector(args.source, settings)
    except KeyError as e:
        print(e, file=sys.stderr)
        return 2

    data_root = args.data_root or settings.paths.data_root
    workspace = Workspace.for_run(data_root, args.date)

    conn = get_connection(settings)
    try:
        results = download.sync(
            conn,
            connector,
            workspace,
            settings=settings,
            full=args.full,
            dry_run=args.dry_run,
            scope_ids=args.scope,
        )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    total = download.DownloadStats(scope_id="TOTAL")
    for r in results:
        total.downloaded += r.downloaded
        total.skipped += r.skipped
        total.failed += r.failed
        total.deleted += r.deleted
        total.images += r.images
        total.attachments += r.attachments
        total.planned_fetch += r.planned_fetch
        total.planned_delete += r.planned_delete
    verb = "将抓取" if args.dry_run else "已下载"
    count = total.planned_fetch if args.dry_run else total.downloaded
    del_count = total.planned_delete if args.dry_run else total.deleted
    print(
        f"[{args.source}] {len(results)} scope：{verb} {count}，跳过 {total.skipped}，"
        f"删除 {del_count}，图片 {total.images}，附件 {total.attachments}，失败 {total.failed}"
    )
    return 1 if total.failed else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    if args.command == "sync":
        return _run_sync(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
