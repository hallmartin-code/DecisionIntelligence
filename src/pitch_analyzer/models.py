"""Pydantic schema for the Decision Intelligence Assessment.

Mirrors `templates/report_structure.md`. Structural constants that the document
must get right — the ten categories, the stage weight profiles, the closed
vocabularies — live here rather than in the prompt, so the arithmetic closes by
construction instead of by the model's good intentions. The model reports which
stage the company is at; it does not get to pick the weights that follow.
"""

from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Closed vocabularies
# --------------------------------------------------------------------------- #

Recommendation = Literal["Invest", "Investigate Further", "Pass"]
RiskLevel = Literal["Low", "Low-Medium", "Medium", "Medium-High", "High"]
#: Where the company stands on the two gates that decide the weighting.
#: "Unknown" is a real answer: a source that does not say must not be guessed
#: into a profile that changes the score.
RevenueStage = Literal["Pre-revenue", "Post-revenue", "Unknown"]
RegulatoryStage = Literal[
    "Pre-approval", "Post-approval", "Not applicable", "Unknown"
]
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
#: Spellings a model reasonably reaches for, keyed by slug. Anything not here
#: becomes "Unknown", which selects the balanced profile and changes nothing.
_REVENUE_BY_SLUG = {
    "pre-revenue": "Pre-revenue",
    "prerevenue": "Pre-revenue",
    "no-revenue": "Pre-revenue",
    "zero-revenue": "Pre-revenue",
    "pre-commercial": "Pre-revenue",
    "precommercial": "Pre-revenue",
    "development-stage": "Pre-revenue",
    "post-revenue": "Post-revenue",
    "postrevenue": "Post-revenue",
    "revenue": "Post-revenue",
    "revenue-generating": "Post-revenue",
    "generating-revenue": "Post-revenue",
    "commercial": "Post-revenue",
    "commercial-stage": "Post-revenue",
    "commercialized": "Post-revenue",
}

_REGULATORY_BY_SLUG = {
    "pre-approval": "Pre-approval",
    "preapproval": "Pre-approval",
    "pre-fda": "Pre-approval",
    "prefda": "Pre-approval",
    "not-approved": "Pre-approval",
    "unapproved": "Pre-approval",
    "pre-clearance": "Pre-approval",
    "clinical": "Pre-approval",
    "clinical-stage": "Pre-approval",
    "preclinical": "Pre-approval",
    "investigational": "Pre-approval",
    "post-approval": "Post-approval",
    "postapproval": "Post-approval",
    "post-fda": "Post-approval",
    "postfda": "Post-approval",
    "approved": "Post-approval",
    "fda-approved": "Post-approval",
    "cleared": "Post-approval",
    "fda-cleared": "Post-approval",
    "510-k-cleared": "Post-approval",
    "de-novo": "Post-approval",
    "not-applicable": "Not applicable",
    "na": "Not applicable",
    "n-a": "Not applicable",
    "none": "Not applicable",
    "not-regulated": "Not applicable",
    "unregulated": "Not applicable",
    "no-fda-pathway": "Not applicable",
}

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

#: The ten assessment categories, in document order. The weights live in
#: WEIGHT_PROFILES, because which categories carry a decision depends on how
#: far the company has actually got.
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("problem_validation", "Problem Validation"),
    ("solution_effectiveness", "Solution Effectiveness"),
    ("market_opportunity", "Market Opportunity"),
    ("competitive_intelligence", "Competitive Intelligence"),
    ("business_model", "Business Model Intelligence"),
    ("traction_evidence", "Traction & Evidence Quality"),
    ("team_assessment", "Team Assessment"),
    ("financial_intelligence", "Financial Intelligence"),
    ("risk_intelligence", "Risk Intelligence"),
    ("assumption_mapping", "Assumption Mapping"),
)

CATEGORY_KEYS = tuple(key for key, _title in CATEGORIES)
CATEGORY_TITLES = {key: title for key, title in CATEGORIES}

#: Scorecard weights per stage profile. Every profile sums to 100, so the
#: weighted total stays on the same 0-10 scale whichever one is chosen and two
#: companies remain comparable. Fixed here rather than asked of the model, so
#: the arithmetic closes by construction.
#:
#: `balanced` is the original weighting and the answer when the stage cannot be
#: established from the source.
#:
#: `foundation` is for a company with nothing to show yet: pre-revenue and
#: pre-approval. There is no traction to weigh, so weighing it heavily just
#: scores the absence twice — the prompt already records it. What can be
#: judged is who is doing this (team) and whether anyone else could (IP and
#: defensibility, which live in Competitive Intelligence).
#:
#: `traction` is for a company past both gates. Once there are customers and a
#: clearance, the market has answered questions the deck can only assert:
#: whether the problem is real, whether the thing works, whether anyone buys
#: it. Evidence outranks argument, so traction roughly doubles and the
#: narrative categories give way to it.
WEIGHT_PROFILES: dict[str, dict[str, int]] = {
    "balanced": {
        "problem_validation": 10,
        "solution_effectiveness": 12,
        "market_opportunity": 10,
        "competitive_intelligence": 8,
        "business_model": 10,
        "traction_evidence": 12,
        "team_assessment": 15,
        "financial_intelligence": 10,
        "risk_intelligence": 8,
        "assumption_mapping": 5,
    },
    "foundation": {
        "problem_validation": 10,
        "solution_effectiveness": 13,
        "market_opportunity": 9,
        "competitive_intelligence": 13,
        "business_model": 7,
        "traction_evidence": 6,
        "team_assessment": 22,
        "financial_intelligence": 6,
        "risk_intelligence": 8,
        "assumption_mapping": 6,
    },
    "traction": {
        "problem_validation": 7,
        "solution_effectiveness": 9,
        "market_opportunity": 9,
        "competitive_intelligence": 8,
        "business_model": 12,
        "traction_evidence": 24,
        "team_assessment": 11,
        "financial_intelligence": 12,
        "risk_intelligence": 5,
        "assumption_mapping": 3,
    },
}

#: How each profile is described in the report, so a reader can see why the
#: weights are what they are without consulting this file.
PROFILE_NAMES: dict[str, str] = {
    "balanced": "Balanced",
    "foundation": "Foundation-weighted",
    "traction": "Traction-weighted",
}

PROFILE_RATIONALES: dict[str, str] = {
    "balanced": (
        "No stage weighting was applied. The company sits across the two "
        "profiles, or the source does not establish where it stands, so the "
        "standard weights are used and no category is emphasised over another "
        "on the basis of an assumption."
    ),
    "foundation": (
        "Nothing is being sold yet and no regulatory gate has been cleared, so "
        "there is little traction to weigh and weighting it heavily would "
        "score the same absence twice. Team Assessment and Competitive "
        "Intelligence — which carries the intellectual property and "
        "defensibility analysis — are weighted most heavily instead, "
        "because at this stage they are what can actually be judged."
    ),
    "traction": (
        "This company is selling, with no regulatory gate left in front of it, "
        "so the market has already answered questions a deck can only assert. "
        "Traction & Evidence Quality is weighted most heavily, and the "
        "narrative categories give way to it: demonstrated performance "
        "outranks argument once there is performance to demonstrate."
    ),
}

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

#: Whole-phrase synonyms for the risk scale, keyed by slug. A model reaching
#: for "Very High" means the top of this scale, and rejecting it costs a second
#: full generation. Only intensity restatements belong here: anything that
#: carries different information must still fail rather than be guessed at.
_RISK_LEVEL_SYNONYMS = {
    "very-low": "Low",
    "negligible": "Low",
    "minimal": "Low",
    "very-high": "High",
    "extreme": "High",
    "critical": "High",
    "severe": "High",
    "moderate": "Medium",
}


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


def _slug(text: str) -> str:
    """Lowercase, with every run of non-alphanumerics collapsed to a hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-")


def _snap(value: Any, table: dict[str, str], fallback: str) -> Any:
    """Map a free-text stage onto a known value, or admit it is unknown."""
    if not isinstance(value, str):
        return value
    return table.get(_slug(value), fallback)


def profile_for(revenue: str, regulatory: str) -> str:
    """Choose the weighting from the two gates.

    Only the two unambiguous corners get a stage weighting. A company that is
    post-revenue but pre-approval, or approved but not yet selling, sits
    between the profiles, and picking one would apply a heavier weight on the
    strength of a guess. "Not applicable" counts with whichever side revenue is
    on, so an unregulated business is still weighted by how far it has got.
    """
    if revenue == "Post-revenue" and regulatory in ("Post-approval", "Not applicable"):
        return "traction"
    if revenue == "Pre-revenue" and regulatory in ("Pre-approval", "Not applicable"):
        return "foundation"
    return "balanced"


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
        if isinstance(value, str):
            synonym = _RISK_LEVEL_SYNONYMS.get(_slug(value))
            if synonym:
                return synonym
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
    """One scorecard line. The weighted value is computed.

    `weight` is filled in by `AnalysisResult.scorecard_rows()` from the stage
    profile, not supplied by the model and not fixed per category — which
    weighting applies depends on the company, so it cannot live on the row.
    """

    category: str
    score: int = Field(ge=0, le=10)
    driver: str
    weight: int = 0

    @field_validator("score", mode="before")
    @classmethod
    def _fix(cls, value: Any) -> Any:
        return _clamp_int(value, 0, 10)

    @property
    def weighted(self) -> float:
        return round(self.score * self.weight / 100, 2)


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


class CompanyStage(_Model):
    """Where the company stands on the two gates that set the weighting.

    The classification is the model's — it is a reading of the source — but the
    weights it selects are not, so a misreading changes the emphasis and never
    the arithmetic.
    """

    revenue: RevenueStage = "Unknown"
    regulatory: RegulatoryStage = "Unknown"
    basis: str = ""

    @field_validator("revenue", mode="before")
    @classmethod
    def _fix_revenue(cls, value: Any) -> Any:
        return _snap(value, _REVENUE_BY_SLUG, "Unknown")

    @field_validator("regulatory", mode="before")
    @classmethod
    def _fix_regulatory(cls, value: Any) -> Any:
        return _snap(value, _REGULATORY_BY_SLUG, "Unknown")

    @property
    def profile(self) -> str:
        return profile_for(self.revenue, self.regulatory)

    @property
    def label(self) -> str:
        """The profile, qualified by the stage actually found in the source."""
        name = PROFILE_NAMES[self.profile]
        if self.profile == "balanced":
            return name
        summary = self.summary
        return f"{name} ({summary[0].lower()}{summary[1:]})"

    @property
    def rationale(self) -> str:
        return PROFILE_RATIONALES[self.profile]

    @property
    def summary(self) -> str:
        """One line naming the two gates, for the report header."""
        if self.revenue == "Unknown":
            revenue = "Revenue stage not established"
        else:
            revenue = self.revenue
        if self.regulatory == "Unknown":
            regulatory = "regulatory stage not established"
        elif self.regulatory == "Not applicable":
            regulatory = "no regulatory gate"
        else:
            regulatory = self.regulatory.lower()
        return f"{revenue}, {regulatory}"


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
    #: Drives the scorecard weighting. Defaults to Unknown, which is the
    #: balanced profile, so an older payload scores exactly as before.
    stage: CompanyStage = Field(default_factory=CompanyStage)

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
        weights = self.weights
        rows: list[ScorecardRow] = []
        for key in CATEGORY_KEYS:
            existing = supplied.get(key)
            rows.append(
                ScorecardRow(
                    category=key,
                    score=self.assessment.section(key).score,
                    driver=existing.driver if existing else "",
                    weight=weights[key],
                )
            )
        return rows

    @property
    def weight_profile(self) -> str:
        """Which stage weighting applies — derived, never taken from the model."""
        return self.stage.profile

    @property
    def weights(self) -> dict[str, int]:
        return WEIGHT_PROFILES[self.weight_profile]

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
