"""yuque connector 单测：分页/详情解析/资源/source_url/鉴权，全离线（fake session）。"""

import pytest

from rag_pipeline.connectors.yuque import YuqueBook, YuqueConnector


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self._status >= 400:
            raise AssertionError(f"HTTP {self._status}")


class _FakeSession:
    """按 (url, offset) 返回预置响应，并记录调用以便断言分页/鉴权。"""

    def __init__(self, list_pages=None, details=None):
        self.list_pages = list_pages or []  # list_docs 的分页响应（按 offset 顺序）
        self.details = details or {}  # doc_id -> detail payload
        self.calls = []

    def get(self, url, headers=None, params=None):
        self.calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        if url.endswith("/docs"):
            offset = (params or {}).get("offset", 0)
            idx = offset // (params or {}).get("limit", 100)
            page = self.list_pages[idx] if idx < len(self.list_pages) else []
            return _Resp({"data": page})
        doc_id = url.rsplit("/", 1)[-1]
        return _Resp(self.details[doc_id])


def _book():
    return YuqueBook(book_id="42", book_slug="kb", namespace="teamx", title="KB")


def test_scopes_maps_facets():
    c = YuqueConnector([_book()], token="T")
    scopes = c.scopes()
    assert len(scopes) == 1
    s = scopes[0]
    assert s.scope_id == "42"
    assert s.facets.collection_id == "42"
    assert s.facets.collection_slug == "kb"
    assert s.facets.namespace == "teamx"
    assert s.dir_name() == "kb_42"


def test_list_docs_paginates_and_normalizes_version():
    # 两页：第一页满 100... 用 page_size=2 简化边界
    page1 = [
        {"id": 1, "title": "a", "slug": "sa", "content_updated_at": "2026-01-01T00:00:00.000Z"},
        {"id": 2, "title": "b", "slug": "sb", "content_updated_at": "2026-01-02T00:00:00.000Z"},
    ]
    page2 = [
        {"id": 3, "title": "c", "slug": "sc", "content_updated_at": "2026-01-03T00:00:00.000Z"},
    ]
    sess = _FakeSession(list_pages=[page1, page2])
    c = YuqueConnector([_book()], token="T", page_size=2, session=sess)
    refs = c.list_docs(c.scopes()[0])
    assert [r.doc_id for r in refs] == [1, 2, 3]
    assert refs[0].source_version == "2026-01-01 00:00:00"  # 已归一化
    assert refs[0].doc_key == "sa"
    # 分页：page1 满 2 → 再取 offset=2 拿到 page2（1 条 <2 停）→ 共 2 次 list 调用
    list_calls = [x for x in sess.calls if x["url"].endswith("/docs")]
    assert [x["params"]["offset"] for x in list_calls] == [0, 2]
    assert all(x["headers"]["X-Auth-Token"] == "T" for x in list_calls)


def test_list_docs_stops_when_page_not_full():
    sess = _FakeSession(list_pages=[[{"id": 1, "slug": "s", "content_updated_at": "x"}]])
    c = YuqueConnector([_book()], token="T", page_size=100, session=sess)
    refs = c.list_docs(c.scopes()[0])
    assert len(refs) == 1
    assert len([x for x in sess.calls if x["url"].endswith("/docs")]) == 1


def test_fetch_parses_body_resources_and_source_url():
    body = "# H\n![](http://img/a.png)\n[报告](http://x/r.pdf)"
    sess = _FakeSession(
        details={
            "1": {
                "data": {
                    "body": body,
                    "slug": "sa",
                    "title": "标题",
                    "book": {"slug": "kb2"},
                    "content_updated_at": "2026-05-05T12:00:00.000Z",
                }
            }
        }
    )
    c = YuqueConnector(
        [_book()],
        token="T",
        session=sess,
        url_template="https://s.yuque.com/{namespace}/{collection_slug}/{doc_key}",
    )
    scope = c.scopes()[0]
    from rag_pipeline.connectors.base import DocRef

    detail = c.fetch(scope, DocRef(doc_id=1, doc_key="sa"))
    assert detail.title == "标题"
    assert detail.body == body
    assert detail.source_version == "2026-05-05 12:00:00"
    # book.slug 覆盖 scope 的 collection_slug
    assert detail.facets.collection_slug == "kb2"
    assert detail.facets.doc_key == "sa"
    assert detail.facets.collection_id == "42"
    assert detail.source_url == "https://s.yuque.com/teamx/kb2/sa"
    kinds = [(r.kind, r.url) for r in detail.resources]
    assert ("image", "http://img/a.png") in kinds
    assert ("attachment", "http://x/r.pdf") in kinds


def test_build_source_url_empty_when_no_doc_key():
    c = YuqueConnector([_book()], token="T")
    from rag_pipeline.connectors.base import DocDetail

    d = DocDetail(doc_id=1, title="t", body="")  # facets.doc_key 空
    assert c.build_source_url(c.scopes()[0], d) == ""


def test_asset_auth_headers_and_cookies():
    c = YuqueConnector([_book()], token="T", cookie="a=1; b=2")
    auth = c.asset_auth(c.scopes()[0])
    assert auth.headers == {"X-Auth-Token": "T"}
    assert auth.cookies == {"a": "1", "b": "2"}


def test_per_book_token_override():
    book = YuqueBook(book_id="9", book_slug="k", token="BOOKTOK")
    sess = _FakeSession(list_pages=[[]])
    c = YuqueConnector([book], token="GLOBAL", session=sess)
    c.list_docs(c.scopes()[0])
    assert sess.calls[0]["headers"]["X-Auth-Token"] == "BOOKTOK"


def test_source_is_yuque():
    assert YuqueConnector([], token="").source == "yuque"


@pytest.mark.parametrize("missing", [{}, {"data": {}}])
def test_fetch_tolerates_missing_fields(missing):
    sess = _FakeSession(details={"7": missing})
    c = YuqueConnector([_book()], token="T", session=sess)
    from rag_pipeline.connectors.base import DocRef

    detail = c.fetch(c.scopes()[0], DocRef(doc_id=7, doc_key="fallback", title="ft"))
    assert detail.doc_id == 7
    assert detail.body == ""
    assert detail.facets.doc_key == "fallback"  # 回退到 ref.doc_key
    assert detail.title == "ft"
