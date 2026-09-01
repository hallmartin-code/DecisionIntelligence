"""Anthropic API call, retry logic, and JSON validation."""

from __future__ import annotations

import base64
import json
import os
import random
import re
import time
from typing import Any, Callable, Optional

from .ingest import DeckContent
from .models import AnalysisResult
from .prompt import SYSTEM_PROMPT, build_user_prompt

DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 48000  # the full report is long; leaves headroom over a ~25k typical
RATE_LIMIT_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0

def _correction_message(problem: str) -> str:
    """Tell the model exactly what failed, so the retry is targeted."""
    return (
        f"Your previous response could not be used: {problem}\n\n"
        "Return the corrected JSON object only — no prose, no code fence — "
        "including every required field."
    )


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


def build_user_content(deck_text: str, images: list[bytes]) -> list[dict[str, Any]]:
    """Slide images first (vision), then the text block."""
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
) -> AnalysisResult:
    """Run the analysis and return a validated `AnalysisResult`.

    On a malformed response the model is asked once more with an explicit
    correction; two failures raise `InvalidJSONResponseError` carrying the raw
    text.
    """
    emit = log or (lambda _message: None)
    if client is None:
        client = _build_client(api_key)

    images = content.images if include_images else []
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": build_user_content(content.text, images)}
    ]

    raw = ""
    last_error = ""
    last_problem = "the response was not valid JSON"
    for attempt in range(2):
        if attempt:
            emit("Retrying with a targeted correction.")
            messages.append({"role": "assistant", "content": raw or "(empty)"})
            messages.append(
                {"role": "user", "content": _correction_message(last_problem)}
            )

        raw = _request_with_backoff(client, model, messages, emit)
        emit(f"Received {len(raw)} characters from {model}.")

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


def _describe_validation(error: Exception) -> str:
    """Name the offending fields, so a schema mismatch is diagnosable."""
    errors = getattr(error, "errors", None)
    if not callable(errors):
        return str(error).splitlines()[0]
    try:
        details = errors()
    except Exception:  # pragma: no cover - defensive
        return str(error).splitlines()[0]

    parts = [
        ".".join(str(piece) for piece in item.get("loc", ())) + f" ({item.get('msg', '')})"
        for item in details[:5]
    ]
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
) -> str:
    """Call the Messages API, retrying rate limits with exponential backoff."""
    import anthropic

    for attempt in range(RATE_LIMIT_ATTEMPTS):
        try:
            # The report is long enough that the SDK refuses a non-streaming
            # request at this max_tokens, and a streamed call also survives a
            # run that takes several minutes.
            with client.messages.stream(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                return _response_text(stream.get_final_message())
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
    """Concatenate the text blocks of a Messages API response."""
    parts = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
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
