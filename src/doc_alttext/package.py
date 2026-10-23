"""Reading and writing Office Open XML packages (DOCX, PPTX).

Only changed XML parts are serialized again. Every other part is copied byte for byte.
"""

import posixpath
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from lxml import etree

from .errors import UnsupportedFileError

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
ADEC_NS = "http://schemas.microsoft.com/office/drawing/2017/decorative"
ADEC = "{" + ADEC_NS + "}"

# Extension URI that PowerPoint and Word use for the decorative flag.
DECORATIVE_URI = "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"

REL_OFFICE_DOCUMENT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
REL_STRICT_OFFICE_DOCUMENT = "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"

_FILE_NAME = re.compile(r"^[\w\s\-.()~]+\.(png|jpe?g|gif|bmp|tiff?|emf|wmf|svg|webp|heic|heif)$", re.I)

# Endings of descriptions that Word and PowerPoint generated automatically.
_AUTO_MARKERS = (
    "description automatically generated",
    "automatically generated description",
    "automatisch generierte beschreibung",
    "beschreibung automatisch generiert",
    "description générée automatiquement",
    "descripción generada automáticamente",
    "descrizione generata automaticamente",
    "automatisch gegenereerde beschrijving",
)


@dataclass
class ImageRef:
    """One image found in a document, before the model is asked."""

    part: str  # XML part that holds the image, e.g. ppt/slides/slide3.xml
    location: str  # readable place, e.g. "slide 3" or "body, paragraph 12"
    shape: str  # shape name from cNvPr/docPr
    targets: list  # cNvPr/docPr elements that receive the alt text
    media: Optional[str] = None  # zip name of the image
    problem: Optional[str] = None  # why the image cannot be handled
    context: str = ""
    old_alt: str = ""
    decorative: bool = False
    plain_shape: bool = False  # a drawn shape without text (card, circle, line), not a picture



@dataclass
class Scan:
    images: List[ImageRef] = field(default_factory=list)
    text: str = ""  # sample of the document text, for language detection
    langs: Counter = field(default_factory=Counter)  # lang attributes found in runs


def parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)


class Package:
    """An open DOCX or PPTX file. Use as a context manager."""

    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            self.zip = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile:
            raise UnsupportedFileError(
                f"{self.path.name} is not a valid Office Open XML file. Password protected files are not supported."
            )
        self.names = set(self.zip.namelist())
        if "[Content_Types].xml" not in self.names:
            self.zip.close()
            raise UnsupportedFileError(f"{self.path.name} has no [Content_Types].xml and is not an Office file.")
        self._xml: Dict[str, etree._Element] = {}
        self.changed: set = set()

    def __enter__(self) -> "Package":
        return self

    def __exit__(self, *exc) -> None:
        self.zip.close()

    def read(self, name: str) -> bytes:
        return self.zip.read(name)

    def xml(self, name: str) -> etree._Element:
        """Parsed XML part, cached, so changes stay on the same tree."""
        if name not in self._xml:
            try:
                self._xml[name] = etree.fromstring(self.zip.read(name), parser())
            except KeyError:
                raise UnsupportedFileError(f"{self.path.name}: part {name} is missing.")
            except etree.XMLSyntaxError as exc:
                raise UnsupportedFileError(f"{self.path.name}: part {name} is not valid XML: {exc}")
        return self._xml[name]

    def rels(self, part: str) -> Dict[str, Tuple[str, str, bool]]:
        """Relationships of a part: id -> (type, target part or URL, external)."""
        folder, base = posixpath.split(part)
        rels_name = posixpath.join(folder, "_rels", base + ".rels")
        if rels_name not in self.names:
            return {}
        result = {}
        for rel in self.xml(rels_name).iter(PR + "Relationship"):
            target = rel.get("Target", "")
            external = rel.get("TargetMode") == "External"
            if not external:
                target = resolve_target(folder, target)
            result[rel.get("Id", "")] = (rel.get("Type", ""), target, external)
        return result

    def main_part(self) -> str:
        for _id, (rel_type, target, external) in self.rels("").items():
            if rel_type in (REL_OFFICE_DOCUMENT, REL_STRICT_OFFICE_DOCUMENT) and not external:
                return target
        raise UnsupportedFileError(f"{self.path.name} has no main document part.")

    def save(self, dst: Path) -> None:
        """Write the package to dst. Parts in self.changed are serialized, all others copied."""
        with zipfile.ZipFile(dst, "w") as out:
            for info in self.zip.infolist():
                if info.filename in self.changed:
                    data = etree.tostring(
                        self._xml[info.filename], xml_declaration=True, encoding="UTF-8", standalone=True
                    )
                else:
                    data = self.zip.read(info)
                out.writestr(info, data)


def resolve_target(folder: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(folder, target))


def blip_target(package: Package, part: str, blip) -> Tuple[Optional[str], Optional[str]]:
    """Zip name of the image a blip points to, or (None, reason)."""
    embed = blip.get(R + "embed")
    if not embed:
        if blip.get(R + "link"):
            return None, "linked image, not embedded"
        return None, "image without reference"
    rel = package.rels(part).get(embed)
    if rel is None:
        return None, f"broken image reference {embed}"
    _type, target, external = rel
    if external:
        return None, "linked image, not embedded"
    if target not in package.names:
        return None, f"image {target} is missing in the file"
    return target, None


# --- alt text on cNvPr / docPr ---------------------------------------------


def is_decorative(cnvpr) -> bool:
    for ext in _decorative_exts(cnvpr):
        flag = ext.find(ADEC + "decorative")
        if flag is not None and flag.get("val", "1").lower() in ("1", "true"):
            return True
    return False


def existing_alt(cnvpr) -> str:
    """Alt text that counts as written by a person. Empty if missing or useless."""
    descr = (cnvpr.get("descr") or "").strip()
    if not descr or _FILE_NAME.match(descr):
        return ""
    lowered = " ".join(descr.lower().split())
    if any(marker in lowered for marker in _AUTO_MARKERS):
        return ""
    return descr


def old_alt_and_flag(targets: list) -> Tuple[str, bool]:
    """Existing alt text and decorative flag, from the first target that has one."""
    decorative = any(is_decorative(t) for t in targets)
    for t in targets:
        alt = existing_alt(t)
        if alt:
            return alt, decorative
    return "", decorative


def set_alt(targets: Iterable, alt: str, decorative: bool) -> None:
    """Write alt text, or the decorative flag, on all given cNvPr/docPr elements."""
    for cnvpr in targets:
        for ext in _decorative_exts(cnvpr):
            ext.getparent().remove(ext)
        ext_list = cnvpr.find(A + "extLst")
        if decorative:
            if "descr" in cnvpr.attrib:
                del cnvpr.attrib["descr"]
            if ext_list is None:
                ext_list = etree.SubElement(cnvpr, A + "extLst")  # extLst is the last child
            ext = etree.SubElement(ext_list, A + "ext", uri=DECORATIVE_URI)
            flag = etree.SubElement(ext, ADEC + "decorative", nsmap={"adec": ADEC_NS})
            flag.set("val", "1")
        else:
            cnvpr.set("descr", alt)
            if ext_list is not None and len(ext_list) == 0:
                cnvpr.remove(ext_list)


def _decorative_exts(cnvpr) -> List:
    ext_list = cnvpr.find(A + "extLst")
    if ext_list is None:
        return []
    return [ext for ext in ext_list.findall(A + "ext") if ext.get("uri", "").upper() == DECORATIVE_URI]


# --- text helpers ------------------------------------------------------------


def text_of(el, text_tag: str) -> str:
    """Text of all text nodes below el, without mc:Fallback copies."""
    return "".join(t.text or "" for t in el.iter(text_tag) if not _in_fallback(t, el))


def _in_fallback(node, stop) -> bool:
    parent = node.getparent()
    while parent is not None and parent is not stop:
        if parent.tag == MC + "Fallback":
            return True
        parent = parent.getparent()
    return False


def in_fallback(node) -> bool:
    return _in_fallback(node, None)


def shorten(text: str, limit: int, from_end: bool = False) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    if from_end:
        cut = text[-limit:]
        return "..." + cut[cut.find(" ") + 1:] if " " in cut else "..." + cut
    cut = text[:limit]
    return (cut[: cut.rfind(" ")] if " " in cut else cut) + "..."
