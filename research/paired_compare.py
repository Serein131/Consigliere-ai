#!/usr/bin/env python3
"""Paired evaluation of a frozen synthetic case set.

No new user data or legal advice. Do not tune DealGuard using these labels
before the frozen test results are recorded.
"""
import argparse
import collections
import csv
import json
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dealguard import check_deal

def render(cases,predictions):
    preds={p["id"]:p for p in predictions}
    if len(preds)!=len(predictions):
        raise ValueError("Duplicate IDs in predictions")
    declared={c["id"] for c in cases}
    if declared!=set(preds):
        raise ValueError("Predictions don't match case set, missing/extra: "+repr(sorted(declared.symmetric_difference(set(preds)))))
    rows=[]
    categories=collections.defaultdict(lambda:{"cases":0,"dealguard":0,"gemini":0})
    confusion=collections.Counter()
    for case in cases:
        result=check_deal(case["proposal"],structured_rules=case["structured_rules"])
        dg_states={f["rule"]:f["status"] for f in result["findings"]}
        dg_risks=sorted({x["code"] for x in result["commercial_risks"]})
        gb=preds[case["id"]]
        gm_states=gb.get("predicted_rule_status",{})
        gm_risks=sorted(set(gb.get("predicted_commercial_risks",[])))
        expected=case["expected_rule_status"]
        exp_risks=sorted(set(case.get("expected_commercial_risks",[])))
        dg_correct=(dg_states==expected and dg_risks==exp_risks)
        gm_correct=(gm_states==expected and gm_risks==exp_risks)
        categories[case["category"]]["cases"]+=1
        categories[case["category"]]["dealguard"]+=int(dg_correct)
        categories[case["category"]]["gemini"]+=int(gm_correct)
        confusion[("paired",dg_correct,gm_correct)]+=1
        rows.append({"id":case["id"],"category":case["category"],"language":case["language"],
                     "proposal":case["proposal"],"notes":case.get("annotation_note",""),
                     "expected_rules":json.dumps(expected,ensure_ascii=False,sort_keys=True),
                     "dealguard_rules":json.dumps(dg_states,ensure_ascii=False,sort_keys=True),
                     "gemini_rules":json.dumps(gm_states,ensure_ascii=False,sort_keys=True),
                     "expected_risks":json.dumps(exp_risks,ensure_ascii=False),
                     "dealguard_risks":json.dumps(dg_risks,ensure_ascii=False),
                     "gemini_risks":json.dumps(gm_risks,ensure_ascii=False),
                     "dealguard_exact":dg_correct,"gemini_exact":gm_correct})
    return rows,dict(categories),confusion

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cases",required=True)
    p.add_argument("--predictions",required=True)
    p.add_argument("--output-prefix",required=True)
    a=p.parse_args()
    data=json.loads(pathlib.Path(a.cases).read_text(encoding="utf-8"))
    cases=data["cases"]
    pred=json.loads(pathlib.Path(a.predictions).read_text(encoding="utf-8"))
    rows,cats,counts=render(cases,pred)
    name=data.get("dataset_name","frozen synthetic set")
    n=len(rows)
    prefix=pathlib.Path(a.output_prefix)
    prefix.parent.mkdir(parents=True,exist_ok=True)
    with prefix.with_suffix(".csv").open("w",newline="",encoding="utf-8") as out:
        writer=csv.DictWriter(out,fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary={"dataset_name":name,"scenario_count":n,
             "dealguard_exact":sum(r["dealguard_exact"] for r in rows),
             "gemini_exact":sum(r["gemini_exact"] for r in rows),
             "both_correct":counts[("paired",True,True)],
             "dealguard_only_correct":counts[("paired",True,False)],
             "gemini_only_correct":counts[("paired",False,True)],
             "neither_correct":counts[("paired",False,False)],
             "by_category":cats,
             "dealguard_mismatches":[r["id"] for r in rows if not r["dealguard_exact"]],
             "gemini_mismatches":[r["id"] for r in rows if not r["gemini_exact"]]}
    prefix.with_suffix(".json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# Frozen synthetic paired evaluation","",
        "Dataset: "+name+"; "+str(n)+" scenarios.","",
        "Labels are AI/developer-authored, not independently reviewed. Engine frozen prior to evaluation.",
        "These results are not production accuracy or legal reliability.","",
        "| Result | Cases |","|---|---:|",
        "| Both systems correct | "+str(summary["both_correct"])+"/"+str(n)+" |",
        "| Only DealGuard correct | "+str(summary["dealguard_only_correct"])+"/"+str(n)+" |",
        "| Only Gemini correct | "+str(summary["gemini_only_correct"])+"/"+str(n)+" |",
        "| Neither correct | "+str(summary["neither_correct"])+"/"+str(n)+" |",
        "| DealGuard exact | "+str(summary["dealguard_exact"])+"/"+str(n)+" |",
        "| Gemini exact | "+str(summary["gemini_exact"])+"/"+str(n)+" |","",
        "## Category breakdown","","| Category | DealGuard | Gemini | Total |","|---|---:|---:|---:|"]
    for k,v in sorted(cats.items()):
        lines.append("| "+k+" | "+str(v["dealguard"])+" | "+str(v["gemini"])+" | "+str(v["cases"])+" |")
    lines.extend(["","## Case-level mistakes",""])
    for r in rows:
        if r["dealguard_exact"] and r["gemini_exact"]:
            continue
        lines += ["### "+r["id"]+" — "+r["category"]+" / "+r["language"],"",
                  "- Proposal: "+r["proposal"],
                  "- Expected rules: "+r["expected_rules"],
                  "- DealGuard rules: "+r["dealguard_rules"],
                  "- Gemini rules: "+r["gemini_rules"],
                  "- Expected commercial flags: "+r["expected_risks"],
                  "- DealGuard commercial flags: "+r["dealguard_risks"],
                  "- Gemini commercial flags: "+r["gemini_risks"],""]
    lines += ["","## Interpretation boundaries","",
              "A synthetic case set is not an unbiased sample of real contracts.",
              "No engine code or scenario labels were patched after predictions in this run.",
              "Independent domain annotation is still necessary.",""]
    prefix.with_suffix(".md").write_text("\n".join(lines),encoding="utf-8")
    print("PAIRED",name,"DealGuard="+str(summary["dealguard_exact"])+"/"+str(n),
          "Gemini="+str(summary["gemini_exact"])+"/"+str(n),
          "both="+str(summary["both_correct"]),
          "dg_only="+str(summary["dealguard_only_correct"]),
          "gemini_only="+str(summary["gemini_only_correct"]),
          "neither="+str(summary["neither_correct"]))
    print("DealGuard mismatches:",",".join(summary["dealguard_mismatches"]))
    print("Gemini mismatches:",",".join(summary["gemini_mismatches"]))
if __name__=="__main__":
    main()
