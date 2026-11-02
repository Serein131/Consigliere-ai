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
                    help="Number of cases to run; start small to control cost")
    ap.add_argument("--cases",default=str(ROOT/"research"/"synthetic_cases.json"),
                    help="JSON dataset with a cases array")
    ap.add_argument("--sleep",type=float,default=2.0,
                    help="Delay between requests to avoid rate limits")
    ap.add_argument("--output",default=str(ROOT/"research"/"baseline_predictions.json"))
    args=ap.parse_args()
    source=json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    if not isinstance(source,dict) or not isinstance(source.get("cases"),list):
        ap.error("--cases must contain a list of test cases")
    if not (1<=args.limit<=len(source["cases"])):
        ap.error("--limit must be 1..dataset case count")
    api_key=(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        ap.error("Set GEMINI_API_KEY in your local environment; do NOT paste it into GitHub")
    model=os.environ.get("GEMINI_MODEL","gemini-3.5-flash-lite").strip()
    cases=source["cases"][:args.limit]
    if len({case["id"] for case in cases})!=len(cases):
        ap.error("Dataset has duplicate case IDs")
    done={}
    output=pathlib.Path(args.output)
    if output.exists():
        for item in json.loads(output.read_text(encoding="utf-8")):
            done[item["id"]]=item
    for case in cases:
        if case["id"] in done:
            continue
        result=None
        for attempt in range(5):
            try:
                result=classify(case,api_key,model)
                break
            except urllib.error.HTTPError as ex:
                # Only log HTTP code and stable error status; never the raw response,
                # request headers, user secrets, or variable API diagnostic strings.
                try:
                    error_status=json.loads(ex.read(4096).decode("utf-8")).get("error",{}).get("status","UNKNOWN")
                    if error_status not in ("INVALID_ARGUMENT","FAILED_PRECONDITION","UNAUTHENTICATED",
                                            "PERMISSION_DENIED","NOT_FOUND","RESOURCE_EXHAUSTED",
                                            "UNAVAILABLE","INTERNAL","UNKNOWN"):
                        error_status="OTHER"
                except (ValueError,UnicodeError,AttributeError):
                    error_status="UNKNOWN"
                if ex.code == 429 and attempt < 4:
                    delay=min(120,30*(2**attempt))
                    print(f"{case['id']}: HTTP 429 rate limit; retry {attempt+1}/4 after {delay}s.",flush=True)
                    time.sleep(delay)
                    continue
                print(f"{case['id']}: Gemini HTTP {ex.code}, status={error_status}. Stopping with partial results.",flush=True)
                break
            except (urllib.error.URLError,ValueError,KeyError,IndexError,TimeoutError) as ex:
                print(f"{case['id']}: request failed ({type(ex).__name__}); stopping with partial results.",flush=True)
                break
        if result is None:
            break
        done[case["id"]]=result
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(list(done.values()),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(f"{case['id']}: saved; {len(done)}/{args.limit}",flush=True)
        time.sleep(max(0,args.sleep))
    print("Predictions stored locally, no raw API key written.")
    print("Next: python research/evaluate.py --baseline-predictions "+str(output))
if __name__=="__main__":
    main()
