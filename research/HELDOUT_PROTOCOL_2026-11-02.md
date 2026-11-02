# Frozen evaluation protocol — 2 Nov 2026

This test is deliberately designed to avoid tuning DealGuard to the examples before measuring it.

## Freeze record

- Holdout dataset: `research/frozen_holdout_v1.json`, 40 **new synthetic cases**, committed before model inference or rule-engine scoring.
- Dataset freeze commit: `8d93f87a82243716bc0ce1453ebcecfd1047fd10`, after two *pre-run* risk-label consistency corrections.
- Prior challenge dataset: `research/challenge_cases.json`, 20 **previously inspected** cases; these are **not** a new holdout.
- Rule engine: existing `dealguard.py` inherited unchanged from the pre-experiment `main` version; do not modify during this experiment.
- Baseline prompt/model: existing `research/run_gemini_baseline.py` prompt and `gemini-3.5-flash-lite` temperature 0, unchanged; only command-line dataset selection is added.
- Gold labels: assistant-authored before scoring, *not* independently expert-adjudicated; possible ambiguities must be declared rather than silently edited later.

## Two distinct analyses

1. **New holdout (40 cases)**: English/Chinese; discounts, buyer/seller payment direction, exclusivity, multiple clauses and commercial risk flags.
2. **Previously known challenge (20 cases)**: a harder stress test that was already run on DealGuard alone. Run Gemini now on the same cases, but **do not pool these with the new holdout**.

Compare full case-level exact agreement and wrong-rule state (including UNKNOWN), false violations, missed violations, extra unconfigured rules, commercial flags and paired disagreements. Report raw predictions, exact case IDs and failures for BOTH systems.

## Threats to validity

- Dataset author and labels share assumptions with the system designer. This is **not independent adjudication**.
- Only 40 newly written cases. Not representative of real negotiated contracts and not a statistical estimate of deployed product accuracy.
- Comparison uses identical authored inputs and fixed model parameters. Gemini has no access to DealGuard's source code or its predictions.
- The **deterministic checker**, not the complete cloud-AI system, is being compared with Gemini. This should not be called an end-to-end agent comparison.
- A PASS/UNKNOWN label depends on how the proposal is interpreted; borderline examples require independent review.
- No scoring code, model or labels may be edited during the run. Future improvements require **another new holdout**.
- API requests may use quota/fees; only sanitized, fictional cases are sent.

## Reproducibility

Actual Gemini predictions and paired per-case CSV, JSON and Markdown will be attached to the GitHub Actions evaluation run as artifacts (subject to GitHub retention). A checksum of the frozen dataset and DealGuard source will be logged before executing both comparators.
