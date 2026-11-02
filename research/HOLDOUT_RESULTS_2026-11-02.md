# Consigliere AI — Frozen holdout and difficult-language evaluation

**Date:** November 2, 2026  
**Execution:** [GitHub Actions run 41417366999](https://github.com/Serein131/Consigliere-ai/actions/runs/41417366999) — **completed successfully**, 40/40 fresh Gemini predictions and 20/20 prior-challenge Gemini predictions.  
**Model:** `gemini-3.5-flash-lite`, temperature 0, normal task-specific structured JSON prompt.  
**Comparator:** frozen `dealguard.py` deterministic rule engine only; not the full Consigliere AI application.  
**Dataset / rule-engine blobs:** holdout `b2c11298c24e218fd77192d33a74e58a71d1e53e`; rule engine `5ea587a8492ff94fed5e02df1ccb5106606b41b0`.

## Study design and freeze controls

1. Authored **40 new Chinese/English synthetic cases** distinct from the earlier 60-case regression suite. Included revised offers, alternative wording/units, net payment terms, seller/buyer interpretation, conditional exclusivity, and deleted contract terms. **No product parser code was altered based on these cases before the run.**
2. Fixed case IDs and expected rule and commercial risk labels in [frozen_holdout_v1.json](frozen_holdout_v1.json). Two obvious risk-label consistency corrections were committed **before any predictions or rule-engine scoring**; last label freeze commit `8d93f87a82243716bc0ce1453ebcecfd1047fd10`.
3. Preserved the existing DealGuard engine unchanged. Ran a live Google Gemini API call on every case with the same configured thresholds but **without DealGuard code or its predictions**.
4. Evaluated **exact case match** as the entire set of configured rule labels **and** commercial-review flags matching the authored answer, and separately measured violation precision/recall and paired case disagreements.
5. Separately ran Gemini against the **older 20-case challenge suite**; this older set had already been seen in previous research and **must not be called a fresh holdout**.
6. Archived raw model predictions, full per-case CSV, JSON and Markdown reports as two **separate downloadable artifacts** linked from the workflow run. Artifacts expire according to GitHub retention; save copies.

## A. New 40-case frozen synthetic holdout (PRIMARY)

| Metric | Plain Gemini | DealGuard deterministic rules |
|---|---:|---:|
| Exact whole-case agreement with authored labels | **31/40 (77.5%)** | **16/40 (40.0%)** |
| Correct configured rule instances | 39/48 (81.3%) | 25/48 (52.1%) |
| Exact commercial-review flags | 38/40 (95.0%) | 34/40 (85.0%) |
| Detected actual violations (true positives) | 15 | 7 |
| False positive violation calls | 2 | 8 |
| Missed violations (false negatives) | 1 | 9 |
| Violation precision | 88.2% | 46.7% |
| Violation recall | 93.8% | 43.8% |

### Paired outcome (same cases, same labels)

| Pair category | Count |
|---|---:|
| Both systems correct | 13 |
| **Only Gemini correct** | **18** |
| **Only DealGuard correct** | **3** |
| Neither correct | 6 |

### Category-level exact case agreements

| Category | Plain Gemini | DealGuard | Total |
|---|---:|---:|---:|
| Discount | 7 | 3 | 10 |
| Payment | 8 | 4 | 10 |
| Exclusivity | 8 | 5 | 10 |
| Mixed deal terms | 4 | 2 | 6 |
| Commercial-review-only | 4 | 2 | 4 |
| **Total** | **31** | **16** | **40** |

### Representative differences

- **HLD-001**: "12 percent reduction" rather than "12% discount". Expected VIOLATION; DealGuard returned UNKNOWN while Gemini detected the violation.
- **HLD-014**: Chinese "收到发票后第75日付款" requires recognizing the time expression and seller cashflow flag. DealGuard failed to extract the payment term; Gemini matched the authored labels.
- **HLD-023**: The old draft included exclusivity, but the signed revision **removed** it. DealGuard incorrectly called VIOLATION; Gemini returned PASS.
- **HLD-027**: Chinese text states an exclusivity clause was **deleted**. DealGuard still called VIOLATION.
- **HLD-038 / HLD-039**: Removed auto-renewal / termination penalty language triggered false commercial-review flags in DealGuard.
- **HLD-003**: Two conflicting current discount proposals with no final rate; the authored expected state is UNKNOWN. Here **both** systems disagreed with the expected label (DealGuard VIOLATION; Gemini PASS).
- **HLD-009**: A 12-percentage-point oral price reduction remains a proposed term, but Gemini returned UNKNOWN; DealGuard also returned UNKNOWN. The gold interpretation should eventually be reviewed by an independent business annotator.

**All DealGuard case mismatches (24):** HLD-001, HLD-002, HLD-003, HLD-004, HLD-006, HLD-008, HLD-009, HLD-011, HLD-012, HLD-014, HLD-015, HLD-017, HLD-018, HLD-023, HLD-024, HLD-026, HLD-027, HLD-028, HLD-031, HLD-033, HLD-035, HLD-036, HLD-038, HLD-039.

**All Gemini case mismatches (9):** HLD-003, HLD-009, HLD-010, HLD-016, HLD-020, HLD-024, HLD-028, HLD-033, HLD-035.

## B. Older 20-case difficult stress suite (SECONDARY, not new holdout)

| Metric | Plain Gemini | DealGuard |
|---|---:|---:|
| Exact whole-case agreement | **13/20 (65.0%)** | **3/20 (15.0%)** |
| Violation precision | 90.0% | 25.0% |
| Violation recall | 100.0% | 11.1% |

Paired exact matches: both correct 2, only Gemini correct 11, only DealGuard correct 1, neither correct 6.

This older set includes challenging negations, numerical expressions, and removal of liability/renewal terms. Its prior DealGuard score was already known before this paired run, so it is **not independent confirmation** of the new 40-case result.

## Why earlier 60/60 was misleading

The earlier 60-case standard suite was developer-authored and used to fix known parsing failures; achieving **60/60** on those familiar patterns was a good regression result, **not proof of generalization**. On new 40-case holdout-style examples, the same unchanged deterministic checker only matched 16/40, whereas plain Gemini matched 31/40. This reversal is evidence of **brittle surface-form parsing and poor handling of clause state**; it does not establish that Gemini is universally better than a well-designed hybrid system.

## Validity limits — be explicit in HAA work

- All gold labels were created with AI assistance, not independently annotated or legally verified. Some UNKNOWN/PASS distinctions and cashflow-warning thresholds are design choices and could be disputed.
- New cases were authored with knowledge of the product's limitations. They were **unused for tuning but not independently sampled or blinded from the author**.
- The sample is small and deliberately enriched with difficult cases; results are not representative production accuracy, clinical/legal safety, statistical proof of general superiority, or actual user feedback.
- This compares **a standalone deterministic checker** against the **base LLM** with a structured audit instruction. It does *not* yet evaluate the full Consigliere AI + Gemini pipeline as a third system.
- Test was one inference per case at temperature 0; model behavior could still vary.
- More defensible next validation: independent review of ambiguous labels, train/test separation, fresh held-out cases after any parser redesign, and a three-way comparison of **Gemini alone vs. deterministic parser vs. Gemini extraction + deterministic constraint checks**.
- **Do not rewrite or remove incorrect cases after seeing results.** Treat new model revisions as a new experiment with a newly frozen set.

## Recommended v5.2 research hypothesis

Instead of extending ad-hoc regex endlessly, test **Evidence-Grounded Term Extraction**: use an LLM for proposal interpretation and extraction of (amount, unit, buyer/seller role, proposal status, quotation evidence, uncertainty), then use deterministic comparisons only on *validated structured facts*. Require explicit UNKNOWN/manual confirmation when evidence is unclear or terms conflict. Audit unsupported interpretation separately.

Success criterion should include fewer false positives/negatives on genuinely new cases, rather than another 100% score on familiar examples. Changes to DealGuard and any new labels must happen **after** this frozen experiment and be tested using a **different unseen set**.

## Reproducibility and code transparency

- [Preregistered protocol](HELDOUT_PROTOCOL_2026-11-02.md)
- [New 40-case dataset](frozen_holdout_v1.json)
- [Prior 20-case challenge](challenge_cases.json)
- [Paired scoring script](paired_compare.py)
- [Gemini baseline script](run_gemini_baseline.py)
- [GitHub Actions execution and downloadable artifacts](https://github.com/Serein131/Consigliere-ai/actions/runs/41417366999)

**No real commercial clients, outside reviewers, or live legal-contract data were involved.** All cases are fictional. The artifacts and experimental framework were developed with AI coding assistance.
