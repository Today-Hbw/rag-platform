"""FastAPI 检索服务：多模态混合检索 + Redis 缓存 + 查询日志。

移植自旧 search/app.py，检索排序剥离到 :mod:`rag_search.retrieve`（纯函数，供 eval）。
依赖（embedder/store/cache/db）经 :class:`SearchService` 注入，便于离线测试。

响应字段向后兼容：``book_slug``/``doc_slug`` 保留（由泛化的 collection_slug/doc_key 映射），
另加 ``source``/``collection_id``。RBAC 过滤为受 ``settings.rbac.enabled`` 保护的挂载点：
关闭时 query_filter=None（旧行为），开启后在 :func:`_resolve_query_filter` 接阶段 5。
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from rag_core.db import get_connection
from rag_core.embedding import EmbeddingClient
from rag_core.settings import Settings, get_settings
from rag_core.vectorstore import VectorStore
from rag_search import auth
from rag_search import retrieve as retrieve_mod
from rag_search.cache import SearchCache, make_cache_key

logger = logging.getLogger("rag-search")

__all__ = ["SearchService", "create_app", "ResultItem", "SearchResponse"]


# ==================== 响应模型 ====================

class ImageInfo(BaseModel):
    url: str = ""
    local_path: str = ""
    served_url: str = ""


class AttachmentInfo(BaseModel):
    filename: str = ""
    file_type: str = ""
    local_path: str = ""
    served_url: str = ""
    text_chars: int = 0


class ResultItem(BaseModel):
    rank: int
    doc_title: str
    doc_id: int
    chunk_index: int
    chunk_text: str
    source_url: str
    book_slug: str  # 向后兼容：= collection_slug
    doc_slug: str  # 向后兼容：= doc_key
    source: str = ""
    collection_id: str = ""
    hybrid_score: float
    vector_score: float
    bm25_score: float
    images: list[ImageInfo] = Field(default_factory=list)
    has_image: bool = False
    attachments: list[AttachmentInfo] = Field(default_factory=list)
    has_attachment: bool = False


class SearchResponse(BaseModel):
    query: str
    total_results: int
    results: list[ResultItem]
    elapsed_ms: int
    from_cache: bool = False


# ==================== 请求模型 ====================

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    refresh: bool = Field(default=False)


class ImageSearchRequest(BaseModel):
    image_base64: str | None = None
    image_url: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    refresh: bool = Field(default=False)


class MultimodalSearchRequest(BaseModel):
    query: str | None = None
    image_base64: str | None = None
    image_url: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    refresh: bool = Field(default=False)


def _to_item(rank: int, r: dict[str, Any]) -> ResultItem:
    return ResultItem(
        rank=rank,
        doc_title=r.get("doc_title", ""),
        doc_id=r.get("doc_id", 0),
        chunk_index=r.get("chunk_index", 0),
        chunk_text=r.get("chunk_text", ""),
        source_url=r.get("source_url", ""),
        book_slug=r.get("collection_slug", ""),
        doc_slug=r.get("doc_key", ""),
        source=r.get("source", ""),
        collection_id=r.get("collection_id", ""),
        hybrid_score=round(r.get("hybrid_score", 0.0), 4),
        vector_score=round(r.get("score", 0.0), 4),
        bm25_score=round(r.get("bm25_score", 0.0), 4),
        images=[ImageInfo(**{k: img.get(k, "") for k in ("url", "local_path", "served_url")})
                for img in r.get("images", [])],
        has_image=r.get("has_image", False),
        attachments=[AttachmentInfo(**a) for a in r.get("attachments", [])],
        has_attachment=bool(r.get("attachments")),
    )


class SearchService:
    """检索服务：装配 embedder + store + cache + DB，执行带缓存/日志的检索。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedder: EmbeddingClient | None = None,
        store: VectorStore | None = None,
        cache: SearchCache | None = None,
        conn_factory=None,
    ):
        self.settings = settings or get_settings()
        self.embedder = embedder or EmbeddingClient(self.settings)
        self.store = store or VectorStore(self.settings)
        self.cache = cache if cache is not None else SearchCache.from_settings(self.settings)
        self._conn_factory = conn_factory or (lambda: get_connection(self.settings))
        self.logs_dir = Path(self.settings.paths.data_root) / "logs"

    def run(
        self,
        *,
        query_text: str,
        image_b64: str | None = None,
        image_url: str | None = None,
        top_k: int = 10,
        refresh: bool = False,
        role_ids: list[str] | None = None,
    ) -> SearchResponse:
        t0 = time.time()
        rbac_on = self.settings.rbac.enabled
        role_ids = role_ids or []
        # 缓存 key 叠权限签名(仅依赖 role_ids,不需 DB) → 缓存命中仍快且不串权限
        sig = auth.scope_sig(role_ids) if rbac_on else ""
        cache_key = make_cache_key(
            query_text, image_b64=image_b64, image_url=image_url, top_k=top_k, scope_sig=sig
        )
        if not refresh:
            cached = self.cache.get(cache_key)
            if cached is not None:
                cached["elapsed_ms"] = int((time.time() - t0) * 1000)
                cached["from_cache"] = True
                return SearchResponse(**cached)

        query_vec = self.embedder.embed_query(
            text=query_text or None, image_b64=image_b64, image_url=image_url
        )
        conn = self._conn_factory()
        try:
            query_filter = None
            if rbac_on:
                scope = auth.resolve_scope(conn, role_ids)
                if scope.denies_all:
                    return self._respond(query_text, [], t0, cache_key)  # 无授权 → 空
                query_filter = auth.build_query_filter(scope)
            results = retrieve_mod.retrieve(
                query_vec,
                store=self.store,
                conn=conn,
                query_text=query_text,
                top_k=top_k,
                settings=self.settings,
                query_filter=query_filter,
            )
        finally:
            _close(conn)

        return self._respond(query_text, results, t0, cache_key)

    def _respond(self, query_text, results, t0, cache_key) -> SearchResponse:
        items = [_to_item(i + 1, r) for i, r in enumerate(results)]
        elapsed = int((time.time() - t0) * 1000)
        top_title = items[0].doc_title if items else ""
        self._log_query(query_text or "(image)", len(items), top_title, elapsed)
        response = SearchResponse(
            query=query_text or "(image)",
            total_results=len(items),
            results=items,
            elapsed_ms=elapsed,
        )
        self.cache.set(cache_key, response.model_dump())
        return response

    def _log_query(self, query: str, count: int, top_title: str, elapsed_ms: int) -> None:
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
            entry = {
                "timestamp": datetime.now().isoformat(),
                "query": query, "result_count": count,
                "top_title": top_title, "elapsed_ms": elapsed_ms,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001 - 日志失败不应影响响应
            logger.warning("写查询日志失败: %s", e)


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def create_app(service: SearchService | None = None) -> FastAPI:
    """构造 FastAPI 应用。service 可注入（测试）；缺省惰性从 settings 装配。"""
    app = FastAPI(title="RAG Search API")
    _svc = service

    def svc() -> SearchService:
        nonlocal _svc
        if _svc is None:
            _svc = SearchService()
        return _svc

    def require_service_token(authorization: str | None = Header(default=None)):
        """校验调用方是业务系统(共享服务令牌)。未配置令牌=不校验(兼容现状)。"""
        expected = svc().settings.rbac.service_token.get_secret_value()
        if not expected:
            return
        token = ""
        if authorization and authorization.startswith("Bearer "):
            token = authorization[len("Bearer "):]
        if not secrets.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="invalid service token")

    guard = [Depends(require_service_token)]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/search", response_model=SearchResponse, dependencies=guard)
    def search(req: SearchRequest, x_role_ids: str | None = Header(default=None)):
        try:
            return svc().run(
                query_text=req.query, top_k=req.top_k, refresh=req.refresh,
                role_ids=auth.parse_role_ids(x_role_ids),
            )
        except Exception as e:
            logger.exception("search failed")
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/image", response_model=SearchResponse, dependencies=guard)
    def search_image(req: ImageSearchRequest, x_role_ids: str | None = Header(default=None)):
        if not req.image_base64 and not req.image_url:
            raise HTTPException(status_code=400, detail="需要 image_base64 或 image_url")
        try:
            return svc().run(
                query_text="(image)", image_b64=req.image_base64,
                image_url=req.image_url, top_k=req.top_k, refresh=req.refresh,
                role_ids=auth.parse_role_ids(x_role_ids),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("image search failed")
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/multimodal", response_model=SearchResponse, dependencies=guard)
    def search_multimodal(
        req: MultimodalSearchRequest, x_role_ids: str | None = Header(default=None)
    ):
        if not req.query and not req.image_base64 and not req.image_url:
            raise HTTPException(status_code=400, detail="至少需要 query 或图片")
        try:
            return svc().run(
                query_text=req.query or "", image_b64=req.image_base64,
                image_url=req.image_url, top_k=req.top_k, refresh=req.refresh,
                role_ids=auth.parse_role_ids(x_role_ids),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("multimodal search failed")
            raise HTTPException(status_code=500, detail=str(e)) from e

    return app
