import csv
import json

import pytest

from doc_alttext.cli import main
from helpers import read_part
from test_core import make_docx, make_pptx


def args(server, *extra):
    return [*extra, "--base-url", server.base_url, "--model", "vision"]


def test_writes_default_output(server, tmp_path, capsys):
    src = make_docx(tmp_path / "report.docx")
    assert main(args(server, str(src))) == 0
    out = tmp_path / "report.alt.docx"
    assert 'descr="A test image"' in read_part(out, "word/document.xml")
    err = capsys.readouterr().err
    assert "1 image: 1 added" in err and "report.alt.docx" in err


def test_second_run_does_not_overwrite(server, tmp_path):
    src = make_docx(tmp_path / "report.docx")
    main(args(server, str(src)))
    main(args(server, str(src)))
    assert (tmp_path / "report.alt-1.docx").exists()


def test_dry_run_prints_json(server, tmp_path, capsys):
    src = make_docx(tmp_path / "a.docx")
    assert main(args(server, str(src), "--dry-run")) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["new_alt"] == "A test image"
    assert data[0]["file"] == str(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.docx"]


def test_several_files_into_folder_with_csv_report(server, tmp_path):
    a = make_docx(tmp_path / "a.docx")
    b = make_pptx(tmp_path / "b.pptx")
    folder = tmp_path / "out"
    report = tmp_path / "review.csv"
    assert main(args(server, str(a), str(b), "-o", str(folder), "--report", str(report))) == 0
    assert sorted(p.name for p in folder.iterdir()) == ["a.alt.docx", "b.alt.pptx"]
    rows = list(csv.DictReader(report.read_text(encoding="utf-8-sig").splitlines()))
    assert [r["file"] for r in rows] == [str(a), str(b)]
    assert rows[1]["location"] == "slide 1"


def test_in_place_and_lang(server, tmp_path):
    src = make_docx(tmp_path / "a.docx")
    assert main(args(server, str(src), "--in-place", "--lang", "Spanish")) == 0
    assert 'descr="A test image"' in read_part(src, "word/document.xml")
    assert "Write it in Spanish." in server.image_requests[0]["body"]["messages"][0]["content"]


@pytest.mark.parametrize(
    "extra, message",
    [
        (["--in-place", "-o", "x.docx"], "not both"),
        (["--report", "r.txt"], ".html, .json or .csv"),
    ],
)
def test_usage_errors(server, tmp_path, capsys, extra, message):
    src = make_docx(tmp_path / "a.docx")
    assert main(args(server, str(src), *extra)) == 2
    assert message in capsys.readouterr().err


def test_missing_config(tmp_path, capsys):
    src = make_docx(tmp_path / "a.docx")
    assert main([str(src)]) == 2
    assert "DOC_ALTTEXT_BASE_URL" in capsys.readouterr().err


def test_failures_give_exit_code_1(server, tmp_path, capsys):
    good = make_docx(tmp_path / "a.docx")
    assert main(args(server, str(good), str(tmp_path / "missing.docx"))) == 1
    assert "missing.docx" in capsys.readouterr().err
    server.status = 500
    assert main(args(server, str(good), "--lang", "English", "--dry-run")) == 1
    assert "Error: body" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "doc-alttext 0.1.0" in capsys.readouterr().out


def test_progress_and_html_report(server, tmp_path, capsys):
    src = make_docx(tmp_path / "a.docx", pictures=2)
    report = tmp_path / "check.html"
    assert main(args(server, str(src), "--dry-run", "--report", str(report))) == 0
    err = capsys.readouterr().err
    assert f"{src}: detecting the language" in err
    assert f"{src}: language: German" in err
    assert f"{src}: image 2/2 done" in err
    assert "data:image/png;base64," in report.read_text(encoding="utf-8")
