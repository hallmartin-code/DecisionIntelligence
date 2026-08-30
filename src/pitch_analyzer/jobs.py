"""In-process job queue for deck analyses.

An analysis takes minutes, which is far too long to hold an HTTP request open,
so the web layer submits a job and polls it. State lives in memory and files
live on local disk: both are lost on restart, which is the right trade for a
single-instance deployment where a lost job simply means re-uploading.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from .analyze import (
    DEFAULT_MODEL,
    InvalidJSONResponseError,
    MissingAPIKeyError,
    RateLimitExceededError,
    analyze_deck,
)
from .ingest import UnsupportedDeckError, guess_company_name, ingest
from .notify import notify_report_ready
from .render import LayoutOverflowError, render_one_pager


class JobState(str, Enum):
    QUEUED = "queued"
    READING = "reading"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.DONE, JobState.FAILED)


PROGRESS = {
    JobState.QUEUED: 5,
    JobState.READING: 15,
    JobState.ANALYZING: 45,
    JobState.RENDERING: 90,
    JobState.DONE: 100,
    JobState.FAILED: 100,
}

# A job still running is only swept once it is this many TTLs old — by then it
# is wedged, not working.
STUCK_JOB_TTL_MULTIPLIER = 4

STATE_LABELS = {
    JobState.QUEUED: "Queued",
    JobState.READING: "Reading the deck",
    JobState.ANALYZING: "Analyzing with Claude",
    JobState.RENDERING: "Rendering the one-pager",
    JobState.DONE: "Complete",
    JobState.FAILED: "Failed",
}


@dataclass
class Job:
    """One deck analysis, from upload through to a downloadable report."""

    id: str
    filename: str
    orientation: str
    model: str
    include_images: bool
    workdir: Path
    deck_path: Path
    created_at: datetime
    state: JobState = JobState.QUEUED
    error: Optional[str] = None
    report_path: Optional[Path] = None
    company_name: Optional[str] = None
    slide_count: int = 0
    recommendation: Optional[str] = None
    confidence_pct: Optional[int] = None
    weighted_overall: Optional[float] = None
    email_status: Optional[str] = None
    log: list[str] = field(default_factory=list)

    @property
    def progress(self) -> int:
        return PROGRESS[self.state]

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]

    @property
    def report_filename(self) -> str:
        stem = Path(self.filename).stem or "deck"
        return f"{stem}_analysis.pdf"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "state": self.state.value,
            "label": self.label,
            "progress": self.progress,
            "done": self.state.is_terminal,
            "error": self.error,
            "company_name": self.company_name,
            "slide_count": self.slide_count,
            "recommendation": self.recommendation,
            "confidence_pct": self.confidence_pct,
            "weighted_overall": self.weighted_overall,
            "email_status": self.email_status,
            "created_at": self.created_at.isoformat(),
            "log": list(self.log),
        }


class JobStore:
    """Thread-safe job registry with a bounded worker pool and TTL cleanup."""

    def __init__(
        self,
        root: Optional[Path] = None,
        max_workers: int = 2,
        ttl_minutes: int = 60,
    ) -> None:
        configured = os.environ.get("DATA_DIR", "").strip()
        self.root = Path(
            root or configured or Path(tempfile.gettempdir()) / "pitch-analyzer"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(minutes=ttl_minutes)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="analysis"
        )

    # -- lifecycle ------------------------------------------------------- #

    def submit(
        self,
        filename: str,
        payload: bytes,
        orientation: str = "landscape",
        model: str = DEFAULT_MODEL,
        include_images: bool = True,
        api_key: Optional[str] = None,
    ) -> Job:
        job_id = uuid.uuid4().hex
        workdir = self.root / job_id
        workdir.mkdir(parents=True, exist_ok=True)

        suffix = Path(filename).suffix.lower()
        deck_path = workdir / f"deck{suffix}"
        deck_path.write_bytes(payload)

        job = Job(
            id=job_id,
            filename=Path(filename).name,
            orientation=orientation,
            model=model,
            include_images=include_images,
            workdir=workdir,
            deck_path=deck_path,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._jobs[job_id] = job

        self._pool.submit(self._run, job, api_key)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def sweep(self) -> int:
        """Drop jobs past their TTL and delete their files.

        A job still running is left alone until a generous grace period has
        passed — deleting its working directory mid-analysis would break it.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - self.ttl
        stuck_cutoff = now - (self.ttl * STUCK_JOB_TTL_MULTIPLIER)

        with self._lock:
            expired = [
                job
                for job in self._jobs.values()
                if job.created_at < (cutoff if job.state.is_terminal else stuck_cutoff)
            ]
            for job in expired:
                self._jobs.pop(job.id, None)
        for job in expired:
            shutil.rmtree(job.workdir, ignore_errors=True)
        return len(expired)

    def shutdown(self, wait: bool = False) -> None:
        """Stop accepting work.

        `wait=True` blocks until in-flight analyses finish — needed in tests, so
        a worker thread cannot outlive the fixtures it depends on.
        """
        self._pool.shutdown(wait=wait, cancel_futures=True)

    # -- worker ---------------------------------------------------------- #

    def _run(self, job: Job, api_key: Optional[str]) -> None:
        try:
            job.state = JobState.READING
            content = ingest(job.deck_path, include_images=job.include_images)
            job.slide_count = content.slide_count
            job.company_name = guess_company_name(
                content.text, fallback=Path(job.filename).stem
            )
            job.log.append(
                f"Read {content.slide_count} slide(s), "
                f"{len(content.text):,} characters, {len(content.images)} image(s)."
            )

            job.state = JobState.ANALYZING
            analysis = analyze_deck(
                content,
                model=job.model,
                api_key=api_key,
                include_images=job.include_images,
                log=job.log.append,
            )
            job.recommendation = analysis.executive_summary.recommendation
            job.confidence_pct = analysis.executive_summary.confidence_pct
            job.weighted_overall = analysis.scores.weighted_overall

            job.state = JobState.RENDERING
            report_path = job.workdir / job.report_filename
            render_one_pager(
                analysis,
                report_path,
                company_name=job.company_name or "Pitch Deck",
                orientation=job.orientation,
            )
            job.report_path = report_path
            job.log.append("Report rendered.")

            # Best-effort: a mail problem must not fail a finished analysis.
            status = notify_report_ready(
                analysis,
                report_path,
                company_name=job.company_name or Path(job.filename).stem,
                deck_filename=job.filename,
                model=job.model,
                slide_count=job.slide_count,
            )
            if status:
                job.log.append(status)
                job.email_status = status

            job.state = JobState.DONE

        except Exception as error:  # noqa: BLE001 - surfaced to the user verbatim
            job.error = _friendly_error(error)
            job.state = JobState.FAILED


def _friendly_error(error: Exception) -> str:
    """Turn a pipeline exception into something a user can act on."""
    if isinstance(error, MissingAPIKeyError):
        return (
            "No Anthropic API key is configured. Set ANTHROPIC_API_KEY in the "
            "service environment."
        )
    if isinstance(error, UnsupportedDeckError):
        return str(error)
    if isinstance(error, RateLimitExceededError):
        return (
            "The Anthropic API rate limit was hit repeatedly. Wait a minute and "
            "try again."
        )
    if isinstance(error, InvalidJSONResponseError):
        return (
            "The model did not return a valid analysis after two attempts. "
            "Try again, or run with a different model."
        )
    if isinstance(error, LayoutOverflowError):
        return f"The report could not be fitted onto one page. {error}"
    if isinstance(error, RuntimeError):
        return str(error)

    try:
        import anthropic

        if isinstance(error, anthropic.AuthenticationError):
            return "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY."
        if isinstance(error, anthropic.APIStatusError):
            return f"The Anthropic API returned an error: {error}"
        if isinstance(error, anthropic.APIConnectionError):
            return "Could not reach the Anthropic API. Check network access."
    except Exception:  # pragma: no cover - anthropic always installed
        pass

    return f"{type(error).__name__}: {error}"
