"""Consigliere DealGuard v2: conservative, auditable deal-terms checks.

NOT a legal opinion. Explicit violations mean a currently proposed/agreed term
conflicts with a user-specified threshold, not that a contract has been executed.
A missing/ambiguous fact is UNKNOWN, never automatically safe.
"""
import re

PCT = r"(\d{1,3}(?:\.\d+)?)\s*(?:%|％)"
DAYS = r"(\d{1,4})\s*(?:days?|天)"
DISCOUNT = r"(?:discount|price\s+(?:cut|reduction)|reduce\s+(?:the\s+)?price|降价(?:幅度)?|价格下调|折扣|优惠)"
PAYMENT = r"(?:payment\s+terms?|payment\s+period|net\s+terms?|账期|付款期限|付款周期|回款周期)"
EXCLUSIVITY = re.compile(r"\bexclusiv(?:e|ity)\b|独家|排他", re.I)
NEGATIVE_EXCLUSIVE = re.compile(
    r"\b(?:no|without|reject(?:ed)?|refus(?:e|ed)|declin(?:e|ed)|remove(?:d)?|"
    r"waiv(?:e|ed)|not\s+(?:accept|require|agree\s+to)|won'?t\s+accept)\b.{0,35}"
    r"\bexclusiv(?:e|ity)\b|"
    r"(?:不(?:接受|同意|需要|要求|签)|拒绝|取消|撤销|没有|无需|无|不含|不包括).{0,9}(?:独家|排他)|"
    r"(?:独家|排他).{0,5}(?:已取消|不接受|取消)", re.I)
UNADDRESSED_EXCLUSIVE = re.compile(
    r"\b(?:not\s+(?:been\s+)?discussed|not\s+mentioned|never\s+discussed|"
    r"not\s+yet\s+discussed|not\s+addressed)\b.{0,45}\bexclusiv(?:e|ity)\b|"
    r"(?:尚未|还未|未|没有)(?:正式)?(?:讨论|涉及|商定|决定).{0,12}(?:独家|排他)|"
    r"(?:独家|排他).{0,12}(?:尚未|还未|未|没有)(?:讨论|涉及|商定|决定)", re.I)
REJECTED = re.compile(r"\b(?:reject(?:ed)?|refus(?:e|ed)|declin(?:e|ed)|won'?t\s+accept|not\s+accept(?:ed)?|turned\s+down)\b|拒绝|不接受|已否决|不考虑|不予接受|撤回", re.I)
HISTORICAL = re.compile(r"\b(?:initially|originally|previously|earlier|formerly|used\s+to)\b|最初|原先|此前|之前|曾经|起初", re.I)
CONFIRMED = re.compile(r"\b(?:agreed|accepted|settled|finalized|confirmed|signed|final)\b|最终|敲定|已同意|正式接受|确认", re.I)
CHANGE = re.compile(r"\b(?:but|however|instead|then|now|finally|ultimately)\b|但是|但|不过|改为|后来|目前|最终|最后|现已", re.I)
MONEY_REVIEW = (
    ("unlimited_liability", re.compile(r"\bunlimited\s+(?:liability|indemnification)\b|无限(?:责任|赔偿)",re.I)),
    ("auto_renewal", re.compile(r"\bautomatic\s+renewal\b|\bauto.renew\b|自动续约",re.I)),
    ("termination_penalty", re.compile(r"\btermination\s+(?:fee|penalty)\b|提前终止(?:罚款|违约金)|解约违约金",re.I)),
)

def _number(value, maximum):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean cannot be a numeric threshold")
    number = float(value)
    if not 0 <= number <= maximum or number != number:
        raise ValueError("Threshold outside supported range")
    return int(number) if number.is_integer() else number

def _parse_rules(rules_text, structured_rules):
    warnings = []
    cfg = {"discount_max_pct":None, "payment_min_days":None,
           "payment_max_days":None, "prohibit_exclusivity":False, "role":"unspecified"}
    if structured_rules is not None:
        if not isinstance(structured_rules, dict):
            return cfg, ["Structured rules must be an object."]
        try:
            cfg["discount_max_pct"] = _number(structured_rules.get("discount_max_pct"), 100)
            payment_days = _number(structured_rules.get("payment_days"), 3650)
            direction = structured_rules.get("payment_direction")
            if payment_days is not None:
                if direction == "minimum":
                    cfg["payment_min_days"] = payment_days
                elif direction == "maximum":
                    cfg["payment_max_days"] = payment_days
                else:
                    warnings.append("Payment threshold needs 'minimum' or 'maximum' direction; not audited.")
            elif direction in ("minimum","maximum"):
                warnings.append("Payment direction selected without a numeric threshold.")
            if type(structured_rules.get("prohibit_exclusivity", False)) is bool:
                cfg["prohibit_exclusivity"] = structured_rules.get("prohibit_exclusivity",False)
            else:
                warnings.append("Exclusivity prohibition must be a boolean.")
            if structured_rules.get("role") in ("buyer","seller"):
                cfg["role"] = structured_rules["role"]
            elif structured_rules.get("role") not in (None, "unspecified"):
                warnings.append("Unrecognized deal role.")
        except (ValueError, TypeError, OverflowError):
            warnings.append("One or more numerical rule fields are invalid; check the configuration.")
        return cfg, warnings

    # Compatibility with older free-text inputs. Dedicated controls are preferred.
    t = str(rules_text or "")
    discount = re.search(
        r"(?:max(?:imum)?\s+discount|discount\s+(?:cap|limit)|"
        r"最大折扣|折扣上限|折扣不得超过|降价(?:幅度)?(?:不超过|不得超过)?|最多降价)"
        r"\s*(?:<=|≤|:|：|不超过|不得超过|为|是|of|at|up\s+to)?\s*" + PCT, t, re.I)
    if discount:
        cfg["discount_max_pct"] = float(discount.group(1))
    elif re.search(DISCOUNT, t, re.I):
        warnings.append("A discount rule was mentioned but could not be parsed; not audited.")
    days = re.search(
        r"(?:payment\s+terms?|payment\s+period|net\s+terms?|账期|付款期限|付款周期)"
        r"\s*(?P<direction>>=|<=|≥|≤|at\s+least|at\s+most|no\s+more\s+than|minimum|maximum|"
        r"绝不低于|不低于|不少于|不得低于|至少|最短|不超过|不得超过|最长|至多)"
        r"\s*" + DAYS, t, re.I)
    if days:
        op=days.group("direction").lower()
        if op in (">=","≥","at least","minimum","绝不低于","不低于","不少于","不得低于","至少","最短"):
            cfg["payment_min_days"]=int(days.group(2))
        else:
            cfg["payment_max_days"]=int(days.group(2))
    elif re.search(PAYMENT, t, re.I):
        warnings.append("A payment-term rule was mentioned but could not be parsed; not audited.")
    cfg["prohibit_exclusivity"]=bool(re.search(
        r"\b(?:no|zero|never|prohibit(?:ed)?)\b.{0,24}\bexclusiv(?:e|ity)\b|"
        r"(?:禁止|不得|不接受|绝不接受|无|零).{0,8}(?:独家|排他)",t,re.I))
    if re.search(EXCLUSIVITY,t) and not cfg["prohibit_exclusivity"]:
        warnings.append("Exclusivity was mentioned without an enforceable prohibition.")
    return cfg,warnings

def _clauses(text):
    # Each clause is examined separately. A later final/agreed term takes priority
    # over an earlier proposal; conflicting or negated statements remain uncertain.
    fragments = re.split(r"[;；。！？\n]|(?<=[.!?])\s+|\b(?:and|then)\s+(?=(?:(?:we|they)\s+)?(?:accepted|agreed|rejected|required|requested|demanded)\b)|\bbut\b|\bhowever\b|\bfinally\b|\bultimately\b|但是|但|不过|最终|最后|后来|现已|改为",text,flags=re.I)
    return [c.strip(" ,，.:：\t") for c in fragments if c and c.strip(" ,，.:：\t")]

def _phase(clause):
    if REJECTED.search(clause):
        return "REJECTED"
    if HISTORICAL.search(clause):
        return "HISTORICAL"
    if CONFIRMED.search(clause):
        return "AGREED"
    return "PROPOSED"

def _extract_numbered(clauses, kind):
    found=[]
    for index, clause in enumerate(clauses):
        patterns = ([
            re.compile(DISCOUNT+r"\s*(?:of|by|is|at|:|：|为|是|达到|到|至)?\s*"+PCT,re.I),
            re.compile(PCT+r"\s*(?:的)?\s*"+DISCOUNT,re.I)
        ] if kind=="discount" else [
            re.compile(r"(?:payment\s+within\b|payment\s+terms?|payment\s+period|net\s*|账期|付款期限|付款周期|回款周期)\s*(?:of|is|at|:|：|为|是|达到|到)?\s*"+DAYS,re.I),
            re.compile(DAYS+r"\s*(?:payment\s+terms?|payment\s+period|net\s*terms?|账期|付款期限|付款周期)",re.I)
        ])
        for pat in patterns:
            for m in pat.finditer(clause):
                # Patterns use a single numeric capture group.
                value = float(m.group(1))
                if kind=="payment" and (value < 0 or value>3650):
                    continue
                if kind=="discount" and value >100:
                    continue
                found.append({"observed":value,"evidence":m.group(0)[:120],
                              "claim_status":_phase(clause),"clause_index":index})
        # "Accepted 8%" following a discount clause is common shorthand; do
        # not guess this is a discount unless the word appears in the clause.
    # Deduplicate overlapping regex hits from two word orders.
    return list({(f["clause_index"],f["observed"],f["evidence"]):f for f in found}.values())

def _latest_terms(terms):
    actionable=[x for x in terms if x["claim_status"] not in ("REJECTED","HISTORICAL")]
    if not actionable:
        return None
    # Last live mention supersedes earlier proposals only when explicitly final.
    agreed=[x for x in actionable if x["claim_status"]=="AGREED"]
    if agreed:
        return agreed[-1]
    values={x["observed"] for x in actionable}
    if len(values)>1:
        return {"ambiguous":True,"reason":"Multiple current values stated without a clear final agreement."}
    return actionable[-1]

def _make_numeric(rule, limit, observed, op, unit):
    if observed is None:
        return {"rule":rule,"status":"UNKNOWN","reason":"No actionable explicit term found."}
    if observed.get("ambiguous"):
        return {"rule":rule,"status":"UNKNOWN","reason":observed["reason"]}
    val=observed["observed"]
    violation=(val>limit if op=="max" else val<limit)
    return {"rule":rule,"status":"VIOLATION" if violation else "PASS",
            "observed":val,"limit":limit,"direction":op,"unit":unit,
            "evidence":observed["evidence"],"claim_status":observed["claim_status"]}

def _exclusive_check(clauses):
    hits=[]
    for i,clause in enumerate(clauses):
        if EXCLUSIVITY.search(clause):
            unaddressed=bool(UNADDRESSED_EXCLUSIVE.search(clause))
            negated=bool(NEGATIVE_EXCLUSIVE.search(clause) or
                         re.search(r"\b(?:rejected|declined|refused)\s+[^.;:!?]*,?\s+and\s+(?:the\s+)?exclusivity\b", clause, re.I))
            status="UNKNOWN" if unaddressed else ("PASS" if negated else "VIOLATION")
            hits.append({"rule":"no_exclusivity","status":status,
                         "evidence":clause[:120],"claim_status":"UNADDRESSED" if unaddressed else ("REJECTED" if negated else _phase(clause)),
                         "clause_index":i})
    if not hits:
        return {"rule":"no_exclusivity","status":"UNKNOWN","reason":"Exclusivity not addressed."}
    current=[h for h in hits if h["claim_status"]!="HISTORICAL"]
    if not current:
        return {"rule":"no_exclusivity","status":"UNKNOWN","reason":"Only historical exclusivity language found."}
    # Later explicit resolution supersedes earlier terms. A rejection of the
    # clause must not itself be reported as demanding the clause.
    return {k:v for k,v in current[-1].items() if k!="clause_index"}

def extract_term_mentions(text):
    """Best-effort surface-evidence ledger, NOT a verified contractual chronology.

    Extracts only short substrings of the already-redacted input, tags likely
    historic/rejected/agreed/proposed wording, and never asserts legal status.
    Its states are *heuristic annotations*, independent of the audited findings.
    """
    raw = str(text or "")[:3500]
    chunks = [part.strip() for part in re.split(r"[。！？;；\n]|(?<=[.!?])\s+", raw) if part.strip()]
    rows = []
    for clause in chunks[:18]:
        if REJECTED.search(clause):
            state = "rejected"
        elif HISTORICAL.search(clause):
            state = "historical"
        elif CONFIRMED.search(clause) or re.search(r"(?:最终同意|双方同意|同意了|已经同意|达成一致)",clause):
            state = "agreed"
        elif re.search(r"\b(?:maybe|might|possibly|subject to|depending on|if approved)\b|"
                       r"(?:可能|如果|待批准|尚未确定|尚待)",clause,re.I):
            state = "ambiguous"
        else:
            state = "proposed"
        discount = _extract_numbered([clause], "discount")
        payment = _extract_numbered([clause], "payment")
        # Supplemental recognition for common word orders not handled by the
        # rules-only engine. This is display-only and NEVER changes a verdict.
        if not payment:
            alt = re.search(r"(\d{1,4})\s*天(?:内)?\s*付款|\bpayment\s+in\s+(\d{1,4})\s*days?\b",clause,re.I)
            if alt:
                val = int(alt.group(1) or alt.group(2))
                payment = [{"observed":val,"evidence":alt.group(0)}] if val<=3650 else []
        for kind,terms in (("discount",discount),("payment",payment)):
            for term in terms[:4]:
                rows.append({"field":kind,"state":state,"value":term["observed"],
                             "evidence":clause[:190]})
        if (EXCLUSIVITY.search(clause) or
            re.search(r"\b(?:only|sole|exclusive)\s+(?:reseller|distributor|supplier)\b",clause,re.I)):
            # A negated exclusivity statement is positive scope evidence,
            # but not proof that the actual deal has been signed.
            negative = bool(NEGATIVE_EXCLUSIVE.search(clause) or
                            re.search(r"非(?:独家|排他)|\bnon[- ]exclusive\b",clause,re.I))
            rows.append({"field":"exclusivity",
                         "state":"not_required" if negative else state,
                         "value":None,"evidence":clause[:190]})
    return rows[:24]


def check_deal(text, rules_text="", structured_rules=None):
    """Evaluate only explicitly configured, machine-recognized deal constraints.

    Status: VIOLATION (conflict in live proposal), PASS (the stated
    term passes configured check), UNKNOWN (insufficient/ambiguous evidence).
    Commercial risks are a separate advisory layer, never a PASS override.
    """
    text=str(text or "")[:12000]
    cfg,warnings=_parse_rules(rules_text,structured_rules)
    clauses=_clauses(text)
    findings=[]
    discount_terms=_extract_numbered(clauses,"discount")
    payment_terms=_extract_numbered(clauses,"payment")
    if cfg["discount_max_pct"] is not None:
        findings.append(_make_numeric("maximum_discount_pct",cfg["discount_max_pct"],
                                     _latest_terms(discount_terms),"max","percent"))
    if cfg["payment_min_days"] is not None:
        findings.append(_make_numeric("payment_days",cfg["payment_min_days"],
                                     _latest_terms(payment_terms),"min","days"))
    if cfg["payment_max_days"] is not None:
        findings.append(_make_numeric("payment_days",cfg["payment_max_days"],
                                     _latest_terms(payment_terms),"max","days"))
    if cfg["prohibit_exclusivity"]:
        findings.append(_exclusive_check(clauses))
    commercial_risks=[]
    current_payment=_latest_terms(payment_terms)
    if current_payment and not current_payment.get("ambiguous"):
        days=current_payment["observed"]
        if cfg["role"]=="seller" and days>60:
            commercial_risks.append({"code":"long_receivables","severity":"REVIEW",
                                     "evidence":current_payment["evidence"],
                                     "reason":"Long buyer payment terms may increase seller cashflow exposure."})
        elif cfg["role"]=="buyer" and days<15:
            commercial_risks.append({"code":"short_payables","severity":"REVIEW",
                                     "evidence":current_payment["evidence"],
                                     "reason":"Short buyer payment terms may increase cashflow pressure."})
    for code,pattern in MONEY_REVIEW:
        match=pattern.search(text)
        if match:
            commercial_risks.append({"code":code,"severity":"REVIEW",
                                    "evidence":match.group(0)[:100],
                                    "reason":"Review this clause separately; legal/commercial meaning is context-dependent."})
    count=sum(f["status"]=="VIOLATION" for f in findings)
    assessment="VIOLATION" if count else ("UNKNOWN" if warnings or not findings or any(f["status"]=="UNKNOWN" for f in findings) else "NO_DETECTED_VIOLATION")
    return {"engine":"dealguard-v2-conservative","findings":findings,
            "violation_count":count,"configured_checks":len(findings),
            "assessment":assessment,"commercial_risks":commercial_risks,
            "commercial_risk_level":"REVIEW" if commercial_risks else "NOT_ASSESSED",
            "rule_warnings":warnings,
            "recognized_rules":cfg,
            "term_mentions":extract_term_mentions(text),
            "scope":"Only configured, recognized checks. PASS does not mean a safe or enforceable deal."}
