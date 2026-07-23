"""eval CLI：``python -m eval {run,compare,harvest}``。

- ``run``     ：对数据集跑检索、算指标、存 run JSON（需 .env + 内网 Qdrant/embedding）。
- ``compare`` ：两次 run 对拍，``--fail-on-regress`` 时有回归则退出码 1（供 CI 门禁）。
- ``harvest`` ：从查询日志 pooling 候选，产出待人工打标的数据集模板。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compare import compare_runs, regressions
from .harvest import harvest_from_logs, to_case_templates
from .report import format_comparison, format_run
from .runner import load_run, run_eval, save_run
from .schema import load_dataset


def _parse_ks(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


def _build_retriever(pool: int, cache_dir: str):
    """装配真实检索器（延迟导入重依赖；仅 run 子命令用）。"""
    from rag_core.embedding import EmbeddingClient
    from rag_core.settings import get_settings
    from rag_core.vectorstore import VectorStore

    from .embed_cache import EmbedCache
    from .retrievers import make_retriever

    settings = get_settings()
    embedder = EmbeddingClient(settings)
    cache = EmbedCache(cache_dir, settings.embedding.model_endpoint)

    def embed_fn(query: str) -> list[float]:
        return cache.embed(query, lambda q: embedder.embed_query(text=q))

    store = VectorStore(settings)
    retriever = make_retriever(store=store, embed_fn=embed_fn, settings=settings, pool=pool)
    meta = {
        "collection": settings.qdrant.collection,
        "model_endpoint": settings.embedding.model_endpoint,
    }
    return retriever, meta, cache


def _cmd_run(args) -> int:
    cases = load_dataset(args.dataset)
    retriever, meta, cache = _build_retriever(args.pool, args.cache_dir)
    run = run_eval(cases, retriever, ks=_parse_ks(args.ks), name=args.name, meta=meta)
    run.meta["embed_cache"] = {"hits": cache.hits, "misses": cache.misses}
    save_run(run, args.out)
    print(format_run(run))
    print(f"\n已保存 run → {args.out}")
    return 0


def _cmd_compare(args) -> int:
    before, after = load_run(args.before), load_run(args.after)
    deltas = compare_runs(before, after)
    regs = regressions(deltas, tol=args.tol)
    print(format_comparison(deltas, regs))
    if args.fail_on_regress and regs:
        print(f"\n❌ 检出 {len(regs)} 项回归，门禁失败")
        return 1
    return 0


def _cmd_harvest(args) -> int:
    rows = harvest_from_logs(
        args.logs_dir, min_freq=args.min_freq, max_candidates=args.max_candidates
    )
    templates = to_case_templates(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for t in templates:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"pooled {len(templates)} 条候选 → {args.out}（relevant_doc_ids 待人工打标）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description="rag-platform 检索评估")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="跑评估")
    r.add_argument("--dataset", required=True, help="JSONL 数据集路径")
    r.add_argument("--out", required=True, help="run 结果输出 JSON 路径")
    r.add_argument("--name", default="run", help="run 名称")
    r.add_argument("--ks", default="1,3,5,10", help="截断位，逗号分隔")
    r.add_argument("--pool", type=int, default=50, help="召回 chunk 池大小")
    r.add_argument("--cache-dir", default=".eval_cache", help="查询向量缓存目录")
    r.set_defaults(func=_cmd_run)

    c = sub.add_parser("compare", help="两次 run 对拍")
    c.add_argument("--before", required=True)
    c.add_argument("--after", required=True)
    c.add_argument("--tol", type=float, default=0.0, help="回归容差")
    c.add_argument("--fail-on-regress", action="store_true", help="有回归则退出码 1")
    c.set_defaults(func=_cmd_compare)

    h = sub.add_parser("harvest", help="从日志 pooling 候选")
    h.add_argument("--logs-dir", required=True, help="rag-search 日志目录")
    h.add_argument("--out", required=True, help="候选数据集模板输出 JSONL")
    h.add_argument("--min-freq", type=int, default=1)
    h.add_argument("--max-candidates", type=int, default=20)
    h.set_defaults(func=_cmd_harvest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
