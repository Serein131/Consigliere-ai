# Consigliere AI v5.1 — Founder DealGuard

Auditable startup deal decision support, not legal advice or autonomous deal execution.

## What's new

- Structured bilingual controls: buyer/seller role, discount cap, minimum or maximum payment days, and exclusivity prohibition.
- Deterministic /audit without an LLM. /analyze passes audit evidence to Gemini.
- Distinguishes some proposed, rejected, historical and agreed statements; uncertain or unsupported terms return UNKNOWN.
- Separate commercial-risk review for long receivables, short payment windows, auto-renewal, penalties and unlimited liability.
- Free-text context is not a machine-enforced rule. Configure structured controls explicitly.
- Removes unsourced statistics, SMS delivery claims, and unsupported recording/privacy promises.

## Test

Run: python -m unittest discover -s tests -v
Run: python -m py_compile app.py dealguard.py
Run: python app.py

POST /audit with text, hard_bottom_line, and structured_rules. Example structured_rules:

    {"role":"seller","discount_max_pct":10,"payment_direction":"maximum","payment_days":45,"prohibit_exclusivity":true}

Try a proposal containing a 15% discount, 90-day payment and exclusivity: three violations should be flagged. Try a rejected 15% discount: it must not be treated as an actionable commitment.

## Evaluation status

The checked-in tests are narrow regression cases, not published detection-accuracy estimates. A stronger study should use independently labeled English and Chinese scenarios to compare baseline prompts with model plus structured constraints, including precision, recall, false alarm rate and unknown handling.

## Limits and privacy

Regex parsing cannot resolve all legal negations, counteroffers, participant attribution or transcript errors. PASS only means the stated term passed a configured check; it does not mean the deal is sound. UNKNOWN must not be considered safe.

Regex redaction is incomplete; app/server/provider data-retention rules are not independently verified. Speech recognition may involve third-party processing. Use only synthetic cases and obtain needed recording consent.

## Research and evaluation

- [Measured synthetic test results](research/RESULTS.md)
- [Experiment methods](research/EXPERIMENT.md)
- [Usability study protocol](research/user_test_protocol.md)
- [Feedback form template](research/feedback_template.csv)
- [Standard cases](research/synthetic_cases.json)
- [Harder challenge cases](research/challenge_cases.json)

The fixtures are synthetic and are not production accuracy evidence. The Gemini comparison and live user recruitment remain future work.

## Portfolio

Show one clearly violating case, one rejected offer, one compliant case, and a separate commercial-risk flag. State AI-assisted implementation and your own decisions/test contributions accurately.