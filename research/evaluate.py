#!/usr/bin/env python3
"""Evaluate synthetic DealGuard fixtures. Does not call Gemini.

This is a developer-written scenario suite, not an independently validated
holdout set. Report both successes AND failures. No claim of generalization.
"""
import argparse
import collections
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dealguard import check_deal

def evaluate(cases, predictions=None):
    by_group = collections.defaultdict(lambda: {"cases": 0, "case_success": 0,
                                                   "rules": 0, "rule_correct": 0})
    failed = []
    per_rule = collections.Counter()
    risk_exact = 0
    cases_ok = 0
    total_items = 0
    total_correct = 0
    violation_confusion = collections.Counter()
    prediction_map = {p["id"]: p for p in (predictions or [])}
    for item in cases:
        category = item["category"]
        if predictions is None:
            result = check_deal(item["proposal"], structured_rules=item["structured_rules"])
            observed = {f["rule"]: f["status"] for f in result["findings"]}
            risk_codes = {r["code"] for r in result["commercial_risks"]}
        else:
            pred = prediction_map.get(item["id"], {})
            observed = pred.get("predicted_rule_status", {})
            risk_codes = set(pred.get("predicted_commercial_risks", []))
        expected = item["expected_rule_status"]
        expected_risks = set(item.get("expected_commercial_risks", []))
        correct_rules = sum(observed.get(k) == state for k, state in expected.items())
        all_keys = set(expected) | set(observed)
        rule_exact = observed == expected
        risk_ok = risk_codes == expected_risks
        case_ok = rule_exact and risk_ok
        by_group[category]["cases"] += 1
        by_group[category]["rules"] += len(all_keys)
        by_group[category]["rule_correct"] += sum(observed.get(k)==expected.get(k) for k in all_keys)
        by_group[category]["case_success"] += int(case_ok)
        risk_exact += int(risk_ok)
        cases_ok += int(case_ok)
        total_items += len(all_keys)
        total_correct += sum(observed.get(k)==expected.get(k) for k in all_keys)
        for k in all_keys:
            want, got = expected.get(k, "NOT_CONFIGURED"), observed.get(k, "MISSING")
            per_rule[(k, want, got)] += 1
            if want=="VIOLATION" and got=="VIOLATION": violation_confusion["tp"] += 1
            elif want!="VIOLATION" and got=="VIOLATION": violation_confusion["fp"] += 1
            elif want=="VIOLATION" and got!="VIOLATION": violation_confusion["fn"] += 1
            else: violation_confusion["tn"] += 1
        if not case_ok:
            failed.append({"id":item["id"], "category":category, "language":item["language"],
                           "text":item["proposal"], "expected_rules":expected, "observed_rules":observed,
                           "expected_commercial_risks":sorted(expected_risks),
                           "observed_commercial_risks":sorted(risk_codes)})
    def ratio(a,b):
        return round(a/b, 4) if b else None
    tp=violation_confusion["tp"];fp=violation_confusion["fp"];fn=violation_confusion["fn"]
    return {"scenarios":len(cases), "exact_case_matches":cases_ok,
            "exact_case_rate":ratio(cases_ok,len(cases)),
            "rule_label_matches":total_correct, "rule_label_total":total_items,
            "rule_label_accuracy":ratio(total_correct,total_items),
            "commercial_risk_exact_matches":risk_exact,
            "commercial_risk_exact_rate":ratio(risk_exact,len(cases)),
            "violation_detection":{"tp":tp,"fp":fp,"fn":fn,"tn":violation_confusion["tn"],
                                   "precision":ratio(tp,tp+fp),"recall":ratio(tp,tp+fn)},
            "by_category":dict(by_group),
            "confusion": [{"rule":k[0],"expected":k[1],"predicted":k[2],"count":v}
                          for k,v in sorted(per_rule.items())],
            "failures":failed}

def markdown(result, name):
    n=result["scenarios"]
    d=result["violation_detection"]
    def pct(val):
        return "n/a" if val is None else f"{val*100:.1f}%"
    rows=[
        "# Consigliere AI — Synthetic Evaluation Report",
        "",
        f"Run timestamp (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"Evaluator: **{name}**",
        "",
        "> **Important:** These are authored synthetic fixtures, not independent third-party labels,",
        "> not real customer transactions, and not a validated measure of production accuracy.",
        "> Numbers are descriptive performance on this small constructed set only.",
        "",
        "## Overall",
        "",
        f"- Cases with all rule labels and commercial risk flags matching: **{result['exact_case_matches']}/{n} ({pct(result['exact_case_rate'])})**.",
        f"- Rule-label agreement: **{result['rule_label_matches']}/{result['rule_label_total']} ({pct(result['rule_label_accuracy'])})**.",
        f"- Exact commercial-risk matches: **{result['commercial_risk_exact_matches']}/{n} ({pct(result['commercial_risk_exact_rate'])})**.",
        f"- Violation precision: **{pct(d['precision'])}**; violation recall: **{pct(d['recall'])}**.",
        f"- Confusion counts on rule instances: TP={d['tp']}, FP={d['fp']}, FN={d['fn']}, TN={d['tn']}.",
        "",
        "## Category breakdown",
        "",
        "| Category | All-label cases matched | Rule labels correct |",
        "|---|---:|---:|",
    ]
    for cat,v in sorted(result["by_category"].items()):
        rows.append(f"| {cat} | {v['case_success']}/{v['cases']} | {v['rule_correct']}/{v['rules']} |")
    rows += ["", f"## Failure examples ({len(result['failures'])} total)", ""]
    if not result["failures"]:
        rows.append("No mismatches on these synthetic fixtures; this does **not** establish real-world reliability.")
    else:
        for f in result["failures"][:20]:
            rows += [
                f"### {f['id']} · {f['category']} / {f['language']}",
                "",
                f"- Input: {f['text']}",
                f"- Expected: {json.dumps(f['expected_rules'],ensure_ascii=False)}",
                f"- Observed: {json.dumps(f['observed_rules'],ensure_ascii=False)}",
                f"- Expected risks: {f['expected_commercial_risks']}",
                f"- Observed risks: {f['observed_commercial_risks']}",
                ""
            ]
    rows += ["", "## Next research steps", "",
             "1. Ask an independent domain reviewer to label additional cases without seeing system predictions.",
             "2. Freeze a holdout set before modifying parser rules.",
             "3. Run the generic LLM baseline using the same inputs and explicit user rules.",
             "4. Report latency and errors separately; repeat runs if the model is stochastic.",
             "5. Do not use this report to claim legal accuracy, commercial success or real user satisfaction."]
    return "\n".join(rows)+"\n"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--cases",default=str(ROOT/"research"/"synthetic_cases.json"))
    parser.add_argument("--output",default=str(ROOT/"research"/"benchmark_report.md"))
    parser.add_argument("--json",default=str(ROOT/"research"/"benchmark_report.json"))
    parser.add_argument("--baseline-predictions",help="Optional JSON array of predictions from generic LLM")
    args=parser.parse_args()
    source=json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    cases=source["cases"]
    if len({c["id"] for c in cases})!=len(cases):
        raise SystemExit("Dataset contains duplicate case ids")
    predictions=None
    if args.baseline_predictions:
        predictions=json.loads(pathlib.Path(args.baseline_predictions).read_text(encoding="utf-8"))
        if not isinstance(predictions,list):
            raise SystemExit("Baseline predictions must be a JSON array")
    if predictions is not None:
        provided={p["id"] for p in predictions}
        cases=[case for case in cases if case["id"] in provided]
        if not cases:
            raise SystemExit("No case IDs match the provided predictions")
        print(f"Comparing baseline on {len(cases)} selected case IDs only; not the full 60-case set.")
    result=evaluate(cases,predictions)
    pathlib.Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    pathlib.Path(args.output).write_text(markdown(result,"Generic LLM submitted predictions" if predictions is not None else "DealGuard deterministic audit"),encoding="utf-8")
    pathlib.Path(args.json).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Scenario exact match: {result['exact_case_matches']}/{result['scenarios']}")
    print(f"Rule labels: {result['rule_label_matches']}/{result['rule_label_total']}")
    print(f"Commercial risk exact: {result['commercial_risk_exact_matches']}/{result['scenarios']}")
    print(f"Violation confusion: {result['violation_detection']}")
    print(f"Failed cases: {[x['id'] for x in result['failures']]}")
    print(f"Written: {args.output}, {args.json}")
if __name__=="__main__":
    main()
