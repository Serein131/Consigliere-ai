# Consigliere AI · Founder DealGuard (research prototype)

A three-stage negotiation copilot with a **model-independent commercial constraint audit**.

## Problem and falsifiable research question

Can deterministic deal constraints + a structured AI analysis reduce explicit rule violations and unsupported safety assurances compared with a generic LLM negotiation prompt?

The aim is **decision support**, not autonomous negotiation, verified psychological assessment, contract enforceability, or legal advice.

## Architecture

- `/audit` — deterministic, model-free, auditable rules (no Gemini API call).
- `/analyze` — same rule audit + Gemini strategic explanation; explicit detected violations cannot be marked SAFE.
- Three workflow stages — pre-deal, live triage, post-deal, with reduced/sanitized prior-stage summaries.
- English/Chinese rules currently supported for **maximum discount**, **minimum or maximum payment days**, and **no exclusivity**. Wording coverage is limited. Absent evidence returns UNKNOWN.

### Test locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python app.py
```

`/audit` example:

```bash
curl -s http://localhost:5000/audit -H 'Content-Type: application/json' -d '{
  "hard_bottom_line": "max discount <=10%; payment terms >=45 days; zero exclusivity",
  "text": "15% discount; payment terms 30 days; exclusivity agreement"
}'
```

Expected: three VIOLATION findings. Counterexample: `10% discount; payment terms 90 days; no exclusivity` is compliant with **these** user-defined rules, though 90 days may be commercially unfavorable for cash collection. Specify a maximum payment window if appropriate.

## Evaluation methodology (planned; not measured)

1. Build >=50 **synthetic**, independently labeled English/Chinese negotiation scenarios, including benign proposals, adversarial pressure, uncertain wording, and contradictory rules.
2. Compare baseline generic Gemini prompts vs. Gemini+DealGuard vs. deterministic `/audit` on the same cases.
3. Record violation detection precision/recall, false positives, unknown calibration, rule-direction errors, and P50/P95 end-to-end latency.
4. Have at least two independent reviewers label borderline cases; report disagreements.
5. Separate **measured** outcomes from aspirations; do not claim reliable sub-2-second latency, zero retention, or business impact without evidence.

## Security and privacy boundaries

Current privacy protections are partial regex-based sanitization, **not verified zero retention, end-to-end confidentiality, or comprehensive DLP**. Commercial terms and residual identifiers may still reach server/cloud model. Use synthetic demo data. Do not paste real sensitive contracts or private negotiation content until a full privacy/security review. The web speech recognition feature may be browser/provider-dependent; do not represent it as on-device-only speech processing without verification.

## Current limits

- The parser does not reliably handle nuanced legal negation, overlapping contractual definitions, currency comparisons, compound rule priority, or multilingual transcription ambiguity.
- An audit status of NO_DETECTED_VIOLATION only means that the explicitly configured and recognized checks passed.
- A high-stakes contract requires qualified professional review.

## Portfolio demo

Present a short video showing three cases: obvious violation, benign compliant proposal, and ambiguous/unknown input. Explain the change from a generic negotiation copilot to a verifiable **commitment firewall**. Include test scripts, transparent failures, and subsequent iterations. Your project description should distinguish your personal contribution from AI-assisted coding.
