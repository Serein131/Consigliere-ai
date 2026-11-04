"""Privacy-minimal decision receipt. No server-side persistence or raw transcript logging.

This is an *audit summary* of deterministic checks, not a cryptographic
attestation, legal opinion, or proof that the LLM interpreted source correctly.
"""
from datetime import datetime, timezone
import secrets

TRACE_VERSION = "decision-trace-v1"
VALID_STATES = {"VIOLATION", "PASS", "UNKNOWN", "NO_DETECTED_VIOLATION"}
VALID_RULES = {"maximum_discount_pct", "payment_days", "no_exclusivity"}


def decision_trace(audit, *, mode="rules", model=None, phase="in_deal"):
    """Return a caller-saveable, non-sensitive receipt without input text/limits.

    An untrusted model must not be able to add arbitrary fields to the receipt.
    Per-rule quote verification is only available for the hybrid extraction
    surface, not for heuristic rules-only matches.
    """
    audit = audit if isinstance(audit, dict) else {}
    findings = audit.get("findings", [])
    findings = findings if isinstance(findings, list) else []
    safe_findings = []
    for item in findings[:12]:
        if not isinstance(item, dict):
            continue
        rule = item.get("rule")
        status = item.get("status")
        if rule in VALID_RULES and status in VALID_STATES:
            safe_findings.append({"rule": rule, "status": status})
    statuses = [row["status"] for row in safe_findings]
    raw_assessment = audit.get("assessment")
    assessment = raw_assessment if raw_assessment in VALID_STATES else "UNKNOWN"
    if "VIOLATION" in statuses:
        assessment = "VIOLATION"
    elif "UNKNOWN" in statuses or not statuses:
        if assessment != "VIOLATION":
            assessment = "UNKNOWN"
    return {
        "receipt_version": TRACE_VERSION,
        "trace_id": secrets.token_hex(12),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pipeline": {
            "mode": mode if mode in ("rules", "hybrid", "strategy") else "unknown",
            "phase": phase if phase in ("pre_deal", "in_deal", "post_deal") else "unknown",
            "model": str(model)[:64] if model else None,
            "rule_engine": str(audit.get("engine", "unknown"))[:80],
        },
        "decision": {
            "assessment": assessment,
            "rule_outcomes": safe_findings,
            "violation_count": statuses.count("VIOLATION"),
            "unknown_count": statuses.count("UNKNOWN"),
            "configured_check_count": len(safe_findings),
            "commercial_review": bool(audit.get("commercial_risks")),
        },
        "safeguards": {
            "unverified_or_missing_facts_are_safe": False,
            "human_review_required": True,
            "external_action_performed": False,
            "original_text_stored_in_receipt": False,
            "thresholds_stored_in_receipt": False,
        },
        "disclaimer": (
            "Client-saveable rule-audit receipt; not a complete model reasoning log, "
            "an independently verified interpretation, or a certification of deal safety."
        ),
    }
