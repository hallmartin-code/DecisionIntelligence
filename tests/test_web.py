"""Web layer tests. The Anthropic call is stubbed — no test hits the network."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitch_analyzer.jobs import JobState, JobStore
from pitch_analyzer.models import AnalysisResult

PASSWORD = "s3cret"
AUTH = ("ten", PASSWORD)


@pytest.fixture(autouse=True)
def configured_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("APP_USERNAME", "ten")
    monkeypatch.delenv("ALLOW_ANONYMOUS", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture
def deck_bytes() -> bytes:
    """A tiny but real 3-page PDF."""
    import io

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    for title in ("Testco", "The Problem", "The Ask"):
        pdf.setFont("Helvetica-Bold", 24)
        pdf.drawString(72, 700, title)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture
def client(monkeypatch, tmp_path, analysis_result):
    """A client whose job store writes to tmp_path and never calls the API."""
    import pitch_analyzer.jobs as jobs_module
    import pitch_analyzer.web as web_module

    monkeypatch.setattr(
        jobs_module, "analyze_deck", lambda *args, **kwargs: analysis_result
    )

    store = JobStore(root=tmp_path / "jobs", max_workers=2, ttl_minutes=60)
    monkeypatch.setattr(web_module, "store", store)

    with TestClient(web_module.app) as test_client:
        yield test_client

    # Block until in-flight workers finish: a thread that outlived this fixture
    # would see the un-patched analyze_deck and could reach the real API.
    store.shutdown(wait=True)


def _wait_for_completion(client, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/jobs/{job_id}/status", auth=AUTH).json()
        if payload["done"]:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# --------------------------------------------------------------------------- #
# Health and auth
# --------------------------------------------------------------------------- #


def test_healthz_needs_no_auth(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_healthz_reports_the_effective_upload_limit(client):
    """A deployment enforcing an unexpected limit must be diagnosable.

    The limit is settable by env var, so a stale or misconfigured deployment can
    silently advertise a smaller size than the code default. Reporting it here
    turns "why does it say 25 MB?" into one request.
    """
    import pitch_analyzer.web as web_module

    body = client.get("/healthz").json()

    assert body["max_upload_mb"] == web_module.MAX_UPLOAD_MB
    assert body["max_upload_bytes"] == web_module.MAX_UPLOAD_BYTES
    assert body["upload_limit_source"] in ("default", "environment")


def test_the_code_default_is_50_mb():
    """The shipped default, independent of whatever the environment sets."""
    import pitch_analyzer.web as web_module

    assert web_module.DEFAULT_MAX_UPLOAD_MB == 50


def test_index_requires_credentials(client):
    assert client.get("/").status_code == 401


def test_index_rejects_a_wrong_password(client):
    assert client.get("/", auth=("ten", "wrong")).status_code == 401


def test_index_renders_for_an_authenticated_user(client):
    response = client.get("/", auth=AUTH)

    assert response.status_code == 200
    assert "Generate the report" in response.text
    assert "Deck Analyzer" in response.text
    assert "TEN Capital" in response.text


def test_index_advertises_only_supported_deck_types(client):
    """The accept filter must match what ingest.py can actually read."""
    response = client.get("/", auth=AUTH)

    assert 'accept=".pdf,.pptx"' in response.text
    assert ".docx" not in response.text


def test_disclosure_matches_reality_when_email_is_off(client):
    """With no Resend key the page must not claim anything is emailed."""
    body = client.get("/", auth=AUTH).text.split("</head>", 1)[1]

    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", body), (
        "an email address is displayed, implying decks are sent somewhere"
    )
    assert "not emailed or shared" in body


def test_disclosure_names_the_recipients_when_email_is_on(client, monkeypatch):
    """If reports are emailed, the uploader must be told before uploading."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("REPORT_EMAIL_TO", "Info@tencapital.group")

    body = client.get("/", auth=AUTH).text.split("</head>", 1)[1]

    assert "emailed to" in body
    assert "Info@tencapital.group" in body
    assert "not emailed or shared" not in body


def test_missing_app_password_locks_the_app_down(client, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)

    response = client.get("/", auth=AUTH)

    assert response.status_code == 503
    assert "APP_PASSWORD" in response.json()["detail"]


def test_allow_anonymous_opens_the_app_deliberately(client, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.setenv("ALLOW_ANONYMOUS", "1")

    assert client.get("/").status_code == 200


def test_api_key_warning_shown_when_unset(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    response = client.get("/", auth=AUTH)

    assert "No API key configured" in response.text


# --------------------------------------------------------------------------- #
# Upload validation
# --------------------------------------------------------------------------- #


def test_upload_rejects_an_unsupported_extension(client):
    response = client.post(
        "/analyze",
        auth=AUTH,
        files={"deck": ("deck.key", b"nope", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "Expected .pdf or .pptx" in response.json()["detail"]


def test_upload_rejects_an_empty_file(client):
    response = client.post(
        "/analyze",
        auth=AUTH,
        files={"deck": ("deck.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400


def test_default_upload_limit_is_50_mb(client):
    """Server, page copy and the client-side check must all agree."""
    import pitch_analyzer.web as web_module

    assert web_module.MAX_UPLOAD_MB == 50
    assert web_module.MAX_UPLOAD_BYTES == 50 * 1024 * 1024

    page = client.get("/", auth=AUTH).text
    assert "up to 50&nbsp;MB" in page
    assert "const MAX_BYTES = 50 * 1024 * 1024" in page


def test_a_deck_at_the_limit_is_accepted(client, deck_bytes, monkeypatch):
    """The cap is exclusive: a deck exactly at the limit must still be taken."""
    import pitch_analyzer.web as web_module
    monkeypatch.setattr(web_module, "MAX_UPLOAD_BYTES", len(deck_bytes))
    response = client.post(
        "/analyze",
        auth=AUTH,
        headers={"Accept": "application/json"},
        files={"deck": ("edge.pdf", deck_bytes, "application/pdf")},
    )
    assert response.status_code == 202
def test_upload_rejects_an_oversized_file(client, monkeypatch):
    import pitch_analyzer.web as web_module

    monkeypatch.setattr(web_module, "MAX_UPLOAD_BYTES", 10)

    response = client.post(
        "/analyze",
        auth=AUTH,
        files={"deck": ("deck.pdf", b"x" * 64, "application/pdf")},
    )

    assert response.status_code == 413


def test_an_oversized_upload_is_refused_without_buffering_it_all(client, monkeypatch):
    """The cap must bound memory, not merely the accepted size.

    Reading the whole body before measuring meant a huge upload was fully held
    in memory before the 413; the read is chunked so it stops near the limit.
    """
    import pitch_analyzer.web as web_module

    monkeypatch.setattr(web_module, "MAX_UPLOAD_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr(web_module, "UPLOAD_CHUNK_BYTES", 256 * 1024)

    response = client.post(
        "/analyze",
        auth=AUTH,
        files={"deck": ("huge.pdf", b"x" * (32 * 1024 * 1024), "application/pdf")},
    )

    assert response.status_code == 413
    assert "50 MB limit" in response.json()["detail"]


def test_a_multi_chunk_deck_survives_reassembly(client, deck_bytes, monkeypatch):
    """A body spanning many read chunks must come back byte-for-byte."""
    import pitch_analyzer.web as web_module

    monkeypatch.setattr(web_module, "UPLOAD_CHUNK_BYTES", 8 * 1024)
    payload = deck_bytes + b" " * (256 * 1024 - len(deck_bytes))

    submitted = client.post(
        "/analyze",
        auth=AUTH,
        headers={"Accept": "application/json"},
        files={"deck": ("chunked.pdf", payload, "application/pdf")},
    )

    assert submitted.status_code == 202
    job = web_module.store.get(submitted.json()["job_id"])
    assert job.deck_path.read_bytes() == payload


def test_upload_requires_auth(client, deck_bytes):
    response = client.post(
        "/analyze", files={"deck": ("deck.pdf", deck_bytes, "application/pdf")}
    )

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Job flow
# --------------------------------------------------------------------------- #


def test_full_job_flow_produces_a_downloadable_report(client, deck_bytes):
    submitted = client.post(
        "/analyze",
        auth=AUTH,
        headers={"Accept": "application/json"},
        files={"deck": ("Testco Deck.pdf", deck_bytes, "application/pdf")},
        data={"include_images": "off"},
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]

    final = _wait_for_completion(client, job_id)
    assert final["state"] == JobState.DONE.value
    assert final["error"] is None
    assert final["recommendation"] == "Investigate Further"
    assert final["confidence_pct"] == 62
    assert final["slide_count"] == 3

    report = client.get(f"/jobs/{job_id}/report.docx", auth=AUTH)
    assert report.status_code == 200
    assert "wordprocessingml" in report.headers["content-type"]
    # Starlette percent-encodes the filename per RFC 5987.
    assert "Testco%20Deck_analysis.docx" in report.headers["content-disposition"]
    assert report.content[:2] == b"PK"
    assert len(report.content) > 5 * 1024


def test_browser_submit_redirects_to_the_job_page(client, deck_bytes):
    response = client.post(
        "/analyze",
        auth=AUTH,
        files={"deck": ("deck.pdf", deck_bytes, "application/pdf")},
        data={"include_images": "off"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/jobs/")

    page = client.get(location, auth=AUTH)
    assert page.status_code == 200
    assert "deck.pdf" in page.text


def test_job_endpoints_require_auth(client, deck_bytes):
    submitted = client.post(
        "/analyze",
        auth=AUTH,
        headers={"Accept": "application/json"},
        files={"deck": ("deck.pdf", deck_bytes, "application/pdf")},
        data={"include_images": "off"},
    )
    job_id = submitted.json()["job_id"]

    assert client.get(f"/jobs/{job_id}").status_code == 401
    assert client.get(f"/jobs/{job_id}/status").status_code == 401
    assert client.get(f"/jobs/{job_id}/report.docx").status_code == 401


def test_unknown_job_is_a_404(client):
    assert client.get("/jobs/does-not-exist/status", auth=AUTH).status_code == 404


def test_unchecked_images_box_produces_a_text_only_analysis(client, deck_bytes):
    """An unticked checkbox is omitted from the POST, so the default must be off."""
    import pitch_analyzer.web as web_module

    submitted = client.post(
        "/analyze",
        auth=AUTH,
        headers={"Accept": "application/json"},
        files={"deck": ("deck.pdf", deck_bytes, "application/pdf")},
        data={},  # no include_images, as a browser sends
    )
    job = web_module.store.get(submitted.json()["job_id"])

    assert job.include_images is False


def test_checked_images_box_enables_images(client, deck_bytes):
    import pitch_analyzer.web as web_module

    submitted = client.post(
        "/analyze",
        auth=AUTH,
        headers={"Accept": "application/json"},
        files={"deck": ("deck.pdf", deck_bytes, "application/pdf")},
        data={"include_images": "on"},
    )
    job = web_module.store.get(submitted.json()["job_id"])

    assert job.include_images is True


# --------------------------------------------------------------------------- #
# Error rendering
# --------------------------------------------------------------------------- #


def test_browser_errors_render_as_styled_html(client):
    response = client.get(
        "/jobs/nope", auth=AUTH, headers={"Accept": "text/html"}
    )

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Nothing here" in response.text
    assert "TEN Capital" in response.text


def test_api_errors_stay_json(client):
    response = client.get(
        "/jobs/nope", auth=AUTH, headers={"Accept": "application/json"}
    )

    assert response.status_code == 404
    assert response.json()["detail"]


def test_status_polling_always_gets_json_even_from_a_browser(client):
    """The job page polls with fetch; an HTML error body would break it."""
    response = client.get(
        "/jobs/nope/status", auth=AUTH, headers={"Accept": "text/html"}
    )

    assert response.status_code == 404
    assert response.json()["detail"]


def test_unauthenticated_browser_request_still_prompts_for_credentials(client):
    response = client.get("/", headers={"Accept": "text/html"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"
    assert "Sign in to continue" in response.text


def test_report_is_409_until_the_job_finishes(client, tmp_path):
    import pitch_analyzer.web as web_module

    job = web_module.store.submit(
        filename="pending.pdf", payload=b"%PDF-1.4 stub", include_images=False
    )
    job.state = JobState.ANALYZING
    job.report_path = None

    response = client.get(f"/jobs/{job.id}/report.docx", auth=AUTH)

    assert response.status_code == 409


def test_a_broken_deck_fails_the_job_with_a_readable_message(client):
    submitted = client.post(
        "/analyze",
        auth=AUTH,
        headers={"Accept": "application/json"},
        files={"deck": ("broken.pdf", b"not really a pdf", "application/pdf")},
        data={"include_images": "off"},
    )
    job_id = submitted.json()["job_id"]

    final = _wait_for_completion(client, job_id)

    assert final["state"] == JobState.FAILED.value
    assert final["error"]
    assert "Traceback" not in final["error"]


# --------------------------------------------------------------------------- #
# Store behaviour
# --------------------------------------------------------------------------- #


def test_sweep_removes_expired_jobs_and_their_files(tmp_path):
    from datetime import datetime, timedelta, timezone

    store = JobStore(root=tmp_path / "jobs", max_workers=1, ttl_minutes=60)
    try:
        job = store.submit(filename="old.pdf", payload=b"%PDF stub")
        deadline = time.time() + 10
        while not job.state.is_terminal and time.time() < deadline:
            time.sleep(0.05)
        assert job.state.is_terminal

        job.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        workdir = job.workdir

        assert store.sweep() == 1
        assert store.get(job.id) is None
        assert not workdir.exists()
    finally:
        store.shutdown(wait=True)


def test_sweep_leaves_a_running_job_alone(tmp_path):
    """Deleting a running job's workdir mid-analysis would break it."""
    from datetime import datetime, timedelta, timezone

    from pitch_analyzer.jobs import Job

    store = JobStore(root=tmp_path / "jobs", max_workers=1, ttl_minutes=60)
    try:
        workdir = store.root / "running"
        workdir.mkdir(parents=True)
        running = Job(
            id="running",
            filename="deck.pdf",
            model="test",
            include_images=False,
            workdir=workdir,
            deck_path=workdir / "deck.pdf",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            state=JobState.ANALYZING,
        )
        store._jobs[running.id] = running

        assert store.sweep() == 0
        assert store.get("running") is not None
        assert workdir.exists()
    finally:
        store.shutdown(wait=True)


def test_friendly_error_hides_stack_traces():
    from pitch_analyzer.analyze import MissingAPIKeyError
    from pitch_analyzer.jobs import _friendly_error

    message = _friendly_error(MissingAPIKeyError("boom"))

    assert "ANTHROPIC_API_KEY" in message
    assert "Traceback" not in message
