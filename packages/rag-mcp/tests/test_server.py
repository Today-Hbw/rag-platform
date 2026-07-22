"""rag-mcp server 单测：格式化(纯) + HTTP 客户端(respx) + 工具处理器。"""

import asyncio

import httpx
import respx

from rag_mcp.server import (
    RemoteSearchClient,
    _handle_health,
    _handle_search,
    format_results,
)


def test_format_results_renders_markdown():
    result = {
        "total_results": 2,
        "elapsed_ms": 12,
        "results": [
            {
                "doc_title": "社保补缴",
                "hybrid_score": 0.1234,
                "vector_score": 0.5,
                "bm25_score": 0.3,
                "source_url": "http://x/1",
                "chunk_text": "正文" * 400,  # 超 500 字应被截断
            }
        ],
    }
    out = format_results(result, "社保", 10)
    assert "## 搜索结果：'社保'" in out
    assert "找到 2 条结果" in out
    assert "社保补缴" in out
    assert "0.1234" in out
    # chunk_text 截到 500
    assert out.count("正文") <= 250 + 1


def test_format_results_empty():
    out = format_results({"total_results": 0, "results": []}, "无", 10)
    assert "找到 0 条结果" in out


def test_client_base_url_stripped():
    c = RemoteSearchClient("http://host:8090/")
    assert c.base_url == "http://host:8090"


def test_client_search_calls_endpoint():
    with respx.mock:
        route = respx.post("http://svc/search").mock(
            return_value=httpx.Response(200, json={"total_results": 1, "results": []})
        )
        c = RemoteSearchClient("http://svc")
        out = asyncio.run(c.search("q", top_k=5))
        assert out["total_results"] == 1
        assert route.called
        sent = route.calls[0].request
        assert b'"top_k":5' in sent.content or b'"top_k": 5' in sent.content


def test_client_health_true_false():
    with respx.mock:
        respx.get("http://svc/health").mock(return_value=httpx.Response(200))
        assert asyncio.run(RemoteSearchClient("http://svc").health()) is True
    with respx.mock:
        respx.get("http://svc/health").mock(return_value=httpx.Response(503))
        assert asyncio.run(RemoteSearchClient("http://svc").health()) is False


def test_client_health_connect_error_is_false():
    with respx.mock:
        respx.get("http://svc/health").mock(side_effect=httpx.ConnectError("x"))
        assert asyncio.run(RemoteSearchClient("http://svc").health()) is False


def test_handle_search_empty_query():
    c = RemoteSearchClient("http://svc")
    out = asyncio.run(_handle_search(c, {"query": "  "}))
    assert "不能为空" in out[0].text


def test_handle_search_clamps_top_k_and_formats():
    with respx.mock:
        respx.post("http://svc/search").mock(
            return_value=httpx.Response(200, json={"total_results": 0, "results": []})
        )
        c = RemoteSearchClient("http://svc")
        out = asyncio.run(_handle_search(c, {"query": "q", "top_k": 999}))
        assert "搜索结果" in out[0].text


def test_handle_search_http_error():
    with respx.mock:
        respx.post("http://svc/search").mock(return_value=httpx.Response(500, text="boom"))
        c = RemoteSearchClient("http://svc")
        out = asyncio.run(_handle_search(c, {"query": "q"}))
        assert "HTTP 500" in out[0].text


def test_handle_search_connect_error():
    with respx.mock:
        respx.post("http://svc/search").mock(side_effect=httpx.ConnectError("x"))
        c = RemoteSearchClient("http://svc")
        out = asyncio.run(_handle_search(c, {"query": "q"}))
        assert "无法连接" in out[0].text


def test_handle_health_ok():
    with respx.mock:
        respx.get("http://svc/health").mock(return_value=httpx.Response(200))
        out = asyncio.run(_handle_health(RemoteSearchClient("http://svc")))
        assert "✅" in out[0].text
