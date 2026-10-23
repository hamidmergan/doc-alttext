"""Web API for the review page: upload one file, let the model write alt texts, edit them, download the result."""

import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from ..config import Settings
from ..core import SUPPORTED, AltTexter, apply_alt_texts
from ..report import DECORATIVE, KEPT, UNSUPPORTED, ImageItem
from ..report_html import thumbnail_png

STATIC = Path(__file__).parent / "static"
CHUNK = 1024 * 1024

_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@dataclass
class Job:
    id: str
    name: str  # file name as uploaded
    path: Path
    state: str = "running"  # running, done, failed
    progress: str = "starting"
    items: List[ImageItem] = field(default_factory=list)
    language: str = ""
    error: str = ""


class Decision(BaseModel):
    alt: str = ""
    decorative: bool = False


class DownloadRequest(BaseModel):
    decisions: List[Optional[Decision]]


def create_app(settings: Settings, workdir: Optional[Path] = None,
               allowed_hosts: Optional[Sequence[str]] = None) -> FastAPI:
    """The review page and its JSON API. One file at a time; a new upload replaces the previous one.

    allowed_hosts limits the Host header (against DNS rebinding). Requests from another origin are refused.
    """
    tmp = None if workdir is not None else tempfile.TemporaryDirectory(prefix="doc-alttext-")
    root = Path(workdir) if workdir is not None else Path(tmp.name)
    root.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    current: dict = {"job": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if tmp is not None:
            tmp.cleanup()

    app = FastAPI(title="doc-alttext", lifespan=lifespan)
    hosts = {h.lower() for h in allowed_hosts} if allowed_hosts is not None else None

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if hosts is not None and _hostname(host) not in hosts:
            return PlainTextResponse("Unknown host", status_code=400)
        origin = request.headers.get("origin")
        own = {host.lower(), request.headers.get("x-forwarded-host", "").lower()}  # also behind a reverse proxy
        if origin is not None and urlsplit(origin).netloc.lower() not in own:
            return PlainTextResponse("Cross-origin requests are not allowed", status_code=403)
        return await call_next(request)

    def job_or_404(job_id: str) -> Job:
        with lock:
            job = current["job"]
        if job is None or job.id != job_id:
            raise HTTPException(404, "This file is no longer open. Upload it again.")
        return job

    def run(job: Job) -> None:
        def progress(message: str) -> None:
            with lock:
                job.progress = message

        try:
            result = AltTexter(progress, settings=settings).process(job.path, dry_run=True)
        except Exception as exc:  # shown on the page
            with lock:
                job.state, job.error = "failed", str(exc)
            return
        with lock:
            job.items, job.language, job.state = result.items, result.language, "done"

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.post("/api/upload")
    def upload(file: UploadFile = File(...)) -> dict:
        name = Path(file.filename or "").name
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(400, f"Unsupported file type {suffix or '(none)'}. Use a Word or PowerPoint file.")
        job = Job(id=uuid.uuid4().hex, name=name, path=root / uuid.uuid4().hex / ("input" + suffix))
        job.path.parent.mkdir(parents=True)
        limit = settings.max_file_mb * 1024 * 1024
        size = 0
        with job.path.open("wb") as out:
            while True:
                chunk = file.file.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    out.close()
                    shutil.rmtree(job.path.parent, ignore_errors=True)
                    raise HTTPException(413, f"The file is larger than {settings.max_file_mb:g} MB.")
                out.write(chunk)
        with lock:
            old = current["job"]
            current["job"] = job
        if old is not None:
            shutil.rmtree(old.path.parent, ignore_errors=True)
        threading.Thread(target=run, args=(job,), daemon=True).start()
        return _job_json(job, settings)

    @app.get("/api/job")
    def job_state() -> dict:
        with lock:
            job = current["job"]
            return _job_json(job, settings) if job is not None else {"state": "empty"}

    @app.get("/api/job/{job_id}/images/{index}.png")
    def image(job_id: str, index: int) -> Response:
        job = job_or_404(job_id)
        with lock:
            items = list(job.items)
        if not 0 <= index < len(items) or not items[index].image:
            raise HTTPException(404, "No such image.")
        try:
            with zipfile.ZipFile(job.path) as archive:
                png = thumbnail_png(archive.read(items[index].image))
        except (OSError, KeyError, zipfile.BadZipFile):
            png = None
        if png is None:
            raise HTTPException(404, "No preview for this image.")
        return Response(png, media_type="image/png")

    @app.post("/api/job/{job_id}/download")
    def download(job_id: str, body: DownloadRequest) -> FileResponse:
        job = job_or_404(job_id)
        if job.state != "done":
            raise HTTPException(409, "The file is not ready yet.")
        stem, suffix = Path(job.name).stem, job.path.suffix
        output = job.path.parent / f"output{suffix}"
        decisions = [None if d is None else {"alt": d.alt, "decorative": d.decorative} for d in body.decisions]
        try:
            apply_alt_texts(job.path, decisions, output)
        except Exception as exc:
            raise HTTPException(400, str(exc))
        return FileResponse(output, media_type=_MEDIA_TYPES.get(suffix, "application/octet-stream"),
                            filename=_safe_name(f"{stem}.alt{suffix}"))

    return app


def _job_json(job: Job, settings: Settings) -> dict:
    items = []
    for i, item in enumerate(job.items):
        decorative = item.status == DECORATIVE or (item.status == KEPT and not item.old_alt)
        items.append({
            "index": i,
            "location": item.location,
            "shape": item.shape,
            "status": item.status,
            "old_alt": item.old_alt,
            "alt": item.new_alt or (item.old_alt if item.status == KEPT else ""),
            "decorative": decorative,
            "editable": item.status != UNSUPPORTED,
            "has_image": bool(item.image),
            "note": item.note,
        })
    return {
        "id": job.id,
        "name": job.name,
        "state": job.state,
        "progress": job.progress,
        "error": job.error,
        "language": job.language,
        "max_chars": settings.max_chars,
        "items": items,
    }


def _hostname(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", name) or "document"
