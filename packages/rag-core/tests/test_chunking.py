from rag_core.chunking import chunk_text, chunk_with_images


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


# ---------- chunk_with_images ----------

def test_chunk_with_images_links_existing_image(tmp_path):
    # 落一个真实图片文件，local_path 相对 data_root
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"x")
    manifest = {
        "images": [
            {"url": "http://cdn/a.png", "local_path": "images/a.png", "status": "ok", "alt": "图A"},
        ]
    }
    text = "前言\n\n[IMG_0]"
    out = chunk_with_images(text, manifest, tmp_path)
    # 占位符被替换为可读描述
    joined = "".join(c for c, _ in out)
    assert "[图片: 图A]" in joined
    assert "[IMG_0]" not in joined
    # 关联信息带 served_url
    infos = [info for _, imgs in out for info in imgs]
    assert infos[0]["served_url"] == "/assets/images/a.png"
    assert infos[0]["url"] == "http://cdn/a.png"


def test_chunk_with_images_skips_missing_or_failed(tmp_path):
    manifest = {
        "images": [
            {"url": "u0", "local_path": "images/missing.png", "status": "ok"},  # 文件不存在
            {"url": "u1", "local_path": "images/x.png", "status": "failed"},  # 状态失败
        ]
    }
    text = "[IMG_0] 和 [IMG_1]"
    out = chunk_with_images(text, manifest, tmp_path)
    infos = [info for _, imgs in out for info in imgs]
    assert infos == []  # 都不关联
    # 但占位符仍被替换为通用 [图片]
    assert "[图片]" in out[0][0]


def test_chunk_with_images_cleans_attachment_placeholders(tmp_path):
    text = "见 [ATT_0:合同.pdf]\n\n[附件内容: 合同.pdf]正文[附件内容结束]"
    out = chunk_with_images(text, {"images": []}, tmp_path)
    joined = "".join(c for c, _ in out)
    assert "[附件: 合同.pdf]" in joined
    assert "[ATT_0:" not in joined
    assert "[附件内容:" not in joined and "[附件内容结束]" not in joined
