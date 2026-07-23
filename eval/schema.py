"""评估数据集 schema 与读写。

数据集为 JSONL，每行一条 :class:`EvalCase`：
    {"id": "q1", "query": "社保补缴流程", "relevant_doc_ids": [101, 102], "note": "..."}

``relevant_doc_ids`` 是人工标注的相关文档（doc_id）；``note`` 可选，记录标注理由/来源。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["EvalCase", "load_dataset", "save_dataset"]


@dataclass
class EvalCase:
    id: str
    query: str
    relevant_doc_ids: list[int] = field(default_factory=list)
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> EvalCase:
        return cls(
            id=str(d["id"]),
            query=str(d["query"]),
            relevant_doc_ids=[int(x) for x in (d.get("relevant_doc_ids") or [])],
            note=str(d.get("note", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "relevant_doc_ids": self.relevant_doc_ids,
            "note": self.note,
        }


def load_dataset(path: str | Path) -> list[EvalCase]:
    """读 JSONL 数据集；跳过空行。重复 id 视为错误（防标注表悄悄覆盖）。"""
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            case = EvalCase.from_dict(json.loads(line))
        except (ValueError, KeyError) as e:
            raise ValueError(f"{path}:{lineno} 解析失败: {e}") from e
        if case.id in seen:
            raise ValueError(f"{path}:{lineno} 重复 case id: {case.id}")
        seen.add(case.id)
        cases.append(case)
    return cases


def save_dataset(cases: list[EvalCase], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
