"""文本分块。忠实移植 vectorize.py:307 chunk_text（纯函数，源无关）。

注意：与上游 `chunk_with_images` 的图文关联部分依赖文件系统路径基准（Workspace），
将在阶段 4 引入 Workspace 后一并迁入；此处仅提供纯文本分块。
"""

from __future__ import annotations

import re

__all__ = ["chunk_text"]


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """按段落切分并带段落级重叠。

    累计字符超过 ``chunk_size * 2`` 时切块；反向取不超过 ``overlap * 2`` 字符的段落做重叠。
    """
    paragraphs = re.split(r"\n\n+", text.strip())
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0

    for p in paragraphs:
        p_chars = len(p)
        if current_chars + p_chars > chunk_size * 2 and current:
            chunks.append("\n\n".join(current))
            overlap_chars = 0
            overlap_paras: list[str] = []
            for para in reversed(current):
                pt = len(para)
                if overlap_chars + pt > overlap * 2:
                    break
                overlap_paras.insert(0, para)
                overlap_chars += pt
            current = overlap_paras
            current_chars = overlap_chars
        current.append(p)
        current_chars += p_chars

    if current:
        chunks.append("\n\n".join(current))

    return chunks
