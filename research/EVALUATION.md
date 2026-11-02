# EVALUATION · methodology and reproducibility

## Scope

Consigliere AI is an early **decision-support prototype**, not autonomous deal execution, legal counsel, or a certified risk evaluation tool. Experiments test synthetic language and explicit user-configured constraint handling, not contract enforceability or business outcome quality.

## Four arms

**A · Gemini:** Gemini API directly classifies PASS, VIOLATION or UNKNOWN and commercial-review flags, with no DealGuard outputs.

**B · GPT:** OpenAI Responses API model (default `gpt-6-luna`) receives the **same rule-classification prompt and inputs as Gemini**, no DealGuard outputs. OpenAI API usage is separate from a ChatGPT subscription.

**C · Deterministic:** Existing `dealguard.py` applies regex-based extraction and explicit rule comparison. This is intentionally unchanged during the experiment.

**D · Hybrid:** Gemini is told to **extract** amounts, units, proposal state (proposed/agreed/rejected/historical/ambiguous/absent), and *verbatim quotes*. `evidence_hybrid.py` validates each citation as an exact substring and checks that the claimed number appears in its cited span. It then applies user-defined thresholds programmatically; missing or unverified facts become UNKNOWN. Commercial-review flags are **separate** from explicit rule compliance. The hybrid is a **research arm**, not yet a production release.

## Data

[Dataset catalog](cases/README.md). In particular, the four-arm dataset [four_arm_frozen_24.json](cases/four_arm_frozen_24.json) contains 24 synthetic bilingual cases. Labels were authored before running any of the four arms, but there was no independent legal, procurement or commercial expert adjudication.

## Running locally (for a technical reviewer)

```bash
python -m unittest discover -s tests -v
python research/run_four_arms.py --cases research/cases/four_arm_frozen_24.json --arm rules --output /tmp/arms/rules.json
```

For API-based models, configure environment secrets **outside version control**. Never put keys in JavaScript or client-side Vercel code.

```bash
export GEMINI_API_KEY="<from Google AI Studio>"
export OPENAI_API_KEY="<from OpenAI platform>"
python research/run_four_arms.py --cases research/cases/four_arm_frozen_24.json --arm gemini --output /tmp/arms/gemini.json
python research/run_four_arms.py --cases research/cases/four_arm_frozen_24.json --arm gpt --output /tmp/arms/gpt.json
python research/run_four_arms.py --cases research/cases/four_arm_frozen_24.json --arm hybrid --output /tmp/arms/hybrid.json
python research/evaluate_four_arms.py --cases research/cases/four_arm_frozen_24.json --results-dir /tmp/arms --output-prefix /tmp/four_arm
```

In GitHub Actions, use **Secrets**, not public repository variables. `GEMINI_API_KEY` is previously configured. `OPENAI_API_KEY` requires independent authorization and billing. If that secret is missing, the workflow must publish results for actual completed groups and mark GPT **NOT_RUN**.

## Technical evaluation

All arms are scored **on the same exact case IDs and expected answers**. Evaluator reports both complete-case match and rule-state violations. Expected label choices are subjective in some cases. Cases with missing/invalid provider responses are explicitly incomplete, not counted as failures or successes. A separate file of actual predictions (not fabricated labels) should be retained in the workflow artifact; model credentials must never be logged.

The hybrid's numeric evidence validation proves only that the model's proposed number is present in a literal quote. It does not verify claim attribution, precise intent, legal status or semantic truth. For instance, a quote containing two numbers may still be ambiguous. D should be held to a higher evidentiary standard than a marketing demo: a successful rule check must not turn missing evidence into PASS.

## Human research

- [Standardized usability protocol](user_test_protocol.md)
- [Blank anonymous feedback template](feedback_template.csv)
- Do **not** publish raw identified participant feedback, private client contracts, contact information, or sensitive commercial details. Create `USER_FINDINGS.md` **only after real, consented participants have actually tested the product**.
- Volunteer usability testing addresses comprehensibility, not professional correctness; expert commercial/legal evaluation is a separate future study.

## Research hygiene

Keep the freeze commit and prompt revision for every experiment. Never tune on a test set and still call it untouched. Preserve incorrect and ambiguous cases, plus any failure to complete an API arm. The strongest HAA evidence is a reproducible engineering decision and transparent negative result, not a superficially high score.
