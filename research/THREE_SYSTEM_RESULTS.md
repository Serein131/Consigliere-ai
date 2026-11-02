# Three-system research comparison — Consigliere AI

**Main portfolio evaluation scope (November 2, 2026): three tested systems**, not four.

## Research question

Does extracting deal terms with an LLM and verifying cited evidence before deterministic constraint checking improve reliability compared with a direct Gemini answer or a standalone regex/rule checker?

## Methods

The same 24 AI-assisted synthetic Chinese/English deal snippets and developer-authored rule labels were evaluated using:

- **A · Gemini direct judgment**: language model directly classifies proposed terms against user-specified rules.
- **C · DealGuard deterministic checker**: the existing regex-based rule engine, without an LLM.
- **D · Hybrid**: Gemini extracts deal terms, states and verbatim evidence; a validator checks citations and numeric support, then applies deterministic constraints. Unsupported facts produce UNKNOWN.

The data set was frozen prior to scoring; see [case file](cases/four_arm_frozen_24.json) and [methodology](EVALUATION.md). These are **not independent expert labels or actual customer contracts**.

## Two executions on the same 24 synthetic cases

| System | First run | Repeat run |
|---|---:|---:|
| A · Gemini | 21/24 (87.5%) | 22/24 (91.7%) |
| C · Deterministic DealGuard | 11/24 (45.8%) | 11/24 (45.8%) |
| D · Evidence-grounded hybrid | 22/24 (91.7%) | 22/24 (91.7%) |

The hybrid's initial one-case advantage over Gemini **did not persist on repeat**. This sample does not establish a meaningful superiority claim.

See [full case-level failure analysis](FOUR_ARM_RESULTS.md) and [actual GitHub Actions run](https://github.com/Serein131/Consigliere-ai/actions/runs/41422998049), which contains separate result artifacts for both attempts.

## Why GPT is excluded from the current scope

An optional **B · OpenAI GPT API** comparison was prepared, but **no valid predictions were obtained**. The GitHub secret was recognized; a direct GPT request returned HTTP 429 and a separate diagnostic identified `credit_balance_exhausted` / `insufficient_quota`. Because funding an additional model is not feasible, the owner has deliberately **removed this fourth group from the active research plan**.

The GPT research code and failure log are archived for reproducibility; they **are not evidence of GPT accuracy**. No subscription, payment, new API key or additional model comparison is required to complete the current three-system study.

## Findings

The earlier familiar 60-case development regression suite gave DealGuard 60/60, but a separate 40-case complex synthetic holdout gave DealGuard 16/40 and Gemini 31/40. The regex-only checker is brittle to unfamiliar language. The evidence-grounded hybrid reached 22/24 in both executions of the smaller three-way set, but did not convincingly outperform direct Gemini and missed a violation after an invented source quotation was correctly rejected by its evidence gate.

**Next validation priorities:** Independent review of borderline labels, a genuinely fresh dataset after future code changes, and a small consent-based user usability study. Do not tune to these already-scored 24 cases while calling them unseen.

## Privacy and honest reporting

All benchmark inputs were fictional. No actual clients, contract documents, independent expert reviews or user-test responses are claimed. The live app does not yet run the hybrid research engine in production. This project uses AI-assisted coding and AI-assisted fixture authoring.

**Use in HAA material:** Clearly describe what you implemented, how the systems were evaluated, the original/replicate results, the observed failures and the unresolved research question. Avoid claiming 100% accuracy or that the hybrid is proved superior.
