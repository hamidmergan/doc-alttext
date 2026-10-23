"""Find images and their context in a DOCX package."""

import re
from typing import Dict, List, Optional, Tuple

from .package import A, ImageRef, Package, Scan, blip_target, in_fallback, old_alt_and_flag, shorten, text_of

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
V = "{urn:schemas-microsoft-com:vml}"
WPS_URI = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
WPG_URI = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_EXTRA_PARTS = {"header": "header", "footer": "footer", "footnotes": "footnote", "endnotes": "endnote"}

_SEQ = re.compile(r"\bSEQ\b", re.I)

CONTEXT_BEFORE = 400
CONTEXT_AFTER = 400
SAMPLE_CHARS = 3000


def scan(pkg: Package) -> Scan:
    result = Scan()
    main = pkg.main_part()
    styles = _styles(pkg, main)
    parts: List[Tuple[str, str]] = [(main, "body")]
    for rel_type, target, external in pkg.rels(main).values():
        kind = rel_type.rsplit("/", 1)[-1]
        if not external and kind in _EXTRA_PARTS and target in pkg.names:
            parts.append((target, _EXTRA_PARTS[kind]))
    for part, kind in parts:
        _scan_part(pkg, part, kind, styles, result)
    return result


def _scan_part(pkg: Package, part: str, kind: str, styles: Dict[str, Tuple[str, bool]], result: Scan) -> None:
    root = pkg.xml(part)
    blocks = [p for p in root.iter(W + "p") if _outer_paragraph(p) is p and not in_fallback(p)]
    index = {id(p): i for i, p in enumerate(blocks)}
    texts = [text_of(p, W + "t") for p in blocks]

    if kind == "body":
        result.text = shorten(" ".join(t for t in texts if t.strip()), SAMPLE_CHARS)
    for lang in root.iter(W + "lang"):
        if lang.get(W + "val"):
            result.langs[lang.get(W + "val")] += 1

    name = part.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    for drawing in root.iter(W + "drawing"):
        if in_fallback(drawing):
            continue
        doc_pr = drawing.find(".//" + WP + "docPr")
        if doc_pr is None:
            continue
        pics = [p for p in drawing.iter(PIC + "pic") if _owner_drawing(p) is drawing]
        outer = _outer_paragraph(drawing)
        i = index.get(id(outer)) if outer is not None else None
        place = _place(kind, name, drawing, i)
        if not pics:
            if _plain_shape(drawing):
                ref = ImageRef(part=part, location=place + ", shape", shape=doc_pr.get("name", ""),
                               targets=[doc_pr], plain_shape=True)
                ref.old_alt, ref.decorative = old_alt_and_flag([doc_pr])
                result.images.append(ref)
            continue  # charts and SmartArt are left alone
        context = _context(blocks, texts, i, kind, styles)
        for pic in pics:
            cnvpr = pic.find(PIC + "nvPicPr/" + PIC + "cNvPr")
            if len(pics) > 1:  # a group: each picture gets its own alt text
                targets = [cnvpr] if cnvpr is not None else []
            else:
                targets = [doc_pr] + ([cnvpr] if cnvpr is not None else [])
            ref = ImageRef(part=part, location=place + (", group" if len(pics) > 1 else ""),
                           shape=(targets[0].get("name") if targets else "") or "", targets=targets, context=context)
            blip = pic.find(PIC + "blipFill/" + A + "blip")
            if blip is None:
                ref.problem = "picture without image data"
            else:
                ref.media, ref.problem = blip_target(pkg, part, blip)
            ref.old_alt, ref.decorative = old_alt_and_flag(targets)
            result.images.append(ref)

    for pict in root.iter(W + "pict"):
        if in_fallback(pict) or pict.find(".//" + V + "imagedata") is None:
            continue
        outer = _outer_paragraph(pict)
        i = index.get(id(outer)) if outer is not None else None
        shape = pict.find(".//" + V + "shape")
        result.images.append(
            ImageRef(
                part=part,
                location=_place(kind, name, pict, i),
                shape=(shape.get("id") if shape is not None else "") or "",
                targets=[],
                problem="legacy VML image, not supported",
                old_alt=(shape.get("alt") if shape is not None else "") or "",
            )
        )


def _plain_shape(drawing) -> bool:
    """A drawn shape or group of shapes without any text."""
    data = drawing.find(".//" + A + "graphicData")
    if data is None or data.get("uri") not in (WPS_URI, WPG_URI):
        return False
    return not text_of(drawing, W + "t").strip()


def _outer_paragraph(el):
    """The outermost w:p that contains el (el itself if it is one)."""
    found = el if el.tag == W + "p" else None
    parent = el.getparent()
    while parent is not None:
        if parent.tag == W + "p":
            found = parent
        parent = parent.getparent()
    return found


def _owner_drawing(el):
    parent = el.getparent()
    while parent is not None and parent.tag != W + "drawing":
        parent = parent.getparent()
    return parent


def _place(kind: str, name: str, el, i: Optional[int]) -> str:
    where = kind if kind == "body" else f"{kind} ({name})"
    parent = el.getparent()
    while parent is not None:
        if parent.tag == W + "tbl":
            where += ", table"
            break
        parent = parent.getparent()
    if i is not None:
        where += f", paragraph {i + 1}"
    return where


def _context(blocks: list, texts: List[str], i: Optional[int], kind: str,
             styles: Dict[str, Tuple[str, bool]]) -> str:
    lines = []
    if kind != "body":
        lines.append(f"The image is in the page {kind} of a Word document.")
        if kind in ("header", "footer"):
            lines.append("Page headers and footers repeat on every page.")
    else:
        lines.append("The image is in a Word document.")
    if i is None:
        return "\n".join(lines)
    heading = next((texts[j] for j in range(i - 1, -1, -1) if _is_heading(blocks[j], styles) and texts[j].strip()), "")
    if heading:
        lines.append("Nearest heading: " + shorten(heading, 150))
    caption_index = next((j for j in (i + 1, i - 1, i) if 0 <= j < len(blocks) and _is_caption(blocks[j], styles)), None)
    if caption_index is not None and texts[caption_index].strip():
        lines.append("Caption: " + shorten(texts[caption_index], 200))
    skip = {caption_index}
    before = " ".join(texts[j] for j in range(max(0, i - 6), i) if j not in skip)
    after = " ".join(texts[j] for j in range(i + 1, min(len(blocks), i + 7)) if j not in skip)
    if texts[i].strip() and caption_index != i:
        lines.append("Text in the same paragraph: " + shorten(texts[i], 200))
    if before.strip():
        lines.append("Text before: " + shorten(before, CONTEXT_BEFORE, from_end=True))
    if after.strip():
        lines.append("Text after: " + shorten(after, CONTEXT_AFTER))
    return "\n".join(lines)


def _style_id(p) -> str:
    style = p.find(W + "pPr/" + W + "pStyle")
    return style.get(W + "val", "") if style is not None else ""


def _has_outline(el) -> bool:
    level = el.find(W + "pPr/" + W + "outlineLvl")
    return level is not None and level.get(W + "val") != "9"  # 9 means body text


def _is_heading(p, styles: Dict[str, Tuple[str, bool]]) -> bool:
    if _has_outline(p):
        return True
    name, outline = styles.get(_style_id(p), ("", False))
    return outline or name.startswith("heading") or name == "title"


def _is_caption(p, styles: Dict[str, Tuple[str, bool]]) -> bool:
    if styles.get(_style_id(p), ("", False))[0] == "caption":
        return True
    instr = " ".join(t.text or "" for t in p.iter(W + "instrText"))
    instr += " ".join(f.get(W + "instr", "") for f in p.iter(W + "fldSimple"))
    return bool(_SEQ.search(instr))


def _styles(pkg: Package, main: str) -> Dict[str, Tuple[str, bool]]:
    """Style id -> (lower-case built-in name, has outline level)."""
    target = next((t for rt, t, ext in pkg.rels(main).values() if rt == _REL + "styles" and not ext), None)
    if target is None or target not in pkg.names:
        return {}
    styles = {}
    for style in pkg.xml(target).iter(W + "style"):
        name_el = style.find(W + "name")
        name = (name_el.get(W + "val", "") if name_el is not None else "").lower()
        styles[style.get(W + "styleId", "")] = (name, _has_outline(style))
    return styles
