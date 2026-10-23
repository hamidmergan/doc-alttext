import json

from doc_alttext import add_alt_text, write_report
from doc_alttext.report import ImageItem
from doc_alttext.report_html import to_html
from helpers import read_part, replace_part
from test_core import make_docx, make_pptx


def run(server, path, **kwargs):
    return add_alt_text(path, base_url=server.base_url, model="vision", max_retries=0, **kwargs)


def test_html_report_shows_image_text_and_before(server, tmp_path):
    src = make_docx(tmp_path / "a.docx")
    xml = read_part(src, "word/document.xml").replace(
        '<wp:docPr id="1" name="Picture 1"', '<wp:docPr id="1" name="Picture 1" descr="image1.png"', 1
    )
    replace_part(src, "word/document.xml", xml.encode())
    server.reply = lambda body: "German" if isinstance(body["messages"][-1]["content"], str) else json.dumps(
        {"decorative": False, "alt": "Chart <b>sales</b> & growth"}
    )
    result = run(server, src, dry_run=True)
    assert result.items[0].old_alt == "image1.png"  # counted as missing, but shown as before

    page = to_html(result.items)
    assert page.startswith("<!doctype html>")
    assert "<script" not in page and "http" not in page.replace("http-equiv", "")
    assert "data:image/png;base64," in page
    assert "Chart &lt;b&gt;sales&lt;/b&gt; &amp; growth" in page
    assert "Before: <s>image1.png</s>" in page
    assert "1 image: 1 added" in page
    assert "body, paragraph 3" in page
    assert f"Added &middot; {len('Chart <b>sales</b> & growth')} chars" in page


def test_html_report_for_problems_and_several_files(server, tmp_path):
    server.status = 500
    a = run(server, make_docx(tmp_path / "a.docx"), lang="English", dry_run=True)
    server.status = 200
    server.reply = lambda body: '{"decorative": true}'
    b = run(server, make_pptx(tmp_path / "b.pptx"), lang="English", dry_run=True)
    items = a.items + b.items + [
        ImageItem(str(tmp_path / "c.docx"), "word/media/image9.emf", "body, paragraph 1", "Pic", "unsupported",
                  note="image format .emf is not supported"),
    ]
    page = to_html(items)
    assert page.count("<h2>") == 3
    assert 'class="card error"' in page and "failed" in page
    assert "Marked as decorative" in page
    assert "No preview" in page and "image format .emf is not supported" in page


def test_write_report_html(server, tmp_path):
    result = run(server, make_docx(tmp_path / "a.docx"), dry_run=True)
    path = write_report(result.items, tmp_path / "out" / "check.html")
    assert "A test image" in path.read_text(encoding="utf-8")


def test_empty_report():
    assert "No images found." in to_html([])
