"""Word (.docx) builder for the Decision Intelligence Assessment.

Implements `templates/di_report_structure.md`. Formatting is applied directly to
runs and cells rather than through named styles, so the output does not depend
on which template Word happens to open it with.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Sequence

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Inches, Pt, RGBColor

from .models import (
    CATEGORIES,
    CATEGORY_TITLES,
    AnalysisResult,
    Bullet,
    Callout,
    SubSection,
)

# --------------------------------------------------------------------------- #
# Design tokens
# --------------------------------------------------------------------------- #

NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x74, 0xB5)
CRIMSON = RGBColor(0xA6, 0x19, 0x2E)
GREY = RGBColor(0x59, 0x59, 0x59)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

PANEL_FILL = "F5F7FA"
HEADER_FILL = "1F3864"

FONT = "Calibri"
#: The house footer is set in Open Sans at 7pt, per the TEN Capital
#: document standard. The body stays Calibri.
FOOTER_FONT = "Open Sans"
SIZE_FOOTER = Pt(7)

#: The footer mark, at the size the standard specifies. The source is
#: 631x232 (2.72:1) and these EMU are 2.69:1, so it is squeezed by about
#: 1% - invisible, and the specified dimensions are what the standard says.
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo_footer.png"
LOGO_WIDTH = Emu(604838)
LOGO_HEIGHT = Emu(224940)

SIZE_BRAND = Pt(10)
SIZE_EYEBROW = Pt(8)
SIZE_TITLE = Pt(25)
SIZE_TAGLINE = Pt(11)
SIZE_H1 = Pt(15)
SIZE_H2 = Pt(12)
SIZE_H3 = Pt(10.5)
SIZE_BODY = Pt(10)
SIZE_VERDICT = Pt(13)
SIZE_TABLE = Pt(9)

PAGE_WIDTH = Inches(8.5)
PAGE_HEIGHT = Inches(11)
MARGIN_X = Inches(0.88)
MARGIN_Y = Inches(0.83)

# Length arithmetic returns a bare EMU int, so keep the usable width in inches.
CONTENT_WIDTH_IN = 8.5 - 2 * 0.88


class RenderError(RuntimeError):
    """Raised when the document cannot be produced."""


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #


def _run(paragraph, text: str, *, size=SIZE_BODY, bold=False, italic=False,
         color: Optional[RGBColor] = None, caps=False):
    run = paragraph.add_run(text.upper() if caps else text)
    run.font.name = FONT
    run.font.size = size
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    return run


def _para(container, text: str = "", *, size=SIZE_BODY, bold=False, italic=False,
          color: Optional[RGBColor] = None, space_before=0, space_after=4,
          align=None, caps=False):
    paragraph = container.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(space_before)
    fmt.space_after = Pt(space_after)
    if align is not None:
        fmt.alignment = align
    if text:
        _run(paragraph, text, size=size, bold=bold, italic=italic, color=color, caps=caps)
    return paragraph


def _shade(cell, fill: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _cell_text(cell, text: str, *, size=SIZE_TABLE, bold=False,
               color: Optional[RGBColor] = None, align=None) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(1)
    paragraph.paragraph_format.space_after = Pt(1)
    if align is not None:
        paragraph.paragraph_format.alignment = align
    _run(paragraph, text or "", size=size, bold=bold, color=color)


def _widths(table, fractions: Sequence[float]) -> None:
    """Set column widths as fractions of the content width."""
    table.autofit = False
    for row in table.rows:
        for cell, fraction in zip(row.cells, fractions):
            cell.width = Inches(CONTENT_WIDTH_IN * fraction)


def _grid(document, headers: Sequence[str], rows: Iterable[Sequence[str]],
          fractions: Sequence[float], *, bold_last_row=False):
    """A navy-headed grid table."""
    rows = [list(row) for row in rows]
    table = document.add_table(rows=1 + len(rows), cols=len(headers))
    try:
        table.style = "Table Grid"
    except KeyError:  # pragma: no cover - style missing from the base template
        pass
    table.alignment = WD_TABLE_ALIGNMENT.LEFT

    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        _shade(cell, HEADER_FILL)
        _cell_text(cell, header, bold=True, color=WHITE)

    for row_index, values in enumerate(rows, start=1):
        last = bold_last_row and row_index == len(rows)
        for col_index, value in enumerate(values):
            _cell_text(table.rows[row_index].cells[col_index], str(value), bold=last)

    _widths(table, fractions)
    _para(document, space_after=6)
    return table


def _callout(document, callout: Callout) -> None:
    """A single-cell shaded panel with an ALL-CAPS title."""
    table = document.add_table(rows=1, cols=1)
    cell = table.rows[0].cells[0]
    _shade(cell, PANEL_FILL)
    cell.text = ""

    title_p = cell.paragraphs[0]
    title_p.paragraph_format.space_after = Pt(2)
    _run(title_p, callout.title, size=SIZE_BODY, bold=True,
         color=CRIMSON if callout.critical else NAVY)

    body_p = cell.add_paragraph()
    body_p.paragraph_format.space_after = Pt(2)
    _run(body_p, callout.body, size=SIZE_BODY)

    _widths(table, [1.0])
    _para(document, space_after=6)


def _bullets(document, items: Iterable[Bullet | str], *, bold=True, numbered=False) -> None:
    for index, item in enumerate(items, start=1):
        bullet = item if isinstance(item, Bullet) else Bullet(text=str(item))
        paragraph = document.add_paragraph()
        fmt = paragraph.paragraph_format
        fmt.left_indent = Inches(0.25)
        fmt.first_line_indent = Inches(-0.15)
        fmt.space_after = Pt(3)
        marker = f"{index}. " if numbered else "•  "
        _run(paragraph, marker + bullet.text, size=SIZE_BODY, bold=bold,
             color=CRIMSON if bullet.adverse else None)


def _h1(document, text: str) -> None:
    _para(document, text, size=SIZE_H1, bold=True, color=NAVY,
          space_before=14, space_after=6)


def _h2(document, text: str) -> None:
    _para(document, text, size=SIZE_H2, bold=True, color=BLUE,
          space_before=10, space_after=4)


def _h3(document, text: str) -> None:
    _para(document, text, size=SIZE_H3, bold=True, color=NAVY,
          space_before=7, space_after=3)


def _subsections(document, subsections: Iterable[SubSection]) -> None:
    for sub in subsections:
        _h3(document, sub.heading)
        for text in sub.paragraphs:
            _para(document, text)
        if sub.bullets:
            _bullets(document, sub.bullets)


def _footer(section, company_name: str, stamp: date) -> None:
    """The house footer: title, page number, attribution, mark - centred.

    Follows the TEN Capital document standard rather than this report's own
    earlier layout, so a reader who has seen one TEN document recognises this
    one. "Confidential" is carried in the title, where the standard puts the
    document's own name: this goes to an investment committee, and dropping a
    confidentiality marker to match a template would be the wrong trade.
    """
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    _footer_run(
        paragraph,
        f"Decision Intelligence Assessment  ·  {company_name}  ·  "
        "Confidential        ",
    )
    _page_field(paragraph, "PAGE")
    _footer_run(paragraph, " of ")
    _page_field(paragraph, "NUMPAGES")
    _footer_run(
        paragraph,
        f"        Compiled on {stamp:%d %B %Y} by TEN Capital Network  ",
    )
    _footer_logo(paragraph)


def _footer_run(paragraph, text: str):
    run = paragraph.add_run(text)
    run.font.name = FOOTER_FONT
    run.font.size = SIZE_FOOTER
    run.font.color.rgb = GREY
    return run


def _footer_logo(paragraph) -> bool:
    """Place the mark inline at the end of the footer.

    A missing or unreadable logo must not fail a finished report - the analysis
    is the deliverable and the mark is decoration - so this reports whether it
    landed instead of raising.
    """
    if not LOGO_PATH.is_file():
        return False
    try:
        paragraph.add_run().add_picture(
            str(LOGO_PATH), width=LOGO_WIDTH, height=LOGO_HEIGHT
        )
    except Exception:  # pragma: no cover - a corrupt asset, not a code path
        return False
    return True


def _page_field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    run.font.name = FOOTER_FONT
    run.font.size = SIZE_FOOTER
    run.font.color.rgb = GREY

    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")

    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def render_report(
    analysis: AnalysisResult,
    output_path: str | Path,
    generated_on: Optional[date] = None,
) -> Path:
    """Render `analysis` to a .docx report and return the path."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stamp = generated_on or date.today()

    document = Document()
    _configure(document, analysis.company_name, stamp)

    _masthead(document, analysis, stamp)
    _part_executive_summary(document, analysis)
    _part_assessment(document, analysis)
    _part_scenarios(document, analysis)
    _part_committee_view(document, analysis)
    _part_scorecard(document, analysis)
    _part_final(document, analysis)
    _part_memo(document, analysis)

    document.save(str(destination))
    return destination


def _configure(document: Document, company_name: str, stamp: date) -> None:
    normal = document.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = SIZE_BODY

    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = PAGE_WIDTH
    section.page_height = PAGE_HEIGHT
    section.left_margin = section.right_margin = MARGIN_X
    section.top_margin = section.bottom_margin = MARGIN_Y
    _footer(section, company_name, stamp)


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


def _masthead(document, analysis: AnalysisResult, stamp: date) -> None:
    _para(document, "TEN CAPITAL GROUP", size=SIZE_BRAND, bold=True, color=BLUE,
          space_after=0)
    _para(document, "INVESTMENT COMMITTEE  ·  DECISION INTELLIGENCE ASSESSMENT",
          size=SIZE_EYEBROW, color=GREY, space_after=6)
    _para(document, analysis.company_name, size=SIZE_TITLE, bold=True, color=NAVY,
          space_after=2)
    if analysis.one_line_descriptor:
        _para(document, analysis.one_line_descriptor, size=SIZE_TAGLINE, color=GREY,
              space_after=8)

    meta = analysis.metadata
    analysis_date = meta.analysis_date or f"{stamp:%d %B %Y}"
    pairs = [
        ("Source document", meta.source_document, "Analysis date", analysis_date),
        ("Company status", meta.company_status, meta.milestone_label, meta.milestone_value),
        ("Regulatory plan", meta.regulatory_plan, "Commercialization", meta.commercialization),
        ("Funding ask", meta.funding_ask, "Valuation / terms", meta.valuation_terms),
        ("Financials", meta.financials, "Cap table / runway", meta.cap_table_runway),
    ]
    table = document.add_table(rows=1 + len(pairs), cols=4)
    try:
        table.style = "Table Grid"
    except KeyError:  # pragma: no cover
        pass
    for index, header in enumerate(("Field", "Detail", "Field", "Detail")):
        cell = table.rows[0].cells[index]
        _shade(cell, HEADER_FILL)
        _cell_text(cell, header, bold=True, color=WHITE)
    for row_index, values in enumerate(pairs, start=1):
        for col_index, value in enumerate(values):
            _cell_text(table.rows[row_index].cells[col_index], str(value),
                       bold=col_index % 2 == 0)
    _widths(table, [0.18, 0.32, 0.18, 0.32])
    _para(document, space_after=6)

    _callout(
        document,
        Callout(
            title=f"RECOMMENDATION:  {analysis.recommendation.upper()}"
            + (f"  ·  {analysis.executive_summary.recommendation_qualifier}"
               if analysis.executive_summary.recommendation_qualifier else ""),
            body=(
                f"Overall Decision Confidence: {analysis.confidence_pct}%.  "
                f"Weighted Decision Intelligence Score: "
                f"{analysis.weighted_overall:.1f} / 10.  "
                f"{analysis.verdict_paragraph}"
            ),
            critical=True,
        ),
    )

    if analysis.scoring_fairness_note:
        _para(document, analysis.scoring_fairness_note, bold=True, space_after=6)


def _part_executive_summary(document, analysis: AnalysisResult) -> None:
    summary = analysis.executive_summary
    _h1(document, "Executive Summary")

    _h2(document, "Investment Recommendation")
    verdict = analysis.recommendation.upper()
    if summary.recommendation_qualifier:
        verdict += f"   — {summary.recommendation_qualifier}"
    _para(document, verdict, size=SIZE_VERDICT, bold=True, color=CRIMSON, space_after=4)
    if summary.confidence_note:
        _para(document, f"Overall Decision Confidence: {analysis.confidence_pct}%  "
                        f"— {summary.confidence_note}", bold=True)

    _h2(document, "Key Investment Thesis")
    for paragraph in summary.key_investment_thesis:
        _para(document, paragraph)

    _h2(document, "Top Three Strengths")
    _bullets(document, summary.top_strengths[:3], numbered=True)

    _h2(document, "Top Three Concerns")
    _bullets(document, summary.top_concerns[:3], numbered=True)


def _part_assessment(document, analysis: AnalysisResult) -> None:
    _h1(document, "Decision Intelligence Assessment")

    for number, (key, title) in enumerate(CATEGORIES, start=1):
        section = analysis.assessment.section(key)
        _h2(document, f"{number}.  {title} — Score {section.score} / 10")
        _subsections(document, section.subsections)

        for callout in section.callouts:
            _callout(document, callout)

        _section_table(document, key, analysis)

        if section.diligence_questions:
            _h3(document, "Recommended diligence questions")
            _bullets(document, section.diligence_questions, bold=False, numbered=True)


def _section_table(document, key: str, analysis: AnalysisResult) -> None:
    """Attach the table that belongs to this assessment section, if any."""
    if key == "market_opportunity" and analysis.market_sizing:
        _h3(document, "Market sizing as presented")
        _grid(document, ["Layer", "As stated", "Assessment"],
              [(r.layer, r.as_stated, r.assessment) for r in analysis.market_sizing],
              [0.24, 0.36, 0.40])

    elif key == "competitive_intelligence" and analysis.competitors:
        _h3(document, "What the summary does not mention")
        _grid(document, ["Competitor", "Type", "Why it competes"],
              [(r.competitor, r.type, r.why_it_competes) for r in analysis.competitors],
              [0.24, 0.22, 0.54])

    elif key == "traction_evidence" and analysis.evidence_quality:
        _h3(document, "What has actually been demonstrated")
        _grid(document, ["Evidence", "What it demonstrates", "What it does not demonstrate"],
              [(r.evidence, r.demonstrates, r.does_not_demonstrate)
               for r in analysis.evidence_quality],
              [0.24, 0.38, 0.38])

    elif key == "financial_intelligence" and analysis.sensitivity:
        _h3(document, "Sensitivity analysis on forecast assumptions")
        _grid(document, ["Variable", "Stated", "What determines it", "Effect if adverse"],
              [(r.variable, r.stated, r.determined_by, r.effect_if_adverse)
               for r in analysis.sensitivity],
              [0.24, 0.16, 0.26, 0.34])

    elif key == "risk_intelligence" and analysis.risk_register:
        _h3(document, "Ranked risk register")
        _grid(document, ["#", "Risk", "Prob.", "Impact", "Mitigation strategy"],
              [(str(i), f"{r.category} — {r.risk}", r.probability, r.impact, r.mitigation)
               for i, r in enumerate(analysis.risk_register, start=1)],
              [0.04, 0.34, 0.10, 0.10, 0.42])

    elif key == "assumption_mapping" and analysis.assumptions:
        _h3(document, "The critical assumptions")
        _grid(document,
              ["#", "Assumption", "Evidence presented", "Confidence", "Validation needed"],
              [(str(i), r.assumption, r.evidence, r.confidence, r.validation)
               for i, r in enumerate(analysis.assumptions, start=1)],
              [0.04, 0.28, 0.26, 0.11, 0.31])


def _part_scenarios(document, analysis: AnalysisResult) -> None:
    _h1(document, "Decision Scenario Analysis")

    for label, scenario in analysis.scenarios.ordered():
        _h2(document, f"{label} — Probability {scenario.probability_pct}%")
        if scenario.narrative:
            _para(document, scenario.narrative)
        if scenario.drivers:
            _h3(document, "Key drivers")
            _bullets(document, scenario.drivers)

    _h2(document, "Probability-weighted outcome")
    _grid(document, ["Scenario", "Probability", "Gross multiple", "Weighted", "Cumulative"],
          analysis.scenario_table(), [0.22, 0.16, 0.24, 0.19, 0.19])

    for callout in (analysis.basis_of_analysis, analysis.expected_outcome_callout):
        if callout is not None:
            _callout(document, callout)


def _part_committee_view(document, analysis: AnalysisResult) -> None:
    view = analysis.committee_view
    _h1(document, "Investment Committee View")

    _h2(document, "Bull Case — The Strongest Argument For Investing")
    _para(document, view.bull_case)

    _h2(document, "Bear Case — The Strongest Argument Against Investing")
    _para(document, view.bear_case)

    _h2(document, "Missing Information — What Would Materially Improve Decision Quality")
    if view.would_enable_a_decision:
        _h3(document, "Would make a decision possible at all")
        _bullets(document, view.would_enable_a_decision)
    if view.would_change_the_assessment:
        _h3(document, "Would materially change the assessment")
        _bullets(document, view.would_change_the_assessment)


def _part_scorecard(document, analysis: AnalysisResult) -> None:
    _h1(document, "Decision Intelligence Scorecard")

    # The weights differ by stage, so the table's numbers are unreadable
    # without saying which weighting produced them and on what evidence.
    stage = analysis.stage
    _para(document, f"Weighting: {stage.label}", bold=True)
    _para(document, f"Company stage: {stage.summary}.")
    if stage.basis:
        _para(document, f"Basis: {stage.basis}")
    _para(document, stage.rationale, italic=True)

    rows = [
        (
            CATEGORY_TITLES[row.category],
            f"{row.score} / 10",
            f"{row.weight}%",
            f"{row.weighted:.2f}",
            row.driver,
        )
        for row in analysis.scorecard_rows()
    ]
    rows.append(
        (
            "WEIGHTED OVERALL SCORE",
            f"{analysis.weighted_overall:.1f} / 10",
            "100%",
            f"{analysis.weighted_overall:.2f}",
            "",
        )
    )
    _grid(document, ["Category", "Score", "Weight", "Weighted", "Principal driver of the score"],
          rows, [0.22, 0.09, 0.08, 0.10, 0.51], bold_last_row=True)

    composite = analysis.composite
    _h2(document, "Composite indices")
    _grid(document, ["Index", "Value", "Interpretation"],
          [
              ("Weighted Overall Score", f"{analysis.weighted_overall:.1f} / 10",
               composite.weighted_interpretation),
              ("Confidence Score", f"{analysis.confidence_pct}%",
               composite.confidence_interpretation),
              ("Decision Quality Score", f"{composite.decision_quality:.1f} / 10",
               composite.decision_quality_interpretation),
          ],
          [0.22, 0.12, 0.66])

    if analysis.comparative_context:
        _h2(document, "Comparative context across this cycle")
        _grid(document, ["Company", "DI score", "Confidence", "Character of the central issue"],
              [(r.company, r.di_score, r.confidence, r.central_issue)
               for r in analysis.comparative_context],
              [0.22, 0.11, 0.12, 0.55])


def _part_final(document, analysis: AnalysisResult) -> None:
    final = analysis.final
    _h1(document, "Final Recommendation")

    if final.how_to_approach:
        _h2(document, "How to approach this")
        _para(document, final.how_to_approach)

    if final.top_five_diligence_questions:
        _h2(document, "Top Five Diligence Questions")
        _bullets(document, final.top_five_diligence_questions[:5], numbered=True)

    if final.milestones:
        _h2(document, "Key Milestones Required Before Investment")
        _grid(document, ["#", "Milestone", "Why it matters"],
              [(str(i), m.milestone, m.why_it_matters)
               for i, m in enumerate(final.milestones, start=1)],
              [0.05, 0.47, 0.48])

    if final.expected_risk_adjusted_outcome:
        _h2(document, "Expected Risk-Adjusted Outcome")
        _para(document, final.expected_risk_adjusted_outcome)

    qualifier = analysis.executive_summary.recommendation_qualifier
    _callout(
        document,
        Callout(
            title=f"{analysis.recommendation.upper()}  ·  Confidence Level "
                  f"{analysis.confidence_pct}%"
                  + (f"  ·  {qualifier}" if qualifier else ""),
            body=final.expected_risk_adjusted_outcome or analysis.verdict_paragraph,
            critical=True,
        ),
    )


def _part_memo(document, analysis: AnalysisResult) -> None:
    _h1(document, "Summary Investment Memo")
    _grid(document, ["Field", "Summary"], analysis.memo_rows, [0.22, 0.78])
