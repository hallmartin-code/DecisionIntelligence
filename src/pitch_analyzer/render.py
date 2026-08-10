"""ReportLab one-pager builder.

The page is laid out top-down as five stacked bands (header, three-column row,
risks, diligence questions, footer). Each band's natural height is measured
before anything is drawn; if the stack does not fit, the whole page is re-laid
at a smaller font until it does, or `LayoutOverflowError` is raised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Sequence
from xml.sax.saxutils import escape

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import landscape, letter, portrait
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

from .models import AnalysisResult

# --------------------------------------------------------------------------- #
# Design tokens
# --------------------------------------------------------------------------- #

INK = HexColor("#111827")
BODY = HexColor("#1f2937")
MUTED = HexColor("#6b7280")
RULE = HexColor("#d1d5db")
TRACK = HexColor("#e5e7eb")
PANEL = HexColor("#f3f4f6")
WHITE = HexColor("#ffffff")

GREEN = HexColor("#16a34a")
AMBER = HexColor("#d97706")
RED = HexColor("#dc2626")

BADGE_COLORS = {
    "Invest": GREEN,
    "Investigate Further": AMBER,
    "Pass": RED,
}
LEVEL_COLORS = {"Low": GREEN, "Medium": AMBER, "High": RED}

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

MARGIN = 22.0
GUTTER = 10.0
BAND_GAP = 9.0
# Leftover vertical space is shared between the bands so a short analysis reads
# as a composed page rather than a top-heavy one. Bounded, so a very sparse
# report does not end up as five islands of text.
MAX_EXTRA_BAND_GAP = 20.0

# Font sizes the fit guard may use, largest first (0.5pt steps, 5.5pt floor).
FONT_SIZES: tuple[float, ...] = (8.0, 7.5, 7.0, 6.5, 6.0, 5.5)
START_FONT_SIZE = FONT_SIZES[0]
MIN_FONT_SIZE = FONT_SIZES[-1]

MAX_RISK_ROWS = 4
MAX_QUESTIONS = 5

# Per-field character budgets at a clip scale of 1.0. A one-pager cannot carry
# an unbounded analysis, so long fields are clipped — but the fit guard spends
# type size before it spends text (see _LAYOUT_STEPS).
CLIP_THESIS = 520
CLIP_BULLET = 210
CLIP_RISK = 190
CLIP_QUESTION = 240
CLIP_CASE = 420
CLIP_DRIVER = 120
CLIP_OUTCOME = 260

# The fit guard walks FONT_SIZES in order. At each size it finds the largest
# text budget that still fits, and stops at the first size that can carry an
# acceptable one — so type size is only spent once text has been.
MIN_CLIP_SCALE = 0.60
MAX_CLIP_SCALE = 1.60
ACCEPTABLE_CLIP_SCALE = 0.90
CLIP_SEARCH_ITERATIONS = 6


class LayoutOverflowError(RuntimeError):
    """Raised when the report cannot be fitted onto one page at 5.5pt."""


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def render_one_pager(
    analysis: AnalysisResult,
    output_path: str | Path,
    company_name: str = "Pitch Deck",
    orientation: str = "landscape",
    logo_path: Optional[str | Path] = None,
    generated_on: Optional[date] = None,
) -> Path:
    """Render `analysis` to a single-page PDF and return the output path."""
    if orientation not in ("landscape", "portrait"):
        raise ValueError("orientation must be 'landscape' or 'portrait'")

    page_size = (landscape if orientation == "landscape" else portrait)(letter)
    stamp = generated_on or date.today()

    layout = _fit_layout(analysis, page_size, company_name, logo_path, stamp)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    canvas = Canvas(str(destination), pagesize=page_size)
    canvas.setTitle(f"{company_name} — Decision Intelligence Analysis")
    layout.draw(canvas)
    canvas.showPage()
    canvas.save()
    return destination


# --------------------------------------------------------------------------- #
# Layout primitives
# --------------------------------------------------------------------------- #


class Stack:
    """A fixed-width column of flowables measured and drawn top-down."""

    def __init__(self, width: float) -> None:
        self.width = width
        self._items: list[tuple[Flowable, float]] = []

    def add(self, flowable: Flowable, gap: float = 0.0) -> "Stack":
        self._items.append((flowable, gap))
        return self

    def height(self) -> float:
        total = 0.0
        for flowable, gap in self._items:
            _, height = flowable.wrap(self.width, 1e6)
            total += height + gap
        return total

    def draw(self, canvas: Canvas, x: float, top: float) -> float:
        cursor = top
        for flowable, gap in self._items:
            _, height = flowable.wrap(self.width, 1e6)
            flowable.drawOn(canvas, x, cursor - height)
            cursor -= height + gap
        return cursor


class ScoreBars(Flowable):
    """The 10-category scorecard: label, gradient bar, numeric value."""

    def __init__(self, rows: Sequence[tuple[str, float]], width: float, font_size: float):
        super().__init__()
        self.rows = list(rows)
        self.width = width
        self.font_size = font_size
        self.row_height = font_size + 4.4
        self.height = self.row_height * len(self.rows)

    def wrap(self, available_width: float, available_height: float):
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        label_width = self.width * 0.50
        bar_x = label_width + 3.0
        value_width = self.font_size * 1.9
        bar_width = max(10.0, self.width - bar_x - value_width)
        bar_height = self.font_size * 0.74

        for index, (label, value) in enumerate(self.rows):
            baseline = self.height - (index + 1) * self.row_height + 2.2
            canvas.setFont(FONT, self.font_size)
            canvas.setFillColor(BODY)
            canvas.drawString(0, baseline + 1.0, label)

            canvas.setFillColor(TRACK)
            canvas.roundRect(
                bar_x, baseline, bar_width, bar_height, bar_height / 2, stroke=0, fill=1
            )

            fraction = max(0.0, min(1.0, float(value) / 10.0))
            if fraction > 0:
                canvas.setFillColor(score_color(fraction))
                canvas.roundRect(
                    bar_x,
                    baseline,
                    max(bar_width * fraction, bar_height),
                    bar_height,
                    bar_height / 2,
                    stroke=0,
                    fill=1,
                )

            canvas.setFont(FONT_BOLD, self.font_size)
            canvas.setFillColor(INK)
            canvas.drawRightString(self.width, baseline + 1.0, _format_score(value))


class ScenarioBar(Flowable):
    """One scenario row: name, probability bar, percentage."""

    def __init__(
        self, name: str, percent: float, width: float, font_size: float, color: Color
    ):
        super().__init__()
        self.name = name
        self.percent = max(0.0, min(100.0, float(percent)))
        self.width = width
        self.font_size = font_size
        self.color = color
        self.height = font_size + 5.0

    def wrap(self, available_width: float, available_height: float):
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        label_width = self.width * 0.30
        value_width = self.font_size * 2.4
        bar_x = label_width + 2.0
        bar_width = max(10.0, self.width - bar_x - value_width)
        bar_height = self.font_size * 0.78
        baseline = 1.5

        canvas.setFont(FONT_BOLD, self.font_size)
        canvas.setFillColor(INK)
        canvas.drawString(0, baseline + 1.0, self.name)

        canvas.setFillColor(TRACK)
        canvas.roundRect(
            bar_x, baseline, bar_width, bar_height, bar_height / 2, stroke=0, fill=1
        )
        fraction = self.percent / 100.0
        if fraction > 0:
            canvas.setFillColor(self.color)
            canvas.roundRect(
                bar_x,
                baseline,
                max(bar_width * fraction, bar_height),
                bar_height,
                bar_height / 2,
                stroke=0,
                fill=1,
            )

        canvas.setFont(FONT, self.font_size)
        canvas.setFillColor(BODY)
        canvas.drawRightString(self.width, baseline + 1.0, f"{self.percent:.0f}%")


class HeaderBand(Flowable):
    """Company name, date, recommendation badge, and the rule beneath them."""

    def __init__(
        self,
        company_name: str,
        stamp: date,
        recommendation: str,
        confidence_pct: int,
        width: float,
        font_size: float,
        logo_path: Optional[str | Path] = None,
    ):
        super().__init__()
        self.company_name = company_name
        self.stamp = stamp
        self.recommendation = recommendation
        self.confidence_pct = confidence_pct
        self.width = width
        self.font_size = font_size
        self.logo_path = logo_path
        self.title_size = font_size + 6.0
        self.height = self.title_size + font_size + 12.0

    def wrap(self, available_width: float, available_height: float):
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        top = self.height

        badge_height = self.title_size + 3.0
        badge_text = f"{self.recommendation.upper()}  ·  {self.confidence_pct}% CONF."
        badge_font = self.font_size + 0.5
        badge_width = canvas.stringWidth(badge_text, FONT_BOLD, badge_font) + 16.0
        badge_x = self.width - badge_width
        badge_y = top - badge_height

        canvas.setFillColor(BADGE_COLORS.get(self.recommendation, AMBER))
        canvas.roundRect(
            badge_x, badge_y, badge_width, badge_height, 2.5, stroke=0, fill=1
        )
        canvas.setFillColor(WHITE)
        canvas.setFont(FONT_BOLD, badge_font)
        canvas.drawCentredString(
            badge_x + badge_width / 2,
            badge_y + (badge_height - badge_font) / 2 + 1.5,
            badge_text,
        )

        text_x = 0.0
        if self.logo_path:
            text_x = self._draw_logo(canvas, top, badge_height)

        canvas.setFillColor(INK)
        canvas.setFont(FONT_BOLD, self.title_size)
        canvas.drawString(
            text_x, top - self.title_size + 1.0, _clip(self.company_name, 60)
        )

        canvas.setFillColor(MUTED)
        canvas.setFont(FONT, self.font_size)
        canvas.drawString(
            text_x,
            top - self.title_size - self.font_size - 1.5,
            f"Decision Intelligence Analysis  ·  {self.stamp:%d %B %Y}",
        )

        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.7)
        canvas.line(0, 3.0, self.width, 3.0)

    def _draw_logo(self, canvas: Canvas, top: float, badge_height: float) -> float:
        """Draw the logo at the left edge; return the x offset for the title."""
        try:
            from reportlab.lib.utils import ImageReader

            image = ImageReader(str(self.logo_path))
            width_px, height_px = image.getSize()
            draw_height = badge_height
            draw_width = draw_height * (width_px / height_px)
            canvas.drawImage(
                image,
                0,
                top - draw_height,
                width=draw_width,
                height=draw_height,
                mask="auto",
            )
            return draw_width + 8.0
        except Exception:
            # A broken logo must not cost the user their report.
            return 0.0


# --------------------------------------------------------------------------- #
# Layout assembly
# --------------------------------------------------------------------------- #


@dataclass
class _Layout:
    page_size: tuple[float, float]
    header: HeaderBand
    columns: list[tuple[Stack, float]]
    bands: list[tuple[str, Stack]]
    band_heights: dict[str, float] = field(default_factory=dict)
    required: float = 0.0
    available: float = 0.0

    @property
    def fits(self) -> bool:
        return self.required <= self.available + 0.01

    @property
    def overflow(self) -> float:
        return max(0.0, self.required - self.available)

    @property
    def tallest_band(self) -> str:
        if not self.band_heights:
            return "layout"
        return max(self.band_heights.items(), key=lambda item: item[1])[0]

    @property
    def band_gap(self) -> float:
        """BAND_GAP plus a bounded share of any unused vertical space."""
        gaps = max(1, len(self.band_heights) - 1)
        slack = max(0.0, self.available - self.required)
        return BAND_GAP + min(MAX_EXTRA_BAND_GAP, slack / gaps)

    def draw(self, canvas: Canvas) -> None:
        _page_width, page_height = self.page_size
        gap = self.band_gap
        cursor = page_height - MARGIN

        self.header.drawOn(canvas, MARGIN, cursor - self.header.height)
        cursor -= self.header.height + gap

        column_top = cursor
        lowest = cursor
        x = MARGIN
        for stack, width in self.columns:
            lowest = min(lowest, stack.draw(canvas, x, column_top))
            x += width + GUTTER
        cursor = lowest - gap

        for _name, stack in self.bands:
            cursor = stack.draw(canvas, MARGIN, cursor) - gap


def _fit_layout(
    analysis: AnalysisResult,
    page_size: tuple[float, float],
    company_name: str,
    logo_path: Optional[str | Path],
    stamp: date,
) -> _Layout:
    """Pick the largest type size that can carry an acceptable text budget.

    At each font size the largest fitting clip scale is found by bisection. The
    first size that reaches `ACCEPTABLE_CLIP_SCALE` wins; if none does, the
    candidate that preserved the most text is used.
    """

    def build(font_size: float, clip_scale: float) -> _Layout:
        return _build_layout(
            analysis, page_size, font_size, company_name, logo_path, stamp, clip_scale
        )

    best: tuple[float, _Layout] | None = None
    tightest: _Layout | None = None

    for font_size in FONT_SIZES:
        generous = build(font_size, MAX_CLIP_SCALE)
        if generous.fits:
            return generous

        tightest = build(font_size, MIN_CLIP_SCALE)
        if not tightest.fits:
            continue  # even the tightest budget overflows at this size

        low, high = MIN_CLIP_SCALE, MAX_CLIP_SCALE
        feasible = (low, tightest)
        for _ in range(CLIP_SEARCH_ITERATIONS):
            middle = (low + high) / 2
            candidate = build(font_size, middle)
            if candidate.fits:
                low, feasible = middle, (middle, candidate)
            else:
                high = middle

        if best is None or feasible[0] > best[0]:
            best = feasible
        if feasible[0] >= ACCEPTABLE_CLIP_SCALE:
            return feasible[1]

    if best is not None:
        return best[1]

    overflowing = tightest or build(MIN_FONT_SIZE, MIN_CLIP_SCALE)
    raise LayoutOverflowError(
        f"Could not fit the report on one page at {MIN_FONT_SIZE}pt: the "
        f"'{overflowing.tallest_band}' section overflows by "
        f"{overflowing.overflow:.0f}pt (needs {overflowing.required:.0f}pt of "
        f"{overflowing.available:.0f}pt available)."
    )


@dataclass(frozen=True)
class Limits:
    """Per-field character budgets for the current fit candidate."""

    thesis: int
    bullet: int
    risk: int
    question: int
    case: int
    driver: int
    outcome: int

    @classmethod
    def scaled(cls, scale: float) -> "Limits":
        return cls(
            thesis=int(CLIP_THESIS * scale),
            bullet=int(CLIP_BULLET * scale),
            risk=int(CLIP_RISK * scale),
            question=int(CLIP_QUESTION * scale),
            case=int(CLIP_CASE * scale),
            driver=int(CLIP_DRIVER * scale),
            outcome=int(CLIP_OUTCOME * scale),
        )


def _build_layout(
    analysis: AnalysisResult,
    page_size: tuple[float, float],
    font_size: float,
    company_name: str,
    logo_path: Optional[str | Path],
    stamp: date,
    clip_scale: float = 1.0,
) -> _Layout:
    page_width, page_height = page_size
    content_width = page_width - 2 * MARGIN
    styles = _make_styles(font_size)
    limits = Limits.scaled(clip_scale)

    header = HeaderBand(
        company_name=company_name,
        stamp=stamp,
        recommendation=analysis.executive_summary.recommendation,
        confidence_pct=analysis.executive_summary.confidence_pct,
        width=content_width,
        font_size=font_size,
        logo_path=logo_path,
    )

    left_width = content_width * 0.29
    middle_width = content_width * 0.42
    right_width = content_width - left_width - middle_width - 2 * GUTTER

    columns = [
        (_scorecard(analysis, left_width, font_size, styles), left_width),
        (_executive_summary(analysis, middle_width, styles, limits), middle_width),
        (_scenarios(analysis, right_width, font_size, styles, limits), right_width),
    ]

    bands = [
        ("top risks", _risks(analysis, content_width, styles, limits)),
        ("diligence questions", _questions(analysis, content_width, styles, limits)),
        ("footer", _footer(analysis, content_width, styles, limits, stamp)),
    ]

    layout = _Layout(
        page_size=page_size, header=header, columns=columns, bands=bands
    )
    layout.band_heights = {
        "header": header.height,
        "scorecard / summary / scenarios": max(
            stack.height() for stack, _ in columns
        ),
        **{name: stack.height() for name, stack in bands},
    }
    layout.required = (
        sum(layout.band_heights.values()) + BAND_GAP * (len(layout.band_heights) - 1)
    )
    layout.available = page_height - 2 * MARGIN
    return layout


# --------------------------------------------------------------------------- #
# Bands
# --------------------------------------------------------------------------- #


def _scorecard(
    analysis: AnalysisResult, width: float, font_size: float, styles: dict
) -> Stack:
    stack = Stack(width)
    stack.add(Paragraph("SCORECARD", styles["heading"]), gap=3.0)
    stack.add(ScoreBars(analysis.scores.category_rows(), width, font_size), gap=4.0)
    stack.add(
        Paragraph(
            f"<b>Weighted overall {analysis.scores.weighted_overall:.1f}/10</b> "
            f"&nbsp;·&nbsp; Decision quality {analysis.scores.decision_quality:.1f}/10",
            styles["note"],
        )
    )
    return stack


def _executive_summary(
    analysis: AnalysisResult, width: float, styles: dict, limits: Limits
) -> Stack:
    summary = analysis.executive_summary
    stack = Stack(width)
    stack.add(Paragraph("EXECUTIVE SUMMARY", styles["heading"]), gap=3.0)
    stack.add(
        Paragraph(
            escape(_clip(summary.investment_thesis, limits.thesis)), styles["body"]
        ),
        gap=4.0,
    )

    stack.add(Paragraph("STRENGTHS", styles["subheading"]), gap=1.5)
    for item in summary.top_strengths[:3]:
        stack.add(Paragraph(_bullet(item, GREEN, limits.bullet), styles["bullet"]), gap=1.0)

    stack.add(Paragraph("CONCERNS", styles["subheading"]), gap=1.5)
    for item in summary.top_concerns[:3]:
        stack.add(Paragraph(_bullet(item, RED, limits.bullet), styles["bullet"]), gap=1.0)
    return stack


def _scenarios(
    analysis: AnalysisResult,
    width: float,
    font_size: float,
    styles: dict,
    limits: Limits,
) -> Stack:
    stack = Stack(width)
    stack.add(Paragraph("SCENARIOS", styles["heading"]), gap=3.0)

    rows = (
        ("Best", analysis.scenarios.best, GREEN),
        ("Base", analysis.scenarios.base, AMBER),
        ("Worst", analysis.scenarios.worst, RED),
    )
    for name, scenario, color in rows:
        stack.add(
            ScenarioBar(name, scenario.probability_pct, width, font_size, color),
            gap=1.0,
        )
        drivers = "  ".join(
            f"&#183;&nbsp;{escape(_clip(driver, limits.driver))}"
            for driver in scenario.drivers[:2]
        )
        if drivers:
            stack.add(Paragraph(drivers, styles["driver"]), gap=4.0)

    stack.add(
        Paragraph(
            "<b>Expected outcome.</b> "
            + escape(_clip(analysis.expected_risk_adjusted_outcome, limits.outcome)),
            styles["note"],
        )
    )
    return stack


def _risks(
    analysis: AnalysisResult, width: float, styles: dict, limits: Limits
) -> Stack:
    stack = Stack(width)
    stack.add(Paragraph("TOP RISKS", styles["heading"]), gap=3.0)

    if not analysis.risks:
        stack.add(Paragraph("No risks were identified in the deck.", styles["body"]))
        return stack

    shown = analysis.risks[:MAX_RISK_ROWS]
    data = [
        [
            Paragraph("Risk", styles["table_head"]),
            Paragraph("Prob / Impact", styles["table_head"]),
            Paragraph("Mitigation", styles["table_head"]),
        ]
    ]
    for risk in shown:
        data.append(
            [
                Paragraph(
                    f"<b>{escape(risk.category)}.</b> "
                    f"{escape(_clip(risk.description, limits.risk))}",
                    styles["table_cell"],
                ),
                Paragraph(
                    f'<font color="{_hex(LEVEL_COLORS[risk.probability])}">'
                    f"<b>{risk.probability}</b></font> / "
                    f'<font color="{_hex(LEVEL_COLORS[risk.impact])}">'
                    f"<b>{risk.impact}</b></font>",
                    styles["table_cell"],
                ),
                Paragraph(
                    escape(_clip(risk.mitigation, limits.risk)), styles["table_cell"]
                ),
            ]
        )

    column_widths = [width * 0.44, width * 0.13, width * 0.43]
    table = Table(data, colWidths=column_widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PANEL),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    stack.add(table, gap=2.0)

    hidden = len(analysis.risks) - len(shown)
    if hidden > 0:
        stack.add(
            Paragraph(
                f"{hidden} further risk{'s' if hidden > 1 else ''} identified — "
                f"see the full analysis.",
                styles["note"],
            )
        )
    return stack


def _questions(
    analysis: AnalysisResult, width: float, styles: dict, limits: Limits
) -> Stack:
    stack = Stack(width)
    stack.add(Paragraph("TOP 5 DILIGENCE QUESTIONS", styles["heading"]), gap=3.0)

    questions = analysis.top_diligence_questions[:MAX_QUESTIONS]
    if not questions:
        stack.add(Paragraph("None specified.", styles["body"]))
        return stack

    for number, question in enumerate(questions, start=1):
        stack.add(
            Paragraph(
                f"<b>{number}.</b>&nbsp; {escape(_clip(question, limits.question))}",
                styles["bullet"],
            ),
            gap=1.0,
        )
    return stack


def _footer(
    analysis: AnalysisResult,
    width: float,
    styles: dict,
    limits: Limits,
    stamp: date,
) -> Stack:
    stack = Stack(width)

    cases = Table(
        [
            [
                Paragraph(
                    f'<font color="{_hex(GREEN)}"><b>BULL CASE</b></font><br/>'
                    f"{escape(_clip(analysis.bull_case, limits.case))}",
                    styles["footer_cell"],
                ),
                Paragraph(
                    f'<font color="{_hex(RED)}"><b>BEAR CASE</b></font><br/>'
                    f"{escape(_clip(analysis.bear_case, limits.case))}",
                    styles["footer_cell"],
                ),
            ]
        ],
        colWidths=[width / 2 - GUTTER / 2, width / 2 - GUTTER / 2],
        hAlign="LEFT",
    )
    cases.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), GUTTER / 2),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LINEABOVE", (0, 0), (-1, 0), 0.7, RULE),
                ("TOPPADDING", (0, 0), (-1, 0), 4),
            ]
        )
    )
    stack.add(cases, gap=3.0)

    summary = analysis.executive_summary
    stack.add(
        Paragraph(
            f"Recommendation: <b>{escape(summary.recommendation)}</b> &nbsp;·&nbsp; "
            f"Confidence: <b>{summary.confidence_pct}%</b> &nbsp;·&nbsp; "
            f"Generated by TEN Capital Decision Intelligence · {stamp:%Y-%m-%d}",
            styles["footer_line"],
        )
    )
    return stack


# --------------------------------------------------------------------------- #
# Styles and text helpers
# --------------------------------------------------------------------------- #


def _make_styles(font_size: float) -> dict[str, ParagraphStyle]:
    leading = font_size * 1.22
    return {
        "heading": ParagraphStyle(
            "heading",
            fontName=FONT_BOLD,
            fontSize=font_size + 0.5,
            leading=(font_size + 0.5) * 1.15,
            textColor=INK,
        ),
        "subheading": ParagraphStyle(
            "subheading",
            fontName=FONT_BOLD,
            fontSize=font_size - 0.5,
            leading=(font_size - 0.5) * 1.2,
            textColor=MUTED,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=FONT,
            fontSize=font_size,
            leading=leading,
            textColor=BODY,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=FONT,
            fontSize=font_size,
            leading=leading,
            textColor=BODY,
            leftIndent=7,
            firstLineIndent=-7,
        ),
        "note": ParagraphStyle(
            "note",
            fontName=FONT,
            fontSize=font_size - 0.5,
            leading=(font_size - 0.5) * 1.25,
            textColor=MUTED,
        ),
        "driver": ParagraphStyle(
            "driver",
            fontName=FONT,
            fontSize=font_size - 0.5,
            leading=(font_size - 0.5) * 1.25,
            textColor=MUTED,
        ),
        "table_head": ParagraphStyle(
            "table_head",
            fontName=FONT_BOLD,
            fontSize=font_size - 0.5,
            leading=(font_size - 0.5) * 1.2,
            textColor=INK,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            fontName=FONT,
            fontSize=font_size - 0.5,
            leading=(font_size - 0.5) * 1.22,
            textColor=BODY,
        ),
        "footer_cell": ParagraphStyle(
            "footer_cell",
            fontName=FONT,
            fontSize=font_size - 0.5,
            leading=(font_size - 0.5) * 1.25,
            textColor=BODY,
        ),
        "footer_line": ParagraphStyle(
            "footer_line",
            fontName=FONT,
            fontSize=font_size - 0.5,
            leading=(font_size - 0.5) * 1.3,
            textColor=MUTED,
        ),
    }


def score_color(fraction: float) -> Color:
    """Red at 0, amber at the midpoint, green at 10."""
    fraction = max(0.0, min(1.0, fraction))
    if fraction <= 0.5:
        return _mix(RED, AMBER, fraction / 0.5)
    return _mix(AMBER, GREEN, (fraction - 0.5) / 0.5)


def _mix(start: Color, end: Color, t: float) -> Color:
    return Color(
        start.red + (end.red - start.red) * t,
        start.green + (end.green - start.green) * t,
        start.blue + (end.blue - start.blue) * t,
    )


def _format_score(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


def _hex(color: Color) -> str:
    """`#rrggbb` for ReportLab's inline `<font color="...">` markup."""
    return "#" + color.hexval()[2:]


def _bullet(text: str, color: Color, limit: int) -> str:
    marker = f'<font color="{_hex(color)}">&#9642;</font>'
    return f"{marker}&nbsp; {escape(_clip(text, limit))}"


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip(" ,;:.") + "…"
