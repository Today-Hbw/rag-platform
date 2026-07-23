# eval 数据集

JSONL，每行一条 `EvalCase`：

```json
{"id": "q1", "query": "社保补缴流程", "relevant_doc_ids": [101, 102], "note": "标注来源/理由"}
```

- `relevant_doc_ids`：人工标注的**相关文档 doc_id**（评估单元是 doc，不是 chunk）。
- `smoke.example.jsonl` 是**格式示例**，`relevant_doc_ids` 为空，不能直接用于门禁。

## 产出真实 golden 集（D9）

1. 先让 rag-search 正常服务一段时间，积累查询日志（`<data_root>/logs/*.jsonl`，已记 `doc_ids`）。
2. `python -m eval harvest --logs-dir <data_root>/logs --out datasets/candidates.jsonl`
   —— 从日志 pooling 出高频查询 + 候选 doc（`note` 里）。
3. 人工在 `candidates.jsonl` 里为每条 query 从候选中勾选真正相关的 doc，填入 `relevant_doc_ids`，
   另存为 `smoke.jsonl` / `golden_v1.jsonl`。
4. **评估须打在冻结的快照 collection 上**（D9），否则 pipeline 持续重灌会让 before/after 分不清
   是算法变了还是索引变了。

## 跑评估

```bash
python -m eval run     --dataset datasets/smoke.jsonl --out runs/baseline.json --name baseline
# 改了 rrf_k/title_weight 后再跑一次
python -m eval run     --dataset datasets/smoke.jsonl --out runs/tuned.json    --name tuned
python -m eval compare --before runs/baseline.json --after runs/tuned.json --fail-on-regress
```

查询向量按 `md5(model_endpoint + query)` 磁盘缓存（默认 `.eval_cache/`）：改融合层时向量复用、
跑分秒级确定；换 embedding 模型（endpoint 变）时自动失效重算。
