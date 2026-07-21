"""哈希工具。统一自 download.py:193 / clean_md.py:111 / vectorize.py:342,350（原为 3+1 份重复）。"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["file_md5", "text_md5"]


def file_md5(filepath: str | Path, *, chunk_size: int = 8192) -> str:
    """分块计算文件 MD5（增量/去重判断用）。"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def text_md5(text: str) -> str:
    """UTF-8 文本 MD5（chunk_hash 用）。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()
