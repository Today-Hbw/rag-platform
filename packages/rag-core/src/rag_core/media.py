"""图片 MIME 检测与 base64 编码。

合并自 vectorize.py 与 search/search.py 的多份冲突实现：
- `image_to_base64` 统一为**不抛异常**契约：成功返回 ``(b64, mime)``，
  超限/无法识别返回 ``(None, None)``（原 vectorize 版即此契约；search 版超限会 raise，
  迁移 rag-search 时改用本函数）。
- `guess_mime_from_path` 取两版并集（含 gif 与 bmp）。
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "SUPPORTED_IMAGE_MIMES",
    "detect_mime_from_data",
    "detect_mime_from_file",
    "guess_mime_from_path",
    "guess_mime_from_ext",
    "guess_mime_from_base64",
    "image_to_base64",
]

# 火山引擎 multimodal embedding 支持的图片格式（注意：不含 gif）
SUPPORTED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/bmp", "image/tiff"}


def detect_mime_from_data(data: bytes) -> str | None:
    """通过文件头 magic bytes 检测真实图片 MIME，未知返回 None。忠实移植 vectorize.py:385。"""
    if len(data) < 12:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    if data[:4] in (b"MM\x00\x2a", b"II\x2a\x00"):
        return "image/tiff"
    return None


def detect_mime_from_file(filepath: str | Path) -> str | None:
    """读取文件头 magic bytes 检测图片 MIME；读失败/未知返回 None。迁自 download.py:216。"""
    try:
        with open(filepath, "rb") as f:
            header = f.read(16)
    except OSError:
        return None
    return detect_mime_from_data(header)


def guess_mime_from_ext(ext: str) -> str:
    """按扩展名（如 ``.png``）推断 MIME，含 svg，默认 image/png。迁自 download.py:207。"""
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }.get(ext.lower(), "image/png")


def guess_mime_from_path(filepath: str | Path) -> str:
    """按扩展名推断 MIME（fallback）。默认 image/png。"""
    ext = Path(filepath).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "image/png")


def guess_mime_from_base64(b64_str: str) -> str:
    """从 base64 头部魔术字节判 MIME，默认 image/png。忠实移植 search/search.py:107。"""
    magic = base64.b64decode(b64_str[:32])
    if magic[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if magic[:4] == b"\x89PNG":
        return "image/png"
    if magic[:3] == b"GIF":
        return "image/gif"
    if magic[:4] == b"RIFF" and magic[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def image_to_base64(filepath: str | Path, max_size_mb: int = 10) -> tuple[str | None, str | None]:
    """读取图片 → ``(base64, mime)``；超限或无法识别格式返回 ``(None, None)``。"""
    with open(filepath, "rb") as f:
        data = f.read()
    if len(data) > max_size_mb * 1024 * 1024:
        logger.warning("Image too large (%d bytes): %s", len(data), filepath)
        return None, None
    mime = detect_mime_from_data(data)
    if mime is None:
        logger.warning("Cannot detect image format: %s", filepath)
        return None, None
    b64 = base64.b64encode(data).decode("utf-8")
    return b64, mime
