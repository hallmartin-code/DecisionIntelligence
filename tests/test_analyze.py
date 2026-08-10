"""Analysis-layer tests with a mocked Anthropic client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from pitch_analyzer.analyze import (
    DEFAULT_MODEL,
    InvalidJSONResponseError,
    MissingAPIKeyError,
    RateLimitExceededError,
    _extract_json,
    analyze_deck,
    build_user_content,
    build_user_prompt,
)
from pitch_analyzer.ingest import DeckContent
from pitch_analyzer.models import AnalysisResult


def _text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _fake_client(*responses) -> MagicMock:
    """A client whose `messages.create` returns/raises the given items in order."""
    client = MagicMock()
    client.messages.create.side_effect = list(responses)
    return client


def _rate_limit_error() -> anthropic.RateLimitError:
    return anthropic.RateLimitError(
        "rate limited", response=MagicMock(status_code=429, headers={}), body=None
    )


@pytest.fixture
def deck() -> DeckContent:
    return DeckContent(
        text="[Slide 1]\nAcme Robotics\n\n[Slide 2]\nThe problem",
        slide_count=2,
        images=[b"\xff\xd8\xff-fake-jpeg"],
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_valid_json_validates_into_model(deck, analysis_payload):
    client = _fake_client(_text_response(json.dumps(analysis_payload)))

    result = analyze_deck(deck, client=client, include_images=False)

    assert isinstance(result, AnalysisResult)
    assert result.executive_summary.recommendation == "Investigate Further"
    assert result.scores.problem_validation == 8
    assert len(result.risks) == 4
    assert client.messages.create.call_count == 1


def test_request_uses_expected_model_and_system_prompt(deck, analysis_payload):
    client = _fake_client(_text_response(json.dumps(analysis_payload)))

    analyze_deck(deck, client=client, include_images=False)

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == DEFAULT_MODEL
    assert "decision intelligence analyst" in kwargs["system"]
    assert kwargs["messages"][0]["role"] == "user"


def test_images_are_sent_as_base64_blocks_before_text(deck, analysis_payload):
    client = _fake_client(_text_response(json.dumps(analysis_payload)))

    analyze_deck(deck, client=client, include_images=True)

    blocks = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    assert blocks[-1]["type"] == "text"


def test_no_images_flag_sends_text_only(deck, analysis_payload):
    client = _fake_client(_text_response(json.dumps(analysis_payload)))

    analyze_deck(deck, client=client, include_images=False)

    blocks = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert [block["type"] for block in blocks] == ["text"]


def test_fenced_json_is_parsed(deck, analysis_payload):
    fenced = "Here you go:\n```json\n" + json.dumps(analysis_payload) + "\n```"
    client = _fake_client(_text_response(fenced))

    result = analyze_deck(deck, client=client, include_images=False)

    assert result.scores.weighted_overall == pytest.approx(6.2)


# --------------------------------------------------------------------------- #
# Retry logic
# --------------------------------------------------------------------------- #


def test_invalid_json_triggers_one_retry(deck, analysis_payload):
    client = _fake_client(
        _text_response("I cannot produce JSON right now."),
        _text_response(json.dumps(analysis_payload)),
    )

    result = analyze_deck(deck, client=client, include_images=False)

    assert isinstance(result, AnalysisResult)
    assert client.messages.create.call_count == 2

    retry_messages = client.messages.create.call_args.kwargs["messages"]
    assert retry_messages[-1]["content"].startswith("Your previous response was not")


def test_schema_violation_also_triggers_retry(deck, analysis_payload):
    broken = dict(analysis_payload)
    broken.pop("scenarios")
    client = _fake_client(
        _text_response(json.dumps(broken)),
        _text_response(json.dumps(analysis_payload)),
    )

    analyze_deck(deck, client=client, include_images=False)

    assert client.messages.create.call_count == 2


def test_two_failures_raise_with_raw_response(deck):
    client = _fake_client(
        _text_response("nope"),
        _text_response("still nope"),
    )

    with pytest.raises(InvalidJSONResponseError) as excinfo:
        analyze_deck(deck, client=client, include_images=False)

    assert excinfo.value.raw_response == "still nope"
    assert client.messages.create.call_count == 2


def test_rate_limit_retries_then_succeeds(deck, analysis_payload):
    client = _fake_client(
        _rate_limit_error(),
        _text_response(json.dumps(analysis_payload)),
    )

    with patch("pitch_analyzer.analyze.time.sleep") as sleep:
        result = analyze_deck(deck, client=client, include_images=False)

    assert isinstance(result, AnalysisResult)
    assert sleep.call_count == 1


def test_rate_limit_gives_up_after_three_attempts(deck):
    client = _fake_client(*[_rate_limit_error() for _ in range(3)])

    with patch("pitch_analyzer.analyze.time.sleep"):
        with pytest.raises(RateLimitExceededError):
            analyze_deck(deck, client=client, include_images=False)

    assert client.messages.create.call_count == 3


# --------------------------------------------------------------------------- #
# Client construction and prompt assembly
# --------------------------------------------------------------------------- #


def test_missing_api_key_raises(deck, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError, match="ANTHROPIC_API_KEY"):
        analyze_deck(deck)


def test_user_prompt_contains_deck_text_and_schema():
    prompt = build_user_prompt("[Slide 1]\nAcme")

    assert "PITCH DECK TEXT:" in prompt
    assert "[Slide 1]" in prompt
    assert '"weighted_overall"' in prompt
    assert "Not presented" in prompt


def test_build_user_content_orders_images_first():
    blocks = build_user_content("text", [b"a", b"b"])

    assert [block["type"] for block in blocks] == ["image", "image", "text"]


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Sure!\n{"a": 1}\nHope that helps.',
        '```\n{"a": 1}\n```',
    ],
)
def test_extract_json_handles_wrapping(raw):
    assert _extract_json(raw) == {"a": 1}


def test_extract_json_rejects_non_json():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("there is no object here")
