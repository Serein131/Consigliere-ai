#!/usr/bin/env python3
"""Reproducible rules-only negotiation safety evaluation (no model calls).

Never print or serialize negotiation text. Fixtures MUST be synthetic or
explicitly authorized and de-identified before use. This diagnostic is not a
legal accuracy claim or an independently labeled holdout.
"""
import argparse
import csv
import hashlib
import json
import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dealguard import check_deal  # noqa: E402

LABELS = {"risk", "benign", "unknown"}
CODES = {
    "MISSED_RISK_AS_PASS": ("P0", "Check source attribution, negation, threshold direction and extraction."),
    "MISSED_RISK_AS_UNKNOWN": ("P1", "Review missing extraction and whether human clarification is required."),
    "FALSE_ALERT": ("P1", "Review historical, rejected, conditional and negated clauses."),
    "UNSUPPORTED_CERTAINTY": ("P1", "Review why uncertain context received a definitive status."),
    "OVER_ABSTENTION": ("P2", "Review missing explicit evidence before broadening recognition."),
}
FIELDNAMES = ("case_id", "category", "expected", "predicted", "error_code",
              "severity", "hypothesis_only", "root_cause_confirmed",
              "reviewer", "reviewed_at_utc", "proposed_change", "regression_case")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def error_for(expected, actual):
    if expected == "risk":
        return None if actual == "VIOLATION" else (
            "MISSED_RISK_AS_PASS" if actual == "NO_DETECTED_VIOLATION" else "MISSED_RISK_AS_UNKNOWN"
        )
    if actual == "VIOLATION":
        return "FALSE_ALERT" if expected == "benign" else "UNSUPPORTED_CERTAINTY"
    if expected == "unknown" and actual != "UNKNOWN":
        return "UNSUPPORTED_CERTAINTY"
    if expected == "benign" and actual == "UNKNOWN":
        return "OVER_ABSTENTION"
    return None


def evaluate(suite):
    if not isinstance(suite, dict) or not isinstance(suite.get("cases"), list):
        raise ValueError("Invalid case suite")
    cases = suite["cases"]
    rules = suite.get("rules")
    if not isinstance(rules, dict) or not cases:
        raise ValueError("Suite must contain shared structured rules and cases")
    ids = set()
    rows = []
    issues = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Case is not an object")
        case_id, expected, source = case.get("id"), case.get("expected"), case.get("text")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("Duplicate or missing case ID")
        if expected not in LABELS or not isinstance(source, str) or not source.strip():
            raise ValueError("Case has invalid expected label or text")
        ids.add(case_id)
        predicted = check_deal(source, structured_rules=rules)["assessment"]
        category = str(case.get("category", "unspecified"))[:80]
        row = {"case_id": case_id, "category": category,
               "expected": expected, "predicted": predicted}
        rows.append(row)
        code = error_for(expected, predicted)
        if code:
            severity, hypothesis = CODES[code]
            issues.append({
                **row, "error_code": code, "severity": severity,
                "hypothesis_only": hypothesis,
                "root_cause_confirmed": "", "reviewer": "",
                "reviewed_at_utc": "", "proposed_change": "", "regression_case": "",
            })

    counts = Counter((r["expected"], r["predicted"]) for r in rows)
    tp = counts[("risk", "VIOLATION")]
    fn = sum(n for (e, a), n in counts.items() if e == "risk" and a != "VIOLATION")
    fp = sum(n for (e, a), n in counts.items() if e != "risk" and a == "VIOLATION")
    tn = len(rows) - tp - fn - fp
    expected_unknown = sum(r["expected"] == "unknown" for r in rows)
    unknown_correct = sum(r["expected"] == "unknown" and r["predicted"] == "UNKNOWN" for r in rows)
    unsafe_pass = sum(i["error_code"] == "MISSED_RISK_AS_PASS" for i in issues)

    def ratio(n, d):
        return round(n / d, 4) if d else None

    return {
        "summary": {
            "count": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "risk_recall": ratio(tp, tp + fn),
            "alert_precision": ratio(tp, tp + fp),
            "false_alert_rate": ratio(fp, fp + tn),
            "unknown_abstention_rate": ratio(unknown_correct, expected_unknown),
            "unsafe_pass_count": unsafe_pass,
            "failure_count": len(issues),
            "error_categories": dict(Counter(i["error_code"] for i in issues)),
        },
        "cases": rows,
        "failures": issues,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="research/live_alert_challenge_v54.json")
    parser.add_argument("--out-dir", default="/tmp/consigliere-continuous-eval")
    parser.add_argument("--max-fn", type=int, default=None,
                        help="Risk alert misses allowed. Compare with recorded baseline.")
    parser.add_argument("--max-fp", type=int, default=None,
                        help="False alerts allowed. Compare with recorded baseline.")
    parser.add_argument("--max-unsafe-pass", type=int, default=None)
    args = parser.parse_args()
    source = pathlib.Path(args.suite)
    if not source.is_absolute():
        source = ROOT / source
    output = pathlib.Path(args.out_dir)
    output.mkdir(parents=True, exist_ok=True)

    data = json.loads(source.read_text(encoding="utf-8"))
    report = evaluate(data)
    report["provenance"] = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "suite_path": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else source.name,
        "suite_sha256": digest(source),
        "rule_engine_sha256": digest(ROOT / "dealguard.py"),
        "label_origin": data.get("description", "Unverified labels; inspect source metadata."),
        "system_under_test": "rules-only DealGuard; not Gemini, full agent or iOS",
    }
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "failure_review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(report["failures"])

    m = report["summary"]
    lines = [
        "# Consigliere AI — reproducible safety evaluation", "",
        "Synthetic developer-authored cases; **not independent expert validation**, "
        "not verified negotiation outcomes and not an evaluation of Gemini.", "",
        f"Dataset SHA-256: `{report['provenance']['suite_sha256']}`",
        f"DealGuard SHA-256: `{report['provenance']['rule_engine_sha256']}`", "",
        "| Metric | Result |", "|---|---:|",
        f"| Cases | {m['count']} |",
        f"| Risk caught (TP) | {m['tp']} |",
        f"| Risk missed (FN) | {m['fn']} |",
        f"| False alerts (FP) | {m['fp']} |",
        f"| Risk treated as no detected violation | {m['unsafe_pass_count']} |",
        f"| Risk recall | {m['risk_recall']} |",
        f"| Alert precision | {m['alert_precision']} |",
        f"| Unknown abstention rate | {m['unknown_abstention_rate']} |",
        "", "## Failures requiring human review", "",
        "| ID | Category | Expected | Actual | Error class |",
        "|---|---|---|---|---|",
    ]
    for issue in report["failures"]:
        lines.append(f"| {issue['case_id']} | {issue['category']} | {issue['expected']} | "
                     f"{issue['predicted']} | {issue['error_code']} |")
    lines.extend(["", "Root cause is **unreviewed**. CSV hypotheses are prompts for investigation, not findings.",
                  "Do not tune on this suite and continue calling it unseen holdout.", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")

    gates = (("fn", args.max_fn), ("fp", args.max_fp),
             ("unsafe_pass_count", args.max_unsafe_pass))
    failed = [f"{name}={m[name]} exceeds {limit}" for name, limit in gates
              if limit is not None and m[name] > limit]
    print(json.dumps({"summary": m, "gates_failed": failed, "report_dir": str(output)}, sort_keys=True))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
