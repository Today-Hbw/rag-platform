# rag-pipeline

离线批处理（离线面），独立部署。把「数据源 → 清洗 → 多模态向量化」编排为来源无关的三阶段，数据源经可插拔 connector 接入。

```bash
rag-pipeline sync --source yuque [--scope <库>] [--full] [--date YYYYMMDD] [--dry-run]
rag-pipeline clean                  # downloaded → cleaned
rag-pipeline vectorize [--recreate] # cleaned → imported（--recreate 慎用）
```

| 模块 | 职责 |
|------|------|
| `connectors/base.py` | `SourceConnector` ABC + 摄取 DTO（`SourceScope/DocRef/DocDetail/ResourceRef/AssetAuth/ChangeSet`）+ `detect_changes` 纯逻辑 + 删除安全阀 |
| `connectors/yuque.py` | 语雀实现（分页 / 详情 / version 归一化 / 鉴权 / 资源） |
| `connectors/local.py` | 本地 stub，验证 ABC 不过拟合 REST |
| `connectors/registry.py` | `register_connector` / `get_connector`（内置注册 yuque/local） |
| `stages/{download,clean,vectorize}.py` | 来源无关编排：增量跳过 / 删除差集软删 / DB upsert / 资产下载 / 分块入库 |
| `workspace.py` | 显式路径基准（`data_root` / `run_date` / `scope`），消除隐式 `SCRIPT_DIR` 契约 |

**破坏性提醒**：删除检测有「抓取完整性守卫」（列举回 0 篇而 DB 有存量 → 不删），迁移期务必先跑 `--dry-run` 核对。
