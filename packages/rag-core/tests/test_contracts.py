from rag_core.contracts import ChunkPayload, DocFacets


def _sample() -> ChunkPayload:
    return ChunkPayload(
        source="yuque",
        doc_id=123,
        doc_title="标题",
        chunk_index=0,
        chunk_text="正文",
        facets=DocFacets(
            namespace="teamA",
            collection_id="1117288",
            collection_slug="kb",
            doc_key="abc",
            dims={"lang": "zh"},
        ),
        source_url="https://example.com/x",
        has_image=True,
        images=[{"url": "u", "served_url": "/assets/x.png"}],
    )


def test_to_payload_is_flat_and_generalized():
    d = _sample().to_payload()
    # facets 展开为顶层键，便于 Qdrant 过滤
    assert d["source"] == "yuque"
    assert d["collection_id"] == "1117288"
    assert d["namespace"] == "teamA"
    assert d["source_dims"] == {"lang": "zh"}
    assert "facets" not in d
    # 不再有语雀专有列名
    assert "team_code" not in d and "book_id" not in d and "book_slug" not in d


def test_roundtrip():
    p = _sample()
    assert ChunkPayload.from_payload(p.to_payload()) == p


def test_from_payload_ignores_unknown_and_fills_missing():
    d = {
        "source": "yuque",
        "doc_id": 1,
        "doc_title": "t",
        "chunk_index": 2,
        "chunk_text": "c",
        "collection_id": "99",
        "extra_key": "ignored",
    }
    p = ChunkPayload.from_payload(d)
    assert p.doc_id == 1
    assert p.facets.collection_id == "99"
    assert p.source_url == ""  # 缺失用默认
    assert p.facets.dims == {}
    assert not hasattr(p, "extra_key")


def test_dims_omitted_when_empty():
    p = ChunkPayload(source="s", doc_id=1, doc_title="t", chunk_index=0, chunk_text="c")
    assert "source_dims" not in p.to_payload()  # 空 dims 不写入 payload
