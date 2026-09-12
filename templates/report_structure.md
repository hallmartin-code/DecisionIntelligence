# Decision Intelligence Assessment — Document Structure

The canonical structure for the full Decision Intelligence report, derived from
`Noleus_Decision_Intelligence_Analysis.docx`. It defines the page, the type
scale, the palette, every section in document order, every table's columns, and
the content conventions that give the document its voice.

Placeholders use `{{ field }}`. No company-specific content appears here.

---

## 1. Page setup

| Property | Value |
|---|---|
| Page size | US Letter, **portrait** (8.5 × 11 in) |
| Margins | 0.88 in left/right, 0.83 in top/bottom |
| Length | Multi-page — typically 8–14 pages. **No one-page constraint.** |
| Body font | Calibri throughout (headings and body) |
| Footer | `TEN Capital Group · Decision Intelligence Assessment · {{ company_name }} · Confidential` + `Page X of Y` (right-aligned tab) |
| Header | Empty |

### Palette

| Token | Hex | Used for |
|---|---|---|
| Navy | `#1F3864` | Document title, H1, H3, table header fill, neutral callout titles |
| Blue | `#2E74B5` | Brand line, H2 |
| Crimson | `#A6192E` | Recommendation line, adverse findings, flagged assumptions, critical callout titles |
| Grey | `#595959` | Eyebrow, tagline, secondary metadata |
| Panel | `#F5F7FA` | Callout box fill |
| Body | default (near-black) | Body copy |

### Type scale

| Element | Size | Weight | Colour |
|---|---|---|---|
| Brand line (`TEN CAPITAL GROUP`) | 10 pt | Bold | Blue |
| Eyebrow (`INVESTMENT COMMITTEE · DECISION INTELLIGENCE ASSESSMENT`) | 8 pt | Regular | Grey |
| Company name | 25 pt | Bold | Navy |
| Tagline / one-line descriptor | 11 pt | Regular | Grey |
| H1 (part title) | 15 pt | Bold | Navy |
| H2 (section) | 12 pt | Bold | Blue |
| H3 (sub-section) | 10.5 pt | Bold | Navy |
| Body | 10 pt | Regular | Body |
| Emphasised body / list items | 10 pt | Bold | Body (crimson when adverse) |

### Two recurring components

**Grid table.** Header row filled navy with white bold text; body rows plain
with hairline rules. Used for every structured table below.

**Callout box.** A single-cell table filled `#F5F7FA`, opening with an
ALL-CAPS title line — navy for neutral/positive, crimson for critical — then a
paragraph of body text. Used for the recommendation, key findings, and
framing statements.

---

## 2. Document order

```
Brand block  →  Metadata table  →  Recommendation callout  →  Scoring note
PART 1  Executive Summary
PART 2  Decision Intelligence Assessment   (10 numbered categories)
PART 3  Decision Scenario Analysis
PART 4  Investment Committee View
PART 5  Decision Intelligence Scorecard
PART 6  Final Recommendation
PART 7  Summary Investment Memo
```

---

## 3. Masthead

Four stacked paragraphs, no rule:

```
TEN CAPITAL GROUP
INVESTMENT COMMITTEE  ·  DECISION INTELLIGENCE ASSESSMENT
{{ company_name }}
{{ one_line_descriptor }}
```

### Metadata table — 6 rows × 4 columns

A `Field | Detail | Field | Detail` grid (two field/value pairs per row):

| Field | Detail | Field | Detail |
|---|---|---|---|
| Source document | `{{ source_document }}` | Analysis date | `{{ analysis_date }}` |
| Company status | `{{ company_status }}` | `{{ milestone_label }}` | `{{ milestone_value }}` |
| Regulatory plan | `{{ regulatory_plan }}` | Commercialization | `{{ commercialization }}` |
| Funding ask | `{{ funding_ask }}` | Valuation / terms | `{{ valuation_terms }}` |
| Financials | `{{ financials }}` | Cap table / runway | `{{ cap_table_runway }}` |

Rows 2–3 carry sector-appropriate labels. Anything absent from the source reads
**`Not disclosed`** — never blank, never inferred.

### Recommendation callout

Critical callout (crimson lead), carrying the verdict and the three headline
numbers in prose:

```
RECOMMENDATION:  {{ recommendation }}  ·  {{ recommendation_qualifier }}
Overall Decision Confidence: {{ confidence_pct }}%.  Weighted Decision
Intelligence Score: {{ weighted_overall }} / 10.  {{ verdict_paragraph }}
```

### Scoring-fairness note

A short bold paragraph, present whenever the source material is thinner than a
full deck. It states what the format cannot carry and commits to the distinction
the whole document rests on:

> **Information missing because of the format** — noted, not scored against the
> company. **Claims inaccurate or internally inconsistent within the space the
> company did use** — scored.

---

## 4. PART 1 — Executive Summary

| H2 | Content |
|---|---|
| Investment Recommendation | Verdict line, 13 pt bold crimson: `{{ recommendation }} — {{ qualifier }}`. Then `Overall Decision Confidence: {{ confidence_pct }}%` with a sentence on what raises and what caps it. |
| Key Investment Thesis | 3–5 body paragraphs: the problem and its economics, the mechanism, the strongest element, and a closing sentence naming what breaks the thesis. |
| Top Three Strengths | Exactly 3 numbered items. Each opens with a **bold claim sentence**, then evidence. |
| Top Three Concerns | Exactly 3 numbered items, same shape. |

---

## 5. PART 2 — Decision Intelligence Assessment

Ten numbered H2 sections, always in this order, each headed
`{{ n }}.  {{ category }} — Score {{ score }} / 10`:

The weight applied to each category depends on the company's stage. Every
profile totals 100%, so the weighted score stays on the same 0–10 scale and two
companies remain comparable however they are weighted.

| # | Category | Balanced | Foundation | Traction |
|---|---|---|---|---|
| 1 | Problem Validation | 10% | 10% | 7% |
| 2 | Solution Effectiveness | 12% | 13% | 9% |
| 3 | Market Opportunity | 10% | 9% | 9% |
| 4 | Competitive Intelligence | 8% | **13%** | 8% |
| 5 | Business Model Intelligence | 10% | 7% | 12% |
| 6 | Traction & Evidence Quality | 12% | 6% | **24%** |
| 7 | Team Assessment | 15% | **22%** | 11% |
| 8 | Financial Intelligence | 10% | 6% | 12% |
| 9 | Risk Intelligence | 8% | 8% | 5% |
| 10 | Assumption Mapping | 5% | 6% | 3% |

- **Foundation** — pre-revenue *and* pre-approval. There is no traction to
  weigh, so Team Assessment and Competitive Intelligence (which carries the
  intellectual property and defensibility analysis) take the weight.
- **Traction** — post-revenue *and* post-approval. Traction & Evidence Quality
  roughly doubles; the narrative categories give way to demonstrated results.
- **Balanced** — anything in between, or a stage the source does not establish.
  A company that is post-revenue but pre-approval, or approved but not yet
  selling, is not weighted on a guess.

"Not applicable" regulatory status counts with whichever side revenue is on, so
an unregulated business is still weighted by how far it has got.

Each section carries 3–5 H3 sub-sections. The first is a question the section
answers; the last is **`Recommended diligence questions`** (a plain numbered
list, regular weight — the only list in the document that is not bold).

### Section-specific structures

**3. Market Opportunity** — `Market sizing as presented`, a 7 × 3 grid:

| Layer | As stated | Assessment |
|---|---|---|
| US procedure volume · Global volume · US TAM · Global TAM · SAM · SOM | `{{ as_stated }}` | `{{ assessment }}` |

Unstated layers read `Not stated` / `—`.

**4. Competitive Intelligence** — `What the summary does not mention`, a 7 × 3 grid:

| Competitor | Type | Why it competes |
|---|---|---|

**6. Traction & Evidence Quality** — a 6 × 3 grid:

| Evidence | What it demonstrates | What it does not demonstrate |
|---|---|---|

**8. Financial Intelligence** — `Sensitivity analysis`, a 7 × 4 grid:

| Variable | Stated | What determines it | Effect if adverse |
|---|---|---|---|

**9. Risk Intelligence** — `Ranked risk register`, a 15 × 5 grid (up to 14 risks,
ranked most severe first):

| # | Risk | Prob. | Impact | Mitigation strategy |
|---|---|---|---|---|

`Risk` opens with an ALL-CAPS category prefix — `REGULATORY —`, `FINANCIAL —`,
`PRODUCT/CLINICAL —`, `PRODUCT/SCIENCE —`, `COMMERCIAL —`, `EXECUTION —`,
`COMPETITIVE —`, `MARKET —`. `Prob.` and `Impact` take `Low` · `Low-Medium` ·
`Medium` · `Medium-High` · `High`. A `Risk category summary` H3 follows.

**10. Assumption Mapping** — `The Ten Critical Assumptions`, an 11 × 5 grid:

| # | Assumption | Evidence presented | Confidence | Validation needed |
|---|---|---|---|---|

`Confidence` takes `LOW` · `LOW-MED` · `MEDIUM` · `MED-HIGH` · `HIGH` ·
`UNKNOWN` (uppercase). Closes with an **assumption-concentration callout**
naming which assumptions carry the outcome.

---

## 6. PART 3 — Decision Scenario Analysis

Three H2 sections — `Best Case — Probability {{ pct }}%`, `Base Case`,
`Worst Case` — each a narrative paragraph plus an H3 `Key drivers` list.
Probabilities must total 100%.

Then `Probability-weighted outcome`, a 4 × 5 grid:

| Scenario | Probability | Gross multiple | Weighted | Cumulative |
|---|---|---|---|---|

Two callouts close the part: **`BASIS OF THIS ANALYSIS`** (states what the
multiples are computed against, and says so plainly when no terms are
disclosed) and **`EXPECTED RISK-ADJUSTED OUTCOME`**.

---

## 7. PART 4 — Investment Committee View

| H2 | Content |
|---|---|
| Bull Case — The Strongest Argument For Investing | The best honest case, stated without hedging. |
| Bear Case — The Strongest Argument Against Investing | The same, inverted. |
| Missing Information — What Would Materially Improve Decision Quality | Two H3 lists: **`Would make a decision possible at all`** and **`Would materially change the assessment`**. |

---

## 8. PART 5 — Decision Intelligence Scorecard

Introduced by the weighting actually applied, so the numbers in the grid can
be read:

```
Weighting: {{ profile_label }}
Company stage: {{ revenue_stage }}, {{ regulatory_stage }}.
Basis: {{ one sentence citing what establishes both }}
{{ why this profile weights what it weights, in italic }}
```

Then a 12 × 5 grid — ten category rows plus a bold total row:

| Category | Score | Weight | Weighted | Principal driver of the score |
|---|---|---|---|---|
| `{{ category }}` | `{{ score }} / 10` | `{{ weight }}%` | `{{ score × weight }}` | `{{ one_line_rationale }}` |
| **WEIGHTED OVERALL SCORE** | **`{{ weighted_overall }} / 10`** | **100%** | **`{{ computed }}`** | **`{{ verdict_phrase }}`** |

`Composite indices`, a 4 × 3 grid:

| Index | Value | Interpretation |
|---|---|---|
| Weighted Overall Score | `{{ weighted_overall }} / 10` | … |
| Confidence Score | `{{ confidence_pct }}%` | … |
| Decision Quality Score | `{{ decision_quality }} / 10` | How well the material supports a rational decision |

`Comparative context across this cycle`, a 5 × 4 grid placing this company
against others assessed in the same period:

| Company | DI score | Confidence | Character of the central issue |
|---|---|---|---|

> Omit this table when no comparison set exists — never populate it with
> invented peers.

---

## 9. PART 6 — Final Recommendation

| H2 | Content |
|---|---|
| How to approach this | The practical next move, in prose. |
| Top Five Diligence Questions | Exactly 5, numbered. |
| Key Milestones Required Before Investment | An 11 × 3 grid: `# \| Milestone \| Why it matters` (up to 10). |
| Expected Risk-Adjusted Outcome | Prose, closing on a **critical callout**: `{{ recommendation }} · Confidence Level {{ confidence_pct }}% · {{ qualifier }}`. |

---

## 10. PART 7 — Summary Investment Memo

A 9 × 2 `Field | Summary` grid — the one-screen version for a reader who opens
nothing else:

| Field |
|---|
| Company · Recommendation · Decision confidence · Weighted DI score · Funding ask · Strongest element · Central issue · Next step · Decision |

---

## 11. Content rules

1. **Absent means absent.** Anything the source does not contain reads
   `Not disclosed` or `Not stated`. Never inferred, never estimated, never
   left blank.
2. **Separate format from substance.** Information missing because the source
   format cannot carry it is noted but not scored against the company. Claims
   that are inaccurate or self-contradictory *within* the material provided are
   scored.
3. **Check the checkable.** Claims that can be verified against public knowledge
   — competitor existence, approval dates, arithmetic consistency — are checked,
   and a failed check is stated plainly with the contradicting fact.
4. **Adverse findings are set in crimson**, at bullet level, so a reader
   scanning the document sees the problems without reading it.
5. **Score the document, cite the document.** Every score is justified by a
   one-line driver in the scorecard that traces to a section above.
6. **Arithmetic must close.** Weighted column = score × weight; the total row
   must equal the sum. Scenario probabilities must total 100%.
7. **State the decision type.** Where no terms are disclosed, the document says
   explicitly that this is a screening decision, not an investment decision.
