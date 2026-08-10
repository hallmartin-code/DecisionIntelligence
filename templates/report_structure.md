# Decision Intelligence One-Pager — Document Structure Template

The canonical structure for every report the app generates. It defines the
page, the bands, the fields in each band, and the constraints on those fields.
No company data appears here — only placeholders and allowed value sets.

Placeholders use `{{ field_name }}` and map to the analysis schema in
`src/pitch_analyzer/models.py`. Rendering is implemented in
`src/pitch_analyzer/render.py`.

A rendered, placeholder-filled version of this template is at
[`report_template.pdf`](report_template.pdf) — regenerate it with
`python templates/make_report_template.py`.

---

## 1. Page setup

| Property | Value |
|---|---|
| Page size | US Letter (8.5 × 11 in) |
| Orientation | `landscape` (default, 792 × 612 pt) or `portrait` (612 × 792 pt) |
| Page count | Exactly 1 — never more, never fewer |
| Margin | 22 pt on all sides |
| Column gutter | 10 pt |
| Font family | Helvetica / Helvetica-Bold (ReportLab built-in; no external fonts) |
| Body type size | 8.0 pt preferred, stepping down by 0.5 pt to a 5.5 pt floor |
| File size | Under 2 MB |

### Colour tokens

| Token | Hex | Used for |
|---|---|---|
| Ink | `#111827` | Headings, values |
| Body | `#1f2937` | Body copy |
| Muted | `#6b7280` | Secondary notes, footer line |
| Rule | `#d1d5db` | Dividers, table lines |
| Track | `#e5e7eb` | Unfilled bar track |
| Panel | `#f3f4f6` | Table header fill |
| Green | `#16a34a` | Invest, strengths, bull case, Low risk level |
| Amber | `#d97706` | Investigate Further, Medium risk level |
| Red | `#dc2626` | Pass, concerns, bear case, High risk level |

---

## 2. Band structure

The page is five bands stacked top to bottom. Leftover vertical space is shared
between bands (up to 20 pt each) so the page reads as composed rather than
top-heavy.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ BAND 1  HEADER          {{ company_name }} · date · recommendation badge │
├──────────────────┬───────────────────────────┬──────────────────────────┤
│ BAND 2a          │ BAND 2b                   │ BAND 2c                  │
│ SCORECARD        │ EXECUTIVE SUMMARY         │ SCENARIOS                │
│ (29% width)      │ (42% width)               │ (remaining width)        │
├──────────────────┴───────────────────────────┴──────────────────────────┤
│ BAND 3  TOP RISKS                    Risk · Prob/Impact · Mitigation     │
├─────────────────────────────────────────────────────────────────────────┤
│ BAND 4  TOP 5 DILIGENCE QUESTIONS                                        │
├─────────────────────────────────────────────────────────────────────────┤
│ BAND 5  FOOTER          Bull case · Bear case · attribution line         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Band 1 — Header

| Element | Placeholder | Source | Format |
|---|---|---|---|
| Company name | `{{ company_name }}` | Inferred from the deck title slide | Bold, body size + 6 pt, clipped at 60 chars |
| Subtitle | `Decision Intelligence Analysis · {{ report_date }}` | Run date | Muted, body size, date as `DD Month YYYY` |
| Badge | `{{ recommendation }} · {{ confidence_pct }}% CONF.` | `executive_summary` | Uppercase, white on a filled rounded rect, right-aligned |
| Logo | *(optional)* | `--logo PATH` | Left of the company name, scaled to badge height |
| Rule | — | — | 0.7 pt hairline beneath the band |

**Badge colour is determined by recommendation and must not vary:**

| `{{ recommendation }}` | Badge fill |
|---|---|
| `Invest` | Green `#16a34a` |
| `Investigate Further` | Amber `#d97706` |
| `Pass` | Red `#dc2626` |

---

## 4. Band 2a — Scorecard

A fixed list of **exactly 10 category scores**, always in this order, always all
present. Each row is `label · gradient bar · numeric value`.

| # | Row label | Schema field |
|---|---|---|
| 1 | Problem Validation | `scores.problem_validation` |
| 2 | Solution Strength | `scores.solution_strength` |
| 3 | Market Opportunity | `scores.market_opportunity` |
| 4 | Competitive Position | `scores.competitive_position` |
| 5 | Business Model | `scores.business_model` |
| 6 | Traction | `scores.traction` |
| 7 | Team | `scores.team` |
| 8 | Financial Quality | `scores.financial_quality` |
| 9 | Risk Profile | `scores.risk_profile` |
| 10 | Investment Attract. | `scores.investment_attractiveness` |

- **Value range:** integer `0`–`10`.
- **Bar fill:** proportional to score, coloured on a continuous red → amber →
  green ramp (red at 0, amber at 5, green at 10).
- **Summary line** beneath the bars:
  `Weighted overall {{ weighted_overall }}/10 · Decision quality {{ decision_quality }}/10`
  — both floats `0.0`–`10.0`, rendered to one decimal.

---

## 5. Band 2b — Executive summary

| Element | Placeholder | Constraint |
|---|---|---|
| Heading | `EXECUTIVE SUMMARY` | Fixed |
| Thesis | `{{ investment_thesis }}` | Free text, budget 520 chars |
| Sub-heading | `STRENGTHS` | Fixed |
| Strengths | `{{ top_strength_1 }}` … `{{ top_strength_3 }}` | Exactly 3 rendered, green square bullet, 210 chars each |
| Sub-heading | `CONCERNS` | Fixed |
| Concerns | `{{ top_concern_1 }}` … `{{ top_concern_3 }}` | Exactly 3 rendered, red square bullet, 210 chars each |

---

## 6. Band 2c — Scenarios

Exactly three scenario rows, always in this order.

| Row | Schema field | Bar colour |
|---|---|---|
| `Best` | `scenarios.best` | Green |
| `Base` | `scenarios.base` | Amber |
| `Worst` | `scenarios.worst` | Red |

Each row renders as:

```
{{ scenario_name }}   [====== bar ======]   {{ probability_pct }}%
· {{ driver_1 }}  · {{ driver_2 }}
```

- `probability_pct` — integer `0`–`100`. The three values are expected to total
  100 but are **not** normalised by the renderer.
- Up to **2 drivers** per scenario, 120 chars each.

Closing line for the band:

```
Expected outcome. {{ expected_risk_adjusted_outcome }}
```
— budget 260 chars.

---

## 7. Band 3 — Top risks

A three-column table with a fixed header row.

| Column | Width | Placeholder | Constraint |
|---|---|---|---|
| `Risk` | 44% | `{{ risk_category }}. {{ risk_description }}` | Category bold, description 190 chars |
| `Prob / Impact` | 13% | `{{ probability }} / {{ impact }}` | Centred, each word coloured by level |
| `Mitigation` | 43% | `{{ mitigation }}` | 190 chars |

**Allowed values**

- `risk_category` — `Market` · `Product` · `Execution` · `Financial` ·
  `Regulatory` · `Competitive`
- `probability`, `impact` — `Low` (green) · `Medium` (amber) · `High` (red)

**Row cap.** A maximum of **4 rows** is rendered. Any remainder must be
disclosed, never dropped silently:

```
{{ n }} further risks identified — see the full analysis.
```

---

## 8. Band 4 — Top 5 diligence questions

| Element | Placeholder | Constraint |
|---|---|---|
| Heading | `TOP 5 DILIGENCE QUESTIONS` | Fixed |
| Items | `1.` … `5.` `{{ diligence_question_n }}` | Max 5, numbered, 240 chars each |

If the analysis returns none, render `None specified.` rather than an empty band.

---

## 9. Band 5 — Footer

Two equal columns above a single attribution line, separated from Band 4 by a
0.7 pt rule.

| Element | Placeholder | Constraint |
|---|---|---|
| Left column | `BULL CASE` (green label) + `{{ bull_case }}` | 420 chars |
| Right column | `BEAR CASE` (red label) + `{{ bear_case }}` | 420 chars |
| Attribution | `Recommendation: {{ recommendation }} · Confidence: {{ confidence_pct }}% · Generated by TEN Capital Decision Intelligence · {{ report_date_iso }}` | Muted; `report_date_iso` as `YYYY-MM-DD` |

The attribution line is **required on every report** and its wording is fixed.

---

## 10. Fitting the page

The report is always exactly one page. Before drawing, every band is measured.
If the stack does not fit:

1. Step the type size down through `8.0 → 7.5 → 7.0 → 6.5 → 6.0 → 5.5` pt.
2. At each size, find the largest text budget that still fits (bisection over a
   `0.60`–`1.60` multiplier on the per-field character budgets above).
3. Stop at the first size that carries an acceptable budget (`≥ 0.90`).

Type size is only spent once text has been, so a normal-length analysis renders
at 8 pt with nothing clipped. Clipped fields end with an ellipsis. If nothing
fits at 5.5 pt, raise `LayoutOverflowError` naming the offending band rather
than emitting a broken page.

---

## 11. Fields captured but not rendered

The analysis schema collects more than the one-pager shows. These fields are
validated and available on the `AnalysisResult` object for downstream documents
(IC memo, founder Q&A, diligence pack) and must remain in the schema:

| Field | Shape |
|---|---|
| `sections` | 8 sections, each `{ score, observations, missing, questions[] }` — `problem_validation`, `solution_effectiveness`, `market_opportunity`, `competitive_intelligence`, `business_model`, `traction_evidence`, `team_assessment`, `financial_intelligence` |
| `assumptions[]` | `{ assumption, evidence, confidence, validation }`; `confidence` ∈ `Low` · `Medium` · `High` |
| `missing_information[]` | Free-text list |
| `key_milestones_before_investment[]` | Free-text list |
| `risks[]` beyond the 4 rendered | Full list retained |
| `top_diligence_questions[]` beyond the 5 rendered | Full list retained |

---

## 12. Content rules

1. **Every band is always present.** A band with no data renders an explicit
   empty-state string, never a blank gap.
2. **Nothing is dropped silently.** Capped lists disclose the remainder; clipped
   text ends in an ellipsis.
3. **Absent information is stated, not inferred.** Where the deck does not cover
   a point, the analysis says `Not presented` rather than speculating.
4. **Slide citations are preserved.** Where the analysis cites a slide, keep the
   `(Slide N)` reference in the rendered text.
5. **Fixed vocabularies are closed sets.** Recommendation, risk category, and
   probability/impact levels accept only the values listed above.
