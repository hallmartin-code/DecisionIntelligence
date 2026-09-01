"""Typer entry point: ingest → analyze → render."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from .analyze import (
    DEFAULT_MODEL,
    InvalidJSONResponseError,
    MissingAPIKeyError,
    RateLimitExceededError,
    analyze_deck,
)
from .ingest import UnsupportedDeckError, guess_company_name, ingest
from .models import AnalysisResult
from .notify import notify_report_ready
from .render import RenderError, render_report

SUPPORTED_SUFFIXES = (".pdf", ".pptx")

app = typer.Typer(
    add_completion=False,
    help="Turn an investor pitch deck into a Decision Intelligence report.",
)
console = Console()
error_console = Console(stderr=True)


@app.callback()
def main() -> None:
    """Pitch Deck Decision Intelligence Analyzer."""


@app.command()
def analyze(
    deck_path: Path = typer.Argument(
        ...,
        metavar="DECK_PATH",
        help="Path to the pitch deck (.pdf or .pptx).",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output .docx path. Defaults to <deck_stem>_analysis.docx.",
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Override the LLM model."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Stream analysis progress to stdout."
    ),
    no_images: bool = typer.Option(
        False, "--no-images", help="Skip image extraction (faster, less context)."
    ),
    no_email: bool = typer.Option(
        False,
        "--no-email",
        help="Skip the email notification even when Resend is configured.",
    ),
) -> None:
    """Analyze DECK_PATH and write a Decision Intelligence report (.docx)."""
    load_dotenv()

    deck = _validate_deck_path(deck_path)
    destination = output or deck.with_name(f"{deck.stem}_analysis.docx")
    include_images = not no_images

    def log(message: str) -> None:
        if verbose:
            console.print(f"  [dim]{message}[/dim]")

    content = _ingest(deck, include_images, log)
    analysis = _analyze(content, model, include_images, destination, log)
    company = _render(analysis, destination, content)
    if not no_email:
        _email(analysis, destination, company, deck.name, model, content.slide_count)

    _print_summary(analysis, destination)


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #


def _ingest(deck: Path, include_images: bool, log):
    with console.status(f"Reading {deck.name}..."):
        try:
            content = ingest(deck, include_images=include_images)
        except UnsupportedDeckError as error:
            raise typer.BadParameter(str(error), param_hint="DECK_PATH") from error
        except RuntimeError as error:
            error_console.print(f"[bold red]Error:[/bold red] {error}")
            raise typer.Exit(1) from error

    console.print(
        f"[green]OK[/green] Read {content.slide_count} slide(s), "
        f"{len(content.text):,} characters, {len(content.images)} image(s)."
    )
    log(f"Images included: {include_images}")
    return content


def _analyze(content, model: str, include_images: bool, destination: Path, log):
    with console.status(f"Analyzing with {model}..."):
        try:
            analysis = analyze_deck(
                content, model=model, include_images=include_images, log=log
            )
        except MissingAPIKeyError:
            error_console.print("Set ANTHROPIC_API_KEY in .env")
            raise typer.Exit(1) from None
        except RateLimitExceededError as error:
            error_console.print(f"[bold red]Error:[/bold red] {error}")
            raise typer.Exit(1) from error
        except InvalidJSONResponseError as error:
            raw_path = destination.with_name(f"{destination.stem}_raw.txt")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(error.raw_response, encoding="utf-8")
            error_console.print(f"[bold red]Error:[/bold red] {error}")
            error_console.print(f"Raw model response saved to {raw_path}")
            raise typer.Exit(1) from error
        except Exception as error:  # authentication, connection, other API errors
            if _is_auth_error(error):
                error_console.print("Set ANTHROPIC_API_KEY in .env")
            else:
                error_console.print(f"[bold red]API error:[/bold red] {error}")
            raise typer.Exit(1) from error

    console.print("[green]OK[/green] Analysis complete.")
    return analysis


def _render(analysis: AnalysisResult, destination: Path, content) -> str:
    company = analysis.company_name or guess_company_name(
        content.text, fallback=destination.stem
    )
    with console.status("Building the report..."):
        try:
            render_report(analysis, destination)
        except RenderError as error:
            error_console.print(f"[bold red]Render error:[/bold red] {error}")
            raise typer.Exit(1) from error
    return company


def _email(
    analysis: AnalysisResult,
    destination: Path,
    company: str,
    deck_filename: str,
    model: str,
    slide_count: int,
) -> None:
    """Best-effort notification; a mail problem never fails a finished run."""
    with console.status("Emailing the report..."):
        status = notify_report_ready(
            analysis,
            destination,
            company_name=company,
            deck_filename=deck_filename,
            model=model,
            slide_count=slide_count,
        )
    if status is None:
        return
    if status.startswith("Could not"):
        error_console.print(f"[yellow]Warning:[/yellow] {status}")
    else:
        console.print(f"[green]OK[/green] {status}")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _validate_deck_path(deck_path: Path) -> Path:
    if not deck_path.exists():
        raise typer.BadParameter(
            f"File not found: {deck_path}", param_hint="DECK_PATH"
        )
    if not deck_path.is_file():
        raise typer.BadParameter(
            f"Not a file: {deck_path}", param_hint="DECK_PATH"
        )
    if deck_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise typer.BadParameter(
            f"Unsupported file type '{deck_path.suffix or deck_path.name}'. "
            "Expected .pdf or .pptx.",
            param_hint="DECK_PATH",
        )
    return deck_path


def _is_auth_error(error: Exception) -> bool:
    try:
        import anthropic

        return isinstance(
            error, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)
        )
    except Exception:
        return False


def _print_summary(analysis: AnalysisResult, destination: Path) -> None:
    colors = {"Invest": "green", "Investigate Further": "yellow", "Pass": "red"}
    color = colors.get(analysis.recommendation, "yellow")

    console.print(
        f"\n[bold {color}]{analysis.recommendation.upper()}[/bold {color}] "
        f"- {analysis.confidence_pct}% confidence "
        f"- weighted {analysis.weighted_overall:.1f}/10"
    )
    console.print(f"[green]OK[/green] Report written to [bold]{destination}[/bold]")


if __name__ == "__main__":  # pragma: no cover
    app()
