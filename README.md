# Consigliere AI · Founder DealGuard

**An auditable AI decision-support prototype for startup deal terms.**

[**Try the live demo**](https://consigliere-ai-seven.vercel.app/) · [**Read the research**](research/BENCHMARK.md) · [**Study the implementation**](dealguard.py)

Consigliere AI helps an early-stage founder separate **what the counterparty actually said**, **which explicitly configured rules would be broken**, and **what still needs verification**. It does not execute negotiations, replace lawyers or financial advisers, or guarantee commercial safety.

## One-minute demo

1. Select **Seller**, maximum discount **10%**, maximum buyer payment window **45 days**, and **no exclusivity**.
2. Enter a **fictional** counterparty proposal: "We require a 15% discount, net 90-day payment terms and an exclusivity agreement."
3. Run the deterministic DealGuard audit. It should flag discount, payment timing and exclusivity as rule conflicts, while discussing 90-day receivables as a **separate** seller cashflow risk.
4. Try a proposal you explicitly rejected. A historical or rejected term must not automatically become a current binding deal.

The public demo contains a three-stage negotiation workflow (pre-meeting planning, on-demand discussion review, post-meeting debrief). The newer evidence-grounded **hybrid system is currently experimental research code**; it has **not** replaced the production engine.

## Architecture

```text
User-defined goals + structured deal rules
                  │
        Current product v5.1
   Input → regex extraction → deterministic checks
                  │
         Risk / UNKNOWN / evidence
                  │
          Gemini-assisted advice
```

**Research direction:** Instead of trusting a language model's unsupported rule judgment, test whether **Gemini term extraction → verbatim evidence validation → deterministic threshold checks** improves reliability. That is a separate, testable hybrid path in [research/evidence_hybrid.py](research/evidence_hybrid.py).

## Key experimental finding

The current regex-based engine matched **60/60 familiar development examples** after targeted fixes, but only **16/40 new difficult synthetic cases**, while a plain Gemini API benchmark matched **31/40** on those same new cases. The result exposes a generalization problem and motivates the hybrid architecture.

These are fictional AI-assisted scenarios with **non-independent labels**. They are *not* validated contract accuracy or proof that one provider universally wins. The next [four-group benchmark](research/BENCHMARK.md) tests Gemini, an OpenAI GPT model, deterministic DealGuard, and the evidence-grounded hybrid. Only actually executed model groups will receive measured scores.

## Repository guide

| Entry | Purpose |
|---|---|
| [research/BENCHMARK.md](research/BENCHMARK.md) | Results, comparison design and honest limitations |
| [research/EVALUATION.md](research/EVALUATION.md) | Scoring rules, reproducibility and four-arm methodology |
| [research/cases/](research/cases/) | Synthetic case catalog (familiar, challenging, frozen) |
| [research/user_test_protocol.md](research/user_test_protocol.md) | Consent-based 5–8 minute usability test plan |
| [research/feedback_template.csv](research/feedback_template.csv) | Blank anonymous feedback form; **not collected responses** |
| [research/HOLDOUT_RESULTS_2026-11-02.md](research/HOLDOUT_RESULTS_2026-11-02.md) | Full negative-result evidence, errors and dataset freeze |
| [tests/](tests/) | Deterministic checks and evidence-validator regression tests |

Actual participant responses are not published. A public `USER_FINDINGS.md` will be created only if real consent-based sessions have been completed.

## Verify code locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python app.py
```

The standalone `/audit` endpoint performs rule checks without invoking Gemini. API-driven experiment runners in `research/` require separate provider credentials and are not needed for normal code tests.

## Known limitations and privacy

- Unstructured contract language, negation, multiple counterparties and changing terms can defeat the current parser.
- `PASS` means *the checked rule passed*, not that the whole deal is good; missing evidence means `UNKNOWN`.
- Commercial-risk warnings are heuristics, not a legal opinion.
- Regex sanitization is **not** comprehensive privacy protection; do not upload real confidential contracts to the public demo.
- Browser speech recognition can depend on external providers; obtain recording consent where required.
- No real founder usability study, domain-expert validation, commercial adoption or retention results are claimed.
- The project includes **AI-assisted implementation and AI-assisted synthetic test authoring**. Personal product decisions and actual work should be described accurately in any application.

## Purpose

This repository is both a working early prototype and a transparent record of its failures, experiments and next research steps. Rather than marketing 100% accuracy, the goal is an **explainable commitment firewall** whose uncertainty and evidence can be inspected.
