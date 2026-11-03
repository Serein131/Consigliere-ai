# Consigliere AI v5.5 — Actionable Risk Intervention

**Date:** 2026-11-03 · **Release scope:** user-authorized, foreground Protect stage; one set of structured rules and one shared text editor.  
**Evidence origin:** Feedback from an AI-operated **five-scenario remote Chrome functional check** of v5.4; the five simulated personas were not five independent human interviewees. The original workbook lives in the founder's ChatGPT Library, not in this public repository.

## What changed

1. **Actionable, rule-specific counter-questions.** A violated exclusivity rule now prompts clarification of scope, geography and duration. Payment rule questions respect **maximum versus minimum** direction. Discount questions explicitly use the configured maximum. The system can show multiple questions for multiple violations instead of repeating one generic instruction.
2. **Heuristic first focus, not a game-theoretic optimum.** An auditable fallback sorts exclusivity, payment and discount questions as a starting point. It is marked *heuristic* and is not evidence of optimal negotiation strategy. Users must decide what matters most to their deal.
3. **Readable business meaning.** Each result shows the detected value with units, configured threshold and direction, and when violated, the numeric difference (days or percentage points). Three rows can be seen even when only one rule is violated. A PASS pertains only to its specific configured rule.
4. **Term-mention source ledger.** A small, no-extra-model extraction layer shows short excerpts tagged by surface language cues (e.g., “rejected wording,” “agreement wording,” “proposal wording”). These labels are **not** a validated contractual state. The hybrid view also shows the Gemini selected term status and verbatim-quote verification status **separately**. A matched quote is not proof the commercial interpretation is correct.
5. **Manual audit consistency.** The existing manual audit receives the same descriptive rule comparison and source ledger; no second editor, account, or permanent data store is added.
6. **Consent preserved.** Automatic checks still require a separate foreground Live Assist enablement and server-processing consent. Gemini requests additionally require opt-in Gemini consent. The browser still initiates transcription only after permission; finalized speech is analyzed only when Live Assist is explicitly enabled. Stopping, switching, revoking or backgrounding cancels/invalidates work. The tactical LLM response remains a *separate user-triggered action*.

## Functional acceptance tests based on the five simulated roles

| Simulated role | Scenario | v5.5 acceptance check |
|---|---|---|
| Founder / first enterprise deal | 15% discount versus 10%, 90 versus max-45 days, exclusivity prohibited | Three **different** example questions, separate rule cards and source quotes |
| Freelance designer | Previously rejected 20% / 90 days, then accepted 5% / 30 days | Source ledger shows rejected *wording* and agreement *wording*, without treating them as legally binding facts |
| Procurement lead (buyer) | Requested 15-day payment when minimum is 60 days; exclusivity prohibited | Display “45 days earlier than minimum,” no inverted advice |
| Sales lead | Exactly within discount/payment thresholds, no exclusivity conflict | Display all evaluated rules and no unsupported 'safe to sign' claim |
| Manufacturer | 12% versus max-6 discount, payment in 75 versus max-30 days, “only reseller in the region” | Display the supplied English quote with separate hybrid quote-verification notice |

**Verification:** [Python trace tests](../tests/test_v55_trace.py), [five-role simulated-browser tests](../tests/check_v55_actionable.js), [v5.4 consent/stop tests](../tests/check_v54_live.js), and [GitHub Actions](https://github.com/Serein131/Consigliere-ai/actions). The simulated-browser tests mock backend responses; they do **not** rerun the five original Chrome interactions against a live Gemini API.

## Why these are not yet user or business outcomes

- A developer-authored functional assertion does not measure real-life legal/contract accuracy or show that founders will act differently.
- The source-mention ledger is a heuristic annotation; contradictory or multi-step utterances can still be labeled incorrectly. **Use the direct quote, not the tag, as the evidence to review.**
- The on-screen example questions are rule-templated, not a personalized payoff/BATNA calculation and not an independently validated game-theoretic recommendation.
- The risk-priority ordering is a transparent default, not the right choice for every company.
- No proof of sub-two-second end-to-end latency, safe cross-app recording, native iOS monitoring, truly local transcription, zero provider retention, persistent founder memory, or calibrated real-time speech performance.
- The 36-case rules-only v5.4 challenge still contained three misses and two false alerts; v5.5's guidance UI does **not** erase those errors. Compare on new independent cases before claiming model performance improvements.

## Suggested next validation

Run the same five fictional tasks with 2–3 real, consenting founders or sales professionals; measure correct interpretation of rule direction, understood current/rejected wording, time to identify the next question, and whether they would use the app instead of ChatGPT/Gemini. Independently annotate a new holdout with contract-experienced reviewers. Test Safari microphone permissions, final transcription events, stop behavior and alert latency on an actual iPad.

**Marketing claim discipline:** v5.5 is an *on-demand / session-authorized decision-support prototype*. It does not autonomously negotiate or certify contract safety.
