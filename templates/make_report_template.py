"""Render `templates/report_template.pdf` — the blank one-pager template.

Every free-text field carries a `{{ placeholder }}`, every numeric field is
zero, and the closed-vocabulary fields (recommendation, risk category,
probability/impact) carry an allowed value so the colour coding is visible.
No company data appears anywhere.

Because it goes through the real renderer, the output is guaranteed to match
what the app produces for a live deck.

Run with:  python templates/make_report_template.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pitch_analyzer.models import AnalysisResult
from pitch_analyzer.render import render_one_pager

PLACEHOLDER_DATE = date(2026, 1, 1)


def _section(name: str) -> dict:
    return {
        "score": 0,
        "observations": f"{{{{ sections.{name}.observations }}}}",
        "missing": f"{{{{ sections.{name}.missing }}}}",
        "questions": [f"{{{{ sections.{name}.questions[] }}}}"],
    }


SECTION_NAMES = (
    "problem_validation",
    "solution_effectiveness",
    "market_opportunity",
    "competitive_intelligence",
    "business_model",
    "traction_evidence",
    "team_assessment",
    "financial_intelligence",
)

# One row per allowed risk category, so the template shows the full vocabulary
# and every probability/impact colour. Only the first four render.
RISK_CATEGORIES = (
    "Market",
    "Product",
    "Execution",
    "Financial",
    "Regulatory",
    "Competitive",
)
RISK_LEVELS = ("High", "Medium", "Low", "Medium", "Low", "High")

TEMPLATE_PAYLOAD: dict = {
    "executive_summary": {
        "recommendation": "Investigate Further",
        "confidence_pct": 0,
        "investment_thesis": "{{ executive_summary.investment_thesis }}",
        "top_strengths": [
            "{{ executive_summary.top_strengths[1] }}",
            "{{ executive_summary.top_strengths[2] }}",
            "{{ executive_summary.top_strengths[3] }}",
        ],
        "top_concerns": [
            "{{ executive_summary.top_concerns[1] }}",
            "{{ executive_summary.top_concerns[2] }}",
            "{{ executive_summary.top_concerns[3] }}",
        ],
    },
    "scores": {
        "problem_validation": 0,
        "solution_strength": 0,
        "market_opportunity": 0,
        "competitive_position": 0,
        "business_model": 0,
        "traction": 0,
        "team": 0,
        "financial_quality": 0,
        "risk_profile": 0,
        "investment_attractiveness": 0,
        "weighted_overall": 0.0,
        "decision_quality": 0.0,
    },
    "sections": {name: _section(name) for name in SECTION_NAMES},
    "risks": [
        {
            "category": category,
            "description": f"{{{{ risks[{index}].description }}}}",
            "probability": level,
            "impact": RISK_LEVELS[-index],
            "mitigation": f"{{{{ risks[{index}].mitigation }}}}",
        }
        for index, (category, level) in enumerate(
            zip(RISK_CATEGORIES, RISK_LEVELS), start=1
        )
    ],
    "assumptions": [
        {
            "assumption": "{{ assumptions[].assumption }}",
            "evidence": "{{ assumptions[].evidence }}",
            "confidence": "Medium",
            "validation": "{{ assumptions[].validation }}",
        }
    ],
    "scenarios": {
        name: {
            "probability_pct": 0,
            "drivers": [
                f"{{{{ scenarios.{name}.drivers[1] }}}}",
                f"{{{{ scenarios.{name}.drivers[2] }}}}",
            ],
        }
        for name in ("best", "base", "worst")
    },
    "bull_case": "{{ bull_case }}",
    "bear_case": "{{ bear_case }}",
    "missing_information": ["{{ missing_information[] }}"],
    "top_diligence_questions": [
        f"{{{{ top_diligence_questions[{n}] }}}}" for n in range(1, 6)
    ],
    "key_milestones_before_investment": [
        "{{ key_milestones_before_investment[] }}"
    ],
    "expected_risk_adjusted_outcome": "{{ expected_risk_adjusted_outcome }}",
}


def build(destination: Path, orientation: str = "landscape") -> Path:
    analysis = AnalysisResult.model_validate(TEMPLATE_PAYLOAD)
    return render_one_pager(
        analysis,
        destination,
        company_name="{{ company_name }}",
        orientation=orientation,
        generated_on=PLACEHOLDER_DATE,
    )


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for orientation, suffix in (("landscape", ""), ("portrait", "_portrait")):
        path = build(here / f"report_template{suffix}.pdf", orientation)
        print(f"Wrote {path}")
