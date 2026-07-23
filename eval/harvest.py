"""从 rag-search 查询日志 pooling 出评估候选，供人工打标。

日志为 ``<data_root>/logs/*.jsonl``，每行含 ``query`` 与（新版）``doc_ids``。
harvest 按 query 聚合：统计频次、并集 pooled 候选 doc_id（各次检索返回的 doc 的并集），
产出候选行。**候选 ≠ 相关**：``relevant_doc_ids`` 留空，由人工从 pooled 候选里勾选。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

__all__ = ["harvest_from_logs", "to_case_templates"]


def _iter_log_entries(logs_dir: str | Path) -> Iterable[dict]:
    for path in sorted(Path(logs_dir).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def harvest_from_logs(
    logs_dir: str | Path, *, min_freq: int = 1, max_candidates: int = 20
) -> list[dict]:
    """聚合日志 → ``[{"query","freq","candidate_doc_ids"}, ...]``，按频次降序。

    ``min_freq`` 过滤低频查询；``candidate_doc_ids`` 为该 query 历次检索 doc 的并集
    （保留首现顺序，截断到 ``max_candidates``）。
    """
    freq: dict[str, int] = {}
    candidates: dict[str, list[int]] = {}
    seen: dict[str, set[int]] = {}
    for entry in _iter_log_entries(logs_dir):
        query = (entry.get("query") or "").strip()
        if not query or query == "(image)":
            continue
        freq[query] = freq.get(query, 0) + 1
        candidates.setdefault(query, [])
        seen.setdefault(query, set())
        for doc_id in entry.get("doc_ids") or []:
            if doc_id is None or doc_id in seen[query]:
                continue
            seen[query].add(doc_id)
            if len(candidates[query]) < max_candidates:
                candidates[query].append(doc_id)
    # 排序在类型明确的 query 键上做（freq[q] 是 int），避免混合值 dict 的类型问题
    ordered = sorted(
        (q for q in freq if freq[q] >= min_freq), key=lambda q: (-freq[q], q)
    )
    return [
        {"query": q, "freq": freq[q], "candidate_doc_ids": candidates[q]} for q in ordered
    ]


def to_case_templates(rows: list[dict], *, prefix: str = "q") -> list[dict]:
    """候选行 → 待人工打标的 EvalCase 模板 dict（relevant_doc_ids 留空）。"""
    templates = []
    for i, row in enumerate(rows, 1):
        templates.append({
            "id": f"{prefix}{i}",
            "query": row["query"],
            "relevant_doc_ids": [],
            "note": f"freq={row['freq']} candidates={row['candidate_doc_ids']}",
        })
    return templates
