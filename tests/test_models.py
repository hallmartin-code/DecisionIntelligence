"""Schema tests: vocabularies, coercion, and computed values."""

from __future__ import annotations

import pytest

from pitch_analyzer.models import (
    CATEGORY_KEYS,
    CATEGORY_WEIGHTS,
    AnalysisResult,
    AssumptionRow,
    RiskRow,
)


def _risk(level: str) -> RiskRow:
    return RiskRow.model_validate(
        {
            "category": "REGULATORY",
            "risk": "x",
            "probability": level,
            "impact": "High",
            "mitigation": "y",
        }
    )


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("Low", "Low"),
        ("Low-Medium", "Low-Medium"),
        ("low-medium", "Low-Medium"),
        ("Low/Medium", "Low-Medium"),
        ("Low - Medium", "Low-Medium"),
        ("Low-Med", "Low-Medium"),
        ("Medium-High", "Medium-High"),
        ("MEDIUM", "Medium"),
    ],
)
def test_risk_levels_tolerate_reasonable_spellings(supplied, expected):
    """A live run failed on 'Low-Medium'; the vocabulary must absorb variants."""
    assert _risk(supplied).probability == expected


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [("low", "LOW"), ("Low-Med", "LOW-MED"), ("unknown", "UNKNOWN")],
)
def test_assumption_confidence_is_uppercased(supplied, expected):
    row = AssumptionRow.model_validate(
        {"assumption": "a", "evidence": "b", "confidence": supplied, "validation": "c"}
    )

    assert row.confidence == expected


def test_category_weights_total_one_hundred():
    assert sum(CATEGORY_WEIGHTS.values()) == 100
    assert len(CATEGORY_KEYS) == 10


def test_weighted_total_is_computed_from_sections_not_the_model(analysis_payload):
    """The scorecard must not be able to disagree with the sections above it."""
    for row in analysis_payload["scorecard"]:
        row["score"] = 10  # the model claims perfection

    analysis = AnalysisResult.model_validate(analysis_payload)

    assert analysis.weighted_overall == pytest.approx(4.59)
    assert [row.score for row in analysis.scorecard_rows()] == [
        analysis.assessment.section(key).score for key in CATEGORY_KEYS
    ]


def test_scores_are_clamped_into_range(analysis_payload):
    analysis_payload["assessment"]["team_assessment"]["score"] = 47
    analysis_payload["confidence_pct"] = 250

    analysis = AnalysisResult.model_validate(analysis_payload)

    assert analysis.assessment.team_assessment.score == 10
    assert analysis.confidence_pct == 100


def test_scenario_cumulative_runs_as_a_total(analysis_result):
    rows = analysis_result.scenario_table()

    assert [row[0] for row in rows] == ["Best case", "Base case", "Worst case"]
    assert rows[-1][4] == "2.92x"


def test_memo_pads_to_nine_fields(analysis_payload):
    analysis_payload["memo"] = ["only one"]

    analysis = AnalysisResult.model_validate(analysis_payload)

    assert len(analysis.memo_rows) == 9
    assert analysis.memo_rows[0] == ("Company", "only one")
    assert analysis.memo_rows[-1][1] == ""
