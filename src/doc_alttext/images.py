"""Turn embedded image bytes into a PNG the model can read."""

import io
from dataclasses import dataclass

from .errors import UnsupportedFileError

# Vector and metafile formats a vision model cannot read and Pillow cannot render everywhere.
UNSUPPORTED_EXTENSIONS = {"emf", "wmf", "emz", "wmz", "svg", "pict", "pct", "eps"}

# Pre-check for lines, spacers and borders: no model call needed.
TINY_SIDE = 16
LINE_RATIO = 15
LINE_SIDE = 30


@dataclass(frozen=True)
class PreparedImage:
    png: bytes
    width: int
    height: int


def prepare(data: bytes, name: str, max_side: int) -> PreparedImage:
    """Open an embedded image, downscale it and return it as PNG.

    width and height are the original size in pixels.
    """
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in UNSUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"image format .{ext} is not supported")
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise UnsupportedFileError(f"image cannot be read: {exc}")
    width, height = img.size
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if "transparency" in img.info or img.mode in ("P", "PA") else "RGB")
    if max(width, height) > max_side:
        img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return PreparedImage(png=out.getvalue(), width=width, height=height)


def looks_decorative(width: int, height: int) -> bool:
    """True for tiny images and thin lines, which carry no information."""
    short, long = min(width, height), max(width, height)
    if short < TINY_SIDE:
        return True
    return short < LINE_SIDE and long >= short * LINE_RATIO
