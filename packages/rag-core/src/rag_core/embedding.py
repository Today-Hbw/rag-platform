"""多模态 embedding 客户端（火山方舟 / 豆包）。

统一 vectorize.embed_multimodal（入库）与 search.embed_query（检索）为一个 provider，
带稳健重试（瞬态网络错误 + HTTP 429/5xx）。为将来换模型/供应商留 provider 边界。
"""

from __future__ import annotations

import logging
import os
import time

import requests

from .media import SUPPORTED_IMAGE_MIMES, guess_mime_from_base64, image_to_base64
from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

__all__ = ["EmbeddingError", "EmbeddingClient"]

_RETRYABLE_HTTP = (429, 500, 502, 503, 504)


class EmbeddingError(RuntimeError):
    """embedding 调用失败（重试耗尽或不可重试的错误）。"""


class EmbeddingClient:
    def __init__(self, settings: Settings | None = None):
        s = (settings or get_settings()).embedding
        self._api_key = s.api_key.get_secret_value()
        self._model = s.model_endpoint
        self._url = s.url
        self._vector_dim = s.vector_dim
        self._max_images = s.max_images_per_chunk
        self._max_image_mb = s.max_image_size_mb

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"}

    def _post(
        self, input_items: list[dict], *, timeout: int = 60, max_retries: int = 3
    ) -> list[float]:
        data = {"model": self._model, "input": input_items, "encoding_format": "float"}
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(self._url, headers=self._headers(), json=data, timeout=timeout)
                resp.raise_for_status()
                return resp.json()["data"]["embedding"]
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_err = e
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Embedding transient error (attempt %d/%d), retry in %ds: %s",
                        attempt + 1, max_retries, wait, e,
                    )
                    time.sleep(wait)
                else:
                    raise EmbeddingError(
                        f"Embedding API 网络错误（重试 {max_retries} 次均失败）: {e}"
                    ) from e
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                body = ""
                try:
                    body = e.response.text[:300] if e.response is not None else ""
                except Exception:
                    pass
                if status in _RETRYABLE_HTTP and attempt < max_retries - 1:
                    wait = 3 * (attempt + 1)
                    logger.warning(
                        "Embedding HTTP %s (attempt %d/%d), retry in %ds",
                        status, attempt + 1, max_retries, wait,
                    )
                    time.sleep(wait)
                else:
                    raise EmbeddingError(f"Embedding API HTTP 错误: {e} | response: {body}") from e
        raise EmbeddingError(f"Embedding failed: {last_err}")  # pragma: no cover

    def embed_text(self, text: str) -> list[float]:
        return self._post([{"type": "text", "text": text}])

    def embed_multimodal(self, text: str, image_paths: list[str] | None = None) -> list[float]:
        """文本 + 图片联合编码为 1 个融合向量（入库侧）。"""
        items: list[dict] = [{"type": "text", "text": text}]
        for path in (image_paths or [])[: self._max_images]:
            if not os.path.exists(path):
                logger.warning("Image file not found, skipping: %s", path)
                continue
            b64, mime = image_to_base64(path, max_size_mb=self._max_image_mb)
            if b64 is None:
                continue
            if mime not in SUPPORTED_IMAGE_MIMES:
                logger.warning(
                    "Unsupported image format '%s' for embedding API, skipping: %s", mime, path
                )
                continue
            url = f"data:{mime};base64,{b64}"
            items.append({"type": "image_url", "image_url": {"url": url}})
        return self._post(items, timeout=120)

    def embed_query(
        self,
        text: str | None = None,
        image_path: str | None = None,
        image_url: str | None = None,
        image_b64: str | None = None,
    ) -> list[float]:
        """检索侧查询编码：文本 / 图片路径 / 图片 URL / 图片 base64。"""
        items: list[dict] = []
        if text:
            items.append({"type": "text", "text": text})
        if image_path:
            b64, mime = image_to_base64(image_path)
            if b64 is not None:
                url = f"data:{mime};base64,{b64}"
                items.append({"type": "image_url", "image_url": {"url": url}})
        elif image_b64:
            mime = guess_mime_from_base64(image_b64)
            url = f"data:{mime};base64,{image_b64}"
            items.append({"type": "image_url", "image_url": {"url": url}})
        elif image_url:
            items.append({"type": "image_url", "image_url": {"url": image_url}})
        if not items:
            raise ValueError("At least one of text/image_path/image_url/image_b64 is required")
        return self._post(items)

    def detect_vector_dim(self) -> int:
        """返回向量维度；配置已给则直接返回，否则探测一次并缓存到实例。"""
        if self._vector_dim:
            return self._vector_dim
        self._vector_dim = len(self.embed_text("探测向量维度"))
        return self._vector_dim
