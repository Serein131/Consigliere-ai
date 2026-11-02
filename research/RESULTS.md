# Consigliere AI — Evidence & Iteration Log

**Date:** 2026-11-02. All cases below are **synthetic, developer-authored**. No real participant responses, domain-expert validation, or real-contract performance measured.

## 1. Reproducible deterministic audit results

| Stage | Cases with all expected rule/risk labels matched | Rule-state matches | Violation precision | Violation recall | Commercial-risk exact |
|---|---:|---:|---:|---:|---:|
| Initial standard suite (before three specific bug fixes) | 57/60 | 57/60 | 94.7% | 90.0% | 60/60 |
| Same standard suite after targeted fixes | 60/60 | 60/60 | 100.0% | 100.0% | 60/60 |
| Separate difficult challenge suite, **before any tuning on it** | **3/20** | **3/18** | **25.0%** | **11.1%** | **18/20** |

CI evidence: [GitHub Actions run with both suites](https://github.com/Serein131/Consigliere-ai/actions/runs/41409885308). The downloadable action artifact includes both machine-readable and Markdown failure reports. Standard suite results after fixes are in the same run.

### Why the numbers differ

The first 60 scenarios are small, relatively formulaic, user-authored test fixtures. We modified the engine specifically after three failures (`DG-004`, `DG-014`, `DG-042`): English 'reduce price', Chinese '价格下调', and '尚未讨论排他问题'. Re-running the **same** tests reached 60/60. **This is regression success, not evidence of generalization.**

The separate 20-case challenge set contains harder language: alternative price expressions, written-out numbers, counteroffers in a single sentence, ambiguous future exclusivity, 'net 90', and removed/negated liability or auto-renewal clauses. These tests surfaced **17 case-level mismatches**. This highlights missing semantic understanding and contextual clause attribution in a regex-only approach. Some manually assigned labels require independent review.

**Important:** The 3/20 challenge figure is also *not* a measured production accuracy estimate, because the set was intentionally hard and synthetic. Neither dataset is an unbiased sample of real negotiation tasks.

## 2. What has NOT been measured

- No executed ordinary-Gemini baseline. `run_gemini_baseline.py` is a preparation tool; it requires a key, a working model and explicit opt-in to API costs.
- No completed real-user usability test; no user quotes or satisfaction ratings.
- No commercial legal-reviewer judgments or contract accuracy accreditation.
- No reliable production latency distribution, privacy zero-retention verification, or revenue.

## 3. Next independent experiment

1. Freeze the challenge-set labels, have at least two independent annotators review ambiguous cases without seeing engine predictions, and log disagreements.
2. Improve the proposal interpretation layer (numeric spans, time ordering, party attribution, negation scope); require explicit user confirmation when confidence is low.
3. Collect a genuinely new **holdout** of 30 unseen cases *after* changes; do not tune on those labels.
4. Run generic Gemini on identical frozen inputs/structured rules using optional script; compare per-case outcomes and abstentions.
5. Conduct 3–5 opt-in usability sessions with fictional deals; keep their findings separate from expert judgments.

## 4. How to report it in a portfolio

Suitable: 'I created a 60-case bilingual synthetic regression suite and a separate 20-case challenge set. After fixing three identified parsing errors, the original tests all passed. The harder set exposed major limits in the regex-only approach, motivating a more context-aware extraction layer.'

Unsuitable: 'DealGuard is 100% accurate' or 'verified better than Gemini' or 'tested by real founders.'

All recorded numbers should be traceable to committed fixtures, code version and CI run. The benchmark was created with AI assistance and has not received independent professional validation.
