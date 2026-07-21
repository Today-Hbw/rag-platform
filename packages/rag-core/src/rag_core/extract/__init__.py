"""附件文本提取子系统。

从 download.py 的 extract_text_from_file 及 _extract_*/_pdf_* 全套迁入（源无关）。
按 D1=Linux：外部工具路径不再硬编码，改由 `ToolPaths.resolve()` 从 Settings/PATH 发现。
重依赖为 optional extras（rag-core[pdf,office,ocr,win]），缺失则该分支静默降级返回 None。
"""

from __future__ import annotations

from .extractors import extract_text_from_file
from .garbled import is_text_garbled
from .tools import ToolPaths

__all__ = ["extract_text_from_file", "is_text_garbled", "ToolPaths"]
