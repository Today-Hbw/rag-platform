from rag_core.placeholders import (
    att_placeholder,
    attachment_block,
    find_img_indices,
    img_placeholder,
    render_readable,
)


def test_placeholder_builders():
    assert img_placeholder(3) == "[IMG_3]"
    assert att_placeholder(2, "a.pdf") == "[ATT_2:a.pdf]"


def test_find_img_indices_order_and_dupes():
    assert find_img_indices("x [IMG_1] y [IMG_0] z [IMG_1]") == [1, 0, 1]


def test_render_readable_image_with_alt():
    assert render_readable("see [IMG_0]", alts={0: "图表"}) == "see [图片: 图表]"


def test_render_readable_image_no_alt():
    assert render_readable("see [IMG_5]") == "see [图片]"


def test_render_readable_attachment_marker():
    assert render_readable("[ATT_1:report.pdf]") == "[附件: report.pdf]"


def test_render_readable_strips_attachment_content_markers():
    block = attachment_block("r.pdf", "正文内容")
    out = render_readable(block)
    assert "正文内容" in out
    assert "附件内容" not in out
    assert "[附件内容结束]" not in out
