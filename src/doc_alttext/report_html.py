"""Review report as a single HTML page: image, place, status and alt text side by side.

No JavaScript and no external resources. Thumbnails are embedded.
"""

import base64
import html
import io
import zipfile
from typing import Dict, List, Optional

from .report import ADDED, DECORATIVE, ERROR, KEPT, UNSUPPORTED, ImageItem, summary

THUMB_SIDE = 320

_LABELS = {
    ADDED: "Added",
    DECORATIVE: "Decorative",
    KEPT: "Kept",
    UNSUPPORTED: "Not supported",
    ERROR: "Error",
}

_CSS = """
body{font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;background:#f4f4f2;color:#222;margin:0;padding:24px}
main{max-width:980px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px} h2{font-size:18px;margin:28px 0 4px}
.intro,.sum{color:#555;margin:0 0 14px}
.card{display:flex;gap:18px;background:#fff;border-radius:8px;padding:14px;margin-bottom:12px}
.pic{width:220px;flex:none;display:flex;align-items:center;justify-content:center;background:#eee;border-radius:6px;min-height:80px}
.pic img{max-width:100%;max-height:160px}
.none{color:#888;font-size:13px}
.meta{font-size:13px;color:#666;margin-bottom:6px}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:10px;background:#eee;margin-right:6px}
.added .badge{background:#dff0e5;color:#1e5c38} .error .badge{background:#f8dcd8;color:#8e2a1f} .unsupported .badge{background:#f8ecd0;color:#7a5400}
.alt{font-size:17px;line-height:1.4}
.before{font-size:14px;color:#777;margin-top:6px} .before s{color:#999}
.note{font-size:14px;margin-top:6px;color:#8e2a1f}
@media (max-width:600px){.card{flex-direction:column}.pic{width:auto}}
"""


def to_html(items: List[ImageItem]) -> str:
    thumbs = _thumbnails(items)
    files: Dict[str, List[ImageItem]] = {}
    for item in items:
        files.setdefault(item.file, []).append(item)
    sections = []
    for name, group in files.items():
        cards = "".join(_card(i, thumbs.get((i.file, i.image))) for i in group)
        sections.append(
            f"<h2>{_e(name)}</h2><p class=\"sum\">{_e(summary(group))}</p>{cards}"
        )
    body = "".join(sections) or "<p>No images found.</p>"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>Alt text report</title><style>{_CSS}</style></head><body><main>"
        "<h1>Alt text report</h1>"
        "<p class=\"intro\">Check each text against its image. Fix single texts in Word or PowerPoint "
        "at the place shown (right-click the image, then alt text).</p>"
        f"{body}</main></body></html>\n"
    )


def _card(item: ImageItem, thumb: Optional[str]) -> str:
    pic = f'<img src="{thumb}" alt="">' if thumb else '<span class="none">No preview</span>'
    meta = _e(item.location) + (f" &middot; {_e(item.shape)}" if item.shape else "")
    lines = []
    if item.status == ADDED:
        lines.append(f'<div class="alt">{_e(item.new_alt)}</div>')
    elif item.status == DECORATIVE:
        lines.append('<div class="alt">Marked as decorative. Screen readers skip it.</div>')
    elif item.status == KEPT:
        text = item.old_alt or "Already marked as decorative."
        lines.append(f'<div class="alt">{_e(text)}</div>')
    if item.old_alt and item.status in (ADDED, DECORATIVE):
        lines.append(f'<div class="before">Before: <s>{_e(item.old_alt)}</s></div>')
    note = _note(item)
    if note:
        lines.append(f'<div class="note">{_e(note)}</div>')
    badge = _LABELS.get(item.status, item.status)
    if item.status == ADDED:
        badge += f" &middot; {item.chars} chars"
    return (
        f'<div class="card {_e(item.status)}"><div class="pic">{pic}</div><div>'
        f'<div class="meta"><span class="badge">{badge}</span>{meta}</div>{"".join(lines)}</div></div>'
    )


def _note(item: ImageItem) -> str:
    if item.note == "too_long":
        return "Longer than the target length. Consider shortening it."
    if item.status in (ERROR, UNSUPPORTED) or (item.note and item.status == DECORATIVE):
        return item.note
    return ""


def _thumbnails(items: List[ImageItem]) -> Dict[tuple, str]:
    """Small PNG data URLs, read from the input files. Missing or unreadable images get none."""
    result: Dict[tuple, str] = {}
    by_file: Dict[str, set] = {}
    for item in items:
        if item.image:
            by_file.setdefault(item.file, set()).add(item.image)
    for name, images in by_file.items():
        try:
            archive = zipfile.ZipFile(name)
        except (OSError, zipfile.BadZipFile):
            continue
        with archive:
            for image in images:
                try:
                    png = thumbnail_png(archive.read(image))
                except KeyError:
                    continue
                if png is not None:
                    result[(name, image)] = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return result


def thumbnail_png(data: bytes, side: int = THUMB_SIDE) -> Optional[bytes]:
    """A small PNG of an image, or None if Pillow cannot read it (e.g. EMF on macOS and Linux)."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.thumbnail((side, side))
        if img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA")
        out = io.BytesIO()
        img.save(out, format="PNG")
    except Exception:
        return None
    return out.getvalue()


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)
