#!/usr/bin/env python3
"""Report four independently computed research arms without inventing unavailable groups."""
import argparse
import csv
import json
import pathlib
from collections import Counter,defaultdict

ARMS=("gemini","gpt","rules","hybrid")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--cases",required=True)
    ap.add_argument("--results-dir",required=True)
    ap.add_argument("--output-prefix",required=True)
    args=ap.parse_args()
    cases=json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))["cases"]
    result_dir=pathlib.Path(args.results_dir)
    canonical={c["id"] for c in cases}
    arms={}
    arm_status={}
    for arm in ARMS:
        f=result_dir/(arm+".json")
        if not f.exists():
            arm_status[arm]={"status":"NOT_RUN","reason":"No actual saved model output"}
            continue
        records=json.loads(f.read_text(encoding="utf-8"))
        given={x.get("id") for x in records}
        if len(records)!=len(cases) or given!=canonical:
            arm_status[arm]={"status":"INCOMPLETE","predictions":len(records),"expected":len(cases)}
            continue
        arms[arm]={x["id"]:x for x in records}
        arm_status[arm]={"status":"COMPLETE","predictions":len(records)}
    rows=[]
    for case in cases:
        exp=case["expected_rule_status"]
        exp_risk=sorted(set(case.get("expected_commercial_risks",[])))
        row={"id":case["id"],"language":case["language"],
             "category":case["category"],"proposal":case["proposal"],
             "expected_rule_states":json.dumps(exp,sort_keys=True,ensure_ascii=False),
             "expected_risks":json.dumps(exp_risk,ensure_ascii=False)}
        for arm in ARMS:
            if arm not in arms:
                row[arm+"_exact"]="NOT_RUN"
                row[arm+"_rules"]=""
                row[arm+"_risks"]=""
                continue
            rec=arms[arm][case["id"]]
            observed=rec.get("predicted_rule_status",{})
            risks=sorted(set(rec.get("predicted_commercial_risks",[])))
            row[arm+"_rules"]=json.dumps(observed,sort_keys=True,ensure_ascii=False)
            row[arm+"_risks"]=json.dumps(risks,ensure_ascii=False)
            row[arm+"_exact"]=bool(observed==exp and risks==exp_risk)
        rows.append(row)
    stats={}
    for arm in ARMS:
        if arm not in arms:
            stats[arm]=arm_status[arm]
            continue
        count=sum(row[arm+"_exact"] is True for row in rows)
        errs=[row["id"] for row in rows if not row[arm+"_exact"]]
        violations=Counter()
        for case in cases:
            expected=case["expected_rule_status"]
            observed=arms[arm][case["id"]]["predicted_rule_status"]
            for rule in set(expected)|set(observed):
                want=expected.get(rule,"NOT_CONFIGURED")=="VIOLATION"
                got=observed.get(rule,"MISSING")=="VIOLATION"
                violations["tp" if want and got else "fp" if got else "fn" if want else "tn"]+=1
        tp,fp,fn=(violations[x] for x in ("tp","fp","fn"))
        stats[arm]={"status":"COMPLETE","full_case_matches":count,"total_cases":len(cases),
                    "exact_match_rate":round(count/len(cases),4),
                    "violations":{"tp":tp,"fp":fp,"fn":fn,"tn":violations["tn"],
                                   "precision":round(tp/(tp+fp),4) if tp+fp else None,
                                   "recall":round(tp/(tp+fn),4) if tp+fn else None},
                    "mismatch_ids":errs}
    summary={"dataset":pathlib.Path(args.cases).name,"sample_size":len(cases),
             "author":"Synthetic AI-assisted cases; no independently validated expert labels",
             "arms":stats,
             "study_limitations":[
                "All scenarios are synthetic, neither a customer sample nor professional legal evidence.",
                "Each configured provider uses its own model and API parameters; cross-model costs and latencies differ.",
                "Gemini and GPT receive the same rule-benchmark instructions; hybrid receives a separate information extraction prompt.",
                "Deterministic rules and hybrid are distinct paths; hybrid is not guaranteed better.",
                "Incomplete or unconfigured model arms are NOT_RUN/INCOMPLETE, never represented as zero accuracy.",
                "Single inference temperature zero is not deterministic guarantee; labels require independent adjudication."
             ]}
    prefix=pathlib.Path(args.output_prefix)
    prefix.parent.mkdir(parents=True,exist_ok=True)
    prefix.with_suffix(".json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with prefix.with_suffix(".csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
        w.writeheader();w.writerows(rows)
    lines=["# Four-arm synthetic benchmark","","**Dataset:** "+summary["dataset"]+" — "+str(len(cases))+" cases.",
           "","Results are provisional synthetic labels, not independently validated contract accuracy.","",
           "| Group | Status | Exact-case matches | Precision (violations) | Recall (violations) |",
           "|---|---|---:|---:|---:|"]
    for arm,name in (("gemini","A · Gemini"),("gpt","B · OpenAI GPT"),("rules","C · deterministic DealGuard"),("hybrid","D · evidence-grounded hybrid")):
        s=stats[arm]
        if s["status"]!="COMPLETE":
            lines.append("| "+name+" | "+s["status"]+" | — | — | — |")
            continue
        v=s["violations"]
        pc="n/a" if v["precision"] is None else str(round(v["precision"]*100,1))+"%"
        rc="n/a" if v["recall"] is None else str(round(v["recall"]*100,1))+"%"
        lines.append("| "+name+" | Complete | "+str(s["full_case_matches"])+"/"+str(len(cases))+
                     " | "+pc+" | "+rc+" |")
    lines.extend(["","## Failure IDs by group",""])
    for arm in ARMS:
        x=stats[arm]
        lines.append("- "+arm+": "+(", ".join(x["mismatch_ids"]) if x["status"]=="COMPLETE" else x["status"]))
    lines.extend(["","## Limits","","These are AI/developer-authored synthetic cases, not independent expert labels.",
                  "A valid future claim requires a new holdout, independent review and actual user research.",
                  "Missing GPT credentials do not imply GPT underperformance.",
                  "Review per-case CSV and saved model predictions rather than treating a single benchmark score as general reliability.",""])
    prefix.with_suffix(".md").write_text("\n".join(lines),encoding="utf-8")
    for arm in ARMS:
        print(arm,json.dumps(stats[arm],ensure_ascii=False)[:1100])
    print("Written",prefix)
if __name__=="__main__":
    main()
