"""落盘布局：显式 ``data_root`` 取代旧 download.py 的 ``SCRIPT_DIR``/``DATE_DIR``。

目录结构（沿用旧布局，仅根基准可配）::

    <data_root>/<date>/<scope.dir_name()>/
        raw/                      # 原始 API 响应存档
        md/<doc_id>_<title>.md    # 归一化 markdown
        assets/<doc_id>/images/   # 图片
        assets/<doc_id>/files/    # 附件
        assets/<doc_id>/texts/    # 附件提取的文本

``data_root`` 即静态资源服务根（挂在 ``/assets/``），故 ``served_url`` 直接由
data_root 相对路径拼成，不再像旧代码去 ``output/`` 前缀。所有相对路径用 posix 分隔符，
与 DB 中 ``source_file``/``local_file`` 及 chunk_with_images 的 ``served_url`` 口径一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rag_core.download_util import sanitize_title
from rag_pipeline.connectors.base import SourceScope

__all__ = ["Workspace"]


@dataclass
class Workspace:
    """某次同步运行的落盘上下文。``date`` 显式传入以便测试可复现。"""

    data_root: Path
    date: str

    def __post_init__(self) -> None:
        self.data_root = Path(self.data_root)

    @classmethod
    def for_run(cls, data_root: str | Path, date: str | None = None) -> Workspace:
        """构造运行工作区；``date`` 缺省取今天（``YYYYMMDD``）。"""
        return cls(Path(data_root), date or datetime.now().strftime("%Y%m%d"))

    # ---------- 目录 ----------

    def scope_dir(self, scope: SourceScope) -> Path:
        return self.data_root / self.date / scope.dir_name()

    def raw_dir(self, scope: SourceScope) -> Path:
        return self.scope_dir(scope) / "raw"

    def md_dir(self, scope: SourceScope) -> Path:
        return self.scope_dir(scope) / "md"

    def assets_dir(self, scope: SourceScope, doc_id) -> Path:
        return self.scope_dir(scope) / "assets" / str(doc_id)

    def images_dir(self, scope: SourceScope, doc_id) -> Path:
        return self.assets_dir(scope, doc_id) / "images"

    def files_dir(self, scope: SourceScope, doc_id) -> Path:
        return self.assets_dir(scope, doc_id) / "files"

    def texts_dir(self, scope: SourceScope, doc_id) -> Path:
        return self.assets_dir(scope, doc_id) / "texts"

    # ---------- 路径换算 ----------

    def rel(self, path: str | Path) -> str:
        """绝对路径 → 相对 data_root 的 posix 字符串（存 DB / 供 served_url）。"""
        return Path(path).relative_to(self.data_root).as_posix()

    def served_url(self, rel_path: str) -> str:
        """data_root 相对路径 → 静态服务 URL（``/assets/`` 挂载 data_root）。"""
        return f"/assets/{str(rel_path).replace(chr(92), '/').lstrip('/')}"

    # ---------- 写入 ----------

    def write_md(self, scope: SourceScope, doc_id, title: str, body: str) -> str:
        """写 markdown 文件，返回相对 data_root 的 posix 路径。"""
        md_dir = self.md_dir(scope)
        md_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{doc_id}_{sanitize_title(title)}.md"
        path = md_dir / filename
        path.write_text(body, encoding="utf-8")
        return self.rel(path)
