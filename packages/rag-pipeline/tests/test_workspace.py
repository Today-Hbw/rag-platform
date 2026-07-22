"""workspace.py 单测：目录布局 / 路径换算 / 写 md。"""

from rag_core.contracts import DocFacets
from rag_pipeline.connectors.base import SourceScope
from rag_pipeline.workspace import Workspace


def _scope():
    return SourceScope(scope_id="42", facets=DocFacets(collection_slug="kb", collection_id="42"))


def test_dir_layout(tmp_path):
    ws = Workspace(tmp_path, "20260722")
    s = _scope()
    assert ws.scope_dir(s) == tmp_path / "20260722" / "kb_42"
    assert ws.md_dir(s) == tmp_path / "20260722" / "kb_42" / "md"
    assert ws.raw_dir(s).name == "raw"
    assert ws.images_dir(s, 7) == ws.assets_dir(s, 7) / "images"
    assert ws.files_dir(s, 7).parent == ws.assets_dir(s, 7)
    assert ws.texts_dir(s, 7).name == "texts"


def test_rel_and_served_url(tmp_path):
    ws = Workspace(tmp_path, "20260722")
    p = tmp_path / "20260722" / "kb_42" / "assets" / "7" / "images" / "a.png"
    rel = ws.rel(p)
    assert rel == "20260722/kb_42/assets/7/images/a.png"  # posix，相对 data_root
    assert ws.served_url(rel) == "/assets/20260722/kb_42/assets/7/images/a.png"


def test_served_url_normalizes_backslash_and_leading_slash(tmp_path):
    ws = Workspace(tmp_path, "d")
    assert ws.served_url("a\\b\\c.png") == "/assets/a/b/c.png"
    assert ws.served_url("/x/y") == "/assets/x/y"


def test_write_md_returns_rel_and_writes_file(tmp_path):
    ws = Workspace(tmp_path, "20260722")
    s = _scope()
    rel = ws.write_md(s, 7, 'T/i:tle*?', "# body")
    assert rel == "20260722/kb_42/md/7_T_i_tle__.md"  # 标题非法字符被清洗
    written = tmp_path / rel
    assert written.read_text(encoding="utf-8") == "# body"


def test_for_run_uses_given_date(tmp_path):
    ws = Workspace.for_run(tmp_path, "20991231")
    assert ws.date == "20991231"
    assert ws.data_root == tmp_path
