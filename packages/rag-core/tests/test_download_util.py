import requests

import rag_core.download_util as du


def test_sanitize_title():
    title = 'a/b:c*?"<>|d'
    out = du.sanitize_title(title)
    assert len(out) == len(title)  # 逐字符替换，长度不变
    assert not any(c in out for c in '\\/*?:"<>|')
    assert out.startswith("a") and out.endswith("d")
    assert du.sanitize_title("plain name") == "plain name"


def test_extract_image_urls():
    body = "![alt](http://x/a.png) text ![](relative/b.png) ![](http://y/c.jpg)"
    assert du.extract_image_urls(body) == ["http://x/a.png", "http://y/c.jpg"]


def test_extract_attachment_urls():
    body = "![img](http://x/p.png) [报告](http://x/r.pdf?v=1) [x](http://x/note.md) [](http://x/d.docx)"
    out = du.extract_attachment_urls(body)
    assert {"filename": "报告", "url": "http://x/r.pdf?v=1"} in out
    assert {"filename": "d.docx", "url": "http://x/d.docx"} in out
    # .md 不在白名单，图片链接也不算附件
    assert all(a["url"] != "http://x/note.md" for a in out)
    assert all(not a["url"].endswith("p.png") for a in out)


def test_parse_cookie_string():
    # 无 '=' 的段被跳过；有 '=' 的按首个 '=' 切分
    assert du.parse_cookie_string("a=1; b=2; noequals") == {"a": "1", "b": "2"}
    assert du.parse_cookie_string("k=v=w") == {"k": "v=w"}
    assert du.parse_cookie_string("") == {}


class _FakeResp:
    def __init__(self, content, content_type="application/pdf", status=200):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(str(self._status))


def test_download_file_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(du.requests, "get", lambda *a, **k: _FakeResp(b"PDFDATA"))
    p = tmp_path / "sub" / "f.pdf"
    assert du.download_file("http://x/f.pdf", str(p)) == 7
    assert p.read_bytes() == b"PDFDATA"


def test_download_file_rejects_html_content_type(tmp_path, monkeypatch):
    monkeypatch.setattr(du.requests, "get", lambda *a, **k: _FakeResp(b"<html>", "text/html"))
    p = tmp_path / "f.pdf"
    try:
        du.download_file("http://x", str(p))
        raise AssertionError("should have raised")
    except ValueError:
        pass
    assert not p.exists()


def test_download_file_rejects_html_body(tmp_path, monkeypatch):
    resp = _FakeResp(b"  <!DOCTYPE HTML><html>", "application/octet-stream")
    monkeypatch.setattr(du.requests, "get", lambda *a, **k: resp)
    p = tmp_path / "f.pdf"
    try:
        du.download_file("http://x", str(p))
        raise AssertionError("should have raised")
    except ValueError:
        pass
    assert not p.exists()


def test_download_with_retry_gives_up_after_max(monkeypatch):
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("x")

    monkeypatch.setattr(du, "download_file", boom)
    monkeypatch.setattr(du.time, "sleep", lambda s: None)
    try:
        du.download_with_retry("http://x", "p", max_retries=3)
        raise AssertionError("should have raised")
    except requests.exceptions.ConnectionError:
        pass
    assert calls["n"] == 3


def test_download_with_retry_succeeds_after_transient(monkeypatch):
    seq = [requests.exceptions.Timeout("t"), 42]

    def flaky(*a, **k):
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(du, "download_file", flaky)
    monkeypatch.setattr(du.time, "sleep", lambda s: None)
    assert du.download_with_retry("u", "p", max_retries=3) == 42


def test_download_with_retry_no_retry_on_http_error(monkeypatch):
    calls = {"n": 0}

    def http_err(*a, **k):
        calls["n"] += 1
        raise requests.HTTPError("404")

    monkeypatch.setattr(du, "download_file", http_err)
    monkeypatch.setattr(du.time, "sleep", lambda s: None)
    try:
        du.download_with_retry("http://x", "p", max_retries=3)
        raise AssertionError("should have raised")
    except requests.HTTPError:
        pass
    assert calls["n"] == 1  # HTTP 错误不重试
