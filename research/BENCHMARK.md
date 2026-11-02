# BENCHMARK · Consigliere AI

**Goal:** Evaluate whether evidence-grounded LLM extraction plus deterministic constraints improves deal-term reliability compared with pure LLMs and pure regex rules.

> **Current evidence is from synthetic, AI-assisted examples.** It is not independent contract accuracy, published academic research, or real customer validation.

## Main study: three-system comparison · measured 2026-11-02

The portfolio's active study compares **three actually measured systems**: direct Gemini **21/24 on attempt 1 and 22/24 on repeat**, deterministic DealGuard **11/24**, and Gemini extraction + evidence validation + deterministic checks **22/24 on both attempts**. The initial hybrid advantage vanished on repeat. These AI-authored synthetic examples are not independently adjudicated and do not show a statistically established advantage. An optional fourth GPT comparison was attempted but **yielded no predictions** due to exhausted API credits; it is deliberately **out of scope**, not pending user payment.

- [Main three-system study, two attempts and limitations](THREE_SYSTEM_RESULTS.md)
- [Detailed historical results and failed GPT attempt](FOUR_ARM_RESULTS.md)
- [GitHub run #41422998049 with original predictions](https://github.com/Serein131/Consigliere-ai/actions/runs/41422998049)
- [Archived optional GPT setup and uncompleted attempt](FOUR_ARM_SETUP.md)

## What has actually been measured

| Date / dataset | Gemini alone | DealGuard deterministic | Interpretation |
|---|---:|---:|---|
| Earlier familiar 60-case development suite | 47/60 | 60/60 | DealGuard was repaired with some of these cases: regression evidence only |
| New 40-case frozen language challenge | **31/40** | **16/40** | Result reverses; regex parser struggles with unanticipated contract language |
| Earlier difficult 20-case suite | **13/20** | **3/20** | Already inspected challenge set, not new unseen data |

Primary reports:

- [40+20 paired comparison, failures and freeze record](HOLDOUT_RESULTS_2026-11-02.md)
- [Previous familiar 60-case API comparison](GEMINI_COMPARISON_2026-11-02.md)
- [Baseline/revision history](RESULTS.md)
- [Original GitHub Actions evidence](https://github.com/Serein131/Consigliere-ai/actions)

## Three tested systems, with optional GPT work archived

| Arm | System | What it tests |
|---|---|---|
| A | Gemini API alone, direct rule judgments | LLM interpretation and compliance with user rules |
| B (archived) | OpenAI GPT API (uncompleted) | No usable predictions; not an active requirement |
| C | Deterministic DealGuard alone | Transparent comparison but limited language coverage |
| D | Gemini structured extraction → exact quote evidence validation → deterministic rule comparison | Hypothesis that combining semantic extraction and reliable threshold comparisons reduces errors |

The Gemini and GPT baseline **share the same rule-auditing task prompt**. The hybrid prompt is deliberately different: it is instructed to extract facts, not to decide PASS/VIOLATION. All arms see the same fictional deal proposal and structured constraints. Arm D does **not** use Gemini's direct rule judgment from Arm A.

**Frozen evaluation set:** [24 newly authored cases](cases/four_arm_frozen_24.json). Set declared before scoring; labels remain AI-assisted, not independently adjudicated.

**Four-arm results:** [now measured for A, C, D](FOUR_ARM_RESULTS.md). Group B is explicitly NOT_RUN pending independent OpenAI API authorization; no GPT scores are inferred from ChatGPT conversation output.

## What to measure

- Exact-case agreement: every configured rule state AND the commercial-risk flags match the predeclared case answer.
- PASS / VIOLATION / UNKNOWN mistakes, especially unsupported safety assurances.
- Precision and recall for explicit violations; missing rule states are not treated as correct.
- Unsupported evidence quotes and model-extracted numbers lacking exact text support.
- Relative inference cost/latency as separate observations, if genuinely measured.

## Experimental threats

Cases are AI/developer-generated with known product domain, not random samples of real negotiations. Even new cases have subjective or ambiguous labels, and one execution per model cannot establish statistical reliability. A future rigorous study must get independent reviewer labels, repeat calls, and reserve unseen cases **after** further code changes. An evaluator cannot claim a model is 100% accurate because it passed the familiar regression suite.
