"""v5.4 frozen synthetic risk-screening report. Diagnostic, not independent accuracy."""
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dealguard import check_deal

DATA = ROOT / "research/live_alert_challenge_v54.json"
REPORT = ROOT / "research/live_alert_report_v54.md"
JSON_REPORT = ROOT / "research/live_alert_report_v54.json"


def ratio(n, d):
    return round(100 * n / d, 1) if d else None


def main():
    fixture = json.loads(DATA.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    assert len(cases) >= 30 and len({c["id"] for c in cases}) == len(cases)
    assert Counter(c["expected"] for c in cases) == {"risk": 15, "benign": 10, "unknown": 11}
    rows = []
    for case in cases:
        result = check_deal(case["text"], structured_rules=fixture["rules"])
        status = result["assessment"]
        is_alert = status == "VIOLATION"
        expected_alert = case["expected"] == "risk"
        rows.append({
            "id": case["id"], "category": case["category"],
            "expected": case["expected"], "predicted": status,
            "alert": is_alert, "expected_alert": expected_alert,
            "matched": (is_alert == expected_alert),
            "findings": {f["rule"]: f["status"] for f in result["findings"]},
        })
    tp = sum(r["expected_alert"] and r["alert"] for r in rows)
    fn = sum(r["expected_alert"] and not r["alert"] for r in rows)
    fp = sum(not r["expected_alert"] and r["alert"] for r in rows)
    tn = sum(not r["expected_alert"] and not r["alert"] for r in rows)
    abstain_expected = [r for r in rows if r["expected"] == "unknown"]
    unknown_found = sum(r["predicted"] == "UNKNOWN" for r in abstain_expected)
    missed_as_safe = sum(r["expected_alert"] and r["predicted"] == "NO_DETECTED_VIOLATION" for r in rows)
    summary = {
        "total": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "alert_recall_pct": ratio(tp, tp + fn), "alert_precision_pct": ratio(tp, tp + fp),
        "false_positive_rate_pct": ratio(fp, fp + tn),
        "expected_unknown_cases": len(abstain_expected),
        "marked_unknown": unknown_found,
        "risk_misclassified_as_no_detected_violation": missed_as_safe,
    }
    JSON_REPORT.write_text(json.dumps({"summary": summary, "cases": rows},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# v5.4 Live Assist challenge: frozen synthetic screening diagnostic",
        "",
        "**Data:** 36 developer-authored fictional, bilingual cases (15 expected risk / "
        "10 expected non-risk / 11 expected unknown). Labels are NOT independent expert truth.",
        "",
        "**What was measured:** backend deterministic rules only. This report does not measure Gemini "
        "hybrid mode, web speech accuracy, consent UX, end-to-end latency or negotiation success.",
        "",
        f"- Risk detection recall: **{tp}/{tp+fn} ({summary['alert_recall_pct']}%)**.",
        f"- Risk alert precision: **{tp}/{tp+fp} ({summary['alert_precision_pct']}%)**.",
        f"- Non-risk false alerts: **{fp}/{fp+tn} ({summary['false_positive_rate_pct']}%)**.",
        f"- Expected-unknown cases correctly left UNKNOWN: **{unknown_found}/{len(abstain_expected)}**.",
        f"- Expected-risk cases incorrectly labeled NO_DETECTED_VIOLATION: **{missed_as_safe}**.",
        "",
        "These diagnostic rates are not generalizable; the dataset includes deliberate difficult "
        "paraphrases, historical offers and conditionals. Review all failure cases.",
        "",
        "| Case | Scenario type | Expected | Predicted | Alert correct? |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['category']} | {r['expected']} | "
                     f"{r['predicted']} | {'yes' if r['matched'] else '**NO**'} |")
    lines += ["", "## Next independent validation",
              "",
              "Commission two reviewers to label *new* fictional cases blind to system output. "
              "Report agreement and resolved disputes before treating labels as externally validated. "
              "Do not tune rules to this same frozen set and then rebrand it as a fresh holdout.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("V54_CHALLENGE: " + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
