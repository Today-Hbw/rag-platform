"""提取文本的乱码检测。忠实移植 download.py:_is_text_garbled（纯函数）。"""

from __future__ import annotations

__all__ = ["is_text_garbled"]


def is_text_garbled(text: str, threshold: float = 0.4) -> bool:
    """检测提取文本是否质量过差。

    覆盖两类：(1) 替换型（大量 ? 或 U+FFFD）；(2) 编码错乱（GBK 被误读为 Latin-1/UTF-8）。
    """
    if not text or len(text) < 20:
        return True
    sample = text[:3000]
    total = len(sample)

    # 类型 1：替换字符
    q_count = sample.count("?") + sample.count("�")
    if q_count / total > 0.05:
        return True

    # 类型 2：编码错乱 —— 统计合法字符占比
    common = 0
    for ch in sample:
        cp = ord(ch)
        if cp < 0x7F:  # ASCII
            common += 1
        elif 0x2000 <= cp <= 0x206F:  # 通用标点
            common += 1
        elif 0x3000 <= cp <= 0x9FFF:  # CJK + 中文标点/符号
            common += 1
        elif 0xF900 <= cp <= 0xFAFF:  # CJK 兼容
            common += 1
        elif 0xFE30 <= cp <= 0xFE4F:  # CJK 兼容形式
            common += 1
        elif 0xFF00 <= cp <= 0xFFEF:  # 全角 / 半角片假名
            common += 1
        elif 0x20000 <= cp <= 0x2FA1F:  # CJK 扩展 B-G
            common += 1
        elif ch.isspace():
            common += 1
    return (common / total) < (1.0 - threshold)
