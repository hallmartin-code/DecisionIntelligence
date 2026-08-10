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

DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 16000
RATE_LIMIT_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0

SYSTEM_PROMPT = """You are a world-class venture capitalist, decision intelligence analyst, and
investment committee member. You will receive the extracted text (and optionally
slide images) from a startup pitch deck. Your task is to produce a structured
Decision Intelligence analysis and return it as a single valid JSON object that
conforms EXACTLY to the schema provided. Do not add prose outside the JSON."""

JSON_SCHEMA = """{
  "executive_summary": {
    "recommendation": "Invest | Investigate Further | Pass",
    "confidence_pct": 0,
    "investment_thesis": "",
    "top_strengths": ["", "", ""],
    "top_concerns":   ["", "", ""]
  },
  "scores": {
    "problem_validation":   0,
    "solution_strength":    0,
    "market_opportunity":   0,
    "competitive_position": 0,
    "business_model":       0,
    "traction":             0,
    "team":                 0,
    "financial_quality":    0,
    "risk_profile":         0,
    "investment_attractiveness": 0,
    "weighted_overall":     0.0,
    "decision_quality":     0.0
  },
  "sections": {
    "problem_validation":      { "score": 0, "observations": "", "missing": "", "questions": [""] },
    "solution_effectiveness":  { "score": 0, "observations": "", "missing": "", "questions": [""] },
    "market_opportunity":      { "score": 0, "observations": "", "missing": "", "questions": [""] },
    "competitive_intelligence":{ "score": 0, "observations": "", "missing": "", "questions": [""] },
    "business_model":          { "score": 0, "observations": "", "missing": "", "questions": [""] },
    "traction_evidence":       { "score": 0, "observations": "", "missing": "", "questions": [""] },
    "team_assessment":         { "score": 0, "observations": "", "missing": "", "questions": [""] },
    "financial_intelligence":  { "score": 0, "observations": "", "missing": "", "questions": [""] }
  },
  "risks": [
    {
      "category": "Market | Product | Execution | Financial | Regulatory | Competitive",
      "description": "",
      "probability": "Low | Medium | High",
      "impact":      "Low | Medium | High",
      "mitigation":  ""
    }
  ],
  "assumptions": [
    {
      "assumption":   "",
      "evidence":     "",
      "confidence":   "Low | Medium | High",
      "validation":   ""
    }
  ],
  "scenarios": {
    "best":  { "probability_pct": 0, "drivers": [""] },
    "base":  { "probability_pct": 0, "drivers": [""] },
    "worst": { "probability_pct": 0, "drivers": [""] }
  },
  "bull_case": "",
  "bear_case": "",
  "missing_information": [""],
  "top_diligence_questions": ["", "", "", "", ""],
  "key_milestones_before_investment": [""],
  "expected_risk_adjusted_outcome": ""
}"""

USER_PROMPT_TEMPLATE = """PITCH DECK TEXT:
{deck_text}

INSTRUCTIONS:
Analyze the deck using the Decision Intelligence framework below and return
a JSON object matching the schema exactly. Be specific and evidence-based;
cite slide numbers when possible. If information is absent from the deck,
say "Not presented" rather than speculating.

OUTPUT SCHEMA:
{json_schema}"""

RETRY_CORRECTION = (
    "Your previous response was not valid JSON. Return only the JSON object."
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


def build_user_prompt(deck_text: str) -> str:
    return USER_PROMPT_TEMPLATE.format(deck_text=deck_text, json_schema=JSON_SCHEMA)


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
    for attempt in range(2):
        if attempt:
            emit("Response was not valid JSON — retrying with a correction.")
            messages.append({"role": "assistant", "content": raw or "(empty)"})
            messages.append({"role": "user", "content": RETRY_CORRECTION})

        raw = _request_with_backoff(client, model, messages, emit)
        emit(f"Received {len(raw)} characters from {model}.")

        try:
            payload = _extract_json(raw)
            return AnalysisResult.model_validate(payload)
        except Exception as error:  # json.JSONDecodeError or pydantic.ValidationError
            last_error = str(error)
            emit(f"Validation failed: {last_error.splitlines()[0]}")

    raise InvalidJSONResponseError(
        f"The model did not return schema-valid JSON after 2 attempts: {last_error}",
        raw,
    )


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
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            return _response_text(response)
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
