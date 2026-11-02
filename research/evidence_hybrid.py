"""Evidence-grounded term checking, separate from LLM extraction.

Untrusted extraction -> provenance validation -> deterministic threshold comparison.
Missing/contradictory/unverifiable facts => UNKNOWN, never SAFE.
This is a research prototype, NOT legal advice or a verified contract parser.
"""
import re

STATUS = ("proposed", "agreed", "rejected", "historical", "ambiguous", "absent")
EXC_STATUS = ("required", "not_required", "rejected", "historical", "unresolved", "absent")
RISK_CODES = ("unlimited_liability", "auto_renewal", "termination_penalty")
NON_CURRENT = ("rejected", "historical", "ambiguous", "absent")
CHINESE_DIGITS = {"零":0,"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}

def _numeric_candidates(span):
    """Only extract values present in the verbatim cited source span."""
    normalized = span.replace("％","%").replace(",", "")
    values = [float(x) for x in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", normalized)]
    for m in re.finditer(r"([零一二两三四五六七八九十百]+)",normalized):
        v=m.group(1)
        if "百" in v:
            parts=v.split("百",1); lead=CHINESE_DIGITS.get(parts[0],1) if parts[0] else 1
            tail=parts[1]
            if "十" in tail:
                pieces=tail.split("十",1)
                ten=CHINESE_DIGITS.get(pieces[0],1) if pieces[0] else 1
                val=100*lead+10*ten+CHINESE_DIGITS.get(pieces[1],0)
            else:val=100*lead+CHINESE_DIGITS.get(tail,0)
        elif "十" in v:
            pieces=v.split("十",1)
            lead=CHINESE_DIGITS.get(pieces[0],1) if pieces[0] else 1
            val=10*lead+CHINESE_DIGITS.get(pieces[1],0)
        else:
            val=CHINESE_DIGITS.get(v)
        if val is not None:values.append(float(val))
    return values

def _has_source(text, quote):
    return (isinstance(quote,str) and len(quote.strip())>=2
            and quote.strip() in text)

def _valid_number(text, item, key, cap):
    """Return validated number and a short quote, else None."""
    if not isinstance(item,dict):
        return None
    quote=item.get("evidence","")
    value=item.get(key)
    if not _has_source(text,quote) or isinstance(value,bool) or not isinstance(value,(int,float)):
        return None
    if not 0<=value<=cap:
        return None
    # Avoid accepting a model-invented number that isn't in its literal quote.
    candidates=_numeric_candidates(quote)
    if not any(abs(float(value)-v)<0.0001 for v in candidates):
        return None
    return (float(value),quote[:160])

def _configured(rules):
    cfg={}
    if not isinstance(rules,dict):
        return cfg
    cap=rules.get("discount_max_pct")
    if isinstance(cap,(int,float)) and not isinstance(cap,bool) and 0<=cap<=100:
        cfg["maximum_discount_pct"]=(float(cap),"max")
    p=rules.get("payment_days")
    direct=rules.get("payment_direction")
    if isinstance(p,(int,float)) and not isinstance(p,bool) and 0<=p<=3650 and direct in ("minimum","maximum"):
        cfg["payment_days"]=(float(p),"min" if direct=="minimum" else "max")
    if rules.get("prohibit_exclusivity") is True:
        cfg["no_exclusivity"]=(True,"no")
    return cfg

def audit_extraction(text, rules, extraction):
    """Validate model-produced facts against exact source quotes, then apply explicit rules."""
    text=str(text or "")
    extraction=extraction if isinstance(extraction,dict) else {}
    cfg=_configured(rules)
    findings=[]
    for rule in ("maximum_discount_pct","payment_days","no_exclusivity"):
        if rule not in cfg:continue
        if rule=="no_exclusivity":
            item=extraction.get("exclusivity",{})
            status=item.get("status") if isinstance(item,dict) else None
            quote=item.get("evidence","") if isinstance(item,dict) else ""
            if status not in EXC_STATUS or (status not in ("absent","unresolved") and not _has_source(text,quote)):
                findings.append({"rule":rule,"status":"UNKNOWN","reason":"Unverifiable exclusivity citation or state."})
            elif status=="required" and _has_source(text,quote):
                findings.append({"rule":rule,"status":"VIOLATION","evidence":quote[:160]})
            elif status in ("rejected","not_required") and _has_source(text,quote):
                findings.append({"rule":rule,"status":"PASS","evidence":quote[:160]})
            else:
                findings.append({"rule":rule,"status":"UNKNOWN","reason":"No verified current exclusivity term."})
        else:
            name="discount" if rule=="maximum_discount_pct" else "payment"
            value_key="value_pct" if name=="discount" else "days"
            item=extraction.get(name,{})
            st=item.get("status") if isinstance(item,dict) else None
            if st not in STATUS or st in NON_CURRENT:
                findings.append({"rule":rule,"status":"UNKNOWN","reason":"No single actionable current term."})
                continue
            value=_valid_number(text,item,value_key,100 if name=="discount" else 3650)
            if value is None:
                findings.append({"rule":rule,"status":"UNKNOWN","reason":"Number lacks verbatim supporting evidence."})
                continue
            observed,quote=value
            threshold,op=cfg[rule]
            violated= observed>threshold if op=="max" else observed<threshold
            findings.append({"rule":rule,"status":"VIOLATION" if violated else "PASS",
                             "observed":observed,"limit":threshold,"direction":op,
                             "evidence":quote,"source_state":st})
    warnings=[]
    risks=[]
    payment=extraction.get("payment",{})
    if isinstance(payment,dict) and payment.get("status") in ("agreed","proposed"):
        number=_valid_number(text,payment,"days",3650)
        if number is not None:
            days,quote=number
            role=rules.get("role") if isinstance(rules,dict) else None
            if role=="seller" and days>60:
                risks.append({"code":"long_receivables","evidence":quote})
            if role=="buyer" and days<15:
                risks.append({"code":"short_payables","evidence":quote})
    qualifiers=extraction.get("commercial",{})
    if isinstance(qualifiers,dict):
        for code in RISK_CODES:
            item=qualifiers.get(code,{})
            if isinstance(item,dict) and item.get("active") is True:
                q=item.get("evidence","")
                if _has_source(text,q):
                    risks.append({"code":code,"evidence":q[:160]})
                else:
                    warnings.append("Unsupported quote for "+code)
    statuses=[x["status"] for x in findings]
    count=statuses.count("VIOLATION")
    return {
        "engine":"gemini-extraction-validated-constraints-v1",
        "assessment":"VIOLATION" if count else ("UNKNOWN" if not findings or "UNKNOWN" in statuses else "NO_DETECTED_VIOLATION"),
        "findings":findings,
        "configured_checks":len(findings),
        "violation_count":count,
        "commercial_risks":risks,
        "rule_warnings":warnings,
        "scope":"Rule comparison only after LLM extraction with literal evidence checks; unverified facts remain UNKNOWN. Not legal advice."
    }

def to_prediction(case_id, audit):
    return {
        "id":case_id,
        "predicted_rule_status":{x["rule"]:x["status"] for x in audit["findings"]},
        "predicted_commercial_risks":sorted({x["code"] for x in audit["commercial_risks"]})
    }
