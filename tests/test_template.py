"""The blank report template must stay valid and in sync with the renderer."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from pitch_analyzer.models import AnalysisResult
from pitch_analyzer.render import BADGE_COLORS, LEVEL_COLORS

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
STRUCTURE_DOC = TEMPLATES_DIR / "report_structure.md"


@pytest.fixture(scope="module")
def template_module():
    """Load templates/make_report_template.py, which is not an installed package."""
    spec = importlib.util.spec_from_file_location(
        "make_report_template", TEMPLATES_DIR / "make_report_template.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_template_payload_matches_the_analysis_schema(template_module):
    analysis = AnalysisResult.model_validate(template_module.TEMPLATE_PAYLOAD)

    assert len(analysis.scores.category_rows()) == 10
    assert len(analysis.top_diligence_questions) == 5
    assert len(analysis.executive_summary.top_strengths) == 3
    assert len(analysis.executive_summary.top_concerns) == 3


def test_template_covers_every_closed_vocabulary(template_module):
    """The template should exercise each allowed enum value at least once."""
    analysis = AnalysisResult.model_validate(template_module.TEMPLATE_PAYLOAD)

    categories = {risk.category for risk in analysis.risks}
    assert categories == set(template_module.RISK_CATEGORIES)
    assert categories == {
        "Market",
        "Product",
        "Execution",
        "Financial",
        "Regulatory",
        "Competitive",
    }

    levels = {risk.probability for risk in analysis.risks} | {
        risk.impact for risk in analysis.risks
    }
    assert levels == set(LEVEL_COLORS)


def test_template_renders_to_one_page_in_both_orientations(
    template_module, tmp_path
):
    for orientation, expected in (
        ("landscape", (792, 612)),
        ("portrait", (612, 792)),
    ):
        output = template_module.build(
            tmp_path / f"template_{orientation}.pdf", orientation
        )

        import pdfplumber

        with pdfplumber.open(str(output)) as pdf:
            assert len(pdf.pages) == 1
            page = pdf.pages[0]
            assert (round(page.width), round(page.height)) == expected


def test_template_carries_no_company_data(template_module, tmp_path):
    """Every free-text field must be a placeholder, not prose."""
    output = template_module.build(tmp_path / "template.pdf")

    import pdfplumber

    with pdfplumber.open(str(output)) as pdf:
        text = pdf.pages[0].extract_text() or ""

    assert "{{ company_name }}" in text
    for token in ("bull_case", "bear_case", "investment_thesis"):
        assert token in text

    # Nothing from the worked example may leak into the template.
    for leaked in ("Northwind", "Acme", "actuator", "warehouse"):
        assert leaked.lower() not in text.lower()


def test_structure_doc_lists_every_scorecard_row(analysis_result):
    doc = STRUCTURE_DOC.read_text(encoding="utf-8")

    for label, _score in analysis_result.scores.category_rows():
        assert label in doc, f"scorecard row missing from the structure doc: {label}"


def test_structure_doc_documents_every_badge_colour():
    doc = STRUCTURE_DOC.read_text(encoding="utf-8")

    for recommendation, color in BADGE_COLORS.items():
        assert recommendation in doc
        assert color.hexval()[2:] in doc.lower()


def test_structure_doc_matches_the_renderer_limits():
    """Character budgets quoted in the doc must match the code."""
    from pitch_analyzer import render

    doc = STRUCTURE_DOC.read_text(encoding="utf-8")
    quoted = {int(value) for value in re.findall(r"(\d+) chars", doc)}

    for limit in (
        render.CLIP_THESIS,
        render.CLIP_BULLET,
        render.CLIP_RISK,
        render.CLIP_QUESTION,
        render.CLIP_CASE,
        render.CLIP_DRIVER,
        render.CLIP_OUTCOME,
    ):
        assert limit in quoted, f"budget {limit} is not documented in the template"
