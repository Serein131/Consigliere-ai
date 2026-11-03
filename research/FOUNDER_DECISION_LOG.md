# Founder Decision Log — Consigliere AI

**Project:** [Consigliere AI v5.4](https://consigliere-ai-seven.vercel.app/) · **Prepared:** November 3, 2026  
**Purpose:** Explain the founder's product judgments, engineering experiments, changes of direction, and unresolved risks to HAA reviewers.  
**Status:** Evidence-backed draft for founder review, **not** an independently verified personal diary.

> **Authorship note:** This record reconstructs decisions from the founder's stated motivations and documented human–AI development process. GitHub proves that work and tests exist, but it does not independently establish who first proposed every technical option. Before submitting, the founder should confirm each first-person attribution and adjust anything that overstates personal involvement.

## Founder thesis

I repeatedly prepared for negotiations involving my interests, yet under pressure overlooked risky terms and conceded more than I intended. I wanted more than an AI that could explain my mistakes afterward: a **cognitive exoskeleton** that could help me recognize a dangerous concession *before* I agreed. I began building **Consigliere AI** for founders dealing with customer contracts, supplier terms, and partnerships.

The core hypothesis is not that my underlying model is smarter than ChatGPT or Gemini. It is that **persistent-within-session, explicit deal limits + evidence-linked auditing + a timely, permission-based workflow** might make important risks harder to miss. This is a product hypothesis, not yet a demonstrated real-world outcome.

## Decision 01 — Focus on a decision moment, not a generic AI chat interface

**Question:** What specific failure should the product prevent?

**Choice:** Organize the experience around **Prepare → Protect → Debrief**: define limits before a meeting, examine terms while negotiating, then reconcile commitments afterward. Keep the user's ability to accept or reject advice.

**Why:** A fluent retrospective explanation cannot undo an impulsive concession. A domain-specific workflow can surface the user's own constraints at the moment they become relevant.

**Trade-off:** This is deliberately narrower than a general autonomous chief-of-staff or a fully automated negotiator.

**Evidence:** [Live app](https://consigliere-ai-seven.vercel.app/) · [v5.3 unified workflow, PR #19](https://github.com/Serein131/Consigliere-ai/pull/19).

**Still unproven:** That this workflow improves actual decision quality, versus a well-configured general-purpose AI.

## Decision 02 — Make negotiable limits explicit and machine-checkable

**Question:** How can a system check a founder's commercial boundaries without inventing preferences?

**Choice:** Start with three configurable controls: maximum discount, payment-term threshold and direction, and prohibited exclusivity. Treat the founder's free-text goals and personality reminders as context, **not silently enforceable rules**. Keep **VIOLATION**, **PASS**, and **UNKNOWN** distinct.

**Why:** An auditable warning requires an explicit rule and supporting evidence. Silence or ambiguity must not become a “safe” result.

**Trade-off:** Three rule families cannot represent every contractual risk, and a PASS on one rule is not an assessment of overall legal or commercial safety.

**Evidence:** [Original DealGuard checker, PR #1](https://github.com/Serein131/Consigliere-ai/pull/1) · [structured rules and context corrections, PR #3](https://github.com/Serein131/Consigliere-ai/pull/3) · [dealguard.py](https://github.com/Serein131/Consigliere-ai/blob/main/dealguard.py).

## Decision 03 — Test beyond familiar examples, even when the result is worse

**Question:** Was the first deterministic rules-only approach actually generalizing?

**Choice:** Compare it with Gemini on new, frozen synthetic negotiations rather than relying on familiar examples previously used to repair the checker.

**Observed result:** The rules-only system matched **60/60 familiar development examples**, but just **16/40 unfamiliar difficult synthetic cases**; Gemini matched **31/40** on that *same* unfamiliar set.

**What changed in my thinking:** Regex and fixed patterns are interpretable but brittle around paraphrases, negation, chronology, and conditional offers. The familiar 60/60 was not a defensible claim of production accuracy.

**Trade-off:** The new examples were still synthetic and AI/developer-authored, with no independent contract-expert ground truth.

**Evidence:** [60-case comparison, PR #10](https://github.com/Serein131/Consigliere-ai/pull/10) · [frozen 40-case comparison, PR #11](https://github.com/Serein131/Consigliere-ai/pull/11) · [holdout results](https://github.com/Serein131/Consigliere-ai/blob/main/research/HOLDOUT_RESULTS_2026-11-02.md).

## Decision 04 — Separate language understanding from rule enforcement

**Question:** How can natural-language understanding improve without letting the model invent the user's bottom lines?

**Choice:** Experiment with a **hybrid architecture**. Gemini extracts candidate deal terms, clause states, and literal source quotes; a validator checks evidence; deterministic code applies explicitly configured limits. If evidence is insufficient or unsupported, the result can remain UNKNOWN.

**Why:** The model can help interpret varied wording while the checker retains a reproducible link between a quoted term and a configured threshold.

**Trade-off:** Quote matching does **not** prove the model interpreted an offer, condition, or legal obligation correctly. A fabricated quote may be rejected by the evidence gate, but rejection can also cause a true violation to be missed.

**Evidence:** [research architecture, PR #12](https://github.com/Serein131/Consigliere-ai/pull/12) · [evidence validator](https://github.com/Serein131/Consigliere-ai/blob/main/research/evidence_hybrid.py) · [product hybrid endpoint, PR #17](https://github.com/Serein131/Consigliere-ai/pull/17).

## Decision 05 — Report results without claiming a model advantage the data does not show

**Question:** Does the hybrid *outperform* direct Gemini judgment?

**Choice:** Repeat the comparison, retain failures, and report all three measured systems rather than presenting a favorable first result alone.

**Observed result on one frozen 24-case synthetic set:**

| System | First execution | Repeat |
|---|---:|---:|
| Gemini direct | 21/24 | 22/24 |
| Deterministic DealGuard | 11/24 | 11/24 |
| Evidence-grounded hybrid | 22/24 | 22/24 |

**Conclusion:** The hybrid had a one-case advantage over Gemini on the first run; **it disappeared on repetition**. This study does **not** establish superior accuracy. These 24-case scores must not be treated as a before/after improvement over the separate 40-case experiment.

**Trade-off:** Better traceability and rule enforcement may justify extra computation, cost, and latency, but their actual value for founders still needs testing.

**Evidence:** [three-system results](https://github.com/Serein131/Consigliere-ai/blob/main/research/THREE_SYSTEM_RESULTS.md) · [full error analysis](https://github.com/Serein131/Consigliere-ai/blob/main/research/FOUR_ARM_RESULTS.md) · [published measurements, PR #14](https://github.com/Serein131/Consigliere-ai/pull/14).

**Scope decision:** An attempted optional OpenAI/GPT comparison produced **zero valid predictions** because API credit was exhausted. Rather than invent or pay for an unmeasured fourth system, I kept the portfolio focused on the three systems actually tested. [Decision record, PR #16](https://github.com/Serein131/Consigliere-ai/pull/16).

## Decision 06 — Simplify the interface around one actual workflow

**Question:** Could a founder understand and use the prototype during a stressful conversation?

**Choice:** Consolidate duplicate stage navigation into one **01 Prepare / 02 Protect / 03 Debrief** flow. Reuse a single visible input editor while keeping different drafts in page memory. Carry structured limits across all stages and support English/Chinese labels.

**Why:** A negotiation aid should reduce interaction overhead, not demand that users navigate several conflicting text fields.

**Trade-off:** This is **session memory**, not durable cross-device or long-term personal memory. Reloading the page can lose drafts.

**Evidence:** [v5.3 unified UX, PR #19](https://github.com/Serein131/Consigliere-ai/pull/19) · [workflow and privacy contract](https://github.com/Serein131/Consigliere-ai/blob/main/research/PRODUCT_WORKFLOW_V53.md).

## Decision 07 — Add proactive alerts, but only with explicit authorization

**Question:** How could the prototype move beyond “ask the AI a question” without intrusive, passive meeting surveillance?

**Choice:** Release **v5.4 Live Assist**: a founder explicitly starts a foreground monitoring session; the default is rule-only checking on typed text or **finalized, voluntarily transcribed** speech. Gemini evidence mode needs additional, separate consent. Backgrounding, stage changes, stop, and permission revocation cancel or invalidate automatic checks. Tactical strategy remains separately user-triggered.

**Why:** The value proposition requires timely risk surfacing, but privacy, human control, and honest technical claims are product requirements rather than afterthoughts.

**Trade-off:** This is **not** native iOS background monitoring, guaranteed sub-two-second response, a full-room listener, or a persistent autonomous agent. Browser speech recognition may use third-party processing; masking is incomplete.

**Evidence:** [Live Assist implementation, PR #20](https://github.com/Serein131/Consigliere-ai/pull/20) · [consent wording refinement, PR #21](https://github.com/Serein131/Consigliere-ai/pull/21) · [CI run: unit + simulated browser tests](https://github.com/Serein131/Consigliere-ai/actions/runs/41613957651).

## Decision 08 — Measure failures, not just demos, before inviting real deals

**Question:** How often do proactive rule alerts miss obvious danger or alarm on a non-dangerous case?

**Choice:** Freeze an additional **36 bilingual, developer-authored synthetic cases** and report risk recall, precision, false positives, and UNKNOWN handling. Publish a separate protocol for independent blinded evaluation and real-device usability.

**Observed rules-only diagnostic:**
- Expected risk correctly alerted: **12/15 (80% recall)**.
- False risk alerts among all 21 cases without an expected risk alert: **2/21 (9.5%)**.
- Risk alert precision: **12/14 (85.7%)**.
- Cases expected to be UNKNOWN and actually marked UNKNOWN: **9/11**.

**Interpretation:** These results reveal both misses and false alerts. They are **not** independent domain accuracy estimates and do not measure Gemini hybrid mode, genuine conversations, end-to-end voice latency, or decision outcomes.

**Evidence:** [frozen challenge](https://github.com/Serein131/Consigliere-ai/blob/main/research/live_alert_challenge_v54.json) · [evaluation code](https://github.com/Serein131/Consigliere-ai/blob/main/research/evaluate_live_alerts.py) · [CI with generated diagnostic artifact](https://github.com/Serein131/Consigliere-ai/actions/runs/41613957651).

## How I worked with AI — and what “I built” means

- **Founder-originated motivation and direction:** I identified the negotiation regret problem and articulated the private-strategist / cognitive-exoskeleton vision. I prioritized an iPhone/iPad-usable bilingual prototype, explicit commercial boundaries, and consent-based intervention.
- **Human–AI development process:** I used AI assistance to propose approaches, draft and revise substantial amounts of implementation code, set up tests, prepare research write-ups, and operate GitHub/Vercel workflows. I should **not** imply I hand-coded every system component.
- **What the repository independently establishes:** The code, test files, frozen datasets, CI outcomes, pull requests and deployed app exist. Their presence does not, by itself, prove who originated each idea or that real users benefited.
- **Founder review required:** Before an application or interview, I will verify which architecture proposals, acceptance criteria and test decisions I personally initiated, accepted, rejected or revised, and describe those contributions accurately.

## What I cannot honestly claim yet

- No measured improvement in real founders' negotiation outcomes or reduction in regretted concessions.
- No independently labeled contract benchmark or qualified expert accuracy audit.
- No verified real-founder willingness to use or pay for the product.
- No verified iPad Safari speech-recognition reliability, guaranteed alert latency, or native/background iOS support.
- No proven general accuracy lead over direct Gemini, no fully local/zero-retention guarantee, and no lasting private user memory.

## Next evidence to collect (not yet completed)

1. **Fair product comparison:** Give ChatGPT, Gemini and Consigliere AI the same fictional terms, thresholds and appropriately strong task instructions. Compare error rates *and* time, clicks, and usability; do not engineer a weak generic-AI baseline.
2. **Independent risk annotation:** Obtain blinded rule labels from two experienced reviewers for a **new**, untouched bilingual set. Preserve disagreements and failures.
3. **Actual founder tests:** Observe at least 2–3 consenting founders or sales professionals using fictional negotiations. Record completion, objections, willingness to reuse and why they might instead choose ChatGPT/Gemini.
4. **Physical iPad test:** Record browser/OS, permission behavior, finalized transcription, background/stop cancellation, latency distribution, and failure cases.

See [independent evaluation and iPad protocol](https://github.com/Serein131/Consigliere-ai/blob/main/research/REVIEWER_PROTOCOL_V54.md).

## Short HAA interview answer

> I started Consigliere AI because I kept recognizing negotiation mistakes only after making concessions. I first built auditable rules for discount, payment terms, and exclusivity, but the regex-only approach matched just 16 of 40 unfamiliar synthetic examples. I introduced Gemini for evidence extraction while keeping explicit thresholds in deterministic checks. The hybrid matched 22 of 24 later synthetic cases, but direct Gemini also reached 22, so I cannot claim superior accuracy. I then added opt-in Live Assist to move the experience closer to timely intervention. AI helped me implement and test the product; the key work I want to demonstrate is my problem framing, iterations, honest evaluation, and next plan to validate it with real founders.

---

**Evidence standards:** Every number above belongs to a described experiment and denominator. This log is a transparent development record, not proof of independent field performance, product-market fit, or founder-authored source-code lines.
