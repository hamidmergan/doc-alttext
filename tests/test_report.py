import csv
import json

import pytest

from doc_alttext.errors import ConfigError
from doc_alttext.report import COLUMNS, ImageItem, summary, write_report

ITEMS = [
    ImageItem("a.docx", "word/media/image1.png", "body, paragraph 3", "Picture 1", "added",
              new_alt="Balkendiagramm: Umsatz verdoppelt", chars=33, language="German"),
    ImageItem("a.docx", "word/media/image2.png", "header (header1)", "Logo", "decorative"),
]


def test_json_report(tmp_path):
    path = write_report(ITEMS, tmp_path / "r.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["new_alt"] == "Balkendiagramm: Umsatz verdoppelt"
    assert list(data[0]) == COLUMNS
    assert "Umsatz" in path.read_text(encoding="utf-8")  # not escaped


def test_csv_report_with_bom(tmp_path):
    path = write_report(ITEMS, tmp_path / "out" / "r.csv")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[1]["status"] == "decorative"
    assert rows[0]["chars"] == "33"


def test_unknown_report_extension(tmp_path):
    with pytest.raises(ConfigError, match=".json, .csv or .html"):
        write_report(ITEMS, tmp_path / "r.txt")


def test_summary():
    assert summary(ITEMS) == "2 images: 1 added, 1 decorative"
    assert summary([]) == "0 images"
