"""外部提取工具的路径解析（D1=Linux：不再硬编码 Windows 路径）。

优先用 Settings.extract 显式配置，否则用 PATH（shutil.which）/常见安装位置自动发现。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from ..settings import Settings, get_settings

__all__ = ["ToolPaths"]

_LIBREOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
)


def _discover_libreoffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for cand in _LIBREOFFICE_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return None


@dataclass
class ToolPaths:
    tesseract_cmd: str | None
    poppler_bin: str | None
    libreoffice_bin: str | None
    antiword_cmd: str
    pdftotext_cmd: str

    @classmethod
    def resolve(cls, settings: Settings | None = None) -> ToolPaths:
        s = (settings or get_settings()).extract
        return cls(
            tesseract_cmd=s.tesseract_cmd or shutil.which("tesseract"),
            poppler_bin=s.poppler_bin,  # None → pdf2image 走 PATH
            libreoffice_bin=s.libreoffice_bin or _discover_libreoffice(),
            antiword_cmd=s.antiword_cmd,
            pdftotext_cmd=s.pdftotext_cmd,
        )
