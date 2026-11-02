# Benchmark methods and reporting boundaries

## What is already measurable
- `synthetic_cases.json`: 60 authored synthetic deal snippets, with pre-specified expected rule states and optional commercial-risk flags. 14 discount, 14 payment, 14 exclusivity, 12 commercial-only, 6 mixed.
- `evaluate.py`: checks the deterministic DealGuard against those labels; produces markdown/JSON reports and enumerates failures.
- `run_gemini_baseline.py`: optional external Gemini comparison using the **same proposals and explicit rules**. It only runs if you supply your own key in an environment variable.

Synthetic fixtures are developer-authored; they are **not independent labels**, and may be biased toward the engine's patterns. This is a smoke/regression benchmark, not a validated model evaluation, academic result, or proof of accuracy. Correctness should eventually be adjudicated by independent reviewers.

## Run the deterministic benchmark
```bash
python research/evaluate.py
```
Files generated: `research/benchmark_report.md` and `research/benchmark_report.json`. The GitHub Actions evaluation workflow will also generate reports as downloadable artifacts, without running Gemini.

## Optional generic Gemini baseline — do not paste your API key into chat

From a private local development terminal or Codespace:
```bash
export GEMINI_API_KEY="YOUR_KEY_FROM_GOOGLE_AI_STUDIO"
export GEMINI_MODEL="YOUR_WORKING_GEMINI_MODEL"
python research/run_gemini_baseline.py --limit 10
```
**Never commit `baseline_predictions.json` if it might later contain private data; the existing benchmark cases are synthetic.** Model API requests consume quota and may incur charges. Use a working model name for your account. No API key is stored in the results.

After the baseline runner completes a full set of 60 (or for a subset when appropriately filtered):
```bash
python research/run_gemini_baseline.py --limit 60
python research/evaluate.py --baseline-predictions research/baseline_predictions.json --output research/gemini_baseline_report.md --json research/gemini_baseline_report.json
```
Do not claim a generic Gemini comparison has occurred until requests were executed and predictions logged. Don't choose only favorable cases for public comparison.

## Evaluation metrics
- **Exact case match**: all configured rule states and commercial flags matched labels on a case.
- **Rule state accuracy**: exact match of PASS/VIOLATION/UNKNOWN on each configured rule.
- **Violation precision and recall**: true detections, false alarms, misses.
- **Commercial risk matches**: exact equality of expected warning codes.

If metrics are poor, report those failures. A 100% score on synthetic templates is not meaningful proof of production reliability.

## Better experiment after the deadline
Create a held-out collection of **unseen**, independently labeled realistic snippets, ideally with an experienced contracts/purchasing reviewer, and pre-register expected labels before examining predictions. Compare baseline vs. DealGuard paired on exactly the same cases. Audit difficult negations, revisions and multiple-party attribution. Report uncertainties and limitations.

## HAA evidence statement: safe format

"Built a deterministic commercial-constraint checker and an independent test harness with 60 synthetic bilingual scenarios. The automated regression test suite passed. The synthetic evaluation showed [fill in actual measured result], while [fill in real errors]. We have not yet validated legal outcomes or real commercial negotiation performance."

For a 1-minute demo, show a case violating three preset rules, a rejected offer that is not a live violation, and commercial risk that exists despite explicit rule compliance.
