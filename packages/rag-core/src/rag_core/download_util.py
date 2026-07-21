"""通用下载与 markdown 资源链接解析。源无关，任意 connector 可复用。

迁自 download.py：sanitize_title / extract_image_urls / extract_attachment_urls /
download_file / _download_with_retry / parse_cookie_string。
"""

from __future__ import annotations

import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

__all__ = [
    "ATTACHMENT_EXTENSIONS",
    "sanitize_title",
    "extract_image_urls",
    "extract_attachment_urls",
    "download_file",
    "download_with_retry",
    "parse_cookie_string",
]

# 从 markdown 识别附件链接的扩展名白名单
ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".zip", ".rar", ".txt", ".csv",
}

_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_LINK_RE = re.compile(r"(?<!\[)\[([^\]]*)\]\(([^)]+)\)")
_HTML_HEADS = (b"<!doctype html", b"<html")


def sanitize_title(title: str) -> str:
    """清洗文件名中的非法字符。"""
    return re.sub(r'[\\/*?:"<>|]', "_", title)


def extract_image_urls(body: str) -> list[str]:
    """从 markdown 提取图片 URL（仅 http(s)）。"""
    urls = []
    for m in _IMG_RE.finditer(body):
        url = m.group(1).strip()
        if url.startswith("http"):
            urls.append(url)
    return urls


def extract_attachment_urls(body: str) -> list[dict[str, str]]:
    """从 markdown 提取附件链接（非图片、扩展名在白名单内）。返回 [{filename, url}]。"""
    out = []
    for m in _LINK_RE.finditer(body):
        text, url = m.group(1), m.group(2)
        if not url.startswith("http"):
            continue
        path = url.split("?")[0].lower()
        if any(path.endswith(ext) for ext in ATTACHMENT_EXTENSIONS):
            filename = text.strip() or os.path.basename(url.split("?")[0])
            out.append({"filename": filename, "url": url})
    return out


def download_file(
    url: str,
    save_path: str,
    timeout: int = 30,
    headers: dict | None = None,
    cookies: dict | None = None,
) -> int:
    """下载文件，返回字节数。双重校验（Content-Type + 文件头）防把 HTML 错误页当文件。

    Raises:
        requests.HTTPError: HTTP 错误。
        ValueError: 响应为 HTML 页面（通常是鉴权失效）。
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    resp = requests.get(url, timeout=timeout, headers=headers or {}, cookies=cookies or {})
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").lower().split(";")[0].strip()
    if content_type in {"text/html", "application/xhtml+xml"}:
        _safe_remove(save_path)
        raise ValueError(
            f"响应为 HTML 页面（Content-Type={content_type}），非目标文件，可能需要认证。"
            f"url={url[:80]}"
        )

    with open(save_path, "wb") as f:
        f.write(resp.content)

    if resp.content[:32].lstrip().lower().startswith(_HTML_HEADS):
        _safe_remove(save_path)
        raise ValueError(f"文件内容为 HTML 页面，非目标文件，可能需要认证。url={url[:80]}")

    return len(resp.content)


def download_with_retry(
    url: str,
    save_path: str,
    headers: dict | None = None,
    cookies: dict | None = None,
    max_retries: int = 3,
    label: str = "",
) -> int:
    """带指数退避的下载。仅对瞬态网络错误重试；HTTP/SSL/内容校验错误立即抛。"""
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return download_file(url, save_path, headers=headers, cookies=cookies)
        except requests.exceptions.SSLError:
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    "  [%s] transient error (attempt %d/%d), retry in %ds: %s",
                    label, attempt + 1, max_retries, wait, e,
                )
                time.sleep(wait)
            else:
                raise
        except Exception:
            raise
    raise last_err  # type: ignore[misc]


def parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """解析浏览器 Cookie 字符串 ``"k1=v1; k2=v2"`` 为 dict。"""
    if not cookie_str:
        return {}
    cookies = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def _safe_remove(path: str) -> None:
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
