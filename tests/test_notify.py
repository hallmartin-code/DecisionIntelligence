"""Email notification tests. No test reaches Resend."""

from __future__ import annotations

import base64
import json

import pytest

from pitch_analyzer.notify import (
    DEFAULT_RECIPIENT,
    DEFAULT_SENDER,
    EmailConfig,
    ResendError,
    build_message,
    describe_failure,
    load_email_config,
    notify_report_ready,
)

CONFIG = EmailConfig(
    api_key="re_test_key",
    sender="TEN Capital <deck-analyzer@tencapital.group>",
    recipients=("Info@tencapital.group",),
)


@pytest.fixture(autouse=True)
def clean_email_env(monkeypatch):
    for name in (
        "RESEND_API_KEY",
        "REPORT_EMAIL_TO",
        "REPORT_EMAIL_FROM",
        "EMAIL_NOTIFICATIONS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def report_pdf(tmp_path, analysis_result):
    from pitch_analyzer.render import render_one_pager

    return render_one_pager(analysis_result, tmp_path / "report.pdf")


class Recorder:
    """Stands in for the Resend transport."""

    def __init__(self, result="msg_123", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, config, message):
        self.calls.append((config, message))
        if self.error:
            raise self.error
        return self.result


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_no_key_means_email_is_off():
    assert load_email_config() is None


def test_key_enables_email_with_documented_defaults(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_abc")

    config = load_email_config()

    assert config is not None
    assert config.recipients == (DEFAULT_RECIPIENT,)
    assert config.sender == DEFAULT_SENDER


def test_recipients_can_be_a_comma_separated_list(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_abc")
    monkeypatch.setenv("REPORT_EMAIL_TO", "a@x.com, b@y.com ,")

    assert load_email_config().recipients == ("a@x.com", "b@y.com")


@pytest.mark.parametrize("value", ["0", "false", "off", "no", "OFF"])
def test_notifications_can_be_switched_off_without_removing_the_key(
    monkeypatch, value
):
    monkeypatch.setenv("RESEND_API_KEY", "re_abc")
    monkeypatch.setenv("EMAIL_NOTIFICATIONS", value)

    assert load_email_config() is None


# --------------------------------------------------------------------------- #
# Message shape
# --------------------------------------------------------------------------- #


def test_message_carries_the_verdict_and_the_pdf(analysis_result, report_pdf):
    message = build_message(
        CONFIG,
        analysis_result,
        report_pdf,
        company_name="Acme Robotics",
        deck_filename="acme.pdf",
        model="claude-sonnet-4-5",
        slide_count=10,
    )

    assert message["from"] == CONFIG.sender
    assert message["to"] == ["Info@tencapital.group"]
    assert "Investigate Further" in message["subject"]
    assert "Acme Robotics" in message["subject"]
    assert "6.2/10" in message["subject"]

    attachment = message["attachments"][0]
    assert attachment["filename"].endswith(".pdf")
    assert base64.standard_b64decode(attachment["content"]).startswith(b"%PDF")


def test_both_html_and_plain_text_bodies_are_present(analysis_result, report_pdf):
    message = build_message(
        CONFIG, analysis_result, report_pdf, "Acme Robotics", "acme.pdf", "m", 10
    )

    for body in (message["html"], message["text"]):
        # The HTML badge uppercases the verdict; the text body does not.
        assert "investigate further" in body.lower()
        assert "62%" in body
    assert message["html"].lstrip().startswith("<!doctype html>")
    assert "<" not in message["text"].split("THESIS")[0]


def test_html_body_escapes_markup_from_the_analysis(analysis_payload, report_pdf):
    from pitch_analyzer.models import AnalysisResult

    analysis_payload["executive_summary"]["investment_thesis"] = "A & B <script>x</script>"
    analysis = AnalysisResult.model_validate(analysis_payload)

    message = build_message(CONFIG, analysis, report_pdf, "Acme", "a.pdf", "m", 1)

    assert "<script>" not in message["html"]
    assert "&lt;script&gt;" in message["html"]


def test_missing_report_still_sends_without_an_attachment(
    tmp_path, analysis_result
):
    message = build_message(
        CONFIG, analysis_result, tmp_path / "gone.pdf", "Acme", "a.pdf", "m", 1
    )

    assert "attachments" not in message
    assert message["html"]


def test_message_is_json_serialisable(analysis_result, report_pdf):
    message = build_message(
        CONFIG, analysis_result, report_pdf, "Acme", "a.pdf", "m", 1
    )

    assert json.loads(json.dumps(message))["to"] == ["Info@tencapital.group"]


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #


def test_successful_send_reports_the_recipient(analysis_result, report_pdf):
    recorder = Recorder(result="msg_abc")

    status = notify_report_ready(
        analysis_result,
        report_pdf,
        company_name="Acme",
        deck_filename="a.pdf",
        model="m",
        config=CONFIG,
        sender_fn=recorder,
    )

    assert "Info@tencapital.group" in status
    assert "msg_abc" in status
    assert len(recorder.calls) == 1


def test_email_is_skipped_entirely_when_unconfigured(analysis_result, report_pdf):
    recorder = Recorder()

    status = notify_report_ready(
        analysis_result, report_pdf, "Acme", "a.pdf", "m", sender_fn=recorder
    )

    assert status is None
    assert recorder.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ResendError(401, "unauthorized"), "API key was rejected"),
        (ResendError(403, "domain not verified"), "verify the domain"),
        (ResendError(422, "invalid to"), "rejected the message"),
        (ResendError(429, "slow down"), "rate limit"),
        (OSError("connection reset"), "OSError"),
    ],
)
def test_delivery_failure_is_reported_but_never_raised(
    analysis_result, report_pdf, error, expected
):
    status = notify_report_ready(
        analysis_result,
        report_pdf,
        company_name="Acme",
        deck_filename="a.pdf",
        model="m",
        config=CONFIG,
        sender_fn=Recorder(error=error),
    )

    assert status.startswith("Could not email the report")
    assert expected in status


def test_describe_failure_never_leaks_the_api_key():
    message = describe_failure(ResendError(401, "key re_secret_value is invalid"))

    assert "re_secret_value" not in message
