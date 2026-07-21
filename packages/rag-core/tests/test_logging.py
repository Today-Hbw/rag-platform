import logging

from rag_core.logging import setup_logging


def test_setup_logging_creates_file(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        _, path = setup_logging(tmp_path, run_ts="20260721_000000")
        assert path.exists()
        assert path.name == "run_20260721_000000.log"
        logging.getLogger().info("hello")
        assert "hello" in path.read_text(encoding="utf-8")
    finally:
        # 还原 root handlers，避免污染其他测试
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()
