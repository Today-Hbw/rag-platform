"""stages/clean.py 单测：占位符替换 + 清洗 + DB 更新，全离线（monkeypatch repository）。"""

from rag_pipeline.stages import clean as cl
from rag_pipeline.workspace import Workspace


class RepoSpy:
    def __init__(self, docs, manifest):
        self._docs = docs
        self._manifest = manifest
        self.updates = []

    def get_docs_to_clean(self, conn):
        return list(self._docs)

    def build_manifest(self, conn, doc_id):
        return self._manifest

    def update_clean_status(self, conn, doc_id, md_hash, clean_rel):
        self.updates.append((doc_id, md_hash, clean_rel))


def test_replace_with_placeholders_images_attachments_and_text(tmp_path):
    (tmp_path / "t.txt").write_text("附件正文", encoding="utf-8")
    manifest = {
        "images": [{"index": 0, "url": "http://cdn/a.png?x=1"}],
        "attachments": [
            {
                "index": 0, "url": "http://x/r.pdf",
                "filename": "报告.pdf", "extracted_text": "t.txt",
            },
        ],
    }
    content = "![](http://cdn/a.png?x=1) 见 [下载](http://x/r.pdf)"
    out = cl.replace_with_placeholders(content, manifest, tmp_path)
    assert "[IMG_0]" in out
    assert "[ATT_0:报告.pdf]" in out
    assert "[附件内容: 报告.pdf]" in out and "附件正文" in out


def test_clean_rel_maps_md_to_md_clean():
    assert cl._clean_rel("20260722/kb_42/md/5_t.md") == "20260722/kb_42/md_clean/5_t.md"
    assert cl._clean_rel("no_md_segment.md") == "no_md_segment.md"  # 无 /md/ 原样


def test_clean_doc_writes_and_updates(monkeypatch, tmp_path):
    # 落一个 md 文件
    md_rel = "20260722/kb_42/md/5_t.md"
    md_abs = tmp_path / md_rel
    md_abs.parent.mkdir(parents=True)
    md_abs.write_text("# 标题\n\n<p>正文</p>\n\n\n\n结尾", encoding="utf-8")

    spy = RepoSpy(docs=[], manifest={"images": [], "attachments": []})
    monkeypatch.setattr(cl, "repository", spy)
    ws = Workspace(tmp_path, "20260722")
    rel = cl.clean_doc(object(), {"doc_id": 5, "source_file": md_rel}, ws)

    assert rel == "20260722/kb_42/md_clean/5_t.md"
    clean_abs = tmp_path / rel
    assert clean_abs.exists()
    cleaned = clean_abs.read_text(encoding="utf-8")
    assert "<p>" not in cleaned  # HTML 被清掉
    assert "\n\n\n" not in cleaned  # 多空行被合并
    assert spy.updates[0][0] == 5  # doc_id
    assert spy.updates[0][2] == rel  # clean_rel


def test_clean_isolates_failure(monkeypatch, tmp_path):
    docs = [
        {"doc_id": 1, "source_file": "missing/md/x.md"},  # 文件不存在 → 失败
    ]
    spy = RepoSpy(docs=docs, manifest={"images": [], "attachments": []})
    monkeypatch.setattr(cl, "repository", spy)
    ws = Workspace(tmp_path, "20260722")
    stats = cl.clean(object(), ws)
    assert stats.cleaned == 0
    assert stats.failed == 1
    assert stats.failures[0]["doc_id"] == 1
