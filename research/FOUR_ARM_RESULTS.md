# Four-arm evaluation · measured 2026-11-02

## Update: OpenAI key added, but GPT remains unmeasured (API billing blocked)

**2026-11-02, GitHub Actions run [#41422998049, attempt 2](https://github.com/Serein131/Consigliere-ai/actions/runs/41422998049/attempts/2):** GitHub successfully loaded the user's `OPENAI_API_KEY` secret. The GPT-6 Luna baseline sent a real request but received **HTTP 429** on its very first scenario; there are **zero valid GPT predictions**, so arm B is still **NOT_RUN**, not 0% accuracy.

A separate one-request [diagnostic run #41427929940](https://github.com/Serein131/Consigliere-ai/actions/runs/41427929940) classified the provider response as **`credit_balance_exhausted` / `insufficient_quota`** without printing the key, raw error message or provider identifiers. This is an API **billing/credit** problem, **not** a bad API-key format or temporary request-rate limit. Additional retries cannot repair an exhausted prepaid API balance.

To finish arm B after the owner resolves OpenAI Platform billing, use the [GPT-only completion workflow](../.github/workflows/gpt-only-completion.yml) or [iPad instructions](FOUR_ARM_SETUP.md). It reuses the exact saved A/C/D predictions, so there is no need to spend Gemini quota again. The preserved artifact must still be available in GitHub Actions (30-day retention).

### Two completed A/C/D inference attempts (same 24 synthetic cases; no rule/label changes)

| Run | Gemini direct A | DealGuard C | Hybrid D | GPT B |
|---|---:|---:|---:|---|
| Attempt 1, before GPT key | **21/24** | **11/24** | **22/24** | NOT_RUN: no key |
| Attempt 2, with key and no API credits | **22/24** | **11/24** | **22/24** | NOT_RUN: credit balance exhausted |

The same Gemini model changed by one exact case across repeats, despite deterministic settings; **the apparent hybrid advantage disappears on attempt 2**. This demonstrates why a one-case gap is not sufficient for broad claims. Both attempts' raw predictions are archived as distinct GitHub Actions artifacts; the latest saved artifact is ID `13132523079`.

The historical description below refers to the **first completed A/C/D attempt**, not a completed four-provider run.



**Status:** Three independent arms ran to **24/24 completion**. The fourth (OpenAI GPT) was **NOT_RUN** because this GitHub repository had no `OPENAI_API_KEY` secret at run time.

**Original A/C/D-only attempt (attempt 1):** [GitHub Actions #41422998049](https://github.com/Serein131/Consigliere-ai/actions/runs/41422998049) · A/C/D steps completed; the overall run now displays failure because a later attempt tried GPT without available credits. The downloadable `four-arm-measured-and-provider-availability` artifact includes 24 raw Gemini predictions, 24 raw hybrid predictions with extracted evidence/audit records, 24 rule-engine predictions, an exact-case CSV, machine-readable JSON summary, and formatted Markdown. Artifacts expire; preserve a copy if needed.

**Dataset:** [four_arm_frozen_24.json](cases/four_arm_frozen_24.json) — 24 English and Chinese synthetic deal snippets, fixed before scoring. These examples and labels were **AI-assisted and not independently expert-adjudicated**. They are not real contracts or production accuracy estimates.

## Actual group results

| Group | Measured state | Whole-case exact match | Violation precision | Violation recall |
|---|---|---:|---:|---:|
| A · Direct Gemini `gemini-3.5-flash-lite` | **COMPLETE** | **21/24 (87.5%)** | **100%** (12 TP, 0 FP) | **100%** (0 FN) |
| B · OpenAI GPT API | **NOT_RUN** | — | — | — |
| C · Deterministic DealGuard v2 | **COMPLETE** | **11/24 (45.8%)** | 54.5% (6 TP, 5 FP) | 50% (6 FN) |
| D · Gemini extraction + evidence validation + deterministic checks | **COMPLETE** | **22/24 (91.7%)** | 100% (11 TP, 0 FP) | 91.7% (1 FN) |

**Pairing A vs. D on the same 24 cases:** both exact 20; D only correct 2; A only correct 1; both wrong 1. **Net +1 case for the hybrid**, which is not statistically persuasive evidence of a broad performance improvement.

### All mismatches on authored labels

- A Gemini direct: `F4-004`, `F4-009`, `F4-015`.
- C deterministic: `F4-001`, `F4-003`, `F4-005`, `F4-006`, `F4-007`, `F4-008`, `F4-009`, `F4-011`, `F4-012`, `F4-015`, `F4-018`, `F4-020`, `F4-023`.
- D hybrid: `F4-001`, `F4-015`.

### What actually happened on the four distinguishing cases

1. **`F4-001`:** Source input describes an active *12 percent reduction* in license fees. Gemini direct found VIOLATION (matches the authored label). Hybrid's **extractor invented a quote** about a customer seeking a *twelve percent discount on first-year services*; that quote is **not an exact substring of the input**. Evidence validator rejected it and returned UNKNOWN rather than treating the invented quotation as a reliable fact. This is a **real missed violation**, but also an example of the evidence gate behaving conservatively.
2. **`F4-004`:** Supplier has not decided whether to offer any discount. Authored label UNKNOWN. Gemini direct returned PASS; hybrid returned UNKNOWN, using the "ambiguous / not decided" status.
3. **`F4-009`:** Chinese 10-day buyer-payable proposal, with a buyer rule requiring at least 45 days. Both models flagged the rule violation; plain Gemini **did not produce the separate short-payables cashflow warning**, so it missed whole-case exact match. Hybrid correctly separated explicit violation and commercial review.
4. **`F4-015`:** Future exclusive territory *may* be discussed, but no current exclusivity is proposed. The authored label is UNKNOWN; **both** Gemini direct and hybrid returned PASS. This distinction needs independent human label review before presenting the result as objectively wrong.

## Why this is a meaningful research result

The prior 40-case frozen challenge showed a brittle regex-only engine (16/40) versus Gemini 31/40. A direct extract-then-validate hybrid can recover some of the model's semantic capacity without letting hallucinated evidence pass as confirmed. **However, it did not outperform a direct Gemini classifier by a convincing margin** in this 24-case synthetic sample and actually missed a violation that Gemini direct caught. This is a prototype research result, not a production recommendation or a proven safety advantage.

## Method and version caveats

- A and intended B direct baselines use the same rule-auditing system instructions; D uses an extraction-only prompt, deliberately no classification requests. C uses the pre-existing deterministic parser.
- Model output is not guaranteed perfectly reproducible even at temperature 0. This study captures one run per case; latency/cost distributions were not established.
- The experiment initially encountered malformed direct Gemini JSON and temporary provider HTTP 503 responses. A follow-up engineering revision reused the **previously validated** direct Gemini baseline prompt/function and added bounded retries for temporary 5xx responses. **The 24 synthetic case IDs, expected labels and rule-engine code were not modified based on results.** The successful follow-up run is linked above; earlier failed runs remain visible.
- `OPENAI_API_KEY` is a **GitHub Actions repository secret** that the user must configure separately, with an OpenAI Platform API account. ChatGPT subscriptions do not automatically provide API keys.
- A score compares authored synthetic answers, not legal validity, customer decisions, deployable commercial reliability, or a human expert's verdict.
- For a stronger scientific study, independently adjudicate labels, repeat predictions, test latency/cost, run the true GPT baseline after authorization, and freeze a fresh external challenge **after** any further hybrid code changes.

## Traceability

- [Benchmark overview](BENCHMARK.md)
- [Protocol](EVALUATION.md)
- [Frozen cases](cases/four_arm_frozen_24.json)
- [Pure evidence validator](evidence_hybrid.py)
- [Direct model + hybrid runner](run_four_arms.py)
- [Actual scoring program](evaluate_four_arms.py)
- [GitHub Actions run and full original artifact](https://github.com/Serein131/Consigliere-ai/actions/runs/41422998049)
- [GPT credential setup](FOUR_ARM_SETUP.md)

**No real participants were used.** Blank feedback templates are not user feedback. Code and case authoring were AI-assisted.
