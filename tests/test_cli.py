"""CLI tests. The API and email are stubbed — no test reaches the network."""

from __future__ import annotations

import io

import pytest
from typer.testing import CliRunner

from pitch_analyzer import cli as cli_module

# Rich wraps its error panel to the terminal width, truncating the message.
WIDE = {"COLUMNS": "200", "TERM": "dumb"}
runner = CliRunner()


@pytest.fixture
def deck(tmp_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path = tmp_path / "Acme Deck.pdf"
    pdf = canvas.Canvas(str(path), pagesize=letter)
    for title in ("Acme Robotics", "The Problem", "The Ask"):
        pdf.setFont("Helvetica-Bold", 24)
        pdf.drawString(72, 700, title)
        pdf.showPage()
    pdf.save()
    return path


@pytest.fixture
def stubbed(monkeypatch, analysis_result):
    """Replace the model call; everything downstream runs for real."""
    monkeypatch.setattr(
        cli_module, "analyze_deck", lambda *args, **kwargs: analysis_result
    )
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    return analysis_result


def test_analyze_writes_a_report_and_prints_the_verdict(deck, tmp_path, stubbed):
    """Regression: `_print_summary` referenced an undeleted local and raised
    NameError *after* the report and the email had already succeeded."""
    output = tmp_path / "report.docx"

    result = runner.invoke(
        cli_module.app,
        ["analyze", str(deck), "-o", str(output), "--no-images", "--no-email"],
    )

    assert result.exit_code == 0, result.output
    assert "INVESTIGATE FURTHER" in result.output
    assert "62% confidence" in result.output
    assert "weighted 4.6/10" in result.output
    assert output.exists()
    assert output.read_bytes()[:2] == b"PK"


def test_output_defaults_to_the_deck_stem(deck, stubbed):
    result = runner.invoke(
        cli_module.app, ["analyze", str(deck), "--no-images", "--no-email"]
    )

    assert result.exit_code == 0, result.output
    assert deck.with_name("Acme Deck_analysis.docx").exists()


def test_email_status_is_reported_when_configured(deck, tmp_path, monkeypatch, stubbed):
    monkeypatch.setattr(
        cli_module, "notify_report_ready", lambda *a, **k: "Emailed the report to x."
    )

    result = runner.invoke(
        cli_module.app,
        ["analyze", str(deck), "-o", str(tmp_path / "r.docx"), "--no-images"],
    )

    assert result.exit_code == 0, result.output
    assert "Emailed the report to x." in result.output


def test_a_mail_failure_warns_but_does_not_fail_the_run(
    deck, tmp_path, monkeypatch, stubbed
):
    monkeypatch.setattr(
        cli_module,
        "notify_report_ready",
        lambda *a, **k: "Could not email the report: Resend rate limit reached.",
    )
    output = tmp_path / "r.docx"

    result = runner.invoke(
        cli_module.app, ["analyze", str(deck), "-o", str(output), "--no-images"]
    )

    assert result.exit_code == 0, result.output
    assert output.exists()


def test_unsupported_extension_is_rejected_before_any_api_call(tmp_path, stubbed):
    bad = tmp_path / "deck.key"
    bad.write_text("not a deck")

    result = runner.invoke(cli_module.app, ["analyze", str(bad)], env=WIDE)

    assert result.exit_code != 0
    assert "Expected .pdf or .pptx" in result.output


def test_missing_file_is_rejected(tmp_path, stubbed):
    result = runner.invoke(
        cli_module.app, ["analyze", str(tmp_path / "nope.pdf")], env=WIDE
    )

    assert result.exit_code != 0
    assert "File not found" in result.output
