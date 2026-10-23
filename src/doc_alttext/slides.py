"""Find images and their context in a PPTX package."""

from typing import List, Optional

from .package import A, R, ImageRef, Package, Scan, blip_target, in_fallback, old_alt_and_flag, shorten, text_of

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_TITLE_TYPES = {"title", "ctrTitle"}
_MEDIA = {A + "videoFile", A + "audioFile", A + "quickTimeFile", A + "audioCd", A + "wavAudioFile"}

SLIDE_TEXT = 600
NOTES_TEXT = 300
SAMPLE_CHARS = 3000


def scan(pkg: Package) -> Scan:
    result = Scan()
    main = pkg.main_part()
    rels = pkg.rels(main)
    samples: List[str] = []
    slides = []
    for sld_id in pkg.xml(main).iter(P + "sldId"):
        rel = rels.get(sld_id.get(R + "id", ""))
        if rel and not rel[2] and rel[1] in pkg.names:
            slides.append(rel[1])
    for number, part in enumerate(slides, start=1):
        text = _scan_slide(pkg, part, number, result)
        if text:
            samples.append(text)
    result.text = shorten(" ".join(samples), SAMPLE_CHARS)
    return result


def _scan_slide(pkg: Package, part: str, number: int, result: Scan) -> str:
    root = pkg.xml(part)
    for el in root.iter(A + "rPr", A + "endParaRPr", A + "defRPr"):
        if el.get("lang"):
            result.langs[el.get("lang")] += 1

    title = ""
    others = []
    for sp in root.iter(P + "sp"):
        if in_fallback(sp):
            continue
        text = text_of(sp, A + "t").strip()
        if not text:
            continue
        ph = sp.find(P + "nvSpPr/" + P + "nvPr/" + P + "ph")
        if ph is not None and ph.get("type") in _TITLE_TYPES and not title:
            title = text
        else:
            others.append(text)
    notes = _notes(pkg, part)

    lines = [f"The image is on slide {number} of a presentation."]
    if title:
        lines.append("Slide title: " + shorten(title, 150))
    if others:
        lines.append("Other text on the slide: " + shorten(" | ".join(others), SLIDE_TEXT))
    if notes:
        lines.append("Speaker notes: " + shorten(notes, NOTES_TEXT))
    context = "\n".join(lines)

    for el in root.iter(P + "pic", P + "sp", P + "cxnSp"):
        if in_fallback(el):
            continue
        ref = _image(pkg, part, el, number, context)
        if ref is not None:
            result.images.append(ref)
    return " ".join([title] + others)


def _image(pkg: Package, part: str, el, number: int, context: str) -> Optional[ImageRef]:
    if el.tag == P + "pic":
        nv = el.find(P + "nvPicPr")
        blip = el.find(P + "blipFill/" + A + "blip")
        media_props = nv.find(P + "nvPr") if nv is not None else None
        if media_props is not None and any(child.tag in _MEDIA for child in media_props):
            return None  # video or audio, not an image
    elif el.tag == P + "cxnSp":
        return _plain_shape(part, el.find(P + "nvCxnSpPr"), el, number, context)
    else:
        nv = el.find(P + "nvSpPr")
        blip = el.find(P + "spPr/" + A + "blipFill/" + A + "blip")
        if blip is None:
            return _plain_shape(part, nv, el, number, context)
    cnvpr = nv.find(P + "cNvPr") if nv is not None else None
    if cnvpr is None:
        return None
    location = f"slide {number}" + (", group" if _in_group(el) else "")
    if el.tag == P + "sp":
        location += ", picture fill"
    ref = ImageRef(part=part, location=location, shape=cnvpr.get("name", ""), targets=[cnvpr], context=context)
    if blip is None:
        ref.problem = "picture without image data"
    else:
        ref.media, ref.problem = blip_target(pkg, part, blip)
    ref.old_alt, ref.decorative = old_alt_and_flag([cnvpr])
    return ref


def _plain_shape(part: str, nv, el, number: int, context: str) -> Optional[ImageRef]:
    """A drawn shape or line without text. Placeholders, text boxes and shapes with text are left out."""
    if nv is None or nv.find(P + "cNvPr") is None:
        return None
    if nv.find(P + "nvPr/" + P + "ph") is not None:
        return None
    sp_props = nv.find(P + "cNvSpPr")
    if sp_props is not None and sp_props.get("txBox") in ("1", "true"):
        return None
    if text_of(el, A + "t").strip():
        return None
    cnvpr = nv.find(P + "cNvPr")
    location = f"slide {number}" + (", group" if _in_group(el) else "") + ", shape"
    ref = ImageRef(part=part, location=location, shape=cnvpr.get("name", ""), targets=[cnvpr], context=context,
                   plain_shape=True)
    ref.old_alt, ref.decorative = old_alt_and_flag([cnvpr])
    return ref


def _in_group(el) -> bool:
    parent = el.getparent()
    while parent is not None:
        if parent.tag == P + "grpSp":
            return True
        parent = parent.getparent()
    return False


def _notes(pkg: Package, part: str) -> str:
    for rel_type, target, external in pkg.rels(part).values():
        if rel_type == _REL + "notesSlide" and not external and target in pkg.names:
            texts = []
            for sp in pkg.xml(target).iter(P + "sp"):
                ph = sp.find(P + "nvSpPr/" + P + "nvPr/" + P + "ph")
                if ph is not None and ph.get("type") == "body":
                    texts.append(text_of(sp, A + "t"))
            return " ".join(t for t in texts if t.strip())
    return ""
