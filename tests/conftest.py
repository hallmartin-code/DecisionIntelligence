"""Shared fixtures: a complete, schema-valid Decision Intelligence Assessment."""

from __future__ import annotations

import copy

import pytest

from pitch_analyzer.models import CATEGORY_KEYS, AnalysisResult


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


@pytest.fixture(autouse=True)
def block_real_email(monkeypatch):
    """No test may send a real email.

    `.env` is loaded when the web app is imported, so a live RESEND_API_KEY can
    leak into the test process. Email is switched off by default and the
    transport is stubbed, so a stray job cannot deliver anything.
    """
    from pitch_analyzer import notify

    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    def _forbidden(config, message):
        raise AssertionError(
            "A test tried to POST to Resend. Pass sender_fn= or keep email off."
        )

    monkeypatch.setattr(notify, "post_to_resend", _forbidden)


#: Scores per category, in `CATEGORY_KEYS` order. Weighted total is 4.59.
SCORES = [7, 5, 3, 3, 3, 4, 8, 2, 4, 5]


def _section(score: int, name: str) -> dict:
    return {
        "score": score,
        "subsections": [
            {
                "heading": f"Is the {name.lower()} claim supported?",
                "paragraphs": [
                    f"The material addresses {name.lower()} directly, and the "
                    "reasoning holds for the part that is evidenced."
                ],
                "bullets": [
                    {"text": "A supporting point drawn from slide 4.", "adverse": False},
                    {
                        "text": "The load-bearing figure is unsourced.",
                        "adverse": True,
                    },
                ],
            },
            {
                "heading": "Assumptions requiring validation",
                "paragraphs": [],
                "bullets": [
                    {"text": "The stated rate is asserted, not shown.", "adverse": True}
                ],
            },
        ],
        "callouts": [],
        "diligence_questions": [
            f"What independent evidence supports the {name.lower()} claim?"
        ],
    }


ANALYSIS_PAYLOAD: dict = {
    "company_name": "Acme Robotics",
    "one_line_descriptor": "Warehouse picking automation for mid-size facilities",
    "metadata": {
        "source_document": "Acme Executive Summary (1 page)",
        "analysis_date": "31 August 2026",
        "company_status": "Clinical stage",
        "milestone_label": "First install",
        "milestone_value": "Completed 2025",
        "regulatory_plan": "Not applicable",
        "commercialization": "Targeted 2028",
        "funding_ask": "Not disclosed",
        "valuation_terms": "Not disclosed",
        "financials": "Not disclosed",
        "cap_table_runway": "Not disclosed",
    },
    "recommendation": "Investigate Further",
    "confidence_pct": 62,
    "verdict_paragraph": (
        "This is a screening decision, not an investment decision: no raise "
        "size, valuation or use of funds is disclosed, so there is nothing to "
        "accept or decline."
    ),
    "scoring_fairness_note": (
        "A note on scoring this document fairly. This is a one-page summary, "
        "not a deck; information the format cannot carry is noted but not "
        "scored against the company."
    ),
    "executive_summary": {
        "recommendation_qualifier": "request full materials",
        "confidence_note": (
            "raised by an unusually well-matched founder, capped by the "
            "absence of any commercial terms"
        ),
        "key_investment_thesis": [
            "Warehouse picking is a genuinely good problem to attack.",
            "The strongest element by some distance is the founder.",
            "The thesis breaks if the cost curve does not hold.",
        ],
        "top_strengths": [
            "Founder-market fit is close to ideal. A 25-year operator who "
            "previously ran the identical commercial motion.",
            "Two paid pilots converted to three-year contracts (Slide 7).",
            "The buyer and the beneficiary are the same party.",
        ],
        "top_concerns": [
            "The regulatory strategy delivers a clearance for the wrong "
            "indication, and the summary does not acknowledge the gap.",
            "The market sizing contradicts itself within two sentences.",
            "No signed supply agreement for the actuator (Slide 12).",
        ],
    },
    "assessment": {
        key: _section(score, title)
        for key, score, title in zip(
            CATEGORY_KEYS,
            SCORES,
            [
                "Problem validation",
                "Solution effectiveness",
                "Market opportunity",
                "Competitive intelligence",
                "Business model",
                "Traction evidence",
                "Team assessment",
                "Financial intelligence",
                "Risk intelligence",
                "Assumption mapping",
            ],
        )
    },
    "market_sizing": [
        {"layer": "US TAM", "as_stated": "$9B", "assessment": "Assumes universal adoption"},
        {"layer": "SAM", "as_stated": "Not stated", "assessment": "—"},
    ],
    "competitors": [
        {
            "competitor": "Incumbent A",
            "type": "Device — shipping since 2019",
            "why_it_competes": "Addresses the same workflow at a higher price point.",
        }
    ],
    "evidence_quality": [
        {
            "evidence": "Clinical prototype",
            "demonstrates": "A physical device exists",
            "does_not_demonstrate": "Manufacturability or design freeze",
        }
    ],
    "sensitivity": [
        {
            "variable": "Effect size on length of stay",
            "stated": "Not stated",
            "determined_by": "The pivotal study",
            "effect_if_adverse": "Below one day, the price cannot be justified.",
        }
    ],
    "risk_register": [
        {
            "category": "REGULATORY",
            "risk": "Cleared indication differs from the marketed use.",
            "probability": "High",
            "impact": "High",
            "mitigation": "Require the intended indications-for-use statement.",
        },
        {
            "category": "FINANCIAL",
            "risk": "No ask, no financials, no runway disclosed.",
            "probability": "High",
            "impact": "High",
            "mitigation": "Request the full financial package before further work.",
        },
        {
            "category": "COMPETITIVE",
            "risk": "A well-funded incumbent holds the adjacent franchise.",
            "probability": "Medium",
            "impact": "Medium-High",
            "mitigation": "Freedom-to-operate opinion against the incumbent estate.",
        },
    ],
    "assumptions": [
        {
            "assumption": "The device clears on a predicate and the indication follows.",
            "evidence": "Stated as the plan; no pre-submission minutes.",
            "confidence": "LOW",
            "validation": "Pre-submission minutes; named predicate.",
        },
        {
            "assumption": "Capital required to reach commercialization is available.",
            "evidence": "Nothing disclosed — no ask, no financials.",
            "confidence": "UNKNOWN",
            "validation": "Raise size, use of funds, current cash and burn.",
        },
    ],
    "scenarios": {
        "best": {
            "probability_pct": 20,
            "narrative": "Supply is locked and the pilots expand on schedule.",
            "drivers": ["Actuator supply locked at the quoted price."],
            "gross_multiple": "8–15x (mid 11x)",
            "weighted_multiple": 2.20,
        },
        "base": {
            "probability_pct": 35,
            "narrative": "Manufacturing slips two quarters.",
            "drivers": ["Revenue reaches $4M by 2028 on flat gross margin."],
            "gross_multiple": "1–3x (mid 1.8x)",
            "weighted_multiple": 0.63,
        },
        "worst": {
            "probability_pct": 45,
            "narrative": "A bridge is required at a flat valuation.",
            "drivers": ["The incumbent undercuts pricing in the core segment."],
            "gross_multiple": "0–0.4x",
            "weighted_multiple": 0.09,
        },
    },
    "basis_of_analysis": {
        "title": "BASIS OF THIS ANALYSIS",
        "body": "No ask or valuation is disclosed, so multiples are computed "
        "against an assumed entry.",
        "critical": False,
    },
    "expected_outcome_callout": {
        "title": "EXPECTED RISK-ADJUSTED OUTCOME",
        "body": "Approximately 2.9x gross expected multiple.",
        "critical": False,
    },
    "committee_view": {
        "bull_case": "If the cost curve holds, Acme becomes the default retrofit.",
        "bear_case": "Cost reductions do not materialise and a bridge is required.",
        "would_enable_a_decision": ["The ask, terms and use of funds."],
        "would_change_the_assessment": ["The full pilot dataset."],
    },
    "scorecard": [
        {"category": key, "score": score, "driver": f"Driver for {key.replace('_', ' ')}."}
        for key, score in zip(CATEGORY_KEYS, SCORES)
    ],
    "composite": {
        "decision_quality": 4.5,
        "weighted_interpretation": "Below the threshold at which capital should be committed.",
        "confidence_interpretation": "The lowest of the cycle, and appropriately so.",
        "decision_quality_interpretation": "The material does not support a decision.",
    },
    "comparative_context": [],
    "final": {
        "how_to_approach": "Request the full package before any further work.",
        "top_five_diligence_questions": [
            "What are the exact terms of the pilot conversions?",
            "Which contract manufacturer is selected, and at what cost?",
            "How was the market size derived?",
            "What is the burn rate and the runway from close?",
            "Who owns the core IP, and is any of it licensed?",
        ],
        "milestones": [
            {
                "milestone": "A complete investment package.",
                "why_it_matters": "No decision is possible without it.",
            }
        ],
        "expected_risk_adjusted_outcome": "Approximately 2.9x gross expected multiple.",
    },
    "memo": [
        "Acme Robotics — warehouse picking automation",
        "INVESTIGATE FURTHER — request the full package",
        "62% (lowest of the cycle)",
        "4.6 / 10",
        "Not disclosed",
        "Founder-market fit",
        "One page of information and no ask",
        "Request the full package",
        "Screen forward",
    ],
}


@pytest.fixture
def analysis_payload() -> dict:
    """A fresh deep copy so tests can mutate it freely."""
    return copy.deepcopy(ANALYSIS_PAYLOAD)


@pytest.fixture
def analysis_result(analysis_payload: dict) -> AnalysisResult:
    return AnalysisResult.model_validate(analysis_payload)
