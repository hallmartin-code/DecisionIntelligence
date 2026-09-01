"""Email the finished analysis to the team via Resend.

Notification is strictly best-effort: a delivery problem is recorded and
reported, but never fails an analysis that already succeeded. The report
rides along as an attachment so the email is self-contained.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence
from xml.sax.saxutils import escape

from .models import AnalysisResult

RESEND_ENDPOINT = "https://api.resend.com/emails"
REQUEST_TIMEOUT_SECONDS = 30.0

DEFAULT_RECIPIENT = "Info@tencapital.group"
DEFAULT_SENDER = "TEN Capital Deck Analyzer <deck-analyzer@tencapital.group>"

# Resend caps a request at 40 MB; our reports are tens of KB, so this only
# guards against a pathological render.
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

BADGE_COLORS = {
    "Invest": "#16a34a",
    "Investigate Further": "#d97706",
    "Pass": "#dc2626",
}


@dataclass(frozen=True)
class EmailConfig:
    api_key: str
    sender: str
    recipients: tuple[str, ...]

    @property
    def is_usable(self) -> bool:
        return bool(self.api_key and self.sender and self.recipients)


class ResendError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Resend returned {status_code}: {message}")
        self.status_code = status_code
        self.message = message


def load_email_config() -> Optional[EmailConfig]:
    """Read email settings from the environment, or None if switched off."""
    if os.environ.get("EMAIL_NOTIFICATIONS", "").strip().lower() in (
        "0",
        "false",
        "off",
        "no",
    ):
        return None

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return None

    recipients = tuple(
        address.strip()
        for address in os.environ.get("REPORT_EMAIL_TO", DEFAULT_RECIPIENT).split(",")
        if address.strip()
    )
    sender = os.environ.get("REPORT_EMAIL_FROM", "").strip() or DEFAULT_SENDER

    config = EmailConfig(api_key=api_key, sender=sender, recipients=recipients)
    return config if config.is_usable else None


def notify_report_ready(
    analysis: AnalysisResult,
    report_path: Path,
    company_name: str,
    deck_filename: str,
    model: str,
    slide_count: int = 0,
    config: Optional[EmailConfig] = None,
    sender_fn: Optional[Callable[[EmailConfig, dict], str]] = None,
) -> Optional[str]:
    """Email the report. Returns a status line, or None when email is off.

    Never raises: the analysis has already succeeded by the time this runs, so
    a mail problem must not turn that into a failure.
    """
    config = config or load_email_config()
    if config is None:
        return None

    try:
        message = build_message(
            config, analysis, report_path, company_name, deck_filename, model, slide_count
        )
        send = sender_fn or post_to_resend
        message_id = send(config, message)
        return f"Emailed the report to {', '.join(config.recipients)} (id {message_id})."
    except Exception as error:  # noqa: BLE001 - reported, never propagated
        return f"Could not email the report: {describe_failure(error)}"


# --------------------------------------------------------------------------- #
# Message construction
# --------------------------------------------------------------------------- #


def build_message(
    config: EmailConfig,
    analysis: AnalysisResult,
    report_path: Path,
    company_name: str,
    deck_filename: str,
    model: str,
    slide_count: int = 0,
) -> dict:
    subject = (
        f"{analysis.recommendation} - {company_name} - "
        f"{analysis.weighted_overall:.1f}/10"
    )

    message: dict = {
        "from": config.sender,
        "to": list(config.recipients),
        "subject": subject,
        "html": _render_html(analysis, company_name, deck_filename, model, slide_count),
        "text": _render_text(analysis, company_name, deck_filename, model, slide_count),
    }

    attachment = _attachment(report_path, company_name)
    if attachment is not None:
        message["attachments"] = [attachment]
    return message


def _attachment(report_path: Path, company_name: str) -> Optional[dict]:
    if not report_path.exists():
        return None
    payload = report_path.read_bytes()
    if len(payload) > MAX_ATTACHMENT_BYTES:
        return None

    safe = "".join(
        character if character.isalnum() or character in " -_" else "_"
        for character in company_name
    ).strip()
    return {
        "filename": f"{safe or 'deck'} - Decision Intelligence.docx",
        "content": base64.standard_b64encode(payload).decode("ascii"),
    }


def _render_text(
    analysis: AnalysisResult,
    company_name: str,
    deck_filename: str,
    model: str,
    slide_count: int,
) -> str:
    summary = analysis.executive_summary
    lines = [
        f"{company_name} - Decision Intelligence Assessment",
        "",
        f"Recommendation: {analysis.recommendation} "
        f"({analysis.confidence_pct}% confidence)",
        f"Weighted overall: {analysis.weighted_overall:.1f}/10",
        f"Decision quality: {analysis.composite.decision_quality:.1f}/10",
        "",
        "THESIS",
        *summary.key_investment_thesis[:1],
        "",
        "STRENGTHS",
    ]
    lines += [f"  - {item}" for item in summary.top_strengths[:3]]
    lines += ["", "CONCERNS"]
    lines += [f"  - {item}" for item in summary.top_concerns[:3]]

    if analysis.risk_register:
        lines += ["", "TOP RISKS"]
        lines += [
            f"  - [{risk.category}] {risk.risk} "
            f"(probability {risk.probability}, impact {risk.impact})"
            for risk in analysis.risk_register[:4]
        ]

    questions = analysis.final.top_five_diligence_questions
    if questions:
        lines += ["", "TOP DILIGENCE QUESTIONS"]
        lines += [
            f"  {number}. {question}"
            for number, question in enumerate(questions[:5], start=1)
        ]

    slides = f" ({slide_count} slides)" if slide_count else ""
    lines += [
        "",
        "The full report is attached as a Word document.",
        "",
        f"Source deck: {deck_filename}{slides}",
        f"Model: {model}",
        "Generated by TEN Capital Decision Intelligence",
    ]
    return "\n".join(lines)


def _bullets(items: Sequence[str], color: str) -> str:
    return "".join(
        f'<li style="margin:0 0 6px;color:#1f2937">'
        f'<span style="color:{color};font-weight:700">&#9642;</span> {escape(item)}</li>'
        for item in items[:3]
    )


def _section_heading(label: str, color: str) -> str:
    return (
        f'<h2 style="margin:0 0 8px;font-size:12px;letter-spacing:.1em;'
        f'text-transform:uppercase;color:{color}">{label}</h2>'
    )


def _risks_block(analysis: AnalysisResult) -> str:
    rows = "".join(
        '<tr>'
        '<td style="padding:7px 10px;border-bottom:1px solid #e5e7eb;'
        'font-size:13px;color:#1f2937">'
        f'<strong>{escape(risk.category)}.</strong> {escape(risk.risk)}</td>'
        '<td style="padding:7px 10px;border-bottom:1px solid #e5e7eb;'
        'font-size:12px;color:#6b7280;white-space:nowrap">'
        f'{escape(risk.probability)} / {escape(risk.impact)}</td>'
        '</tr>'
        for risk in analysis.risk_register[:4]
    )
    if not rows:
        return ""
    return (
        _section_heading("Top risks", "#111827")
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="margin:0 0 22px;border-top:1px solid #e5e7eb">'
        + rows
        + "</table>"
    )


def _questions_block(analysis: AnalysisResult) -> str:
    items = "".join(
        f'<li style="margin:0 0 6px;color:#1f2937">{escape(question)}</li>'
        for question in analysis.final.top_five_diligence_questions[:5]
    )
    if not items:
        return ""
    return (
        _section_heading("Top diligence questions", "#111827")
        + '<ol style="margin:0 0 22px;padding-left:20px;font-size:13.5px;'
        'line-height:1.55">' + items + "</ol>"
    )


def _render_html(
    analysis: AnalysisResult,
    company_name: str,
    deck_filename: str,
    model: str,
    slide_count: int,
) -> str:
    summary = analysis.executive_summary
    badge = BADGE_COLORS.get(analysis.recommendation, "#d97706")
    slides = f" &middot; {slide_count} slides" if slide_count else ""

    return (
        '<!doctype html><html><body style="margin:0;padding:24px;background:#f3f4f6;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,"
        'sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:640px;margin:0 auto;background:#ffffff;'
        'border:1px solid #d1d5db;border-radius:10px">'
        '<tr><td style="height:3px;background:linear-gradient(90deg,#EE5A4E,#F3A22A,'
        '#35BEBB);border-radius:10px 10px 0 0"></td></tr>'
        '<tr><td style="padding:26px 28px">'
        '<p style="margin:0 0 4px;font-size:11px;letter-spacing:.12em;'
        'text-transform:uppercase;color:#6b7280">Decision Intelligence Analysis</p>'
        f'<h1 style="margin:0 0 14px;font-size:22px;color:#111827">'
        f"{escape(company_name)}</h1>"
        '<p style="margin:0 0 18px">'
        f'<span style="display:inline-block;padding:6px 12px;border-radius:5px;'
        f'background:{badge};color:#ffffff;font-weight:700;font-size:13px;'
        f'letter-spacing:.03em">{escape(analysis.recommendation.upper())} &middot; '
        f'{analysis.confidence_pct}% CONFIDENCE</span></p>'
        '<p style="margin:0 0 20px;font-size:13px;color:#6b7280">Weighted overall '
        f'<strong style="color:#111827">{analysis.weighted_overall:.1f}/10'
        '</strong> &middot; Decision quality '
        f'<strong style="color:#111827">{analysis.composite.decision_quality:.1f}/10'
        "</strong></p>"
        '<p style="margin:0 0 22px;font-size:14px;line-height:1.6;color:#1f2937">'
        f"{escape(summary.key_investment_thesis[0] if summary.key_investment_thesis else '')}</p>"
        + _section_heading("Strengths", "#16a34a")
        + '<ul style="margin:0 0 20px;padding-left:18px;font-size:13.5px;'
        'line-height:1.55">' + _bullets(summary.top_strengths, "#16a34a") + "</ul>"
        + _section_heading("Concerns", "#dc2626")
        + '<ul style="margin:0 0 22px;padding-left:18px;font-size:13.5px;'
        'line-height:1.55">' + _bullets(summary.top_concerns, "#dc2626") + "</ul>"
        + _risks_block(analysis)
        + _questions_block(analysis)
        + '<p style="margin:0 0 6px;padding-top:16px;border-top:1px solid #e5e7eb;'
        'font-size:13px;color:#1f2937">The full report is attached as a Word document.</p>'
        '<p style="margin:0;font-size:11.5px;color:#6b7280">Source deck: '
        f"{escape(deck_filename)}{slides} &middot; Model: {escape(model)}<br>"
        "Generated by TEN Capital Decision Intelligence</p>"
        "</td></tr></table></body></html>"
    )


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #


def post_to_resend(config: EmailConfig, message: dict) -> str:
    import httpx

    response = httpx.post(
        RESEND_ENDPOINT,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        json=message,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise ResendError(response.status_code, _error_message(response))
    return str(response.json().get("id", "unknown"))


def _error_message(response) -> str:
    try:
        body = response.json()
    except Exception:
        return response.text[:200]
    return str(body.get("message") or body.get("error") or body)[:300]


def describe_failure(error: Exception) -> str:
    """Turn a delivery failure into a line an operator can act on."""
    if isinstance(error, ResendError):
        if error.status_code == 401:
            return "the Resend API key was rejected (check RESEND_API_KEY)."
        if error.status_code == 403:
            return (
                "Resend refused the sender address - verify the domain used in "
                f"REPORT_EMAIL_FROM at resend.com/domains. ({error.message})"
            )
        if error.status_code == 422:
            return f"Resend rejected the message: {error.message}"
        if error.status_code == 429:
            return "Resend rate limit reached; the report was not emailed."
        return str(error)
    return f"{type(error).__name__}: {error}"
