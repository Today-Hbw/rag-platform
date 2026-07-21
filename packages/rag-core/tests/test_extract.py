import zipfile

import pytest

from rag_core.extract import extract_text_from_file, is_text_garbled
from rag_core.extract.tools import ToolPaths
from rag_core.settings import Settings

# ---------- garbled ----------

def test_is_text_garbled():
    assert is_text_garbled("") is True
    assert is_text_garbled("short") is True
    good = "这是一段正常的中文文档内容，包含标点符号与数字 123。" * 3
    assert is_text_garbled(good) is False
    assert is_text_garbled("�?�?�?" * 20) is True


# ---------- tools ----------

def test_toolpaths_settings_override(monkeypatch):
    monkeypatch.setenv("RAG_EXTRACT__TESSERACT_CMD", "/opt/tess")
    monkeypatch.setenv("RAG_EXTRACT__LIBREOFFICE_BIN", "/opt/soffice")
    tp = ToolPaths.resolve(Settings())
    assert tp.tesseract_cmd == "/opt/tess"
    assert tp.libreoffice_bin == "/opt/soffice"
    assert tp.antiword_cmd == "antiword"  # 默认
    assert tp.pdftotext_cmd == "pdftotext"


def test_toolpaths_falls_back_to_which(monkeypatch):
    import rag_core.extract.tools as t

    monkeypatch.delenv("RAG_EXTRACT__TESSERACT_CMD", raising=False)
    monkeypatch.setattr(
        t.shutil, "which", lambda n: "/usr/bin/tesseract" if n == "tesseract" else None
    )
    tp = ToolPaths.resolve(Settings())
    assert tp.tesseract_cmd == "/usr/bin/tesseract"


# ---------- dispatch: txt / unsupported ----------

def test_extract_txt(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("纯文本内容\nsecond line", encoding="utf-8")
    assert extract_text_from_file(str(p), "txt") == "纯文本内容\nsecond line"


def test_extract_csv(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("a,b,c", encoding="utf-8")
    assert extract_text_from_file(str(p), "csv") == "a,b,c"


def test_extract_unsupported_returns_none(tmp_path):
    p = tmp_path / "a.rar"
    p.write_bytes(b"whatever")
    assert extract_text_from_file(str(p), "rar") is None


def test_file_type_dot_and_case_insensitive(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    assert extract_text_from_file(str(p), ".TXT") == "x"


# ---------- office (extras 已装) ----------

def test_extract_docx(tmp_path):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("你好世界")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "单元格A"
    table.rows[0].cells[1].text = "单元格B"
    p = tmp_path / "d.docx"
    doc.save(str(p))
    out = extract_text_from_file(str(p), "docx")
    assert "你好世界" in out
    assert "单元格A" in out and "单元格B" in out


def test_extract_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "表头"
    ws["B1"] = 42
    p = tmp_path / "s.xlsx"
    wb.save(str(p))
    out = extract_text_from_file(str(p), "xlsx")
    assert "工作表" in out and "表头" in out and "42" in out


def test_extract_pptx(tmp_path):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    box = slide.shapes.add_textbox(0, 0, 100, 100)
    box.text_frame.text = "幻灯片文本"
    p = tmp_path / "p.pptx"
    prs.save(str(p))
    out = extract_text_from_file(str(p), "pptx")
    assert "幻灯片文本" in out


# ---------- zip 递归 ----------

def test_extract_zip_recurses_into_txt(tmp_path):
    inner = tmp_path / "note.txt"
    inner.write_text("压缩包内文本", encoding="utf-8")
    zpath = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(inner, "note.txt")
    out = extract_text_from_file(str(zpath), "zip")
    assert "压缩包内文本" in out
    assert "[note.txt]" in out
