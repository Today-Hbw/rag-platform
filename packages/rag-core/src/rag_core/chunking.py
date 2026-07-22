"""文本分块。忠实移植 vectorize.py chunk_text / chunk_with_images（源无关）。

``chunk_with_images`` 依赖文件系统路径基准（旧代码硬编码 SCRIPT_DIR，现改为显式
``data_root``，由 pipeline 侧的 Workspace 提供），故只接收 data_root 字符串而非
Workspace 对象，避免 rag-core 反向依赖 rag-pipeline。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = ["chunk_text", "chunk_with_images"]


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


def chunk_with_images(
    text: str,
    manifest: dict[str, Any],
    data_root: str | Path,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[tuple[str, list[dict[str, str]]]]:
    """分块并关联每块引用的图片，同时把占位符还原为可读描述。

    忠实移植 vectorize.py:436，仅把路径基准 SCRIPT_DIR 换成显式 ``data_root``：
    manifest 中 ``images[i].local_path`` 相对 ``data_root``；``served_url`` 直接由
    相对路径拼 ``/assets/<rel>``（旧代码另去 ``output/`` 前缀，新布局 data_root 即服务根）。

    Args:
        text: 含 ``[IMG_n]`` / ``[ATT_n:...]`` 占位符的清洗后 markdown。
        manifest: ``{"images": [{url, local_path, status, alt?}, ...]}``。
        data_root: 资源本地路径基准（Workspace.data_root）。

    Returns:
        ``[(chunk_readable, [{"url","local_path","served_url"}, ...]), ...]``。
    """
    chunks = chunk_text(text, chunk_size, overlap)
    images = manifest.get("images", [])
    root = Path(data_root)
    result: list[tuple[str, list[dict[str, str]]]] = []

    for chunk in chunks:
        img_indices = [int(m) for m in re.findall(r"\[IMG_(\d+)\]", chunk)]

        img_infos: list[dict[str, str]] = []
        for idx in img_indices:
            if idx < len(images) and images[idx].get("status") == "ok":
                local_path = images[idx].get("local_path", "")
                if local_path and (root / local_path).exists():
                    served = str(local_path).replace("\\", "/").lstrip("/")
                    img_infos.append(
                        {
                            "url": images[idx].get("url", ""),
                            "local_path": local_path,
                            "served_url": f"/assets/{served}",
                        }
                    )

        chunk_readable = chunk
        for idx in set(img_indices):
            if idx < len(images):
                alt = images[idx].get("alt", "")
                desc = f"[图片: {alt}]" if alt else "[图片]"
                chunk_readable = chunk_readable.replace(f"[IMG_{idx}]", desc)

        # 附件占位符：保留文件名语义，去掉包裹标记
        chunk_readable = re.sub(r"\[ATT_\d+:([^\]]+)\]", r"[附件: \1]", chunk_readable)
        chunk_readable = re.sub(r"\[附件内容: [^\]]+\]", "", chunk_readable)
        chunk_readable = re.sub(r"\[附件内容结束\]", "", chunk_readable)

        result.append((chunk_readable, img_infos))

    return result
