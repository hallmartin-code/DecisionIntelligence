"""Shared fixtures: a complete, schema-valid analysis payload."""

from __future__ import annotations

import copy

import pytest

from pitch_analyzer.models import AnalysisResult


@pytest.fixture(autouse=True)
def block_real_api_clients(monkeypatch):
    """No test may reach the Anthropic API.

    Background workers can outlive the test that started them, so without this
    guard a stray job could construct a real client and spend credits. Tests
    must pass a stub client or patch `analyze_deck`.
    """
    import anthropic

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "A test tried to construct a real Anthropic client. Pass a stub "
            "client or patch analyze_deck."
        )

    monkeypatch.setattr(anthropic, "Anthropic", _forbidden)


def _section(score: int, name: str) -> dict:
    return {
        "score": score,
        "observations": f"{name} is supported by slides 3-5 with named customers.",
        "missing": f"No third-party validation of the {name.lower()} claims.",
        "questions": [f"What independent evidence supports {name.lower()}?"],
    }


ANALYSIS_PAYLOAD: dict = {
    "executive_summary": {
        "recommendation": "Investigate Further",
        "confidence_pct": 62,
        "investment_thesis": (
            "Acme Robotics sells a warehouse picking arm at roughly half the "
            "installed cost of incumbent systems, and has converted two paid "
            "pilots into multi-year contracts. The thesis rests on whether that "
            "cost advantage survives volume manufacturing."
        ),
        "top_strengths": [
            "Two paid pilots converted to 3-year contracts (Slide 7).",
            "Founding team shipped a comparable arm at a public robotics firm.",
            "Unit economics improve materially at 500 units/year (Slide 11).",
        ],
        "top_concerns": [
            "No signed supply agreement for the actuator (Slide 12).",
            "TAM is top-down and unsourced (Slide 5).",
            "18 months of runway against a 30-month milestone plan.",
        ],
    },
    "scores": {
        "problem_validation": 8,
        "solution_strength": 7,
        "market_opportunity": 6,
        "competitive_position": 5,
        "business_model": 7,
        "traction": 6,
        "team": 8,
        "financial_quality": 4,
        "risk_profile": 5,
        "investment_attractiveness": 6,
        "weighted_overall": 6.2,
        "decision_quality": 5.8,
    },
    "sections": {
        "problem_validation": _section(8, "Problem validation"),
        "solution_effectiveness": _section(7, "Solution effectiveness"),
        "market_opportunity": _section(6, "Market opportunity"),
        "competitive_intelligence": _section(5, "Competitive intelligence"),
        "business_model": _section(7, "Business model"),
        "traction_evidence": _section(6, "Traction evidence"),
        "team_assessment": _section(8, "Team assessment"),
        "financial_intelligence": _section(4, "Financial intelligence"),
    },
    "risks": [
        {
            "category": "Financial",
            "description": "Runway ends 12 months before the stated Series A milestone.",
            "probability": "High",
            "impact": "High",
            "mitigation": "Raise a bridge or cut the hardware roadmap to one SKU.",
        },
        {
            "category": "Execution",
            "description": "Contract manufacturer has not been selected (Slide 12).",
            "probability": "Medium",
            "impact": "High",
            "mitigation": "Sign an NRE agreement before the round closes.",
        },
        {
            "category": "Competitive",
            "description": "A well-funded incumbent is shipping a similar arm in Europe.",
            "probability": "Medium",
            "impact": "Medium",
            "mitigation": "Lock in exclusivity with the two pilot customers.",
        },
        {
            "category": "Market",
            "description": "TAM figure is unsourced and likely overstated.",
            "probability": "Medium",
            "impact": "Medium",
            "mitigation": "Rebuild the model bottom-up from facility counts.",
        },
    ],
    "assumptions": [
        {
            "assumption": "Bill of materials falls 30% at 500 units/year.",
            "evidence": "Vendor quote referenced on Slide 11; quote not attached.",
            "confidence": "Low",
            "validation": "Request the quote and a second supplier bid.",
        },
        {
            "assumption": "Both pilot customers renew at contract end.",
            "evidence": "Signed 3-year contracts shown on Slide 7.",
            "confidence": "Medium",
            "validation": "Reference calls with both operations leads.",
        },
    ],
    "scenarios": {
        "best": {
            "probability_pct": 20,
            "drivers": [
                "Actuator supply locked at quoted price.",
                "Pilots expand to 40 units across both accounts.",
            ],
        },
        "base": {
            "probability_pct": 55,
            "drivers": [
                "Manufacturing slips two quarters.",
                "Revenue reaches $4M by 2028 on flat gross margin.",
            ],
        },
        "worst": {
            "probability_pct": 25,
            "drivers": [
                "Bridge round required at a flat valuation.",
                "Incumbent undercuts pricing in the core segment.",
            ],
        },
    },
    "bull_case": (
        "If the actuator cost curve holds, Acme reaches positive unit economics "
        "at 500 units and becomes the default retrofit option for mid-size "
        "warehouses, a segment incumbents price out of reach."
    ),
    "bear_case": (
        "Hardware cost reductions do not materialise, the company burns the "
        "round on a single custom deployment, and a bridge is required within "
        "18 months at a flat valuation."
    ),
    "missing_information": [
        "Signed supply agreement for the actuator.",
        "Bottom-up TAM methodology.",
        "Cap table and prior note terms.",
    ],
    "top_diligence_questions": [
        "What are the exact terms of the two pilot-to-contract conversions?",
        "Which contract manufacturer is selected, and at what NRE cost?",
        "How was the $12B TAM on Slide 5 derived?",
        "What is the burn rate and the actual runway from close?",
        "Who owns the actuator IP, and is any of it licensed?",
    ],
    "key_milestones_before_investment": [
        "Signed NRE agreement with a contract manufacturer.",
        "Reference calls completed with both pilot customers.",
    ],
    "expected_risk_adjusted_outcome": (
        "A probability-weighted 2.1x over five years, dominated by the base "
        "case; the outcome is highly sensitive to the actuator supply question."
    ),
}


@pytest.fixture
def analysis_payload() -> dict:
    """A fresh deep copy so tests can mutate it freely."""
    return copy.deepcopy(ANALYSIS_PAYLOAD)


@pytest.fixture
def analysis_result(analysis_payload: dict) -> AnalysisResult:
    return AnalysisResult.model_validate(analysis_payload)
