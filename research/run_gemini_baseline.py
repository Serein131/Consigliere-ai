#!/usr/bin/env python3
"""Optional external Gemini baseline. NEVER runs without explicit API key & invocation.

All provided fixtures are synthetic. Calls may incur API charges and use quotas.
Keep API keys in environment, never in source or results.
"""
import argparse
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
RULE_NAMES=["maximum_discount_pct","payment_days","no_exclusivity"]
RISK_NAMES=["long_receivables","short_payables","unlimited_liability","auto_renewal","termination_penalty"]

def classify(case, key, model):
    instruction=(
        "You are a rule-auditing comparison baseline. You are NOT given the "
        "DealGuard algorithm or its predictions. Given ONLY explicit deal rules "
        "and proposal, for each configured rule decide VIOLATION, PASS or UNKNOWN. "
        "Do not presume any unstated contractual terms. Detect business review "
        "flags separately (long_receivables, short_payables, unlimited_liability, "
        "auto_renewal, termination_penalty). Only evaluate rules actually configured. "
        "A rejected or historical term is not a current binding deal term. "
        "Return JSON with exactly two keys: predicted_rule_status (a map with keys "
        "maximum_discount_pct, payment_days, no_exclusivity as applicable and "
        "values VIOLATION/PASS/UNKNOWN) and predicted_commercial_risks (an array of "
        "codes). No explanations."
    )
    prompt=json.dumps({"structured_rules":case["structured_rules"],
                       "proposal":case["proposal"]},ensure_ascii=False)
    request_body=json.dumps({
        "systemInstruction":{"parts":[{"text":instruction}]},
        "contents":[{"role":"user","parts":[{"text":prompt}]}],
        "generationConfig":{"temperature":0,"responseMimeType":"application/json"}
    },ensure_ascii=False).encode("utf-8")
    request=urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=request_body,
        headers={"Content-Type":"application/json","x-goog-api-key":key},
        method="POST"
    )
    with urllib.request.urlopen(request,timeout=40) as response:
        payload=json.load(response)
    parts=payload["candidates"][0]["content"]["parts"]
    text="".join(p.get("text","") for p in parts)
    result=json.loads(text)
    if not isinstance(result,dict):
        raise ValueError("Model response is not a JSON object")
    statuses=result.get("predicted_rule_status",{})
    risks=result.get("predicted_commercial_risks",[])
    if not isinstance(statuses,dict) or not isinstance(risks,list):
        raise ValueError("Invalid response fields")
    statuses={k:v for k,v in statuses.items() if k in RULE_NAMES and v in ("PASS","VIOLATION","UNKNOWN")}
    risks=[r for r in risks if r in RISK_NAMES]
    return {"id":case["id"],"predicted_rule_status":statuses,
            "predicted_commercial_risks":risks}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--limit",type=int,default=10,
                    help="Number of cases; start small to control cost (max 60)")
    ap.add_argument("--sleep",type=float,default=2.0,
                    help="Delay between requests to avoid rate limits")
    ap.add_argument("--output",default=str(ROOT/"research"/"baseline_predictions.json"))
    args=ap.parse_args()
    if not (1<=args.limit<=60):
        ap.error("--limit must be 1..60")
    api_key=os.environ.get("GEMINI_API_KEY")
    if not api_key:
        ap.error("Set GEMINI_API_KEY in your local environment; do NOT paste it into GitHub")
    model=os.environ.get("GEMINI_MODEL","gemini-3.5-flash-lite").strip()
    cases=json.loads((ROOT/"research"/"synthetic_cases.json").read_text(encoding="utf-8"))["cases"][:args.limit]
    done={}
    output=pathlib.Path(args.output)
    if output.exists():
        for item in json.loads(output.read_text(encoding="utf-8")):
            done[item["id"]]=item
    for case in cases:
        if case["id"] in done:
            continue
        try:
            result=classify(case,api_key,model)
        except (urllib.error.HTTPError,urllib.error.URLError,ValueError,KeyError,IndexError,TimeoutError) as ex:
            # Do not silently turn failed API requests into apparent model errors.
            print(f"{case['id']}: request failed ({type(ex).__name__}); stop and resume later")
            break
        done[case["id"]]=result
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(list(done.values()),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(f"{case['id']}: saved; {len(done)}/{args.limit}")
        time.sleep(max(0,args.sleep))
    print("Predictions stored locally, no raw API key written.")
    print("Next: python research/evaluate.py --baseline-predictions "+str(output))
if __name__=="__main__":
    main()
