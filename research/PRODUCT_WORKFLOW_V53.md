# Consigliere AI v5.3 · Unified workflow and privacy contract

**Status:** Implemented in the Flask app; deployment and browser checks must be verified separately. This document describes product structure rather than scientific accuracy.

## One navigation · One input · Shared limits

| Stage | Screen | State retained inside the active page |
|---|---|---|
| **01 Prepare** | Goals, constraints, personal reminders and optional context → strategy button | Structured deal guardrails shared with other stages, current Prepare draft and optional AI summary |
| **02 Protect** | One editor for typed text **or** voluntary browser speech transcript → evidence audit → optional tactical reply | Same guardrails, current Protect draft and optional Gemini/DealGuard audit |
| **03 Debrief** | Reuses the same editor for a *separate* post-meeting memo → optional follow-up drafting | Shared guardrails, current Debrief draft and optional previous stage summaries |

The three drafts remain distinct in a JavaScript object, and the same DOM textarea is reused. Switching stages saves the active text and restores the destination draft; it stops speech recognition first. Text is **not** automatically transmitted when navigating or editing.

No persistence across browser refresh, SMS integration or continuous background monitoring is claimed. Stage memory stored in the current browser session is neither encrypted local-storage memory nor a separate database.

## Protect speech-to-text: intentionally user-controlled

1. Check the permission notice (obtain applicable consent from people whose voices are transcribed).
2. Press **Start transcription**; the browser requests microphone/voice-recognition permission.
3. Interim and final recognition results update the **one shared stage input** while preserving previously typed text.
4. Stop voluntarily, or let the browser stop due to inactivity. In both cases, the text stays visible and editable.
5. Only a separate, explicit **AI evidence + rule audit**, **Rules only**, or **Generate tactical counter-question** button starts an analysis.

The former 4.5-second silence timer and automatic `runAgent()` calls were removed. Starting transcription is **not** consent to Gemini inference. Browser speech recognition may be processed by external services; its behavior depends on browser/device support. We do not claim a particular latency, local-only speech processing, full privacy guarantees or actual negotiation performance.

## Audit and strategy are distinct calls

- `POST /audit` is rules only and does not use Gemini.
- `POST /hybrid-audit` requires a separate affirmative processing consent, uses Gemini extraction, verifies literal evidence and numeric support, and applies deterministic checks. A verbatim quote only verifies surface text, not interpretation.
- `POST /analyze` is an independent stage-specific strategic suggestion. Its output is **not** independently validated by the hybrid quote checker. The frontend requires an explicit consent gate before this call, even if voice transcription was enabled.
- Any real confidential contract may survive heuristic redaction; this demo should use fictional inputs only.

## Usability and regression acceptance criteria

- Only one visible `textarea` for all three phases; there is one top-level 01/02/03 navigation.
- Goals and programmed guardrails entered in Prepare apply in Protect and Debrief.
- Stage switching restores edited drafts without overwriting them; changing interface language preserves the user's own text.
- Protect shows both evidence-driven and rules-only audits against exactly the same entered text and rules.
- Speech recognition has an explicit on/off state, uses that editor, stops on stage switch and **does not invoke any AI after silence or stop**.
- Each model-dependent action requires its own UI consent; non-consented calls are blocked in the browser. The hybrid API also enforces consent on the server.
- Technical details are under **How it works**, not a fake fourth or second “third” workflow stage.
- All historical synthetic research scores remain unchanged. Redesigning the interface does not establish a new model benchmark result.

## Known follow-up work

Independent expert annotation, authentic founder usability sessions, durable private session memory, accessibility testing on actual iOS browsers and production-side durable rate limits have not been completed. Public voice capture and Gemini quota use should not be confused with a certified real-time agent.

**Verification:** `python -m unittest discover -s tests -v`, `node tests/check_v53_browser.js`, JavaScript syntax gate, no-billing Vercel smoke checks and a preview/production rollout check.
