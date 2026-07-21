"""HTML→纯文本清洗。忠实移植 clean_md.py:177 clean_md（纯函数，源无关）。

零宽字符改用 unicode 转义书写（U+200B/200C/200D/FEFF/2060），行为等价且不怕编码损坏。
"""

from __future__ import annotations

import html
import re

__all__ = ["clean_markdown"]

# 零宽字符：ZWSP / ZWNJ / ZWJ / ZWNBSP(BOM) / WORD JOINER
_ZERO_WIDTH_RE = re.compile("[​‌‍﻿⁠]")


def clean_markdown(content: str) -> str:
    """清洗语雀导出的内嵌 HTML markdown → 纯文本，保留代码块缩进。"""
    # 1. 去 HTML 注释
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    # 2. <br/> → 换行
    content = re.sub(r"<br\s*/?\s*>", "\n", content, flags=re.IGNORECASE)
    # 3. <p> → 换行
    content = re.sub(r"</?p[^>]*>", "\n", content, flags=re.IGNORECASE)
    # 4. <div> → 换行
    content = re.sub(r"</?div[^>]*>", "\n", content, flags=re.IGNORECASE)
    # 5. 表格：<tr> → 换行，<td>/<th> → 制表符
    content = re.sub(r"</?tr[^>]*>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</?td[^>]*>", "\t", content, flags=re.IGNORECASE)
    content = re.sub(r"</?th[^>]*>", "\t", content, flags=re.IGNORECASE)
    # 6. 移除剩余 HTML 标签
    content = re.sub(r"<[^>]+>", "", content)
    # 7. 解码 HTML 实体
    content = html.unescape(content)
    # 8. 去零宽字符
    content = _ZERO_WIDTH_RE.sub("", content)
    # 9. 去行首尾空白（代码块内保留缩进）
    lines = content.split("\n")
    cleaned: list[str] = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        cleaned.append(line if in_code_block else line.strip())
    content = "\n".join(cleaned)
    # 10. 合并 3+ 连续空行为单个空行
    content = re.sub(r"\n{3,}", "\n\n", content)
    # 11. 去首尾空白，补末尾换行
    return content.strip() + "\n"
