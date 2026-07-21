from rag_core.chunking import chunk_text


def test_empty():
    # 忠实于原始行为：re.split(r"\n\n+", "") 返回 [""]，故空输入产出 [""]
    assert chunk_text("") == [""]


def test_single_chunk_short():
    assert chunk_text("hello world") == ["hello world"]


def test_split_large_paragraphs():
    # 每段 600 字，chunk_size*2=1000，每加一段就超限 → 每段独立成块（重叠因单段>200 而为空）
    paras = ["A" * 600, "B" * 600, "C" * 600]
    chunks = chunk_text("\n\n".join(paras), chunk_size=500, overlap=100)
    assert chunks == paras


def test_paragraphs_grouped_until_limit():
    # 每段 100 字，累计到 >1000 才切
    paras = ["p" * 100 for _ in range(15)]
    chunks = chunk_text("\n\n".join(paras), chunk_size=500, overlap=100)
    assert len(chunks) >= 2
    # 每个 chunk 由完整段落用 \n\n 连接
    for c in chunks:
        for part in c.split("\n\n"):
            assert part == "p" * 100
