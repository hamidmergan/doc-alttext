"""Review report: one row per image."""

import csv
import io
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterable, List, Union

from .errors import ConfigError

# Status values
ADDED = "added"
DECORATIVE = "decorative"
KEPT = "kept"
UNSUPPORTED = "unsupported"
ERROR = "error"


@dataclass
class ImageItem:
    file: str
    image: str  # zip part of the image, e.g. ppt/media/image3.png
    location: str  # e.g. "slide 3" or "body, paragraph 12"
    shape: str
    status: str
    old_alt: str = ""
    new_alt: str = ""
    chars: int = 0
    language: str = ""
    note: str = ""


COLUMNS = [f.name for f in fields(ImageItem)]
REPORT_SUFFIXES = (".json", ".csv", ".html", ".htm")


def to_json(items: Iterable[ImageItem]) -> str:
    return json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2) + "\n"


def to_csv(items: Iterable[ImageItem]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in items:
        writer.writerow(asdict(item))
    return out.getvalue()


def write_report(items: List[ImageItem], path: Union[str, Path]) -> Path:
    """Write the report as JSON, CSV or HTML, chosen by the file extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        data, encoding = to_json(items), "utf-8"
    elif suffix == ".csv":
        data, encoding = to_csv(items), "utf-8-sig"  # BOM, so Excel shows umlauts correctly
    elif suffix in (".html", ".htm"):
        from .report_html import to_html

        data, encoding = to_html(items), "utf-8"
    else:
        raise ConfigError(f"Report file must end in .json, .csv or .html, not {path.suffix or '(none)'}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding=encoding)
    return path


def summary(items: List[ImageItem]) -> str:
    counts = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    parts = [f"{counts[s]} {s}" for s in (ADDED, DECORATIVE, KEPT, UNSUPPORTED, ERROR) if counts.get(s)]
    total = f"{len(items)} image" + ("" if len(items) == 1 else "s")
    return total + (": " + ", ".join(parts) if parts else "")
