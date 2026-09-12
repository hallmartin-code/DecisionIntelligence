"""Anthropic API call, retry logic, and JSON validation."""

from __future__ import annotations

import base64
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .config import env_flag
from .files import (
    MAX_NATIVE_PAGES,
    FileUploadError,
    delete_file,
    supports_document_block,
    upload_deck,
)
from .ingest import DeckContent
from .models import AnalysisResult
from .prompt import SYSTEM_PROMPT, build_user_prompt

DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 48000  # the full report is long; leaves headroom over a ~25k typical
RATE_LIMIT_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
#: How many times a paused turn may be resumed before giving up. The API
#: pauses a long turn and expects the response handed back to continue it;
#: a sandbox session can pause more than once on a dense deck.
MAX_TURN_CONTINUATIONS = 6

#: Server-side Python sandbox. The prompt asks the model to check the deck's
#: arithmetic; without this it can only do that in its head, which is exactly
#: the kind of claim it is being asked to audit. Needs no beta header.
CODE_EXECUTION_TOOL = {"type": "code_execution_20250825", "name": "code_execution"}


def _correction_message(problem: str) -> str:
    """Tell the model exactly what failed, so the retry is targeted."""
    return (
        f"Your previous response could not be used: {problem}\n\n"
        "Return the corrected JSON object only — no prose, no code fence — "
        "including every required field."
    )


#: What went wrong when the turn ended on a tool call. The model does the whole
#: analysis, writes the report into a file in the sandbox, and ends its turn --
#: so the reply carries only its narration. Nothing reads that file, and the
#: work is lost unless the reply is continued rather than restarted.
NO_JSON_IN_REPLY = (
    "your reply contained no JSON - you ended your turn on a tool call. "
    "Anything written to a file in the sandbox is discarded; only the text of "
    "your reply is read"
)


def _reply_is_only_narration(raw: str, message: Any) -> bool:
    """True when the turn ended on tool use rather than on the answer."""
    blocks = list(getattr(message, "content", []))
    if not blocks:
        return False
    ended_on_a_tool = getattr(blocks[-1], "type", "") != "text"
    return ended_on_a_tool and "{" not in raw


class MissingAPIKeyError(RuntimeError):
    """Raised when no Anthropic API key is configured."""


class RateLimitExceededError(RuntimeError):
    """Raised after the retry budget for 429s is exhausted."""


class InvalidJSONResponseError(RuntimeError):
    """Raised when the model never returned schema-valid JSON.

    Carries the last raw response so the CLI can persist it for debugging.
    """

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


def build_user_content(
    deck_text: str,
    images: list[bytes],
    file_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """The deck itself when it was uploaded, otherwise images then text.

    With a `file_id` the model reads the PDF natively, so the locally extracted
    text and rendered page images would be the same content a second time —
    paid for twice and lower fidelity on both counts.
    """
    if file_id:
        return [
            {"type": "document", "source": {"type": "file", "file_id": file_id}},
            {"type": "text", "text": build_user_prompt()},
        ]

    blocks: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(blob).decode("ascii"),
            },
        }
        for blob in images
    ]
    blocks.append({"type": "text", "text": build_user_prompt(deck_text)})
    return blocks


def analyze_deck(
    content: DeckContent,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    include_images: bool = True,
    log: Optional[Callable[[str], None]] = None,
    client: Any = None,
    deck_path: Optional[str | Path] = None,
    use_files_api: Optional[bool] = None,
    use_code_execution: Optional[bool] = None,
) -> AnalysisResult:
    """Run the analysis and return a validated `AnalysisResult`.

    When `deck_path` is a PDF it is uploaded to the Files API and sent as a
    document block, so the model reads the file rather than our extraction of
    it. The upload is deleted before returning.

    On a malformed response the model is asked once more with an explicit
    correction; two failures raise `InvalidJSONResponseError` carrying the raw
    text.
    """
    emit = log or (lambda _message: None)
    if client is None:
        client = _build_client(api_key)

    if use_files_api is None:
        use_files_api = env_flag("USE_FILES_API")
    if use_code_execution is None:
        use_code_execution = env_flag("USE_CODE_EXECUTION")

    file_id = _upload_if_supported(
        client, deck_path, use_files_api, include_images, content.slide_count, emit
    )
    try:
        try:
            return _run_analysis(
                client=client,
                content=content,
                model=model,
                include_images=include_images,
                file_id=file_id,
                use_code_execution=use_code_execution,
                emit=emit,
            )
        except Exception as error:
            # The docs warn that a large PDF can be rejected at request time
            # even under the page limit. The extracted text is always within
            # budget, so retry there rather than losing the run.
            if not (file_id and _is_bad_request(error)):
                raise
            emit(
                f"The API rejected the attached PDF ({error}). "
                "Retrying with extracted text."
            )
            return _run_analysis(
                client=client,
                content=content,
                model=model,
                include_images=include_images,
                file_id=None,
                use_code_execution=use_code_execution,
                emit=emit,
            )
    finally:
        if file_id and not delete_file(client, file_id):
            # Uploads are readable by every key in the workspace, so a leaked
            # deck is worth saying out loud. It still expires on its own.
            emit(
                f"Could not delete the uploaded deck ({file_id}); "
                "it expires on its own."
            )


def _upload_if_supported(
    client: Any,
    deck_path: Optional[str | Path],
    use_files_api: bool,
    include_images: bool,
    page_count: int,
    emit: Callable[[str], None],
) -> Optional[str]:
    """Upload the deck, or return None to fall back to extracted text."""
    if not (use_files_api and deck_path and supports_document_block(deck_path)):
        return None
    if not include_images:
        # Reading the PDF natively renders every page as an image, which is the
        # most expensive path there is. Asking for no images and getting it
        # would make the flag mean the opposite of what it says.
        emit("Images are off, so the deck is analysed from extracted text.")
        return None
    if page_count > MAX_NATIVE_PAGES:
        emit(
            f"{page_count} pages exceeds the {MAX_NATIVE_PAGES}-page budget for "
            "reading the PDF directly; using extracted text."
        )
        return None
    try:
        file_id = upload_deck(client, deck_path)
    except FileUploadError as error:
        # Never fail an analysis over the upload: the extracted text is a
        # complete, if lower-fidelity, source.
        emit(f"{error} Falling back to extracted text.")
        return None
    emit(f"Uploaded the deck as {file_id}; the model reads the PDF directly.")
    return file_id


def _run_analysis(
    client: Any,
    content: DeckContent,
    model: str,
    include_images: bool,
    file_id: Optional[str],
    use_code_execution: bool,
    emit: Callable[[str], None],
) -> AnalysisResult:
    images = content.images if include_images else []
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": build_user_content(content.text, images, file_id)}
    ]
    tools = [CODE_EXECUTION_TOOL] if use_code_execution else []
    if tools:
        emit("Code execution enabled; the model can check the deck's arithmetic.")

    raw = ""
    last_error = ""
    last_problem = "the response was not valid JSON"
    previous: Any = None
    for attempt in range(2):
        if attempt:
            emit("Retrying with a targeted correction.")
            # Hand back the whole assistant turn, tool calls and results
            # included, rather than just its text. The sandbox work is the
            # expensive part - tens of thousands of output tokens - and
            # replaying only the narration makes the model redo all of it.
            content = getattr(previous, "content", None) or raw or "(empty)"
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {"role": "user", "content": _correction_message(last_problem)}
            )

        previous = _request_with_backoff(client, model, messages, emit, tools)
        raw = _response_text(previous)
        emit(f"Received {len(raw)} characters from {model}.")

        if _reply_is_only_narration(raw, previous):
            last_error = "the turn ended on a tool call"
            last_problem = NO_JSON_IN_REPLY
            emit("The reply carried no JSON; the report was written nowhere.")
            continue

        try:
            payload = _extract_json(raw)
            return AnalysisResult.model_validate(payload)
        except Exception as error:  # json.JSONDecodeError or pydantic.ValidationError
            last_error = str(error)
            last_problem = _describe_validation(error)
            emit(f"Validation failed: {last_problem}")

    raise InvalidJSONResponseError(
        f"The model did not return schema-valid JSON after 2 attempts: {last_error}",
        raw,
    )


def _is_bad_request(error: Exception) -> bool:
    """True for a 400 — the class of failure a smaller request can survive."""
    try:
        import anthropic

        return isinstance(error, anthropic.BadRequestError)
    except Exception:  # pragma: no cover - anthropic always installed
        return False


def _describe_validation(error: Exception) -> str:
    """Name the offending fields, so a schema mismatch is diagnosable."""
    errors = getattr(error, "errors", None)
    if not callable(errors):
        return str(error).splitlines()[0]
    try:
        details = errors()
    except Exception:  # pragma: no cover - defensive
        return str(error).splitlines()[0]

    parts = []
    for item in details[:5]:
        location = ".".join(str(piece) for piece in item.get("loc", ()))
        # The rejected value, quoted. A message naming only the field leaves
        # the model to guess which part of it was wrong, and leaves the next
        # reader of the log unable to widen the schema.
        received = repr(item.get("input"))
        if len(received) > 60:
            received = received[:57] + "..."
        parts.append(f"{location} received {received} ({item.get('msg', '')})")
    suffix = f" and {len(details) - 5} more" if len(details) > 5 else ""
    return f"{len(details)} error(s): " + "; ".join(parts) + suffix


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _build_client(api_key: Optional[str]) -> Any:
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise MissingAPIKeyError("Set ANTHROPIC_API_KEY in .env")
    return anthropic.Anthropic(api_key=key)


def _request_with_backoff(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    emit: Callable[[str], None],
    tools: Optional[list[dict[str, Any]]] = None,
) -> Any:
    """Call the Messages API, retrying rate limits with exponential backoff.

    Returns the final message rather than its text: the caller needs the
    content blocks to hand a failed turn back for continuation.
    """
    import anthropic

    # Omitted rather than passed empty: an empty list is a different request,
    # and older stubs in the tests do not accept the argument at all.
    extra = {"tools": tools} if tools else {}

    conversation = list(messages)

    for attempt in range(RATE_LIMIT_ATTEMPTS):
        try:
            # The report is long enough that the SDK refuses a non-streaming
            # request at this max_tokens, and a streamed call also survives a
            # run that takes several minutes. Code execution runs server-side
            # inside this same call, so there is no client-side tool loop —
            # but a long turn can be paused and handed back to be resumed.
            for continuation in range(MAX_TURN_CONTINUATIONS + 1):
                with client.messages.stream(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    messages=conversation,
                    **extra,
                ) as stream:
                    message = stream.get_final_message()

                if getattr(message, "stop_reason", None) != "pause_turn":
                    return message

                # Without this the paused turn reads as a finished one, and
                # what comes back is the model's opening narration rather than
                # the report.
                emit(f"The turn paused; resuming it ({continuation + 1}).")
                conversation = conversation + [
                    {"role": "assistant", "content": message.content}
                ]

            emit(
                f"The turn was still paused after {MAX_TURN_CONTINUATIONS} "
                "resumptions; using what it produced."
            )
            return message
        except anthropic.RateLimitError:
            if attempt == RATE_LIMIT_ATTEMPTS - 1:
                raise RateLimitExceededError(
                    f"Rate limited by the Anthropic API after {RATE_LIMIT_ATTEMPTS} attempts."
                ) from None
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 1)
            emit(f"Rate limited — retrying in {delay:.1f}s.")
            time.sleep(delay)

    raise RateLimitExceededError("Rate limit retry loop exited unexpectedly.")


def _response_text(response: Any) -> str:
    """The model's final answer, as text.

    With code execution the response interleaves the model's working — text
    commentary, `server_tool_use`, and tool results — before the answer. Only
    the run of text blocks at the end is the answer; concatenating all of them
    would splice the narration into the JSON. Falls back to every text block
    for a response that used no tools.
    """
    content = list(getattr(response, "content", []))

    trailing: list[str] = []
    for block in reversed(content):
        if getattr(block, "type", None) != "text":
            break
        trailing.append(block.text)
    if trailing:
        return "".join(reversed(trailing)).strip()

    parts = [
        block.text for block in content if getattr(block, "type", None) == "text"
    ]
    return "".join(parts).strip()


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """Parse the JSON object out of a model response.

    Handles a bare object, a fenced code block, and an object surrounded by
    stray prose.
    """
    candidates: list[str] = [text.strip()]

    fenced = _FENCE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as error:
            last_error = error

    raise last_error or json.JSONDecodeError("No JSON object found", text, 0)
