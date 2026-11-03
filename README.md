# Consigliere AI · Founder DealGuard

**An auditable AI decision-support prototype for startup deal terms.**

[**Try the live demo**](https://consigliere-ai-seven.vercel.app/) · [**Read the research**](research/BENCHMARK.md) · [**Study the implementation**](dealguard.py)

Consigliere AI helps an early-stage founder separate **what the counterparty actually said**, **which explicitly configured rules would be broken**, and **what still needs verification**. It does not execute negotiations, replace lawyers or financial advisers, or guarantee commercial safety.

## Product experience · v5.4 — opt-in Live Assist in the unified workflow

The live web app adds **Protect → Live Assist**, an explicitly authorized, foreground-only automatic alert session. It is off by default. The user checks an independent live-processing notice, chooses **Rules only** (default; sends masked fictional text to this Flask app but not Gemini) or **Gemini evidence + rules** (additionally requires its own Gemini consent), and presses **Start Live Assist**. The app checks typed terms after debouncing and finalized on-demand speech-recognition results; **interim speech, microphone stop, phase transitions and page backgrounding never start an automatic model call**. Results flag configured 10% discount / 45-day payment / no-exclusivity limits with actual evidence when available. Tactical advice still requires a separate user click.

Stopping Live Assist, revoking consent, changing modes, navigating away or backgrounding aborts/invalidates outstanding checks. No persistent monitoring, native iOS background recording, guaranteed response time or independently validated detection accuracy is claimed. Browser speech recognition can use external providers; even rule-only audits send text to the app's server after user authorization.

**New tests:** [headless Live Assist session test](tests/check_v54_live.js), [36-case bilingual synthetic alert challenge](research/live_alert_challenge_v54.json) and [diagnostic report generator](research/evaluate_live_alerts.py). These cases are developer-authored and cannot substitute for independent contract review or real iPad testing. [Reviewer protocol](research/REVIEWER_PROTOCOL_V54.md) explains how to collect independent labels.

## Previous v5.3 foundation — one unified three-stage flow

**One set of structured deal guardrails. One editable note/transcript box. One top-level 01 → 02 → 03 navigation.**

| Stage | What the user does | What the system does |
|---|---|---|
| **01 · Prepare** | Enter personal goals, preferences and explicit commercial thresholds. Optionally add fictional meeting context. | Provides optional pre-meeting strategy and reminder drafts using the user's configured rules. |
| **02 · Protect** | Type/paste deal text **or actively start browser speech-to-text**. Review the transcript and press either **AI evidence + rule check** or **Rules only**. | Gemini can extract term candidates with verbatim source excerpts, validated by Python before deterministic discount/payment/exclusivity checks. Separate commercial flags and **UNKNOWN** remain visible. User may then explicitly request a tactical question. |
| **03 · Debrief** | Enter post-meeting notes or dictate a brief voice memo into the **same input field**. | Optionally drafts a commitment review, follow-up email and next steps using previous phase summaries if those were generated. It never sends email automatically. |

Each stage keeps its own draft **in the current browser page's memory** during switching. It is **not** a persistent account or long-term-memory service: refreshing or closing the page can lose this session. Stage 1 thresholds are reused in all stages. Only the active stage's controls are displayed, so the app no longer has two overlapping sets of numbered workflows or duplicate deal text boxes.

### One-minute fictional demonstration

1. Open the [web app](https://consigliere-ai-seven.vercel.app/) and, in **01 Prepare**, set *Seller*, maximum discount **10%**, maximum payment window **45 days** and *No exclusivity*. Set a goal and personal decision reminders.
2. Select **02 Protect**, choose **Load 3-conflict example**, or type a fictional offer such as *“The buyer requires 15% discount, net 90 days and 12-month exclusivity.”*
3. Choose **Rules only** for a zero-model check, or review and accept the processing notice before **AI evidence + rule audit**. Inspect quoted terms, per-rule statuses, separate cashflow concerns, and unresolved facts.
4. Optionally click **Generate tactical counter-question** (a **separate** user-authorized AI strategy request).
5. Switch to **03 Debrief**, optionally dictate a fictional 60-second memo, and ask the strategy assistant to draft a follow-up. Your Stage 2 text is retained if you switch back during the same page session.

### Voice transcription and privacy boundaries

Speech-to-text remains a valuable **opt-in input mode** in Protect and Debrief, next to normal typing. It is intentionally **not a continuous, background-recording agent**:

- You must check an explicit transcription-permission notice and grant the browser's microphone permission before manually starting.
- Transcribed speech appears in the **same stage editor**, alongside any text already typed. You can edit or delete it.
- **Stopping speech, encountering silence, or switching stages never automatically calls Gemini or initiates advice.** A separate Analyze button and consent gate are required for every AI pathway. Stage changes stop transcription.
- Browser Web Speech API availability and privacy depend on the browser and provider; transcription may be remotely processed. Regex redaction of text is incomplete. **Only fictional examples** should be used in this public prototype.
- Drafts, stage summaries and checkboxes are not permanent account storage. The current product does not implement native iOS background listening, SMS interception, real-time push alerts or automatic email sending.

### Engineering and reproducibility

```text
01 Prepare  →  shared explicit thresholds + goals
                         │
02 Protect  →  ONE user-controlled editor ← optional live speech-to-text
                         │
                ┌────────┴─────────┐
                │                  │
           Rules only         Optional Gemini
                │             term extraction
                │                  ↓
                │             quoted evidence
                │                  ↓
                └────── deterministic checks
                               │
                 PASS / VIOLATION / UNKNOWN
                   + commercial review
                               │
                 optional tactical AI request
                         │
03 Debrief → same editor, different draft → optional reflection and follow-up
```

The source of the optional Gemini extractor is [hybrid_service.py](hybrid_service.py), the evidence validator is [research/evidence_hybrid.py](research/evidence_hybrid.py), and server endpoints remain `/hybrid-audit`, `/audit` and `/analyze`. The strategy endpoint remains **distinct from the hybrid evidence audit**: the tactical draft should not be described as independently verified by the quote validator.

Tests include Flask consent/redaction/UNKNOWN behavior, **Node simulated-browser UI tests** ([tests/check_v53_browser.js](tests/check_v53_browser.js)) of all three stages, consent and speech-to-text controls, and a previous [single fictional live Gemini smoke test](https://github.com/Serein131/Consigliere-ai/actions/runs/41443685466). These are software functional tests, **not** expert domain accuracy or user retention studies. See [v5.3 workflow and privacy notes](research/PRODUCT_WORKFLOW_V53.md).

## Key experimental finding

The current regex-based engine matched **60/60 familiar development examples** after targeted fixes, but only **16/40 new difficult synthetic cases**, while a plain Gemini API benchmark matched **31/40** on those same new cases. The result exposes a generalization problem and motivates the hybrid architecture.

These are fictional, AI-assisted scenarios with **non-independent labels**, not verified contract accuracy. The **[three-system experiment](research/THREE_SYSTEM_RESULTS.md)** compared Gemini directly, deterministic DealGuard, and the evidence-grounded hybrid on 24 frozen synthetic cases. Across two runs, Gemini scored **21/24 then 22/24**, DealGuard **11/24**, and the hybrid **22/24 in both**. The initial one-case hybrid advantage disappeared on repetition. An optional GPT comparison was attempted but produced **zero valid predictions** because the OpenAI API balance was exhausted; it has been **dropped from the active research scope**, with the failed attempt preserved for transparency. No payment or GPT experiment is required. The original benchmark evaluates the research implementation. v5.3 presents the already-tested hybrid API in a single Prepare / Protect / Debrief browser workflow; new language-domain accuracy has not been established by the interface redesign.

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
| [tests/](tests/) | Deterministic, hybrid-service, privacy, endpoint and browser-flow checks |
| [research/PRODUCT_WORKFLOW_V53.md](research/PRODUCT_WORKFLOW_V53.md) | Unified product architecture, UX and privacy limitations |

Actual participant responses are not published. A public `USER_FINDINGS.md` will be created only if real consent-based sessions have been completed.

## Verify code locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node tests/check_v53_browser.js
python app.py
```

The standalone `/audit` endpoint performs rule checks without invoking Gemini. `/hybrid-audit` makes a real provider call only when the user explicitly confirms the consent checkbox. A server-side `GEMINI_API_KEY` is required; no API key is exposed to browser JavaScript. Set `ENABLE_HYBRID_AUDIT=false` in the deployment environment to disable AI auditing instantly without disabling rules-only mode. The `/analyze` strategy workflow is a separate user-authorized AI call; its output is not automatically evidence-verified by the hybrid audit. OpenAI GPT API funding is not required.

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
