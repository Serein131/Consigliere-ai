"""DealGuard deterministic checks for explicitly configured commercial constraints.

Not legal advice. Missing data is UNKNOWN, not SAFE. Do not infer counterpart motives.
The engine only checks supported numerical/exclusivity rules, with source excerpts.
"""
import re

PERCENT = r"(\d+(?:\.\d+)?)\s*%"
DAYS = r"(\d+)\s*(?:days?|天)"
def _first(patterns, text):
    for p in patterns:
        m = re.search(p, text, flags=re.I)
        if m:
            return m
    return None

def check_deal(text, rules):
    """Return auditable findings; does not use a language model."""
    text, rules = str(text or ""), str(rules or "")
    findings = []
    limits = {}
    max_discount = _first([
        r"(?:max(?:imum)?\s+discount|discount\s*(?:<=|≤|no more than|not above))\s*(?:<=|≤|:|is|of)?\s*" + PERCENT,
        r"(?:最大折扣|折扣上限|折扣不得超过|降价不超过|最多降价|折扣不超过)\s*(?:为|是|:|：|≤|不超过)?\s*" + PERCENT
    ], rules)
    proposed_discount = _first([
        r"(?:discount|price\s+(?:cut|reduction)|reduce\s+(?:the\s+)?price(?:\s+by)?)\s*(?:of|by|is|:|=)?\s*" + PERCENT,
        PERCENT + r"\s*(?:discount|price\s+cut|reduction|off)",
        r"(?:折扣|降价|价格下调|优惠)\s*(?:为|是|到|:|：)?\s*" + PERCENT,
        PERCENT + r"\s*(?:的)?(?:折扣|降价|价格下调)"
    ], text)
    if max_discount:
        limit = float(max_discount.group(1))
        limits["maximum_discount_pct"] = limit
        if proposed_discount:
            value = float(proposed_discount.group(1))
            findings.append({"rule":"maximum_discount_pct","status":"VIOLATION" if value>limit else "PASS",
                             "observed":value,"limit":limit,"unit":"percent",
                             "evidence":proposed_discount.group(0)[:100]})
        else:
            findings.append({"rule":"maximum_discount_pct","status":"UNKNOWN","reason":"No explicit proposed discount found."})
    min_days = _first([
        r"(?:payment\s+terms?|payment\s+period)\s*(?:>=|≥|at\s+least|minimum|min\.?)\s*" + DAYS,
        r"(?:minimum|min\.?)\s*(?:payment\s+terms?|payment\s+period)\s*(?:of|:|is)?\s*" + DAYS,
        r"(?:付款期限|账期)\s*(?:不低于|不少于|至少|≥)\s*" + DAYS
    ], rules)
    max_days = _first([
        r"(?:payment\s+terms?|payment\s+period)\s*(?:<=|≤|at\s+most|maximum|max\.?|no\s+more\s+than)\s*" + DAYS,
        r"(?:maximum|max\.?)\s*(?:payment\s+terms?|payment\s+period)\s*(?:of|:|is)?\s*" + DAYS,
        r"(?:付款期限|账期)\s*(?:不超过|至多|最多|≤)\s*" + DAYS
    ], rules)
    proposed_days = _first([
        r"(?:payment\s+terms?|payment\s+period|net)\s*(?:of|:|is|=)?\s*" + DAYS,
        DAYS + r"\s*(?:payment\s+terms?|payment\s+period)",
        r"(?:付款期限|账期|付款周期)\s*(?:为|是|:|：)?\s*" + DAYS,
        DAYS + r"\s*(?:付款|账期)"
    ], text)
    if min_days or max_days:
        if min_days and max_days and int(min_days.group(1))>int(max_days.group(1)):
            findings.append({"rule":"payment_days","status":"UNKNOWN","reason":"Contradictory minimum and maximum payment constraints."})
        elif proposed_days:
            value=int(proposed_days.group(1))
            lower=int(min_days.group(1)) if min_days else None
            upper=int(max_days.group(1)) if max_days else None
            violation=(lower is not None and value<lower) or (upper is not None and value>upper)
            findings.append({"rule":"payment_days","status":"VIOLATION" if violation else "PASS",
                             "observed":value,"minimum":lower,"maximum":upper,"unit":"days",
                             "evidence":proposed_days.group(0)[:100]})
        else:
            findings.append({"rule":"payment_days","status":"UNKNOWN","reason":"No explicit proposed payment term found."})
    no_exclusive=bool(re.search(r"(?:zero|no|prohibit(?:ed)?|without|never)\s+(?:\w+\s+){0,2}exclusiv|(?:禁止|不得|不接受|零|无)(?:任何)?(?:独家|排他)|(?:独家|排他)(?:条款)?(?:禁止|不接受)",rules,re.I))
    if no_exclusive:
        explicit_demand=bool(re.search(r"(?:require|demand|request|need|want|insist(?:\s+on)?|must\s+have)\s+(?:\w+\s+){0,5}exclusiv|(?:独家|排他)(?:合作|协议|条款|授权|要求)?|(?:exclusive|exclusivity)\s+(?:agreement|rights?|clause|deal|term)",text,re.I))
        explicit_negative=bool(re.search(r"(?:no|without|remove|waive|not\s+requiring)\s+(?:\w+\s+){0,3}exclusiv|(?:不要求|取消|没有|无需)(?:任何)?(?:独家|排他)",text,re.I))
        status="PASS" if explicit_negative else ("VIOLATION" if explicit_demand else "UNKNOWN")
        findings.append({"rule":"no_exclusivity","status":status,
                         "evidence":"Explicit exclusivity language detected." if status!="UNKNOWN" else None})
    violations=[f for f in findings if f["status"]=="VIOLATION"]
    return {"engine":"dealguard-v1-deterministic","findings":findings,
            "violation_count":len(violations),"configured_checks":len(findings),
            "assessment":"VIOLATION" if violations else ("UNKNOWN" if any(f["status"]=="UNKNOWN" for f in findings) or not findings else "NO_DETECTED_VIOLATION"),
            "scope":"Only explicit configured rules and extractable terms; no legal, psychological or outcome guarantees."}
