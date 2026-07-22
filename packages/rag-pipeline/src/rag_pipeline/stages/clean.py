"""清洗阶段：把 status='downloaded' 文档的 md 清洗为 md_clean（源无关）。

流程：``get_docs_to_clean`` → 读 ``source_file``(md) → 用 DB manifest 把图片/附件 URL
替换成占位符 + 追加附件提取文本 → ``clean_markdown`` → 写 md_clean → ``update_clean_status``。

移植自旧 clean_md.py，去掉 ``find_md_file`` 目录遍历（改用 doc_meta.source_file 直取），
占位符/清洗规则复用 rag-core ``placeholders`` / ``cleaning``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_core import repository
from rag_core.cleaning import clean_markdown
from rag_core.hashing import file_md5
from rag_core.placeholders import att_placeholder, attachment_block, img_placeholder
from rag_pipeline.workspace import Workspace

logger = logging.getLogger(__name__)

__all__ = ["CleanStats", "replace_with_placeholders", "clean"]


@dataclass
class CleanStats:
    cleaned: int = 0
    failed: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)


def replace_with_placeholders(content: str, manifest: dict[str, Any], data_root: Path) -> str:
    """图片/附件 URL → 占位符，并把附件提取文本追加到正文末尾。纯文本，无网络。"""
    for img in manifest.get("images", []):
        clean_url = img["url"].split("?")[0]
        pattern = re.compile(r"!\[[^\]]*\]\(" + re.escape(clean_url) + r"(?:\?[^)]*)?\)")
        content = pattern.sub(img_placeholder(img["index"]), content)

    attachment_texts: list[str] = []
    for att in manifest.get("attachments", []):
        idx = att["index"]
        filename = att.get("filename", "附件")
        pattern = re.compile(r"\[[^\]]*\]\(" + re.escape(att["url"]) + r"\)")
        content = pattern.sub(att_placeholder(idx, filename), content)
        text_rel = att.get("extracted_text")
        if text_rel:
            tp = Path(data_root) / text_rel
            if tp.exists():
                attachment_texts.append(attachment_block(filename, tp.read_text(encoding="utf-8")))

    if attachment_texts:
        content += "\n".join(attachment_texts)
    return content


def _clean_rel(md_rel: str) -> str:
    """md 相对路径 → md_clean 相对路径（``.../md/x.md`` → ``.../md_clean/x.md``）。"""
    return md_rel.replace("/md/", "/md_clean/", 1) if "/md/" in md_rel else md_rel


def clean_doc(conn, doc: dict, workspace: Workspace) -> str:
    """清洗单篇，返回 md_clean 相对路径。"""
    doc_id = doc["doc_id"]
    md_abs = workspace.data_root / doc["source_file"]
    content = md_abs.read_text(encoding="utf-8")

    manifest = repository.build_manifest(conn, doc_id)
    content = replace_with_placeholders(content, manifest, workspace.data_root)
    cleaned = clean_markdown(content)

    clean_rel = _clean_rel(doc["source_file"])
    clean_abs = workspace.data_root / clean_rel
    clean_abs.parent.mkdir(parents=True, exist_ok=True)
    clean_abs.write_text(cleaned, encoding="utf-8")

    repository.update_clean_status(conn, doc_id, file_md5(clean_abs), clean_rel)
    return clean_rel


def clean(conn, workspace: Workspace, *, settings=None) -> CleanStats:
    """清洗所有待清洗文档，单篇失败隔离。"""
    stats = CleanStats()
    docs = repository.get_docs_to_clean(conn)
    logger.info("待清洗 %d 篇", len(docs))
    for doc in docs:
        try:
            rel = clean_doc(conn, doc, workspace)
            stats.cleaned += 1
            logger.info("[%s] cleaned → %s", doc["doc_id"], rel)
        except Exception as e:  # noqa: BLE001 - 单篇失败不影响其它
            logger.error("[%s] clean failed: %s", doc.get("doc_id"), e)
            stats.failed += 1
            stats.failures.append({"doc_id": doc.get("doc_id"), "error": str(e)})
    return stats
