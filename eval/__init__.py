"""rag-platform 检索评估工具（顶层工具目录，D8；非部署包）。

离线复用 rag-search 的纯 ``retrieve()`` 打分，锚定 doc_id 做 @k 指标评估。
入口：``python -m eval {run,compare,harvest}``。
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
