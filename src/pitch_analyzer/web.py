"""FastAPI web front end: upload a deck, poll the job, download the report.

Deployed as a single instance (Railway), so job state is in-process and files
are on local disk. See `jobs.py` for the queue.
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from . import __version__
from .analyze import DEFAULT_MODEL
from .jobs import JobStore
from .notify import load_email_config

load_dotenv()

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".pdf", ".pptx")
TEMPLATES_DIR = Path(__file__).resolve().parent / "web_templates"

DEFAULT_MAX_UPLOAD_MB = 50
#: True when the limit came from the environment rather than the code default.
#: A deployment that sets this lower than the default silently shrinks the UI,
#: which is invisible unless it is reported — see /healthz.
UPLOAD_LIMIT_FROM_ENV = bool(os.environ.get("MAX_UPLOAD_MB", "").strip())
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB") or DEFAULT_MAX_UPLOAD_MB)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
JOB_TTL_MINUTES = int(os.environ.get("JOB_TTL_MINUTES", "60"))
MAX_CONCURRENT_ANALYSES = int(os.environ.get("MAX_CONCURRENT_ANALYSES", "2"))

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
security = HTTPBasic(auto_error=False)

store = JobStore(max_workers=MAX_CONCURRENT_ANALYSES, ttl_minutes=JOB_TTL_MINUTES)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    source = "MAX_UPLOAD_MB env var" if UPLOAD_LIMIT_FROM_ENV else "code default"
    logger.info("Upload limit: %s MB (from %s)", MAX_UPLOAD_MB, source)
    if UPLOAD_LIMIT_FROM_ENV and MAX_UPLOAD_MB < DEFAULT_MAX_UPLOAD_MB:
        logger.warning(
            "MAX_UPLOAD_MB=%s is below the %s MB default — the upload form will "
            "advertise and enforce the smaller value. Unset the variable to use "
            "the default.",
            MAX_UPLOAD_MB,
            DEFAULT_MAX_UPLOAD_MB,
        )
    yield
    store.shutdown()


app = FastAPI(
    title="Pitch Deck Decision Intelligence",
    version=__version__,
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Error pages
# --------------------------------------------------------------------------- #

ERROR_HEADINGS = {
    400: "That upload was not usable",
    401: "Sign in to continue",
    404: "Nothing here",
    409: "Not ready yet",
    413: "That deck is too large",
    503: "Not configured",
}


@app.exception_handler(HTTPException)
async def render_http_exception(request: Request, exc: HTTPException):
    """Styled HTML for browsers, JSON for everything else."""
    if not _wants_html(request):
        return await http_exception_handler(request, exc)

    response = templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": exc.status_code,
            "heading": ERROR_HEADINGS.get(exc.status_code, "Something went wrong"),
            "detail": exc.detail,
        },
        status_code=exc.status_code,
    )
    # Preserve WWW-Authenticate so the browser still prompts for credentials.
    for key, value in (exc.headers or {}).items():
        response.headers[key] = value
    return response


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


def require_auth(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> None:
    """Gate every user-facing route behind a shared password.

    This endpoint spends Anthropic credits on every upload, so it must not be
    left open to the internet. Set APP_PASSWORD, or set ALLOW_ANONYMOUS=1 to
    deliberately run it open (local development).
    """
    password = os.environ.get("APP_PASSWORD", "")
    if not password:
        if os.environ.get("ALLOW_ANONYMOUS") == "1":
            return
        raise HTTPException(
            status_code=503,
            detail=(
                "APP_PASSWORD is not set. Configure it in the service "
                "environment, or set ALLOW_ANONYMOUS=1 to run without a "
                "password."
            ),
        )

    expected_user = os.environ.get("APP_USERNAME", "ten")
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )

    user_ok = secrets.compare_digest(credentials.username, expected_user)
    password_ok = secrets.compare_digest(credentials.password, password)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/healthz", include_in_schema=False)
def healthz() -> JSONResponse:
    """Unauthenticated health check, and the effective upload limit.

    The limit is reported here so a deployment enforcing an unexpected value can
    be diagnosed from one URL, without reading the container's logs.
    """
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "upload_limit_source": (
                "environment" if UPLOAD_LIMIT_FROM_ENV else "default"
            ),
        }
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, _: None = Depends(require_auth)) -> HTMLResponse:
    store.sweep()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "default_model": DEFAULT_MODEL,
            "max_upload_mb": MAX_UPLOAD_MB,
            "job_ttl_minutes": JOB_TTL_MINUTES,
            "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "email_recipients": _email_recipients(),
        },
    )


@app.post("/analyze")
async def submit_analysis(
    request: Request,
    deck: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL),
    # An unchecked HTML checkbox is omitted from the POST entirely, so the
    # default here must be "off" — otherwise unticking the box would do nothing.
    include_images: str = Form("off"),
    _: None = Depends(require_auth),
):
    filename = deck.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix or filename}'. Expected .pdf or .pptx.",
        )

    payload = await _read_capped(deck)
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    store.sweep()
    job = store.submit(
        filename=filename,
        payload=payload,
        model=model.strip() or DEFAULT_MODEL,
        include_images=include_images == "on",
    )

    if _wants_json(request):
        return JSONResponse({"job_id": job.id, **job.as_dict()}, status_code=202)
    return HTMLResponse(
        status_code=303, headers={"Location": f"/jobs/{job.id}"}, content=""
    )


async def _read_capped(deck: UploadFile) -> bytes:
    """Read the upload, refusing it as soon as it passes the limit.

    Reading the whole body first and measuring afterwards means an oversized
    upload is fully buffered before it is rejected, so memory use is set by
    whatever was sent rather than by the limit. Reading in chunks bounds it.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await deck.read(UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Deck is larger than the {MAX_UPLOAD_MB} MB limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(
    request: Request, job_id: str, _: None = Depends(require_auth)
) -> HTMLResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    return templates.TemplateResponse(request, "job.html", {"job": job})


@app.get("/jobs/{job_id}/status")
def job_status(job_id: str, _: None = Depends(require_auth)) -> JSONResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    return JSONResponse(job.as_dict())


@app.get("/jobs/{job_id}/report.docx")
def job_report(job_id: str, _: None = Depends(require_auth)) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    if job.report_path is None or not job.report_path.exists():
        raise HTTPException(status_code=409, detail="The report is not ready yet.")
    return FileResponse(
        job.report_path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        filename=job.report_filename,
    )


def _email_recipients() -> list[str]:
    """Who each finished report is emailed to, for the upload-page disclosure."""
    config = load_email_config()
    return list(config.recipients) if config else []


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def _wants_html(request: Request) -> bool:
    """True for a browser navigation, false for fetch/curl/API clients."""
    if request.url.path.startswith("/jobs/") and request.url.path.endswith("/status"):
        return False
    return "text/html" in request.headers.get("accept", "")
