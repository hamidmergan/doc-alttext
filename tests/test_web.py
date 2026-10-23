import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from doc_alttext.config import resolve  # noqa: E402
from doc_alttext.package import Package  # noqa: E402
from doc_alttext.web.app import create_app  # noqa: E402
from doc_alttext.word import scan  # noqa: E402
from test_core import make_docx, make_pptx  # noqa: E402


@pytest.fixture
def client(server, tmp_path):
    settings = resolve(base_url=server.base_url, model="vision", max_retries=0)
    with TestClient(create_app(settings, workdir=tmp_path / "work")) as c:
        yield c


def upload(client, path):
    return client.post("/api/upload", files={"file": (path.name, path.read_bytes(), "application/octet-stream")})


def wait_done(client, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get("/api/job").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_page_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "doc-alttext" in res.text and "/api/upload" in res.text


def test_empty_state(client):
    assert client.get("/api/job").json() == {"state": "empty"}


def test_upload_review_edit_download(client, tmp_path):
    src = make_docx(tmp_path / "Bericht 2024.docx", pictures=3)
    res = upload(client, src)
    assert res.status_code == 200
    job = wait_done(client)
    assert job["state"] == "done" and job["language"] == "German"
    assert job["name"] == "Bericht 2024.docx"
    assert [i["status"] for i in job["items"]] == ["added"] * 3
    assert job["items"][0]["alt"] == "A test image" and job["items"][0]["editable"]
    assert job["max_chars"] == 150

    png = client.get(f"/api/job/{job['id']}/images/0.png")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")

    decisions = [{"alt": "Edited by a person"}, {"decorative": True}, None]
    res = client.post(f"/api/job/{job['id']}/download", json={"decisions": decisions})
    assert res.status_code == 200
    assert "Bericht%202024.alt.docx" in res.headers["content-disposition"]
    out = tmp_path / "out.docx"
    out.write_bytes(res.content)
    with Package(out) as pkg:
        images = scan(pkg).images
    assert images[0].old_alt == "Edited by a person"
    assert images[1].decorative
    assert images[2].old_alt == ""  # None keeps the file as it was, the model text is not written


def test_model_error_shows_per_image(client, server, tmp_path):
    server.status = 500
    upload(client, make_pptx(tmp_path / "deck.pptx"))
    job = wait_done(client)
    assert job["state"] == "done"
    assert job["items"][0]["status"] == "error"
    assert "failed" in job["items"][0]["note"]


def test_new_upload_replaces_old_job(client, tmp_path):
    first = upload(client, make_docx(tmp_path / "a.docx")).json()
    wait_done(client)
    upload(client, make_pptx(tmp_path / "b.pptx"))
    wait_done(client)
    res = client.post(f"/api/job/{first['id']}/download", json={"decisions": [None]})
    assert res.status_code == 404


def test_bad_uploads(client, tmp_path, server):
    bad = tmp_path / "notes.pdf"
    bad.write_bytes(b"%PDF")
    res = upload(client, bad)
    assert res.status_code == 400 and "Unsupported file type .pdf" in res.json()["detail"]

    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")
    upload(client, broken)
    job = wait_done(client)
    assert job["state"] == "failed" and "not a valid" in job["error"]


def test_upload_size_limit(server, tmp_path):
    settings = resolve(base_url=server.base_url, model="vision", max_file_mb=0.001)
    with TestClient(create_app(settings, workdir=tmp_path / "work")) as c:
        res = upload(c, make_docx(tmp_path / "a.docx"))
    assert res.status_code == 413


def test_wrong_decision_count(client, tmp_path):
    job = upload(client, make_docx(tmp_path / "a.docx")).json()
    wait_done(client)
    res = client.post(f"/api/job/{job['id']}/download", json={"decisions": [None, None]})
    assert res.status_code == 400 and "decisions" in res.json()["detail"]


def test_host_and_origin_guard(server, tmp_path):
    settings = resolve(base_url=server.base_url, model="vision")
    app = create_app(settings, workdir=tmp_path / "work", allowed_hosts=["127.0.0.1", "localhost"])
    with TestClient(app, base_url="http://localhost:8000") as c:
        assert c.get("/api/job").status_code == 200
        assert c.get("/api/job", headers={"host": "evil.example"}).status_code == 400
        res = c.get("/api/job", headers={"origin": "http://evil.example"})
        assert res.status_code == 403
        assert c.get("/api/job", headers={"origin": "http://localhost:8000"}).status_code == 200


def test_serve_without_config(capsys):
    from doc_alttext.cli import main

    assert main(["serve"]) == 2
    assert "DOC_ALTTEXT_BASE_URL" in capsys.readouterr().err
