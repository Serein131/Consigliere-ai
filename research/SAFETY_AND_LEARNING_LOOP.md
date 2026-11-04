# Consigliere AI — Safety assurance and continuous evaluation (v5.6 candidate)

**Status:** proposed engineering controls, not an independently audited security certification. This is a decision-support prototype. No autonomous deal signature, message delivery, external account access, or legally binding action is permitted.

## 1. Trust and data boundaries

| Boundary | Current control | Known residual risk |
|---|---|---|
| Speech → browser | User mic permission and deliberate transcription | Browser speech recognition may use provider infrastructure; not an on-device confidentiality guarantee |
| Browser → app backend | Consent-gated Live Assist; no-store headers; 32 KiB JSON body limit | An API client can bypass browser UX; no authentication, per-user authorization or distributed rate limit |
| Backend → Gemini | Opt-in hybrid mode; model API key in HTTP header, not query string; best-effort masking | Masking can miss names, sensitive information and contextual commercial secrets |
| Model extraction → rule outcome | Literal evidence verification, deterministic threshold comparisons, missing evidence => UNKNOWN | A literal quote is not semantic attribution, signed agreement or legal proof |
| Model recommendation → user | No external actions; conservative output risk gating; user decides | Strategic advice can still be misleading, biased or commercially harmful |
| Audit → user | Redacted evidence displayed separately and privacy-minimal decision_trace returned | Trace is an API response only, **not** an immutable, persisted or tamper-proof audit trail |

**Prioritized open controls for production:** backend consent/authorization enforcement for all model routes (including /analyze); identity and session isolation; trusted rate limiter and budget guard; privacy-by-design review of model vendors/retention; secret scanning and rotation; a dedicated threat model/red-team suite; encrypted authenticated audit storage with retention/deletion controls if user requests persistent auditing. Do not claim zero retention.

### Audit receipt schema

Each audit/strategy response includes `decision_trace`: random trace ID, UTC time, engine/mode/model metadata, rule statuses, unknown/violation counts, commercial review flag and no-action/human-review indicators. It deliberately omits proposal text, counterpart names, evidence quotations and private numeric thresholds. It is only a **summary of server-side checks at request time**, not a chain-of-thought record and not evidence the LLM made a sound inference. To retain it, the caller must explicitly save it. No database or log persistence is added.

**Risk policy:** a model-provided SAFE status is downgraded to LOW because passing configured checks cannot establish that a deal is safe. A deterministic violation forces CRITICAL. The accepted response keys are allowlisted; provider error bodies and API keys are not returned to clients.

## 2. Model/data separation

Untrusted deal text, meeting history and user profile are *data*, never system authority. Model suggestions cannot override verified deterministic risk findings. Human review remains mandatory; no command to sign, send or commit exists. Redaction is best effort and potentially incomplete. Use fictional cases for public demo and GitHub Actions.

Threats to track: direct/indirect prompt injection, sensitive information disclosure, hallucinated numeric evidence, false alarms, false 'safe' claims, data poisoning in feedback, cost exhaustion, and third-party model outages. Relevant references: OWASP LLM Top 10 (2025) and NIST AI RMF Govern/Map/Measure/Manage.

## 3. Case → failure → root cause → change → regression loop

1. **Intake**: de-identified negotiation snippet and *voluntary, authorized* source; scenario type; timestamp; source language; configured rule direction; disclosure/consent flag. Never commit client contracts, original recordings, email addresses, or financial terms to a public repository.
2. **Label**: two independent reviewers label the actionable proposed/agreed/rejected/historical/unknown terms; mark disputes; freeze expected label and label provenance **before** model prediction. Keep an untouched, privately held release holdout. Developer-created cases remain explicitly labeled synthetic.
3. **Run**: freeze dataset hash and rule engine hash; run deterministic audit and optional separately cost-controlled Gemini experiment. Store raw provider errors only as safe error codes.
4. **Triage**: each failure gets ID, predicted vs expected, error classification and severity. `failure_review.csv` has **hypotheses only**; a reviewer must record confirmed root cause before a fix is accepted.
5. **Change one variable**: decide whether the problem is input/consent, transcription, extraction, interpretation, threshold direction, prompt wording, model version, or UI presentation. Make a minimal change with a linked regression case and commit.
6. **Gate**: unit tests + previously encountered failures + frozen synthetic safety suite. Do not increase false negatives or false positives beyond the published baseline. Independently assess a new holdout before claiming accuracy gains; compare versions on identical cases and report uncertainty. A candidate that fails the gate is not auto-deployed.
7. **Monitor**: report errors and user corrections only after opt-in. Avoid direct self-training from user messages or online rule edits. Shipping/rollback require a deliberate human decision.

### First reproducible gate

```bash
python research/continuous_eval.py \
  --suite research/live_alert_challenge_v54.json \
  --out-dir /tmp/consigliere-eval \
  --max-fn 3 --max-fp 2 \
  --expected-suite-git-sha1 ce4c3cf014c9c0fb7f141a62352c74ce3f197dc0
```

The **3 missed alerts / 2 false alerts** are the existing v5.4 36-case developer-authored rules-only diagnostic baseline, not acceptable production standards. The new gate is a *non-regression check* on that same synthetic suite, not proof of improvement. Reports include all per-case outcomes, failures, and blank review fields. The default output path is outside the repository to avoid accidentally publishing real cases.

**Privacy requirement:** The script reports only case IDs, categories, expected/predicted statuses and review hypotheses; it does not serialize original deal text. However, if fixtures are committed publicly, their source text is still public. Always use invented or properly cleared, de-identified test input.

### Metrics to display together

- Safety: risk recall/FN; false alert rate/FP; risk incorrectly labeled NO_DETECTED_VIOLATION; abstention on expected UNKNOWN.
- Reliability: malformed output, timeout, provider rate/quota failure, cancelled requests, unavailable service, consent/revocation behavior.
- Auditability: rule status provenance, trace completeness, reproducible source hashes, reviewer adjudication coverage.
- Continuous improvement: new-regression count, prior-error reproduction count, turnaround from identified to reviewed, independently held-out change in error rates.

**Do not optimize for aggregate accuracy alone.** In a negotiation product, a critical missed breach is different from a nuisance alert. Report confusion matrices and severity-weighted failures alongside any match rate.

## 4. What is *not* accomplished here

This upgrade is not model fine-tuning or autonomous learning. The current benchmark tests the **rules-only** engine. It does not re-evaluate live Gemini, iOS speech, production latency, legally binding outcomes, or third-party privacy guarantees. It does not establish a secure multi-tenant system or complete event-sourced, tamper-evident audit log. All such claims require additional engineering and independent verification.
