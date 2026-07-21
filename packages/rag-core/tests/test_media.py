import base64

import pytest

from rag_core.media import (
    SUPPORTED_IMAGE_MIMES,
    detect_mime_from_data,
    detect_mime_from_file,
    guess_mime_from_base64,
    guess_mime_from_ext,
    guess_mime_from_path,
    image_to_base64,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff" + b"\x00" * 12
GIF = b"GIF89a" + b"\x00" * 8
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4
BMP = b"BM" + b"\x00" * 12
TIFF = b"II\x2a\x00" + b"\x00" * 12


@pytest.mark.parametrize(
    "data,expected",
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF, "image/gif"),
        (WEBP, "image/webp"),
        (BMP, "image/bmp"),
        (TIFF, "image/tiff"),
        (b"\x00" * 4, None),  # 太短
        (b"nonsense____", None),  # 无法识别
    ],
)
def test_detect_mime_from_data(data, expected):
    assert detect_mime_from_data(data) == expected


def test_gif_not_in_supported():
    # 记录已知行为：gif 能被检测但不在 embedding 白名单
    assert "image/gif" not in SUPPORTED_IMAGE_MIMES


def test_guess_mime_from_path():
    assert guess_mime_from_path("a.PNG") == "image/png"
    assert guess_mime_from_path("a.jpeg") == "image/jpeg"
    assert guess_mime_from_path("a.bmp") == "image/bmp"
    assert guess_mime_from_path("a.unknown") == "image/png"  # 默认


def test_guess_mime_from_base64():
    assert guess_mime_from_base64(base64.b64encode(JPEG).decode()) == "image/jpeg"
    assert guess_mime_from_base64(base64.b64encode(PNG).decode()) == "image/png"


def test_image_to_base64_ok(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(PNG)
    b64, mime = image_to_base64(p)
    assert mime == "image/png"
    assert base64.b64decode(b64) == PNG


def test_image_to_base64_too_large(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(PNG)
    assert image_to_base64(p, max_size_mb=0) == (None, None)


def test_image_to_base64_unknown_format(tmp_path):
    p = tmp_path / "x.dat"
    p.write_bytes(b"not an image")
    assert image_to_base64(p) == (None, None)


def test_detect_mime_from_file(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(PNG)
    assert detect_mime_from_file(p) == "image/png"
    assert detect_mime_from_file(tmp_path / "missing.png") is None


def test_guess_mime_from_ext():
    assert guess_mime_from_ext(".SVG") == "image/svg+xml"
    assert guess_mime_from_ext(".png") == "image/png"
    assert guess_mime_from_ext(".xyz") == "image/png"  # 默认
