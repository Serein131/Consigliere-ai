# Consigliere AI · Measured Gemini vs. DealGuard experiment

> **Important later validation (same date):** A newly frozen 40-case synthetic holdout *reversed* the direction of the standard benchmark: Gemini 31/40 vs. DealGuard 16/40 exact authored-label matches. On a separate previously inspected 20-case challenge suite, Gemini 13/20 vs. DealGuard 3/20. [See the latest frozen holdout results](HOLDOUT_RESULTS_2026-11-02.md) before interpreting the familiar 60-case regression results below.


**Experiment date:** 2026-11-02

**Important:** This is a comparison on **60 developer-authored synthetic negotiation cases**, not independent legal review, real customer deals, or a claim of production accuracy. DealGuard was previously improved using this very same standard suite. The dataset is **not a clean holdout**. Some expected labels may reasonably be disputed.

## Reproducible source and records

- [Full 60-case GitHub Actions execution](https://github.com/Serein131/Consigliere-ai/actions/runs/41415291016) — completed successfully, and **all 60 Gemini API predictions were saved**.
- [Synthetic scenarios and predeclared labels](synthetic_cases.json).
- [Evaluator](evaluate.py) and [plain Gemini prompt/API runner](run_gemini_baseline.py).
- Model: `gemini-3.5-flash-lite` via Google Generative Language API, generation temperature 0.
- Two comparators were given the same synthetic proposal and structured deal thresholds. The plain Gemini baseline did not receive DealGuard's predictions or deterministic parsing code.
- The GitHub Actions **measured-gemini-vs-dealguard** artifact contains the unmodified 60 Gemini predictions, the Gemini evaluation JSON/Markdown, and the DealGuard evaluation JSON/Markdown. Artifacts have limited retention (30 days); download and archive if required.

## Results on these 60 familiar synthetic scenarios

| Measurement | Plain Gemini | DealGuard deterministic rules |
|---|---:|---:|
| Fully matching cases (rule state **and** commercial flags) | **47/60 (78.3%)** | **60/60 (100.0%)** |
| Exact commercial risk flags | 55/60 (91.7%) | 60/60 (100.0%) |
| Rule-label matches | 51/62* (82.3%) | 60/60 (100.0%) |
| Violation true positives | 20 | 20 |
| Violation false positives | 3 | 0 |
| Violation false negatives | 0 | 0 |
| Violation precision | 87.0% | 100.0% |
| Violation recall | 100.0% | 100.0% |

\* Two plain-Gemini responses introduced rule labels not configured in those cases; the evaluator includes these unsupported extra labels in its comparison. The discrepancy means the raw rule-label denominators differ; do not present the rule-label figures as a perfectly symmetric metric without explaining this.

### Plain Gemini breakdown by category

| Case group | Cases fully matched |
|---|---:|
| Discount | 11/14 |
| Payment | 8/14 |
| Exclusivity | 12/14 |
| Commercial-risk-only | 11/12 |
| Mixed rules | 5/6 |
| **Total** | **47/60** |

### All 13 baseline case-level mismatches

`DG-005`, `DG-008`, `DG-012`, `DG-018`, `DG-019`, `DG-021`, `DG-025`, `DG-027`, `DG-028`, `DG-033`, `DG-039`, `DG-043`, `DG-057`.

Examples:

- **Rejected terms:** `DG-005`, "We rejected the 20% discount." The declared expected rule state was UNKNOWN because no active discount rate was stated; Gemini returned PASS.
- **Unresolved revisions:** `DG-008`, both 15% and 8% proposed discounts appear without a definitive acceptance. The declared expected state was UNKNOWN; Gemini returned PASS.
- **Buyer vs seller direction:** `DG-027` configured a **buyer** requiring a minimum 45-day payment period. A 90-day period passes that explicit constraint. The reference answer was PASS; Gemini returned VIOLATION.
- **Historical clauses:** `DG-039` mentioned a previously discussed exclusivity term, which should not automatically be treated as a current demand. Expected UNKNOWN; Gemini returned VIOLATION.
- **Extra checks:** `DG-043` specified no machine-enforced payment or exclusivity constraint, but Gemini output unnecessary rule states.
- **Cashflow advisory disagreement:** `DG-018` and `DG-025` illustrate that cashflow-warning expectations depend on chosen thresholds and context. The synthetic label is a design choice, not a legal or financial judgment.

## Crucial counter-evidence: harder synthetic challenge suite

A **separate set of 20 deliberately difficult synthetic cases**, tested before modifying the engine to address them, produced only **3/20 fully matching cases for DealGuard**, including 17 mismatches. [See the earlier research log](RESULTS.md) and the [20 challenge cases](challenge_cases.json).

The separate challenge set was **not evaluated against ordinary Gemini in this run**. Therefore, the 60-case result does **not** establish superiority on unseen difficult language, real-world contracts, or autonomous negotiation.

## What can and cannot be concluded

**Supported:** An independently executed Gemini API baseline completed all 60 authored standard cases. DealGuard matched the predeclared labels more often than plain Gemini on that familiar set, largely due to treating rule checking as an explicit programmatic step.

**Not supported:** "DealGuard is 100% accurate", "DealGuard is always better than Gemini", "the experiment proves legal reliability", "users prefer DealGuard", "these are real-world performance figures", or "this is an academic peer-reviewed result".

**Next evidence to collect:** Independent review of labels; a fresh *frozen* holdout not used in coding; paired model-vs-system evaluation on that holdout; participant consent-based usability feedback; and (eventually) domain expert validation. Abstention/UNKNOWN calibration and unsupported extra checks should be tracked separately from outright rule violations.

## Potential HAA portfolio wording to adapt in your own voice

"I built a deterministic commercial-rule checker and tested it against an unmodified Gemini baseline on 60 synthetic English/Chinese scenarios. The model completed all 60 API evaluations; our system matched the authored labels in 60/60 versus 47/60 for Gemini. However, these were familiar developer-written test cases, and our separate 20-case challenge exposed significant shortcomings (3/20), especially on complex contract language. My next research focus is context-aware term extraction and auditable uncertainty."

The project used AI-assisted coding and AI-assisted scenario authoring. The applicant should accurately distinguish her own design, debugging and experimental choices from assistance.
