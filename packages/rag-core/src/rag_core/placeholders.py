"""图片/附件占位符协议（原为 clean_md 产出、vectorize 消费的隐式跨模块契约，现固化）。

- 图片：``[IMG_{idx}]``
- 附件：``[ATT_{idx}:{filename}]``
- 附件正文包裹：``[附件内容: {filename}]`` ... ``[附件内容结束]``
"""

from __future__ import annotations

import re

__all__ = [
    "IMG_RE",
    "ATT_RE",
    "img_placeholder",
    "att_placeholder",
    "attachment_block",
    "find_img_indices",
    "render_readable",
]

IMG_RE = re.compile(r"\[IMG_(\d+)\]")
ATT_RE = re.compile(r"\[ATT_(\d+):([^\]]+)\]")
_ATT_CONTENT_OPEN_RE = re.compile(r"\[附件内容: [^\]]+\]")
_ATT_CONTENT_CLOSE = "[附件内容结束]"


def img_placeholder(idx: int) -> str:
    return f"[IMG_{idx}]"


def att_placeholder(idx: int, filename: str) -> str:
    return f"[ATT_{idx}:{filename}]"


def attachment_block(filename: str, text: str) -> str:
    """附件提取文本的包裹块（追加到正文末尾）。"""
    return f"\n\n[附件内容: {filename}]\n{text}\n[附件内容结束]\n"


def find_img_indices(text: str) -> list[int]:
    """按出现顺序返回 chunk 中的 [IMG_N] 序号（可重复）。"""
    return [int(m) for m in IMG_RE.findall(text)]


def render_readable(text: str, alts: dict[int, str] | None = None) -> str:
    """把占位符替换为可读描述，供文本 embedding。忠实移植 vectorize.py:467-478。

    - ``[IMG_N]`` → ``[图片: alt]`` 或 ``[图片]``
    - ``[ATT_N:filename]`` → ``[附件: filename]``
    - 去掉 ``[附件内容: ...]`` / ``[附件内容结束]`` 标记（保留其间正文）
    """
    alts = alts or {}
    for idx in set(find_img_indices(text)):
        alt = alts.get(idx, "")
        desc = f"[图片: {alt}]" if alt else "[图片]"
        text = text.replace(img_placeholder(idx), desc)
    text = ATT_RE.sub(r"[附件: \2]", text)  # \2 = 文件名（\1 是序号）
    text = _ATT_CONTENT_OPEN_RE.sub("", text)
    text = text.replace(_ATT_CONTENT_CLOSE, "")
    return text
