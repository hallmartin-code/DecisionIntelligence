"""Files API: upload the deck once and reference it by id.

Sending a PDF as a `document` block lets Claude read the file itself — layout,
charts and slide imagery together — rather than the flattened text pdfplumber
can recover plus a handful of separately rendered page images. In a pitch deck
the argument frequently lives in a chart, so that difference is the point of
using the API at all.

PPTX has no `document` block type, so those decks keep the local extraction
path in `ingest.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

#: The shortest expiry the API accepts. A deck is needed only for the length of
#: one analysis, and uploads are visible to the whole workspace, so the file is
#: deleted as soon as the run finishes; this is the backstop for a run that
#: dies before it can clean up.
DEFAULT_EXPIRY_SECONDS = 3600

#: Only PDFs go through the Files API as documents — see the module docstring.
DOCUMENT_SUFFIXES = (".pdf",)
PDF_MIME_TYPE = "application/pdf"

#: Above this page count the deck is analysed from extracted text instead.
#:
#: The API caps a request at 100 pages, but context runs out first: every page
#: is charged as text (1,500-3,000 tokens) *and* as an image, and a 10-page
#: sample deck measured ~3,750 tokens per page. Against a 200k window with
#: MAX_TOKENS reserved for the report and ~10k for the schema and structure
#: notes, roughly 140k is left for the deck — about 37 pages. 35 keeps a
#: margin, because the cost per page rises with visual density and the docs
#: warn that large PDFs can fail before the page limit is reached.
#:
#: The failure this avoids is expensive: it lands minutes into a run, after the
#: upload, rather than at submission.
MAX_NATIVE_PAGES = 35


class FileUploadError(RuntimeError):
    """Raised when a deck could not be uploaded to the Files API."""


def supports_document_block(path: str | Path) -> bool:
    """True when this deck can be sent natively instead of as extracted text."""
    return Path(path).suffix.lower() in DOCUMENT_SUFFIXES


def upload_deck(
    client: Any,
    path: str | Path,
    expires_in_seconds: int = DEFAULT_EXPIRY_SECONDS,
) -> str:
    """Upload a deck and return its `file_id`."""
    deck = Path(path)
    if not supports_document_block(deck):
        raise FileUploadError(
            f"{deck.suffix or deck.name} cannot be sent as a document block; "
            "only PDF is supported."
        )
    try:
        with deck.open("rb") as handle:
            uploaded = client.files.upload(
                file=(deck.name, handle, PDF_MIME_TYPE),
                expires_in_seconds=expires_in_seconds,
            )
    except Exception as error:  # network, auth, quota
        raise FileUploadError(f"Could not upload {deck.name}: {error}") from error

    file_id = getattr(uploaded, "id", None)
    if not file_id:
        raise FileUploadError("The Files API response contained no file id.")
    return file_id


def delete_file(client: Any, file_id: Optional[str]) -> bool:
    """Delete an uploaded file, reporting success rather than raising.

    Cleanup must never turn a finished analysis into a failed one, and an
    undeleted file expires on its own. Uploads are readable by any key in the
    workspace, though, so a leak is worth logging.
    """
    if not file_id:
        return False
    try:
        client.files.delete(file_id)
        return True
    except Exception:
        return False
