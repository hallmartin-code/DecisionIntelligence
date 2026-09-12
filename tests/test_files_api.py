"""Files API upload and the code execution tool.

Covers the wiring between `analyze_deck` and the two server-side features: that
a PDF is uploaded and referenced by id, that the upload is always cleaned up,
that a failure anywhere in that path degrades to the extracted-text analysis
rather than failing the run, and that the model's answer is read from the right
place once tool blocks appear in the response.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import anthropic
import pytest

from pitch_analyzer.analyze import (
    CODE_EXECUTION_TOOL,
    _response_text,
    analyze_deck,
    build_user_content,
)
from pitch_analyzer.files import (
    MAX_NATIVE_PAGES,
    FileUploadError,
    delete_file,
    supports_document_block,
    upload_deck,
)
from pitch_analyzer.ingest import DeckContent
from pitch_analyzer.prompt import ATTACHED_DOCUMENT_NOTE


@pytest.fixture(autouse=True)
def _default_flags(monkeypatch):
    """Both features on, regardless of the developer's environment."""
    monkeypatch.delenv("USE_FILES_API", raising=False)
    monkeypatch.delenv("USE_CODE_EXECUTION", raising=False)


@pytest.fixture
def deck() -> DeckContent:
    return DeckContent(text="[Slide 1]\nAcme Robotics", slide_count=1, images=[b"jpeg"])


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "acme.pdf"
    path.write_bytes(b"%PDF-1.4 not a real pdf, never parsed here")
    return path


def _block(kind: str, text: str = "") -> MagicMock:
    block = MagicMock()
    block.type = kind
    block.text = text
    return block


def _stream(text: str) -> MagicMock:
    context = MagicMock()
    response = MagicMock()
    response.content = [_block("text", text)]
    context.__enter__.return_value.get_final_message.return_value = response
    context.__exit__.return_value = False
    return context


def _client(payload: dict, file_id: str = "file_abc123") -> MagicMock:
    client = MagicMock()
    client.messages.stream.return_value = _stream(json.dumps(payload))
    client.files.upload.return_value = MagicMock(id=file_id)
    return client


def _sent_content(client: MagicMock) -> list[dict]:
    return client.messages.stream.call_args.kwargs["messages"][0]["content"]


# --------------------------------------------------------------------------- #
# files.py
# --------------------------------------------------------------------------- #


def test_only_pdf_is_sent_as_a_document() -> None:
    assert supports_document_block("deck.pdf")
    assert supports_document_block("DECK.PDF")
    # PPTX has no document block type, so it keeps the local extraction path.
    assert not supports_document_block("deck.pptx")


def test_upload_returns_the_file_id_and_sets_an_expiry(pdf) -> None:
    client = MagicMock()
    client.files.upload.return_value = MagicMock(id="file_xyz")

    assert upload_deck(client, pdf) == "file_xyz"

    kwargs = client.files.upload.call_args.kwargs
    assert kwargs["expires_in_seconds"] >= 3600
    name, handle, mime = kwargs["file"]
    assert (name, mime) == ("acme.pdf", "application/pdf")
    assert handle.closed, "the file handle must not outlive the upload"


def test_upload_refuses_a_non_pdf(tmp_path) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"PK")
    with pytest.raises(FileUploadError, match="only PDF"):
        upload_deck(MagicMock(), deck)


def test_upload_wraps_a_transport_failure(pdf) -> None:
    client = MagicMock()
    client.files.upload.side_effect = RuntimeError("connection reset")
    with pytest.raises(FileUploadError, match="connection reset"):
        upload_deck(client, pdf)


def test_upload_rejects_a_response_without_an_id(pdf) -> None:
    client = MagicMock()
    client.files.upload.return_value = MagicMock(id=None)
    with pytest.raises(FileUploadError, match="no file id"):
        upload_deck(client, pdf)


def test_delete_reports_failure_instead_of_raising() -> None:
    client = MagicMock()
    client.files.delete.side_effect = RuntimeError("gone")
    assert delete_file(client, "file_abc") is False
    assert delete_file(MagicMock(), None) is False
    assert delete_file(MagicMock(), "file_abc") is True


# --------------------------------------------------------------------------- #
# Request construction
# --------------------------------------------------------------------------- #


def test_a_file_id_replaces_the_text_and_images() -> None:
    blocks = build_user_content("extracted text", [b"jpeg"], file_id="file_abc")

    kinds = [block["type"] for block in blocks]
    assert kinds == ["document", "text"]
    assert blocks[0]["source"] == {"type": "file", "file_id": "file_abc"}
    # Paying twice for the same deck is the thing being avoided.
    assert "extracted text" not in blocks[1]["text"]
    assert ATTACHED_DOCUMENT_NOTE in blocks[1]["text"]


def test_without_a_file_id_the_extracted_text_is_still_used() -> None:
    blocks = build_user_content("extracted text", [b"jpeg"])
    assert [block["type"] for block in blocks] == ["image", "text"]
    assert "extracted text" in blocks[1]["text"]


def test_a_pdf_is_uploaded_referenced_and_then_deleted(deck, pdf, analysis_payload):
    client = _client(analysis_payload)

    analyze_deck(deck, client=client, deck_path=pdf)

    assert client.files.upload.call_count == 1
    assert _sent_content(client)[0] == {
        "type": "document",
        "source": {"type": "file", "file_id": "file_abc123"},
    }
    client.files.delete.assert_called_once_with("file_abc123")


def test_the_upload_is_deleted_even_when_the_analysis_fails(deck, pdf):
    client = _client({})
    client.messages.stream.return_value = _stream("not json at all")

    with pytest.raises(Exception):
        analyze_deck(deck, client=client, deck_path=pdf)

    client.files.delete.assert_called_once_with("file_abc123")


def test_a_pptx_is_not_uploaded(deck, tmp_path, analysis_payload):
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"PK")
    client = _client(analysis_payload)

    analyze_deck(deck, client=client, deck_path=pptx)

    client.files.upload.assert_not_called()
    assert _sent_content(client)[0]["type"] != "document"


def test_an_upload_failure_falls_back_to_extracted_text(deck, pdf, analysis_payload):
    """A Files API outage must not take the whole analysis with it."""
    client = _client(analysis_payload)
    client.files.upload.side_effect = RuntimeError("503 from the Files API")
    logged: list[str] = []

    result = analyze_deck(deck, client=client, deck_path=pdf, log=logged.append)

    assert result.recommendation == "Investigate Further"
    assert "extracted text" in " ".join(logged).lower()
    assert _sent_content(client)[0]["type"] != "document"
    client.files.delete.assert_not_called()


# --------------------------------------------------------------------------- #
# Code execution
# --------------------------------------------------------------------------- #


def test_the_code_execution_tool_is_offered(deck, analysis_payload) -> None:
    client = _client(analysis_payload)
    analyze_deck(deck, client=client)
    assert client.messages.stream.call_args.kwargs["tools"] == [CODE_EXECUTION_TOOL]


def test_the_tool_version_needs_no_beta_header() -> None:
    assert CODE_EXECUTION_TOOL["type"] == "code_execution_20250825"
    assert CODE_EXECUTION_TOOL["name"] == "code_execution"


@pytest.mark.parametrize(
    "variable,key",
    [("USE_CODE_EXECUTION", "tools"), ("USE_FILES_API", "files")],
)
def test_either_half_can_be_switched_off(
    monkeypatch, deck, pdf, analysis_payload, variable, key
):
    monkeypatch.setenv(variable, "0")
    client = _client(analysis_payload)

    analyze_deck(deck, client=client, deck_path=pdf)

    if key == "tools":
        assert "tools" not in client.messages.stream.call_args.kwargs
    else:
        client.files.upload.assert_not_called()


def test_the_answer_is_read_from_after_the_tool_blocks(analysis_payload) -> None:
    """The narration before a tool call must not be spliced into the JSON."""
    payload = json.dumps(analysis_payload)
    response = MagicMock()
    response.content = [
        _block("text", "Let me check the market sizing arithmetic."),
        _block("server_tool_use"),
        _block("bash_code_execution_tool_result"),
        _block("text", payload),
    ]

    assert _response_text(response) == payload


def test_a_response_with_no_tool_blocks_still_concatenates() -> None:
    response = MagicMock()
    response.content = [_block("text", "{\"a\": "), _block("text", "1}")]
    assert _response_text(response) == '{"a": 1}'


def test_a_response_ending_in_a_tool_block_falls_back_to_all_text() -> None:
    response = MagicMock()
    response.content = [_block("text", "partial"), _block("server_tool_use")]
    assert _response_text(response) == "partial"


# --------------------------------------------------------------------------- #
# Size guards
# --------------------------------------------------------------------------- #


def test_a_long_deck_is_not_sent_natively(pdf, analysis_payload) -> None:
    """Past the page budget the request would run out of context mid-run."""
    long_deck = DeckContent(
        text="[Slide 1]\nAcme", slide_count=MAX_NATIVE_PAGES + 1, images=[]
    )
    client = _client(analysis_payload)
    logged: list[str] = []

    analyze_deck(long_deck, client=client, deck_path=pdf, log=logged.append)

    client.files.upload.assert_not_called()
    assert _sent_content(client)[0]["type"] != "document"
    assert "extracted text" in " ".join(logged)


def test_a_deck_at_the_budget_is_still_sent_natively(pdf, analysis_payload) -> None:
    at_limit = DeckContent(text="x", slide_count=MAX_NATIVE_PAGES, images=[])
    client = _client(analysis_payload)

    analyze_deck(at_limit, client=client, deck_path=pdf)

    client.files.upload.assert_called_once()


def test_a_rejected_pdf_retries_without_it(deck, pdf, analysis_payload) -> None:
    """A 400 on the attached PDF must not cost the whole run."""
    client = _client(analysis_payload)
    client.messages.stream.side_effect = [
        anthropic.BadRequestError(
            "too many pages", response=MagicMock(status_code=400, headers={}), body=None
        ),
        _stream(json.dumps(analysis_payload)),
    ]
    logged: list[str] = []

    result = analyze_deck(deck, client=client, deck_path=pdf, log=logged.append)

    assert result.recommendation == "Investigate Further"
    assert client.messages.stream.call_count == 2
    first, second = client.messages.stream.call_args_list
    assert first.kwargs["messages"][0]["content"][0]["type"] == "document"
    assert second.kwargs["messages"][0]["content"][0]["type"] != "document"
    # The upload is still cleaned up despite the detour.
    client.files.delete.assert_called_once_with("file_abc123")


def test_other_errors_are_not_retried(deck, pdf, analysis_payload) -> None:
    """Only a 400 is recoverable by shrinking the request."""
    client = _client(analysis_payload)
    client.messages.stream.side_effect = anthropic.AuthenticationError(
        "bad key", response=MagicMock(status_code=401, headers={}), body=None
    )

    with pytest.raises(anthropic.AuthenticationError):
        analyze_deck(deck, client=client, deck_path=pdf)

    assert client.messages.stream.call_count == 1


def test_no_images_also_skips_the_native_pdf(deck, pdf, analysis_payload) -> None:
    """--no-images asks for a cheap run; the native PDF is the priciest path."""
    client = _client(analysis_payload)
    logged: list[str] = []

    analyze_deck(
        deck, client=client, deck_path=pdf, include_images=False, log=logged.append
    )

    client.files.upload.assert_not_called()
    content = _sent_content(client)
    assert [block["type"] for block in content] == ["text"]
    assert "extracted text" in " ".join(logged)


def test_healthz_reports_whether_the_features_are_on(monkeypatch) -> None:
    """A deployment that has them switched off should say so in one request."""
    from fastapi.testclient import TestClient

    from pitch_analyzer import web

    monkeypatch.setenv("ALLOW_ANONYMOUS", "1")
    with TestClient(web.app) as client:
        body = client.get("/healthz").json()
    assert body["files_api"] is True and body["code_execution"] is True

    monkeypatch.setenv("USE_CODE_EXECUTION", "0")
    with TestClient(web.app) as client:
        body = client.get("/healthz").json()
    assert body["files_api"] is True and body["code_execution"] is False


def _paused(text: str) -> MagicMock:
    stream = _stream(text)
    stream.__enter__.return_value.get_final_message.return_value.stop_reason = (
        "pause_turn"
    )
    return stream


def _finished(text: str) -> MagicMock:
    stream = _stream(text)
    stream.__enter__.return_value.get_final_message.return_value.stop_reason = "end_turn"
    return stream


def test_a_paused_turn_is_resumed_not_treated_as_the_answer(deck, analysis_payload):
    """A long sandbox turn pauses; taking that as the answer yields narration."""
    client = MagicMock()
    client.messages.stream.side_effect = [
        _paused("I'll start by checking the market sizing arithmetic."),
        _finished(json.dumps(analysis_payload)),
    ]
    logged: list[str] = []

    result = analyze_deck(deck, client=client, log=logged.append)

    assert result.recommendation == "Investigate Further"
    assert client.messages.stream.call_count == 2
    # The paused turn is handed back so the model can continue it.
    resumed = client.messages.stream.call_args_list[1].kwargs["messages"]
    assert resumed[-1]["role"] == "assistant"
    assert any("paused" in line for line in logged)


def test_resumption_is_bounded() -> None:
    """A turn that never finishes must not loop forever.

    Tested against the request helper rather than analyze_deck, because the
    latter's JSON-correction retry runs the whole request a second time.
    """
    from pitch_analyzer.analyze import MAX_TURN_CONTINUATIONS, _request_with_backoff

    client = MagicMock()
    client.messages.stream.side_effect = [
        _paused("still working") for _ in range(MAX_TURN_CONTINUATIONS + 5)
    ]
    logged: list[str] = []

    from pitch_analyzer.analyze import _response_text

    message = _request_with_backoff(client, "model", [], logged.append, None)

    assert client.messages.stream.call_count == MAX_TURN_CONTINUATIONS + 1
    assert _response_text(message) == "still working"
    assert any("still paused" in line for line in logged)


# --------------------------------------------------------------------------- #
# The turn that ends on a tool call
# --------------------------------------------------------------------------- #


def _wrote_to_a_file() -> MagicMock:
    """The real shape of the failure, from a live run.

    The model analyses the deck, writes the report into a file in the sandbox,
    and ends its turn - so the reply carries only its narration and ~26,000
    output tokens of analysis are stranded in a container nothing reads.
    """
    stream = _stream("")
    message = stream.__enter__.return_value.get_final_message.return_value
    message.stop_reason = "end_turn"
    message.content = [
        _block("text", "I will now analyze the deck systematically."),
        _block("server_tool_use"),
        _block("bash_code_execution_tool_result"),
        _block("text", "Now I'll create the final JSON assessment:"),
        _block("server_tool_use"),
        _block("text_editor_code_execution_tool_result"),
    ]
    return stream


def test_a_turn_that_ends_on_a_tool_call_is_not_mistaken_for_an_answer(
    deck, analysis_payload
) -> None:
    from pitch_analyzer.analyze import NO_JSON_IN_REPLY

    client = MagicMock()
    client.messages.stream.side_effect = [
        _wrote_to_a_file(),
        _finished(json.dumps(analysis_payload)),
    ]
    logged: list[str] = []

    result = analyze_deck(deck, client=client, log=logged.append)

    assert result.recommendation == "Investigate Further"
    # The follow-up must name the actual problem, not "invalid JSON": the model
    # did not write malformed JSON, it wrote none at all.
    follow_up = client.messages.stream.call_args_list[1].kwargs["messages"][-1]
    assert follow_up["role"] == "user"
    assert NO_JSON_IN_REPLY in follow_up["content"]


def test_the_retry_keeps_the_sandbox_work(deck, analysis_payload) -> None:
    """Replaying only the narration makes the model redo every calculation.

    The tool blocks are the expensive part of the turn, so they go back as-is.
    """
    first = _wrote_to_a_file()
    client = MagicMock()
    client.messages.stream.side_effect = [
        first,
        _finished(json.dumps(analysis_payload)),
    ]

    analyze_deck(deck, client=client)

    replayed = client.messages.stream.call_args_list[1].kwargs["messages"][-2]
    assert replayed["role"] == "assistant"
    kinds = [getattr(block, "type", None) for block in replayed["content"]]
    assert "server_tool_use" in kinds and "text" in kinds, kinds


def test_a_normal_reply_is_unaffected(deck, analysis_payload) -> None:
    """A turn ending on the JSON must not be treated as narration."""
    from pitch_analyzer.analyze import _reply_is_only_narration

    message = MagicMock()
    message.content = [_block("server_tool_use"), _block("text", '{"a": 1}')]
    assert not _reply_is_only_narration('{"a": 1}', message)

    # Nor should a tool-free response with no JSON: that is malformed output,
    # a different problem with a different correction.
    message.content = [_block("text", "sorry, I cannot")]
    assert not _reply_is_only_narration("sorry, I cannot", message)


def test_the_prompt_forbids_writing_the_report_to_a_file() -> None:
    import re

    from pitch_analyzer.prompt import SYSTEM_PROMPT

    # The prompt is hard-wrapped, so a phrase can straddle a line break.
    flat = re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()
    assert "do not write the assessment to a file" in flat
    assert "nothing in the sandbox is read back" in flat
