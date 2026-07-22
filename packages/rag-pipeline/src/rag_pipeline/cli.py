"""rag-pipeline CLI 入口。三个阶段子命令，可分步或串起来跑：

``rag-pipeline sync --source yuque [--scope ID ...] [--full] [--date YYYYMMDD]
[--data-root DIR] [--dry-run]``  下载
``rag-pipeline clean [--data-root DIR]``                    清洗 downloaded→cleaned
``rag-pipeline vectorize [--data-root DIR] [--recreate]``   向量化 cleaned→imported

装配：settings → (registry.get_connector) → db → Workspace → stages.*。
"""

from __future__ import annotations

import argparse
import logging
import sys

from rag_core.db import get_connection
from rag_core.settings import get_settings
from rag_pipeline.connectors.registry import available_connectors, get_connector
from rag_pipeline.stages import clean as clean_stage
from rag_pipeline.stages import download
from rag_pipeline.stages import vectorize as vectorize_stage
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

    c = sub.add_parser("clean", help="清洗 downloaded → cleaned")
    c.add_argument("--data-root", default=None, help="覆盖 settings.paths.data_root")

    v = sub.add_parser("vectorize", help="向量化 cleaned → imported")
    v.add_argument("--data-root", default=None, help="覆盖 settings.paths.data_root")
    v.add_argument("--recreate", action="store_true", help="重建 Qdrant collection（慎用）")
    return parser


def _workspace(args, settings) -> Workspace:
    data_root = args.data_root or settings.paths.data_root
    return Workspace.for_run(data_root, getattr(args, "date", None))


def _run_sync(args) -> int:
    settings = get_settings()
    try:
        connector = get_connector(args.source, settings)
    except KeyError as e:
        print(e, file=sys.stderr)
        return 2

    workspace = _workspace(args, settings)

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


def _run_clean(args) -> int:
    settings = get_settings()
    workspace = _workspace(args, settings)
    conn = get_connection(settings)
    try:
        stats = clean_stage.clean(conn, workspace, settings=settings)
    finally:
        _close(conn)
    print(f"[clean] 清洗 {stats.cleaned}，失败 {stats.failed}")
    return 1 if stats.failed else 0


def _run_vectorize(args) -> int:
    settings = get_settings()
    workspace = _workspace(args, settings)
    conn = get_connection(settings)
    try:
        stats = vectorize_stage.vectorize(
            conn, workspace, settings=settings, recreate=args.recreate
        )
    finally:
        _close(conn)
    print(
        f"[vectorize] 向量化 {stats.vectorized}（{stats.chunks} 块），跳过 {stats.skipped}，"
        f"删除 {stats.deleted}，失败 {stats.failed}"
    )
    return 1 if stats.failed else 0


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    if args.command == "sync":
        return _run_sync(args)
    if args.command == "clean":
        return _run_clean(args)
    if args.command == "vectorize":
        return _run_vectorize(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
