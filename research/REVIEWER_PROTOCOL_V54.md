# Independent validation protocol for Consigliere AI v5.4

**Status: a proposed study, not completed human validation.** No people have been recruited or independent labels collected under this protocol.

## Study goals

Measure how frequently three explicit commercial rule violations are caught, how many normal agreements are falsely flagged, whether UNCERTAIN/UNKNOWN results are correctly interpreted, how long a prompt takes from completion to an alert, and whether a founder can act on the interface without guessing.

## Phase A: independently labeled fictional corpus

1. Recruit two qualified reviewers with contract negotiation experience who have not seen the product outputs. Explain that the examples are invented and are not legal advice.
2. Write a **new** balanced set (at least 40–60) of English and Chinese proposals, including accepted/rejected offers, negation, role reversal, conditions, late revisions, contradictory numbers, false deadlines, payment rules and exclusivity clauses. Do not reuse or rewrite the frozen 24-case study or the v5.4 36-case developer challenge and call it new.
3. Freeze and timestamp the raw examples, rule thresholds, target seller/buyer role and reference outcome before running the live system. Give each reviewer cases in randomized order without any AI or DealGuard predictions.
4. Each reviewer independently marks each rule as VIOLATION / PASS / UNKNOWN, records the exact supporting quote and a short reason. Treat source quote as text evidence, not proof of the statement's legal or commercial interpretation.
5. Resolve disagreements through discussion or a third qualified reviewer. Preserve original independent labels, disagreements and final adjudicated labels.
6. Run the exact same cases on rules-only, direct Gemini, and hybrid where permission, credits and capacity allow; record raw responses, model IDs, date and error/abstention rates. Do not delete failures.
7. Report per-rule recall, risk precision, false alert rate, false reassurance rate, UNKNOWN frequency, 95% interval for appropriate metrics, and reviewer agreement (Cohen's kappa or raw percent agreement), with denominators. Record multiple independent model repeats to measure output variability.
8. **Do not optimize against the frozen evaluation set and claim it remains unseen.** For any redesigned model, freeze a completely new holdout.

## Phase B: real-device usability (not automated tests)

Use iPad Safari and, if available, Chrome on iOS/iPhone. Under explicit permission, run **fictional or consented nonconfidential** negotiations. Record device model, OS/browser versions, speech API availability, mic permission prompts, whether each speech chunk was final, connection drops, background/lock behavior, error messages, time from final transcript to alert, number of unwanted requests, and consent revocation. A real physical device/operator is required; a Node browser mock is not a substitute.

## Phase C: 2–3 founder or sales-user sessions

Ask consent before participation. Give a fictional negotiation and tasks to set limits, recognize a bad offer, understand the confidence/UNKNOWN notice, stop Live Assist and choose a counter-question. Capture completion, confusing controls, mistaken reliance on results, suggestions, and opt-in willingness. Avoid collecting identifying commercial contracts; do not call a hypothetical session completed until actually conducted.

## Scope and safeguards

Current v5.4 Live Assist auto-runs **rule audits** by default, and optional consented Gemini extraction; it does not continuously overhear room audio, autonomously negotiate, send messages, or prove sub-2s latency. The automatic counter-question is a generic template, not independently validated strategic advice. Do not enter trade secrets or real confidential client data; heuristic masking may miss identifiers.
