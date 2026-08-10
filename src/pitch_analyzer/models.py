"""Pydantic models for the Decision Intelligence analysis schema.

Everything else in the package depends on these definitions. The shapes here
mirror the JSON schema embedded in the analysis prompt (see `analyze.py`)
exactly; the validators exist only to absorb harmless LLM formatting variance
(case, out-of-range numbers) rather than to reshape the contract.
"""

from __future__ import annotations

from typing import Any, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Recommendation = Literal["Invest", "Investigate Further", "Pass"]
Confidence = Literal["Low", "Medium", "High"]
RiskCategory = Literal[
    "Market", "Product", "Execution", "Financial", "Regulatory", "Competitive"
]

_RECOMMENDATIONS = ("Invest", "Investigate Further", "Pass")
_LEVELS = ("Low", "Medium", "High")
_RISK_CATEGORIES = (
    "Market",
    "Product",
    "Execution",
    "Financial",
    "Regulatory",
    "Competitive",
)


def _normalize_choice(value: Any, options: tuple[str, ...], default: str) -> Any:
    """Case-insensitively snap a string onto one of `options`.

    Anything unrecognised is passed through untouched so Pydantic reports a
    real validation error instead of silently mislabelling the analysis.
    """
    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    for option in options:
        if cleaned.lower() == option.lower():
            return option
    return cleaned or default


def _clamp_number(value: Any, low: float, high: float) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return max(low, min(high, number))


class ExecutiveSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recommendation: Recommendation
    confidence_pct: int = Field(ge=0, le=100)
    investment_thesis: str
    top_strengths: List[str] = Field(min_length=1)
    top_concerns: List[str] = Field(min_length=1)

    @field_validator("recommendation", mode="before")
    @classmethod
    def _fix_recommendation(cls, value: Any) -> Any:
        return _normalize_choice(value, _RECOMMENDATIONS, "Investigate Further")

    @field_validator("confidence_pct", mode="before")
    @classmethod
    def _fix_confidence(cls, value: Any) -> Any:
        clamped = _clamp_number(value, 0, 100)
        return round(clamped) if isinstance(clamped, float) else clamped


class Scores(BaseModel):
    model_config = ConfigDict(extra="ignore")

    problem_validation: int = Field(ge=0, le=10)
    solution_strength: int = Field(ge=0, le=10)
    market_opportunity: int = Field(ge=0, le=10)
    competitive_position: int = Field(ge=0, le=10)
    business_model: int = Field(ge=0, le=10)
    traction: int = Field(ge=0, le=10)
    team: int = Field(ge=0, le=10)
    financial_quality: int = Field(ge=0, le=10)
    risk_profile: int = Field(ge=0, le=10)
    investment_attractiveness: int = Field(ge=0, le=10)
    weighted_overall: float = Field(ge=0, le=10)
    decision_quality: float = Field(ge=0, le=10)

    @field_validator(
        "problem_validation",
        "solution_strength",
        "market_opportunity",
        "competitive_position",
        "business_model",
        "traction",
        "team",
        "financial_quality",
        "risk_profile",
        "investment_attractiveness",
        mode="before",
    )
    @classmethod
    def _fix_category_score(cls, value: Any) -> Any:
        clamped = _clamp_number(value, 0, 10)
        return round(clamped) if isinstance(clamped, float) else clamped

    @field_validator("weighted_overall", "decision_quality", mode="before")
    @classmethod
    def _fix_aggregate_score(cls, value: Any) -> Any:
        return _clamp_number(value, 0, 10)

    def category_rows(self) -> list[tuple[str, int]]:
        """The 10 category scores, in scorecard display order."""
        return [
            ("Problem Validation", self.problem_validation),
            ("Solution Strength", self.solution_strength),
            ("Market Opportunity", self.market_opportunity),
            ("Competitive Position", self.competitive_position),
            ("Business Model", self.business_model),
            ("Traction", self.traction),
            ("Team", self.team),
            ("Financial Quality", self.financial_quality),
            ("Risk Profile", self.risk_profile),
            ("Investment Attract.", self.investment_attractiveness),
        ]


class Section(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: int = Field(ge=0, le=10)
    observations: str
    missing: str
    questions: List[str] = Field(default_factory=list)

    @field_validator("score", mode="before")
    @classmethod
    def _fix_score(cls, value: Any) -> Any:
        clamped = _clamp_number(value, 0, 10)
        return round(clamped) if isinstance(clamped, float) else clamped


class Sections(BaseModel):
    model_config = ConfigDict(extra="ignore")

    problem_validation: Section
    solution_effectiveness: Section
    market_opportunity: Section
    competitive_intelligence: Section
    business_model: Section
    traction_evidence: Section
    team_assessment: Section
    financial_intelligence: Section


class Risk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: RiskCategory
    description: str
    probability: Confidence
    impact: Confidence
    mitigation: str

    @field_validator("category", mode="before")
    @classmethod
    def _fix_category(cls, value: Any) -> Any:
        return _normalize_choice(value, _RISK_CATEGORIES, "Execution")

    @field_validator("probability", "impact", mode="before")
    @classmethod
    def _fix_level(cls, value: Any) -> Any:
        return _normalize_choice(value, _LEVELS, "Medium")


class Assumption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assumption: str
    evidence: str
    confidence: Confidence
    validation: str

    @field_validator("confidence", mode="before")
    @classmethod
    def _fix_confidence(cls, value: Any) -> Any:
        return _normalize_choice(value, _LEVELS, "Medium")


class Scenario(BaseModel):
    model_config = ConfigDict(extra="ignore")

    probability_pct: int = Field(ge=0, le=100)
    drivers: List[str] = Field(default_factory=list)

    @field_validator("probability_pct", mode="before")
    @classmethod
    def _fix_probability(cls, value: Any) -> Any:
        clamped = _clamp_number(value, 0, 100)
        return round(clamped) if isinstance(clamped, float) else clamped


class Scenarios(BaseModel):
    model_config = ConfigDict(extra="ignore")

    best: Scenario
    base: Scenario
    worst: Scenario


class AnalysisResult(BaseModel):
    """The complete Decision Intelligence analysis returned by the model."""

    model_config = ConfigDict(extra="ignore")

    executive_summary: ExecutiveSummary
    scores: Scores
    sections: Sections
    risks: List[Risk] = Field(default_factory=list)
    assumptions: List[Assumption] = Field(default_factory=list)
    scenarios: Scenarios
    bull_case: str
    bear_case: str
    missing_information: List[str] = Field(default_factory=list)
    top_diligence_questions: List[str] = Field(default_factory=list)
    key_milestones_before_investment: List[str] = Field(default_factory=list)
    expected_risk_adjusted_outcome: str
