"""日志配置。迁自 run.py:setup_logging（控制台 + 按时间戳的文件），data_root 显式传入。"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

__all__ = ["setup_logging"]


def setup_logging(
    log_dir: str | Path,
    *,
    level: int = logging.INFO,
    run_ts: str | None = None,
) -> tuple[logging.Logger, Path]:
    """配置根 logger：控制台（仅消息）+ 文件（带时间/级别，UTF-8）。

    Args:
        log_dir: 日志目录（会自动创建）。
        run_ts: 日志文件时间戳，默认取当前时间（``run_YYYYmmdd_HHMMSS.log``）。
    Returns:
        (模块 logger, 日志文件路径)
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = run_ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"run_{ts}.log"

    root = logging.getLogger()
    root.setLevel(level)

    # Windows 控制台可能非 UTF-8，尽力切到 utf-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(message)s"))

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )

    root.addHandler(console)
    root.addHandler(file_handler)
    return logging.getLogger(__name__), log_file
