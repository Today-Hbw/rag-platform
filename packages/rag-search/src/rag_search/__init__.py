"""rag-search：在线检索服务（FastAPI + 向量/BM25/标题 RRF 混合检索 + Redis 缓存）。

- ``retrieve``：纯排序（tokenize/BM25/fuse/retrieve），供 eval 直接 import，绕开 HTTP。
- ``app``：FastAPI 端点 + 缓存 + 日志 + RBAC 挂载点（受 rbac.enabled 保护）。
- ``cache``：Redis 缓存封装。
"""

__version__ = "0.1.0"
