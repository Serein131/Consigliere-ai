# Consigliere AI · Founder DealGuard

**An auditable AI decision-support prototype for startup deal terms.**

[**Try the live demo**](https://consigliere-ai-seven.vercel.app/) · [**Read the research**](research/BENCHMARK.md) · [**Study the implementation**](dealguard.py)

Consigliere AI helps an early-stage founder separate **what the counterparty actually said**, **which explicitly configured rules would be broken**, and **what still needs verification**. It does not execute negotiations, replace lawyers or financial advisers, or guarantee commercial safety.

## Live product experience · v5.2

This release adds an **optional hybrid deal audit to the same web interface** while preserving the existing free **Rules only** check and three-stage negotiation assistant. The hybrid uses **Gemini for language extraction** and **Python for evidence-gated rule decisions**; it is not a new GPT/OpenAI API dependency.

### One-minute synthetic demo

1. Select **Seller** and configure a maximum discount **10%**, maximum payment window **45 days**, and **no exclusivity**.
2. Use **Load 3-conflict example**, or enter the entirely fictional offer: "Buyer requires 15% discount, payment terms 90 days and 12-month exclusivity."
3. To use AI mode, acknowledge the model-processing notice, then select **AI extraction + rule audit**. For a no-model comparison select **Rules only · no Gemini**.
4. Review the three separate outputs: **term source quotes**, **per-rule PASS / VIOLATION / UNKNOWN**, and **commercial risks**. A quote only proves literal text was found, not semantic accuracy.
5. Try **Load rejected-offer example**. When a term was rejected or the proposal is ambiguous, the correct behavior may be **UNKNOWN**, not an invented safe result.
6. **Use proposal in three-stage strategy assistant** transfers text to the existing pre/in/post workflow; this stage is still a separate, legacy AI assistant, not the hybrid audit.

The hybrid frontend is bilingual (English/简体中文), responsive, preserves an explicit no-model fallback, invalidates stale results after edits, and handles quota/unavailable-model errors without claiming a successful audit.

### Architecture and integration

```text
Fictional proposal + user's structured thresholds
                   │
      ┌────────────┴─────────────┐
      │                          │
 Rules only                  Hybrid (opt-in)
 regex extraction            masked text → Gemini
 + deterministic comparison      ↓
      │                   candidate terms and quotes
      │                          ↓
      │                  exact-text / number check
      │                          ↓
      └────────────┬────── deterministic constraints
                   │
        PASS / VIOLATION / UNKNOWN
            + separate cashflow flags
                   │
      optional handoff to 3-stage copilot
```

Hybrid implementation: [hybrid_service.py](hybrid_service.py), [research/evidence_hybrid.py](research/evidence_hybrid.py), `POST /hybrid-audit`. Original `POST /audit` and `POST /analyze` remain available.

**Actual API validation:** A GitHub Actions [one-case Gemini smoke run](https://github.com/Serein131/Consigliere-ai/actions/runs/41443685466) returned three cited source terms and three rule violations for a fictional case. All mock API, consent, redaction, legacy audit, and JavaScript syntax checks passed. This is *not* a production load test, full browser-interaction test or expert accuracy validation.

## Key experimental finding

The current regex-based engine matched **60/60 familiar development examples** after targeted fixes, but only **16/40 new difficult synthetic cases**, while a plain Gemini API benchmark matched **31/40** on those same new cases. The result exposes a generalization problem and motivates the hybrid architecture.

These are fictional, AI-assisted scenarios with **non-independent labels**, not verified contract accuracy. The **[three-system experiment](research/THREE_SYSTEM_RESULTS.md)** compared Gemini directly, deterministic DealGuard, and the evidence-grounded hybrid on 24 frozen synthetic cases. Across two runs, Gemini scored **21/24 then 22/24**, DealGuard **11/24**, and the hybrid **22/24 in both**. The initial one-case hybrid advantage disappeared on repetition. An optional GPT comparison was attempted but produced **zero valid predictions** because the OpenAI API balance was exhausted; it has been **dropped from the active research scope**, with the failed attempt preserved for transparency. No payment or GPT experiment is required. The original benchmark evaluates the research implementation. v5.2 exposes the hybrid workflow in the web app; public Vercel deployment status must still be verified separately.

## Repository guide

| Entry | Purpose |
|---|---|
| [research/BENCHMARK.md](research/BENCHMARK.md) | Research overview, historical reversals and study design |
| [research/THREE_SYSTEM_RESULTS.md](research/THREE_SYSTEM_RESULTS.md) | **Main three-system study**, results, replication and limits |
| [research/FOUR_ARM_RESULTS.md](research/FOUR_ARM_RESULTS.md) | Detailed historical four-arm attempt, including the uncompleted GPT group |
| [research/EVALUATION.md](research/EVALUATION.md) | Scoring rules, reproducibility and four-arm methodology |
| [research/cases/](research/cases/) | Synthetic case catalog (familiar, challenging, frozen) |
| [research/user_test_protocol.md](research/user_test_protocol.md) | Consent-based 5–8 minute usability test plan |
| [research/feedback_template.csv](research/feedback_template.csv) | Blank anonymous feedback form; **not collected responses** |
| [research/HOLDOUT_RESULTS_2026-11-02.md](research/HOLDOUT_RESULTS_2026-11-02.md) | Full negative-result evidence, errors and dataset freeze |
| [tests/](tests/) | Deterministic, hybrid-service, privacy, endpoint and web script checks |

Actual participant responses are not published. A public `USER_FINDINGS.md` will be created only if real consent-based sessions have been completed.

## Verify code locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python app.py
```

The standalone `/audit` endpoint performs rule checks without invoking Gemini. `/hybrid-audit` makes a real provider call only when the user explicitly confirms the consent checkbox. A server-side `GEMINI_API_KEY` is required; no API key is exposed to browser JavaScript. Set `ENABLE_HYBRID_AUDIT=false` in the deployment environment to disable AI auditing instantly without disabling rules-only mode. The older `/analyze` stage has its own AI workflow. OpenAI GPT API funding is not required.

## Known limitations and privacy

- Unstructured contract language, negation, multiple counterparties and changing terms can defeat the current parser.
- `PASS` means *the checked rule passed*, not that the whole deal is good; missing evidence means `UNKNOWN`.
- Commercial-risk warnings are heuristics, not a legal opinion.
- Regex sanitization is **not** comprehensive privacy protection; do not upload real confidential contracts to the public demo.
- Browser speech recognition can depend on external providers; obtain recording consent where required.
- A source quote being present does not prove the right party, term status or meaning was inferred. No real founder usability study, domain-expert validation, commercial adoption or retention results are claimed.
- Public AI routes can consume Gemini API quota; per-request size and timeout limits are not a substitute for production authentication and persistent server-side rate limits.
- The project includes **AI-assisted implementation and AI-assisted synthetic test authoring**. Personal product decisions and actual work should be described accurately in any application.

## Purpose

This repository is both a working early prototype and a transparent record of its failures, experiments and next research steps. Rather than marketing 100% accuracy, the goal is an **explainable commitment firewall** whose uncertainty and evidence can be inspected.
