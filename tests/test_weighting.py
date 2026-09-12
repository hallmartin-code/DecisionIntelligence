"""Stage-dependent scorecard weighting.

The model classifies the company; the code picks the weights. That split is the
point of these tests: a misread stage must be able to change the emphasis of a
report and never the arithmetic underneath it.
"""

from __future__ import annotations

import copy

import pytest

from pitch_analyzer.models import (
    CATEGORY_KEYS,
    PROFILE_LABELS,
    WEIGHT_PROFILES,
    AnalysisResult,
    CompanyStage,
    profile_for,
)


def _with_stage(payload: dict, revenue: str, regulatory: str, basis: str = "") -> dict:
    payload = copy.deepcopy(payload)
    payload["stage"] = {
        "revenue": revenue,
        "regulatory": regulatory,
        "basis": basis,
    }
    return payload


# --------------------------------------------------------------------------- #
# Which profile applies
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "revenue,regulatory,expected",
    [
        # The two corners the weighting exists for.
        ("Pre-revenue", "Pre-approval", "foundation"),
        ("Post-revenue", "Post-approval", "traction"),
        # No regulatory gate: revenue alone decides how far it has got.
        ("Pre-revenue", "Not applicable", "foundation"),
        ("Post-revenue", "Not applicable", "traction"),
        # Between the two. Picking a profile here would weight on a guess.
        ("Post-revenue", "Pre-approval", "balanced"),
        ("Pre-revenue", "Post-approval", "balanced"),
        # Not established by the source.
        ("Unknown", "Unknown", "balanced"),
        ("Pre-revenue", "Unknown", "balanced"),
        ("Unknown", "Post-approval", "balanced"),
    ],
)
def test_profile_selection(revenue, regulatory, expected) -> None:
    assert profile_for(revenue, regulatory) == expected


@pytest.mark.parametrize(
    "written,revenue",
    [
        ("Pre-revenue", "Pre-revenue"),
        ("pre revenue", "Pre-revenue"),
        ("PRE-REVENUE", "Pre-revenue"),
        ("no revenue", "Pre-revenue"),
        ("pre-commercial", "Pre-revenue"),
        ("Post-revenue", "Post-revenue"),
        ("post revenue", "Post-revenue"),
        ("revenue-generating", "Post-revenue"),
        ("commercial stage", "Post-revenue"),
        ("something else entirely", "Unknown"),
    ],
)
def test_revenue_spellings_are_folded(written, revenue) -> None:
    assert CompanyStage(revenue=written).revenue == revenue


@pytest.mark.parametrize(
    "written,regulatory",
    [
        ("Pre-approval", "Pre-approval"),
        ("pre-FDA", "Pre-approval"),
        ("clinical stage", "Pre-approval"),
        ("Post-approval", "Post-approval"),
        ("post-FDA", "Post-approval"),
        ("FDA approved", "Post-approval"),
        ("510(k) cleared", "Post-approval"),
        ("N/A", "Not applicable"),
        ("not applicable", "Not applicable"),
        ("who knows", "Unknown"),
    ],
)
def test_regulatory_spellings_are_folded(written, regulatory) -> None:
    assert CompanyStage(regulatory=written).regulatory == regulatory


# --------------------------------------------------------------------------- #
# What the weighting does to the score
# --------------------------------------------------------------------------- #


def test_the_weighting_moves_the_score_in_the_intended_direction(
    analysis_payload,
) -> None:
    """The fixture scores team 8 and traction 4 — strong people, thin evidence.

    Foundation weighting should reward that profile and traction weighting
    should penalise it. If both produced the same number the feature would be
    doing nothing.
    """
    foundation = AnalysisResult.model_validate(
        _with_stage(analysis_payload, "Pre-revenue", "Pre-approval")
    )
    traction = AnalysisResult.model_validate(
        _with_stage(analysis_payload, "Post-revenue", "Post-approval")
    )
    balanced = AnalysisResult.model_validate(copy.deepcopy(analysis_payload))

    assert foundation.weighted_overall > balanced.weighted_overall
    assert traction.weighted_overall < balanced.weighted_overall


def test_a_traction_heavy_company_is_rewarded_by_the_traction_profile(
    analysis_payload,
) -> None:
    """The mirror image: weak team, strong traction reverses the ordering, so
    the effect follows the scores rather than being a constant offset."""
    payload = copy.deepcopy(analysis_payload)
    payload["assessment"]["team_assessment"]["score"] = 3
    payload["assessment"]["traction_evidence"]["score"] = 9

    foundation = AnalysisResult.model_validate(
        _with_stage(payload, "Pre-revenue", "Pre-approval")
    )
    traction = AnalysisResult.model_validate(
        _with_stage(payload, "Post-revenue", "Post-approval")
    )

    assert traction.weighted_overall > foundation.weighted_overall


@pytest.mark.parametrize("profile", sorted(WEIGHT_PROFILES))
def test_the_score_stays_on_a_ten_point_scale(analysis_payload, profile) -> None:
    """Comparability across stages depends on this: a perfect company scores 10
    under every profile, not 10 under one and 8.7 under another."""
    payload = copy.deepcopy(analysis_payload)
    for key in CATEGORY_KEYS:
        payload["assessment"][key]["score"] = 10
    stage = {
        "foundation": ("Pre-revenue", "Pre-approval"),
        "traction": ("Post-revenue", "Post-approval"),
        "balanced": ("Unknown", "Unknown"),
    }[profile]

    analysis = AnalysisResult.model_validate(_with_stage(payload, *stage))

    assert analysis.weight_profile == profile
    assert analysis.weighted_overall == pytest.approx(10.0)


def test_the_weights_on_the_rows_match_the_chosen_profile(analysis_payload) -> None:
    analysis = AnalysisResult.model_validate(
        _with_stage(analysis_payload, "Post-revenue", "Post-approval")
    )
    rows = {row.category: row.weight for row in analysis.scorecard_rows()}

    assert rows == WEIGHT_PROFILES["traction"]
    assert sum(rows.values()) == 100


def test_the_model_cannot_set_its_own_weights(analysis_payload) -> None:
    """A weight supplied in the response is ignored, like the scores are."""
    payload = _with_stage(analysis_payload, "Pre-revenue", "Pre-approval")
    for row in payload["scorecard"]:
        row["weight"] = 99

    analysis = AnalysisResult.model_validate(payload)

    assert all(
        row.weight == WEIGHT_PROFILES["foundation"][row.category]
        for row in analysis.scorecard_rows()
    )


def test_a_payload_without_a_stage_scores_exactly_as_before(analysis_payload) -> None:
    """Backward compatibility: the balanced profile is the original weighting."""
    analysis = AnalysisResult.model_validate(copy.deepcopy(analysis_payload))

    assert "stage" not in analysis_payload
    assert analysis.weight_profile == "balanced"
    assert analysis.weighted_overall == pytest.approx(4.59)


# --------------------------------------------------------------------------- #
# What the report says about it
# --------------------------------------------------------------------------- #


def test_each_profile_is_explained_in_the_report(analysis_payload) -> None:
    for profile in WEIGHT_PROFILES:
        assert profile in PROFILE_LABELS
    analysis = AnalysisResult.model_validate(
        _with_stage(analysis_payload, "Pre-revenue", "Pre-approval", "Slide 9.")
    )
    assert analysis.stage.label == PROFILE_LABELS["foundation"]
    assert "Team Assessment" in analysis.stage.rationale
    assert "intellectual property" in analysis.stage.rationale


@pytest.mark.parametrize(
    "revenue,regulatory,expected",
    [
        ("Pre-revenue", "Pre-approval", "Pre-revenue, pre-approval"),
        ("Post-revenue", "Not applicable", "Post-revenue, no regulatory gate"),
        ("Unknown", "Unknown",
         "Revenue stage not established, regulatory stage not established"),
    ],
)
def test_the_stage_summary_reads_as_a_sentence(revenue, regulatory, expected) -> None:
    assert CompanyStage(revenue=revenue, regulatory=regulatory).summary == expected


def test_the_weighting_is_stated_in_the_document(analysis_payload, tmp_path) -> None:
    """The scorecard's numbers are unreadable without it."""
    import docx

    from pitch_analyzer.render import render_report

    analysis = AnalysisResult.model_validate(
        _with_stage(
            analysis_payload,
            "Post-revenue",
            "Post-approval",
            "Slide 7 shows $1.4M ARR; slide 11 shows 510(k) clearance.",
        )
    )
    destination = tmp_path / "report.docx"
    render_report(analysis, destination)

    text = "\n".join(p.text for p in docx.Document(destination).paragraphs)
    assert PROFILE_LABELS["traction"] in text
    assert "Post-revenue, post-approval" in text
    assert "510(k) clearance" in text
    assert "Traction & Evidence Quality is weighted most heavily" in text


@pytest.mark.parametrize(
    "document,title_column",
    [("templates/report_structure.md", 1), ("README.md", 0)],
)
def test_the_documented_weights_match_the_code(document, title_column) -> None:
    """Both documents restate the weights for a human reader.

    Three copies of the same numbers drift, and the drifting copy is always the
    prose, so each table is parsed and compared rather than trusted.
    """
    import re
    from pathlib import Path

    from pitch_analyzer.models import CATEGORY_TITLES

    path = Path(__file__).resolve().parents[1] / document
    by_title = {title: key for key, title in CATEGORY_TITLES.items()}
    columns = ("balanced", "foundation", "traction")
    documented: dict[str, dict[str, int]] = {name: {} for name in columns}

    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip().strip("*") for cell in line.split("|")[1:-1]]
        if len(cells) != title_column + 4:
            continue
        key = by_title.get(cells[title_column])
        if key is None:
            continue
        for name, cell in zip(columns, cells[title_column + 1:]):
            if not re.fullmatch(r"\d+%", cell):
                break
            documented[name][key] = int(cell.rstrip("%"))

    for name in columns:
        assert documented[name] == WEIGHT_PROFILES[name], (
            f"{document} disagrees with WEIGHT_PROFILES[{name!r}] — "
            "update the table in the document."
        )


def test_the_email_names_the_weighting(analysis_payload, tmp_path) -> None:
    """The score in the email depends on a weighting the reader cannot infer."""
    from pitch_analyzer.notify import EmailConfig, build_message

    analysis = AnalysisResult.model_validate(
        _with_stage(analysis_payload, "Post-revenue", "Post-approval")
    )
    report = tmp_path / "report.docx"
    report.write_bytes(b"not a real docx; only its size is read here")
    message = build_message(
        EmailConfig(api_key="x", recipients=("a@b.c",), sender="TEN <d@e.f>"),
        analysis,
        report,
        company_name="Acme",
        deck_filename="acme.pdf",
        model="claude-sonnet-4-5",
        slide_count=10,
    )

    label = PROFILE_LABELS["traction"]
    assert label in message["text"]
    assert label in message["html"]
