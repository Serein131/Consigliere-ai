#!/usr/bin/env python3
"""Run independent research arms: Gemini only, GPT only, DealGuard only, Gemini extractor + deterministic checker.

All requests use synthetic cases. Explicit API credentials required per model.
Nothing is trained. No source labels are included in model prompts.
Failed/absent inference never counts as an actual prediction.
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dealguard import check_deal
from evidence_hybrid import audit_extraction,to_prediction

RULE_NAMES=("maximum_discount_pct","payment_days","no_exclusivity")
RISK_NAMES=("long_receivables","short_payables","unlimited_liability","auto_renewal","termination_penalty")
MODEL_PROMPT=(
    "You are an independent commercial-rules evaluation baseline. "
    "Decide PASS, VIOLATION, or UNKNOWN for each configured rule. "
    "No other rule may be added. UNKNOWN means no confirmed actionable information. "
    "Previously proposed, rejected, and withdrawn terms are not current commitments. "
    "For seller receivables over 60 days report long_receivables; for buyer payables "
    "shorter than 15 days report short_payables. Separately report active current "
    "unlimited_liability, auto_renewal, and termination_penalty clauses, not removed ones. "
    "Return ONLY JSON with predicted_rule_status and predicted_commercial_risks."
)
EXTRACTION_PROMPT=(
    "You are a source-grounded information extractor, NOT a decision maker or legal advisor. "
    "Do not decide rule compliance. Do not access or infer expected answers. "
    "Extract the *currently proposed/agreed* deal terms from text, distinguishing superseded, "
    "rejected, ambiguous and absent terms. When conflicting proposals lack a final agreement, "
    "status must be ambiguous with value null. Verbatim evidence must be an exact CONTIGUOUS "
    "substring of user-provided text, unchanged (do not translate, normalize, or invent). "
    "For a numeric value, quote must contain that value as digits or number words. "
    "For a discount percentage, value_pct is an actual percentage reduction (0 to 100). "
    "For payment, days means explicit integer days; DO NOT assume one month is 30 days. "
    "If no exact number can be verified, value must be null and status ambiguous/absent. "
    "Exclusivity status is one of required, not_required, rejected, historical, unresolved, absent. "
    "Only say 'required' if an active offer/accepted clause explicitly demands exclusivity. "
    "For commercial clauses mark active true only for active terms, false for explicitly deleted/"
    "withdrawn clauses, null if uncertain, with exact quote. "
    "For each numeric item status is proposed/agreed/rejected/historical/ambiguous/absent. "
    "Return only JSON exactly with keys discount, payment, exclusivity, commercial. "
    "discount: {status, value_pct, evidence}; payment: {status, days, evidence}; "
    "exclusivity: {status, evidence}; commercial: {unlimited_liability: {active,evidence}, "
    "auto_renewal: {active,evidence}, termination_penalty: {active,evidence}}."
)

def _request(url, body, headers):
    req=urllib.request.Request(url,
        data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(req,timeout=55) as response:
        return json.load(response)

def _model_json(text):
    """Handle optional Markdown fences and JSON envelopes without inventing a prediction."""
    text=str(text).strip()
    fence=chr(96)*3
    if text.startswith(fence) and "\n" in text:
        text=text.split("\n",1)[1].rsplit(fence,1)[0].strip()
    try:
        result=json.loads(text)
    except json.JSONDecodeError as error:
        # All case inputs are synthetic. Log only response format, no credentials.
        print("Model produced malformed JSON; chars:",len(text),
              "start:",repr(text[:85]),"parse category:",type(error).__name__,flush=True)
        raise
    if isinstance(result,str):
        result=json.loads(result)
    if not isinstance(result,dict):
        raise ValueError("Model output was not a JSON object")
    return result

def _gemini_direct(case, key, model):
    # Identical task instruction and user JSON as GPT, aside from provider transport.
    prompt=json.dumps({"structured_rules":case["structured_rules"],
                       "proposal":case["proposal"]},ensure_ascii=False)
    payload={
        "systemInstruction":{"parts":[{"text":MODEL_PROMPT}]},
        "contents":[{"role":"user","parts":[{"text":prompt}]}],
        "generationConfig":{"temperature":0,"responseMimeType":"application/json"}
    }
    doc=_request("https://generativelanguage.googleapis.com/v1beta/models/"+model+":generateContent",
        payload,{"Content-Type":"application/json","x-goog-api-key":key})
    text="".join(x.get("text","") for x in doc["candidates"][0]["content"]["parts"])
    result=_model_json(text)
    if "predicted_rule_status" not in result or "predicted_commercial_risks" not in result:
        print("Gemini returned unexpected field names:",sorted(result)[:8],flush=True)
    states=result.get("predicted_rule_status",{})
    risks=result.get("predicted_commercial_risks",[])
    if not isinstance(states,dict) or not isinstance(risks,list):
        raise ValueError("Gemini returned unexpected JSON shape")
    states={k:v for k,v in states.items() if k in RULE_NAMES and v in ("PASS","VIOLATION","UNKNOWN")}
    risks=sorted(set(x for x in risks if x in RISK_NAMES))
    return {"id":case["id"],"predicted_rule_status":states,"predicted_commercial_risks":risks}

def _gemini_extract(text, key, model):
    payload={
        "systemInstruction":{"parts":[{"text":EXTRACTION_PROMPT}]},
        "contents":[{"role":"user","parts":[{"text":json.dumps({"text":text},ensure_ascii=False)}]}],
        "generationConfig":{"temperature":0,"responseMimeType":"application/json"}
    }
    doc=_request("https://generativelanguage.googleapis.com/v1beta/models/"+model+":generateContent",
        payload,{"Content-Type":"application/json","x-goog-api-key":key})
    chunks=doc["candidates"][0]["content"]["parts"]
    return _model_json("".join(p.get("text","") for p in chunks))

def _openai_direct(case, key, model):
    prompt=json.dumps({"structured_rules":case["structured_rules"],
                       "proposal":case["proposal"]},ensure_ascii=False)
    payload={
        "model":model,
        "input":[{"role":"system","content":MODEL_PROMPT},
                 {"role":"user","content":prompt}],
        "text":{"format":{"type":"json_object"}},
        "max_output_tokens":900
    }
    doc=_request("https://api.openai.com/v1/responses",payload,{
        "Content-Type":"application/json",
        "Authorization":"Bearer "+key})
    pieces=[]
    for entry in doc.get("output",[]):
        if entry.get("type")=="message":
            for part in entry.get("content",[]):
                if part.get("type")=="output_text":
                    pieces.append(part.get("text",""))
    if not pieces:raise ValueError("OpenAI returned no text output")
    result=_model_json("".join(pieces))
    states=result.get("predicted_rule_status",{})
    risks=result.get("predicted_commercial_risks",[])
    if not isinstance(states,dict) or not isinstance(risks,list):
        raise ValueError("OpenAI returned unexpected JSON shape")
    states={k:v for k,v in states.items() if k in RULE_NAMES and v in ("PASS","VIOLATION","UNKNOWN")}
    risks=sorted(set(x for x in risks if x in RISK_NAMES))
    return {"id":case["id"],"predicted_rule_status":states,"predicted_commercial_risks":risks}

def _predict(case,mode,gemini_key,openai_key,gemini_model,gpt_model):
    if mode=="gemini":
        return _gemini_direct(case,gemini_key,gemini_model)
    if mode=="gpt":
        return _openai_direct(case,openai_key,gpt_model)
    if mode=="rules":
        audit=check_deal(case["proposal"],structured_rules=case["structured_rules"])
        return to_prediction(case["id"],audit)
    if mode=="hybrid":
        extraction=_gemini_extract(case["proposal"],gemini_key,gemini_model)
        audit=audit_extraction(case["proposal"],case["structured_rules"],extraction)
        pred=to_prediction(case["id"],audit)
        # Save evidence/provenance only, never a label or key.
        pred["extraction"]=extraction
        pred["audit"]=audit
        return pred
    raise ValueError("Unknown mode")

def run(cases,mode,output,model,keys,delay=6):
    done={}
    if output.exists():
        for entry in json.loads(output.read_text(encoding="utf-8")):
            done[entry["id"]]=entry
    for case in cases:
        if case["id"] in done:continue
        result=None
        for attempt in range(5):
            try:
                result=_predict(case,mode,keys["gemini"],keys["openai"],
                                keys["gemini_model"],keys["gpt_model"])
                break
            except urllib.error.HTTPError as error:
                if error.code==429 and attempt<4:
                    pause=min(120,25*2**attempt)
                    print(case["id"],mode,"HTTP 429; backoff",pause,"seconds",flush=True)
                    time.sleep(pause)
                    continue
                # Never print Google/OpenAI response body or Authorization header.
                print(case["id"],mode,"HTTP",error.code,"request failed",flush=True)
                break
            except (urllib.error.URLError,ValueError,KeyError,IndexError,TimeoutError,TypeError) as error:
                if attempt<2 and mode!="rules":
                    print(case["id"],mode,"response issue:",type(error).__name__,"retry",attempt+1,flush=True)
                    time.sleep(8)
                    continue
                print(case["id"],mode,"error category:",type(error).__name__,flush=True)
                break
        if result is None:
            print("STOP: incomplete arm",mode,"saved",len(done),"/",len(cases),flush=True)
            return False
        done[case["id"]]=result
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(list(done.values()),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(case["id"],mode,"saved",len(done),"/",len(cases),flush=True)
        if mode!="rules":time.sleep(delay)
    return len(done)==len(cases)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--cases",required=True)
    parser.add_argument("--arm",choices=["gemini","gpt","rules","hybrid"],required=True)
    parser.add_argument("--limit",type=int,default=0)
    parser.add_argument("--output",required=True)
    parser.add_argument("--sleep",type=float,default=6)
    args=parser.parse_args()
    cases=json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.limit:
        if not 1<=args.limit<=len(cases):parser.error("--limit out of range")
        cases=cases[:args.limit]
    gemini=(os.environ.get("GEMINI_API_KEY") or "").strip()
    openai=(os.environ.get("OPENAI_API_KEY") or "").strip()
    if args.arm in ("gemini","hybrid") and not gemini:
        parser.error("GEMINI_API_KEY is not configured; no Gemini predictions generated")
    if args.arm=="gpt" and not openai:
        parser.error("OPENAI_API_KEY is not configured; no GPT predictions generated")
    keys={"gemini":gemini,"openai":openai,"gemini_model":os.environ.get("GEMINI_MODEL","gemini-3.5-flash-lite"),
          "gpt_model":os.environ.get("OPENAI_MODEL","gpt-6-luna")}
    if not run(cases,args.arm,pathlib.Path(args.output),args.arm,keys,args.sleep):
        sys.exit("Incomplete arm; only completed predictions saved")
    print("COMPLETE",args.arm,len(cases),"/",len(cases),flush=True)
if __name__=="__main__":
    main()
