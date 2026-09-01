"""Pydantic schema for the Decision Intelligence Assessment.

Mirrors `templates/di_report_structure.md`. Structural constants that the
document must get right — the ten categories, their weights, the closed
vocabularies — live here rather than in the prompt, so the arithmetic closes by
construction instead of by the model's good intentions.
"""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Closed vocabularies
# --------------------------------------------------------------------------- #

Recommendation = Literal["Invest", "Investigate Further", "Pass"]
RiskLevel = Literal["Low", "Low-Medium", "Medium", "Medium-High", "High"]
AssumptionConfidence = Literal[
    "LOW", "LOW-MED", "MEDIUM", "MED-HIGH", "HIGH", "UNKNOWN"
]
RiskCategory = Literal[
    "REGULATORY",
    "FINANCIAL",
    "PRODUCT/CLINICAL",
    "PRODUCT/SCIENCE",
    "COMMERCIAL",
    "EXECUTION",
    "COMPETITIVE",
    "MARKET",
    "TEAM",
    "IP",
]

_RECOMMENDATIONS = ("Invest", "Investigate Further", "Pass")
_RISK_LEVELS = ("Low", "Low-Medium", "Medium", "Medium-High", "High")
_CONFIDENCES = ("LOW", "LOW-MED", "MEDIUM", "MED-HIGH", "HIGH", "UNKNOWN")
_RISK_CATEGORIES = (
    "REGULATORY",
    "FINANCIAL",
    "PRODUCT/CLINICAL",
    "PRODUCT/SCIENCE",
    "COMMERCIAL",
    "EXECUTION",
    "COMPETITIVE",
    "MARKET",
    "TEAM",
    "IP",
)

#: The ten assessment categories, in document order, with their scorecard
#: weights. Weights are fixed here so the weighted total always reconciles.
CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("problem_validation", "Problem Validation", 10),
    ("solution_effectiveness", "Solution Effectiveness", 12),
    ("market_opportunity", "Market Opportunity", 10),
    ("competitive_intelligence", "Competitive Intelligence", 8),
    ("business_model", "Business Model Intelligence", 10),
    ("traction_evidence", "Traction & Evidence Quality", 12),
    ("team_assessment", "Team Assessment", 15),
    ("financial_intelligence", "Financial Intelligence", 10),
    ("risk_intelligence", "Risk Intelligence", 8),
    ("assumption_mapping", "Assumption Mapping", 5),
)

CATEGORY_KEYS = tuple(key for key, _title, _weight in CATEGORIES)
CATEGORY_TITLES = {key: title for key, title, _weight in CATEGORIES}
CATEGORY_WEIGHTS = {key: weight for key, _title, weight in CATEGORIES}

MEMO_FIELDS: tuple[str, ...] = (
    "Company",
    "Recommendation",
    "Decision confidence",
    "Weighted DI score",
    "Funding ask",
    "Strongest element",
    "Central issue",
    "Next step",
    "Decision",
)

NOT_DISCLOSED = "Not disclosed"


_ABBREVIATIONS = {"med": "medium", "mid": "medium", "hi": "high", "lo": "low"}


def _canonical(text: str) -> str:
    """Fold the spellings a model reasonably reaches for onto one form.

    Expansion is done per hyphen-separated part: a substring replace turns
    "low-medium" into "low-mediumium".
    """
    folded = text.strip().lower().replace("/", "-").replace(" to ", "-")
    parts = [part.strip() for part in folded.split("-") if part.strip()]
    return "-".join(_ABBREVIATIONS.get(part, part) for part in parts)


def _normalize(value: Any, options: tuple[str, ...], upper: bool = False) -> Any:
    """Snap a string onto one of `options`, tolerating spelling variants."""
    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    target = _canonical(cleaned)
    for option in options:
        if target == _canonical(option):
            return option
    return cleaned.upper() if upper else cleaned


def _clamp(value: Any, low: float, high: float) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return max(low, min(high, number))


def _clamp_int(value: Any, low: int, high: int) -> Any:
    clamped = _clamp(value, low, high)
    return round(clamped) if isinstance(clamped, float) else clamped


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


class Bullet(_Model):
    """A list item. `adverse` items are set in crimson."""

    text: str
    adverse: bool = False


class SubSection(_Model):
    """An H3 block inside an assessment section."""

    heading: str
    paragraphs: List[str] = Field(default_factory=list)
    bullets: List[Bullet] = Field(default_factory=list)


class Callout(_Model):
    """A shaded panel with an ALL-CAPS title."""

    #: Titles are written in caps by the author; the renderer does not force
    #: case, so a lowercase qualifier inside a title survives.
    title: str
    body: str
    critical: bool = False


class AssessmentSection(_Model):
    score: int = Field(ge=0, le=10)
    subsections: List[SubSection] = Field(default_factory=list)
    callouts: List[Callout] = Field(default_factory=list)
    diligence_questions: List[str] = Field(default_factory=list)

    @field_validator("score", mode="before")
    @classmethod
    def _fix(cls, value: Any) -> Any:
        return _clamp_int(value, 0, 10)


# --------------------------------------------------------------------------- #
# Table rows
# --------------------------------------------------------------------------- #


class MarketSizingRow(_Model):
    layer: str
    as_stated: str = NOT_DISCLOSED
    assessment: str = "—"


class CompetitorRow(_Model):
    competitor: str
    type: str
    why_it_competes: str


class EvidenceRow(_Model):
    evidence: str
    demonstrates: str
    does_not_demonstrate: str


class SensitivityRow(_Model):
    variable: str
    stated: str = "Not stated"
    determined_by: str
    effect_if_adverse: str


class RiskRow(_Model):
    category: RiskCategory
    risk: str
    probability: RiskLevel
    impact: RiskLevel
    mitigation: str

    @field_validator("category", mode="before")
    @classmethod
    def _fix_category(cls, value: Any) -> Any:
        return _normalize(value, _RISK_CATEGORIES, upper=True)

    @field_validator("probability", "impact", mode="before")
    @classmethod
    def _fix_level(cls, value: Any) -> Any:
        return _normalize(value, _RISK_LEVELS)


class AssumptionRow(_Model):
    assumption: str
    evidence: str
    confidence: AssumptionConfidence
    validation: str

    @field_validator("confidence", mode="before")
    @classmethod
    def _fix(cls, value: Any) -> Any:
        return _normalize(value, _CONFIDENCES, upper=True)


class ComparativeRow(_Model):
    company: str
    di_score: str
    confidence: str
    central_issue: str


class MilestoneRow(_Model):
    milestone: str
    why_it_matters: str


class ScorecardRow(_Model):
    """One scorecard line. Weight and the weighted value are computed."""

    category: str
    score: int = Field(ge=0, le=10)
    driver: str

    @field_validator("score", mode="before")
    @classmethod
    def _fix(cls, value: Any) -> Any:
        return _clamp_int(value, 0, 10)

    @property
    def weight(self) -> int:
        return CATEGORY_WEIGHTS.get(self.category, 0)

    @property
    def weighted(self) -> float:
        return round(self.score * self.weight / 100, 2)


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


class Metadata(_Model):
    source_document: str = NOT_DISCLOSED
    analysis_date: str = ""
    company_status: str = NOT_DISCLOSED
    milestone_label: str = "Key milestone"
    milestone_value: str = NOT_DISCLOSED
    regulatory_plan: str = NOT_DISCLOSED
    commercialization: str = NOT_DISCLOSED
    funding_ask: str = NOT_DISCLOSED
    valuation_terms: str = NOT_DISCLOSED
    financials: str = NOT_DISCLOSED
    cap_table_runway: str = NOT_DISCLOSED


class ExecutiveSummary(_Model):
    recommendation_qualifier: str = ""
    confidence_note: str = ""
    key_investment_thesis: List[str] = Field(min_length=1)
    top_strengths: List[str] = Field(min_length=1)
    top_concerns: List[str] = Field(min_length=1)


class Assessment(_Model):
    problem_validation: AssessmentSection
    solution_effectiveness: AssessmentSection
    market_opportunity: AssessmentSection
    competitive_intelligence: AssessmentSection
    business_model: AssessmentSection
    traction_evidence: AssessmentSection
    team_assessment: AssessmentSection
    financial_intelligence: AssessmentSection
    risk_intelligence: AssessmentSection
    assumption_mapping: AssessmentSection

    def section(self, key: str) -> AssessmentSection:
        return getattr(self, key)


class Scenario(_Model):
    probability_pct: int = Field(ge=0, le=100)
    narrative: str = ""
    drivers: List[str] = Field(default_factory=list)
    gross_multiple: str = "—"
    weighted_multiple: float = 0.0

    @field_validator("probability_pct", mode="before")
    @classmethod
    def _fix_pct(cls, value: Any) -> Any:
        return _clamp_int(value, 0, 100)

    @field_validator("weighted_multiple", mode="before")
    @classmethod
    def _fix_weighted(cls, value: Any) -> Any:
        return _clamp(value, 0, 1000)


class Scenarios(_Model):
    best: Scenario
    base: Scenario
    worst: Scenario

    def ordered(self) -> list[tuple[str, Scenario]]:
        return [("Best case", self.best), ("Base case", self.base), ("Worst case", self.worst)]


class CommitteeView(_Model):
    bull_case: str
    bear_case: str
    would_enable_a_decision: List[str] = Field(default_factory=list)
    would_change_the_assessment: List[str] = Field(default_factory=list)


class CompositeIndices(_Model):
    decision_quality: float = Field(ge=0, le=10)
    weighted_interpretation: str = ""
    confidence_interpretation: str = ""
    decision_quality_interpretation: str = ""

    @field_validator("decision_quality", mode="before")
    @classmethod
    def _fix(cls, value: Any) -> Any:
        return _clamp(value, 0, 10)


class FinalRecommendation(_Model):
    how_to_approach: str = ""
    top_five_diligence_questions: List[str] = Field(default_factory=list)
    milestones: List[MilestoneRow] = Field(default_factory=list)
    expected_risk_adjusted_outcome: str = ""


# --------------------------------------------------------------------------- #
# Root
# --------------------------------------------------------------------------- #


class AnalysisResult(_Model):
    """A complete Decision Intelligence Assessment."""

    company_name: str
    one_line_descriptor: str = ""
    metadata: Metadata = Field(default_factory=Metadata)

    recommendation: Recommendation
    confidence_pct: int = Field(ge=0, le=100)
    verdict_paragraph: str = ""
    scoring_fairness_note: str = ""

    executive_summary: ExecutiveSummary
    assessment: Assessment

    market_sizing: List[MarketSizingRow] = Field(default_factory=list)
    competitors: List[CompetitorRow] = Field(default_factory=list)
    evidence_quality: List[EvidenceRow] = Field(default_factory=list)
    sensitivity: List[SensitivityRow] = Field(default_factory=list)
    risk_register: List[RiskRow] = Field(default_factory=list)
    assumptions: List[AssumptionRow] = Field(default_factory=list)

    scenarios: Scenarios
    basis_of_analysis: Optional[Callout] = None
    expected_outcome_callout: Optional[Callout] = None

    committee_view: CommitteeView
    scorecard: List[ScorecardRow] = Field(default_factory=list)
    composite: CompositeIndices
    comparative_context: List[ComparativeRow] = Field(default_factory=list)

    final: FinalRecommendation
    memo: List[str] = Field(default_factory=list)

    @field_validator("recommendation", mode="before")
    @classmethod
    def _fix_recommendation(cls, value: Any) -> Any:
        return _normalize(value, _RECOMMENDATIONS)

    @field_validator("confidence_pct", mode="before")
    @classmethod
    def _fix_confidence(cls, value: Any) -> Any:
        return _clamp_int(value, 0, 100)

    # -- computed ---------------------------------------------------------- #

    def scorecard_rows(self) -> list[ScorecardRow]:
        """Scorecard in canonical order, backfilled from the assessment.

        The model supplies the one-line drivers; scores come from the sections
        themselves so the two can never disagree.
        """
        supplied = {row.category: row for row in self.scorecard}
        rows: list[ScorecardRow] = []
        for key in CATEGORY_KEYS:
            existing = supplied.get(key)
            rows.append(
                ScorecardRow(
                    category=key,
                    score=self.assessment.section(key).score,
                    driver=existing.driver if existing else "",
                )
            )
        return rows

    @property
    def weighted_overall(self) -> float:
        """Weighted total, computed — never taken from the model."""
        return round(sum(row.weighted for row in self.scorecard_rows()), 2)

    @property
    def memo_rows(self) -> list[tuple[str, str]]:
        values = list(self.memo) + [""] * len(MEMO_FIELDS)
        return list(zip(MEMO_FIELDS, values[: len(MEMO_FIELDS)]))

    def scenario_table(self) -> list[tuple[str, str, str, str, str]]:
        """Scenario rows with a running cumulative column."""
        rows = []
        cumulative = 0.0
        for label, scenario in self.scenarios.ordered():
            cumulative += scenario.weighted_multiple
            rows.append(
                (
                    label,
                    f"{scenario.probability_pct}%",
                    scenario.gross_multiple,
                    f"{scenario.weighted_multiple:.2f}x",
                    f"{cumulative:.2f}x",
                )
            )
        return rows
