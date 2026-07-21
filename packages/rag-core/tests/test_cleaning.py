from rag_core.cleaning import clean_markdown


def test_strip_tags_and_br():
    assert clean_markdown("a<br/>b") == "a\nb\n"


def test_html_comment_removed():
    assert clean_markdown("x<!-- hidden -->y") == "xy\n"


def test_entities_unescaped():
    assert clean_markdown("a &amp; b &lt;c&gt;") == "a & b <c>\n"


def test_zero_width_removed():
    assert clean_markdown("a​b‌﻿c") == "abc\n"


def test_collapse_blank_lines():
    assert clean_markdown("a\n\n\n\n\nb") == "a\n\nb\n"


def test_code_block_indent_preserved():
    src = "```\n    indented\n```"
    out = clean_markdown(src)
    assert "    indented" in out


def test_outside_code_block_stripped():
    out = clean_markdown("   spaced   ")
    assert out == "spaced\n"


def test_table_cells_to_tabs():
    out = clean_markdown("<tr><td>a</td><td>b</td></tr>")
    assert "\t" in out
