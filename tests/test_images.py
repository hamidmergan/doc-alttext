import io

import pytest
from PIL import Image

from doc_alttext.errors import UnsupportedFileError
from doc_alttext.images import looks_decorative, prepare


def image_bytes(size=(200, 100), mode="RGB", fmt="PNG"):
    out = io.BytesIO()
    Image.new(mode, size).save(out, format=fmt)
    return out.getvalue()


def test_prepare_keeps_small_image_size():
    img = prepare(image_bytes(), "image1.png", 1024)
    assert (img.width, img.height) == (200, 100)
    assert Image.open(io.BytesIO(img.png)).size == (200, 100)


def test_prepare_downscales_but_reports_original_size():
    img = prepare(image_bytes((3000, 1500), fmt="JPEG"), "image1.jpeg", 1000)
    assert (img.width, img.height) == (3000, 1500)
    assert Image.open(io.BytesIO(img.png)).size == (1000, 500)


@pytest.mark.parametrize("mode, fmt", [("CMYK", "JPEG"), ("P", "GIF"), ("RGB", "BMP"), ("RGB", "TIFF"), ("RGB", "WEBP")])
def test_prepare_converts_to_png(mode, fmt):
    img = prepare(image_bytes(mode=mode, fmt=fmt), "x", 1024)
    assert img.png.startswith(b"\x89PNG")


@pytest.mark.parametrize("name", ["image1.emf", "image2.WMF", "image3.svg"])
def test_vector_formats_unsupported(name):
    with pytest.raises(UnsupportedFileError, match="not supported"):
        prepare(b"anything", name, 1024)


def test_broken_image():
    with pytest.raises(UnsupportedFileError, match="cannot be read"):
        prepare(b"not an image", "image1.png", 1024)


@pytest.mark.parametrize(
    "size, expected",
    [((10, 10), True), ((800, 4), True), ((600, 20), True), ((200, 100), False), ((600, 40), False), ((300, 25), False)],
)
def test_looks_decorative(size, expected):
    assert looks_decorative(*size) is expected
