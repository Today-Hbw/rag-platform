import hashlib

from rag_core.hashing import file_md5, text_md5


def test_text_md5_known_value():
    assert text_md5("hello") == hashlib.md5(b"hello").hexdigest()


def test_text_md5_utf8():
    assert text_md5("语雀") == hashlib.md5("语雀".encode()).hexdigest()


def test_file_md5(tmp_path):
    p = tmp_path / "f.bin"
    data = b"a" * 20000  # 跨多个 8192 分块
    p.write_bytes(data)
    assert file_md5(p) == hashlib.md5(data).hexdigest()
