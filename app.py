import os
import re
import time
import json
import logging
import http.client
from flask import Flask, request, jsonify, render_template_string
from dealguard import check_deal
from hybrid_service import execute_hybrid, HybridError, MAX_PROPOSAL_CHARS, MAX_REQUEST_BYTES

app = Flask(__name__)

# 关闭 Werkzeug 默认请求体日志，防止服务端记录任何敏感内容
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

API_HOST = "generativelanguage.googleapis.com"

def server_fallback_redact(text: str) -> dict:
    redacted = text
    # 邮箱脱敏
    redacted = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED_EMAIL]', redacted)
    # 电话脱敏
    redacted = re.sub(r'(\+?\d{1,3}[-\s]?)?\(?\d{3}\)?[-\s]?\d{3,4}[-\s]?\d{4}', '[REDACTED_PHONE]', redacted)
    # 合同编号 / ID
    redacted = re.sub(r'\b([A-Z]{2,5}-\d{2,6}|\#[A-Za-z0-9]{4,10})\b', '[REDACTED_ID]', redacted)
    # 金额与百分比（保护“60秒、15分钟、45天、30天”等纯时间词不被误伤）
    redacted = re.sub(
        r'([\$¥￥€£]\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:万美金|万美元|万港币|万元|万|亿|million|billion|k|m|b))?|\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万美金|万美元|万港币|万元|万|亿|美金|美元|港币|元|块|million|billion|k|m|b))',
        '[REDACTED_VALUE]',
        redacted,
        flags=re.IGNORECASE
    )
    # 公司与资本机构
    redacted = re.sub(
        r'([A-Za-z0-9\u4e00-\u9fa5]{2,16}(?:公司|集团|科技|资本|银行|厂|Inc\.?|Corp\.?|LLC|Ltd\.?|Ventures|Capital))',
        '[COMPANY_ENTITY]',
        redacted
    )
    count = len(re.findall(r'\[(?:REDACTED_\w+\vert{}COMPANY_ENTITY)\]', redacted))
    return {"sanitized_text": redacted, "redaction_count": count}

def discover_available_flash_model(api_key: str) -> str:
    conn = http.client.HTTPSConnection(API_HOST, timeout=6)
    try:
        conn.request("GET", f"/v1beta/models?key={api_key}")
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="ignore")
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}: {raw[:120]}")
        data = json.loads(raw)
    finally:
        conn.close()

    models = data.get("models", [])
    flash_candidates = []
    for m in models:
        name = m.get("name", "").replace("models/", "")
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods and "flash" in name.lower() and "2.0-flash" not in name.lower() and "2.5-flash" not in name.lower():
            flash_candidates.append(name)
    for preferred in flash_candidates:
        if "flash-lite" in preferred:
            return preferred
    for preferred in flash_candidates:
        if "flash" in preferred and "tts" not in preferred and "image" not in preferred:
            return preferred
    return flash_candidates[0] if flash_candidates else "gemini-3.5-flash-lite"

def call_gemini_rest(api_key: str, model_name: str, system_instruction: str, user_text: str) -> dict:
    path = f"/v1beta/models/{model_name}:generateContent?key={api_key}"
    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json"
        }
    }
    payload_bytes = json.dumps(body).encode("utf-8")

    conn = http.client.HTTPSConnection(API_HOST, timeout=14)
    try:
        conn.request("POST", path, body=payload_bytes, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="ignore")
        if resp.status != 200:
            err = RuntimeError(f"HTTP_{resp.status}:{raw[:220]}")
            err.status_code = resp.status
            err.err_body = raw
            raise err
        return json.loads(raw)
    finally:
        conn.close()

@app.route("/audit", methods=["POST"])
def audit_only():
    """Deterministic demo: no Gemini call; unsupported/missing terms remain UNKNOWN."""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object"}), 400
    text = str(payload.get("text") or "")[:12000]
    rules = str(payload.get("hard_bottom_line") or "")[:2000]
    if not text.strip():
        return jsonify({"error": "Deal proposal text is required."}), 400
    if not rules.strip() and payload.get("structured_rules") is None:
        return jsonify({"error": "Configure structured rules or hard_bottom_line."}), 400
    # Percentages / durations must remain measurable; identifiers and money are scrubbed.
    return jsonify(check_deal(
        server_fallback_redact(text)["sanitized_text"],
        server_fallback_redact(rules)["sanitized_text"],
        payload.get("structured_rules")
    ))

@app.route("/hybrid-audit", methods=["POST"])
def hybrid_audit():
    """Opt-in Gemini term extraction + deterministic evidence-grounded audit."""
    if request.content_length and request.content_length > MAX_REQUEST_BYTES:
        return jsonify({"error": "REQUEST_TOO_LARGE"}), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "INVALID_JSON"}), 400
    if os.environ.get("ENABLE_HYBRID_AUDIT", "true").lower() in ("false", "0", "off"):
        return jsonify({"error": "HYBRID_DISABLED"}), 503
    if payload.get("consent_to_model_processing") is not True:
        return jsonify({"error": "MODEL_CONSENT_REQUIRED"}), 400
    proposal = payload.get("text")
    if not isinstance(proposal, str) or not proposal.strip():
        return jsonify({"error": "EMPTY_PROPOSAL"}), 400
    if len(proposal) > MAX_PROPOSAL_CHARS:
        return jsonify({"error": "PROPOSAL_TOO_LONG"}), 413
    # Both client and server perform only best-effort regex redaction.
    # Financial terms, discount rates and payment days remain analyzable.
    redacted = server_fallback_redact(proposal)
    try:
        output = execute_hybrid(
            redacted["sanitized_text"],
            payload.get("structured_rules"),
            os.environ.get("GEMINI_API_KEY", ""),
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        )
    except HybridError as exc:
        return jsonify({"error": exc.code}), exc.status_code
    output["redacted_items_count"] = redacted["redaction_count"]
    response = jsonify(output)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/analyze", methods=["POST"])
def analyze_negotiation():
    start_time = time.perf_counter()
    payload = request.get_json(silent=True) or {}

    phase = payload.get("phase", "in_deal")
    lang_pref = payload.get("lang", "en")
    incoming_text = str(payload.get("text") or "")[:12000].strip()
    user_goal = str(payload.get("user_goal") or "")[:2000].strip()
    hard_bottom_line = str(payload.get("hard_bottom_line") or "")[:2000].strip()
    risk_preference = str(payload.get("risk_preference") or "")[:2000].strip()
    session_context = payload.get("session_context") or {}

    if not incoming_text:
        return jsonify({"error": "Please enter negotiation input or select a preset case."}), 400

    redaction_result = server_fallback_redact(incoming_text)
    sanitized_text = redaction_result["sanitized_text"]
    dealguard_audit = check_deal(sanitized_text, hard_bottom_line, payload.get("structured_rules"))
    user_goal = server_fallback_redact(user_goal)["sanitized_text"]
    hard_bottom_line = server_fallback_redact(hard_bottom_line)["sanitized_text"]
    risk_preference = server_fallback_redact(risk_preference)["sanitized_text"]
    if isinstance(session_context, dict):
        session_context = {
            phase: {
                key: server_fallback_redact(str((session_context.get(phase) or {}).get(key) or "")[:300])["sanitized_text"]
                for key in ("trap", "rule")
            }
            for phase in ("pre_deal", "in_deal")
            if isinstance(session_context.get(phase), dict)
        }
    else:
        session_context = {}


    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not configured in Vercel environment."}), 500

    if lang_pref == "zh":
        lang_rule = """【语言纯度绝对铁律 (CRITICAL LANGUAGE PURITY)】:
当前交互环境为纯中文。你输出的 JSON 中，除 'risk_level' 必须保留英文枚举字符串 ("SAFE", "LOW", "MEDIUM", "CRITICAL") 供前端样式绑定外，其余所有字段值（'trap_or_intent', 'triggered_rule', 'box1_text', 'box2_text', 'box3_text', 'counter_question', 'draft_reply'）必须 100% 使用流利、专业、地道的简体中文！
严禁混杂任何英文段落或术语！"""
    else:
        lang_rule = """【LANGUAGE PURITY RULE】:
The UI language is English. ALL values in your JSON output MUST be in fluent, executive-level American English without any Chinese characters."""

    asr_fuzzy_repair_instruction = """
ACOUSTIC NOISE & TRANSCRIPT FAULT-TOLERANCE:
The input transcript may be captured live from a conference room and contain minor acoustic homophones, dropped characters, or misheard commercial jargon. 
You MUST cross-reference the input with the User's Strategic Profile (Goals, Bottom Lines, Opponent Name) to flag potentially ambiguous words, without inventing missing facts or asserting hidden motives as facts."""

    phase_instructions = {
        "pre_deal": """CURRENT STAGE: PHASE 1 — T-15m PRE-DEAL BRIEFING & WARGAMING (战前15分钟沙盘预警).
Objective: Prepare verifiable facts, constraints, questions and a measured opening. Do not imply a proven win rate.
- In 'trap_or_intent': Identify the most likely Game-Theoretic Playbook the opponent will use (e.g. Ultimatum Game / Artificial Urgency / Cheap Talk Future Bait).
- In 'triggered_rule': Cite the exact reservation value (BATNA / Hard Bottom Line) most at risk today and lock it.
- In 'box1_text': [Opening Anchor & Framing]: Proactive agenda frame or opening anchor the user should set in the first 2 minutes.
- In 'box2_text': [Predicted Traps & Signaling Test]: Specific traps to anticipate and how to test whether opponent claims are 'Cheap Talk' vs. 'Costly Signals'.
- In 'box3_text': [Decision Reminder]: Pause or verification steps grounded in user-entered preferences.
- In 'counter_question': [Pre-Meeting Reminder Draft]: One concise reminder for the user to copy; do not claim it was delivered by SMS.
- In 'draft_reply': [Pre-Meeting Agenda Opener]: Crisp opening statement to establish leverage before sitting down.""",

        "in_deal": """CURRENT STAGE: PHASE 2 — IN-DEAL LIVE INTERVENTION (战中无痕交锋与三元拆解).
Objective: Analyze voluntarily provided text or user-controlled transcripts. Distinguish explicitly stated terms, hypotheses and unknowns.
- Do not infer a safe transaction merely because the other party is cooperative. Explicitly check rule evidence.
- Use only the configured structured thresholds and deterministic audit for rule conflicts; never assume fixed 10% or 45-day constraints.
- In 'triggered_rule': Cite which exact Goal, Budget, or Hard Bottom Line was triggered or satisfied.
- In 'box1_text': [Verified Facts]: Objective terms explicitly stated by counterparty (zero speculation).
- In 'box2_text': [Strategic Inferences]: Clearly labeled alternative interpretations; do not claim knowledge of the opponent's intentions.
- In 'box3_text': [Unknowns to Probe]: Critical missing variables required to test their bluff or verify constraints.
- In 'counter_question': [Live Counter-Question (<25 words)]: Sharp, non-defensive question to say out loud right now to flip leverage.
- In 'draft_reply': [Tactical Reply / Live Pivot]: Complete, poised response ready to speak or negotiate.""",

        "post_deal": """CURRENT STAGE: PHASE 3 — T+0m POST-DEAL 60s VOICE DEBRIEF & FOLLOW-UP (战后60秒口述复盘与跟进闭环).
Objective: The user dictated a 60s summary right after the meeting. Cross-examine what actually happened against the pre-deal bottom lines and any pre-wargame predictions in session context!
- If all bottom lines were held, set 'risk_level' to 'SAFE'. If the user made an unconditioned verbal concession that breached or neared a bottom line, set 'risk_level' to 'MEDIUM' or 'CRITICAL'.
- In 'trap_or_intent': Audit verdict (e.g. '监测到口头妥协漏洞 — 需强制附加条件纠偏' or 'Verbal Slippage Detected — Conditional Walk-Back Required').
- In 'triggered_rule': Specific bottom line or goal that was defended or breached.
- In 'box1_text': [Defended Ground]: Key terms and bottom lines successfully protected during the meeting.
- In 'box2_text': [Slippage & Risk Exposure]: Verbal compromises or unverified opponent promises that must be fenced in.
- In 'box3_text': [Quid Pro Quo Conditioning]: Concrete reciprocal condition that must be attached to any concession made.
- In 'counter_question': [Core Debrief Takeaway]: 1-sentence strategic priority for the next 24 hours.
- In 'draft_reply': [High-Leverage Follow-Up Email]: A masterfully written email that politely summarizes agreed points while conditioning any verbal concessions on strict reciprocal terms."""
    }

    selected_phase_prompt = phase_instructions.get(phase, phase_instructions["in_deal"])

    session_history_str = ""
    if phase == "post_deal" and session_context:
        if session_context.get("pre_deal"):
            session_history_str += f"\n[STAGE 1 WARGAME HISTORY (Prior Context)]: {json.dumps(session_context['pre_deal'], ensure_ascii=False)}"
        if session_context.get("in_deal"):
            session_history_str += f"\n[STAGE 2 IN-DEAL HISTORY (Live Context)]: {json.dumps(session_context['in_deal'], ensure_ascii=False)}"

    system_instruction = f"""You are Consigliere AI (v5.1), an evidence-aware commercial negotiation decision assistant.
You support user-controlled, consent-based workflows; never assume recording is illegal or automatically private. You are not a lawyer.

USER STRATEGIC PROFILE (MEMORY BANK):
- [Core Goal & Budget]: {user_goal}
- [Free-text context, not machine-enforced thresholds]: {hard_bottom_line}
- [User-entered decision preferences]: {risk_preference}

{asr_fuzzy_repair_instruction}

{selected_phase_prompt}

{lang_rule}

Output ONLY a single valid JSON object with these exact 8 keys (no Markdown code block wrappers):
{{
  "risk_level": "SAFE, LOW, MEDIUM, or CRITICAL",
  "trap_or_intent": "Classification or audit verdict",
  "triggered_rule": "Evidence-based reference to user-configured constraints or unknowns",
  "box1_text": "Pillar 1 Content",
  "box2_text": "Pillar 2 Content",
  "box3_text": "Pillar 3 Content",
  "counter_question": "Immediate counter-question or copyable reminder draft (<25 words)",
  "draft_reply": "Complete follow-up email, tactical reply draft, or pre-meeting framing note"
}}"""

    user_prompt = f"[{phase.upper()} INPUT (Sanitized)]: {sanitized_text}{session_history_str}"
    user_prompt += "\n[DETERMINISTIC DEALGUARD AUDIT]: " + json.dumps(dealguard_audit, ensure_ascii=False)
    user_prompt += "\nExplicit audit findings take precedence. UNKNOWN does not mean SAFE. Never invent terms or assert inferred motives as facts."
    user_prompt += "\nSeparate rule compliance from commercial risk. A passed explicit rule does not imply a good or legally safe deal. Treat REJECTED/HISTORICAL terms as non-binding and seek clarification for contradictions."
    user_prompt += "\nThis is decision support only; no legal advice or contract execution."

    primary_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    candidate_models = [primary_model, "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3-flash-preview"]
    used_model = None
    raw_api_resp = None
    error_logs = []
    has_429 = False

    for candidate in dict.fromkeys(candidate_models):
        try:
            used_model = candidate
            raw_api_resp = call_gemini_rest(api_key, candidate, system_instruction, user_prompt)
            break
        except Exception as e:
            status_code = getattr(e, "status_code", None)
            if status_code == 429:
                has_429 = True
                error_logs.append(f"{candidate}: 429 配额限制")
            elif "timed out" in str(e).lower():
                error_logs.append(f"{candidate}: 响应超时")
            else:
                error_logs.append(f"{candidate}: {str(e)[:70]}")

    if not raw_api_resp:
        try:
            discovered = discover_available_flash_model(api_key)
            if discovered not in candidate_models:
                used_model = discovered
                raw_api_resp = call_gemini_rest(api_key, discovered, system_instruction, user_prompt)
        except Exception as disc_err:
            error_logs.append(f"Auto-Discovery: {str(disc_err)[:70]}")

    if not raw_api_resp:
        if has_429:
            msg = "⚡ 触发 Google 免费 API 每分钟频次限制。免费版配额正在重置，请稍候 15~20 秒后再次点击即可正常推演！"
        else:
            msg = f"模型调用失败。详细状态: {'; '.join(error_logs)}"
        return jsonify({"error": msg}), 500

    try:
        candidates = raw_api_resp.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", [])
        text_out = ""
        for p in parts:
            if "text" in p and not p.get("thought", False):
                text_out += p["text"]
        text_out = text_out.strip()
        if text_out.startswith("```"):
            text_out = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_out, flags=re.DOTALL).strip()

        tactical_output = json.loads(text_out)
        if not isinstance(tactical_output, dict):
            raise ValueError("Expected JSON object")
        if tactical_output.get("risk_level") not in ("SAFE","LOW","MEDIUM","CRITICAL"):
            tactical_output["risk_level"] = "MEDIUM"
        if dealguard_audit["violation_count"] > 0:
            tactical_output["risk_level"] = "CRITICAL"
            prefix = "确定性规则审计检测到交易底线冲突。" if lang_pref == "zh" else "Deterministic rule audit detected explicit constraint violation."
            tactical_output["triggered_rule"] = prefix + " " + str(tactical_output.get("triggered_rule",""))
        elif dealguard_audit["assessment"] == "UNKNOWN" and tactical_output["risk_level"] == "SAFE":
            tactical_output["risk_level"] = "LOW"
        if dealguard_audit["commercial_risks"] and tactical_output["risk_level"] == "SAFE":
            tactical_output["risk_level"] = "LOW"
        latency_ms = round((time.perf_counter() - start_time) * 1000)

        return jsonify({
            "sanitized_payload_sent_to_llm": sanitized_text,
            "redacted_items_count": redaction_result["redaction_count"],
            "measured_latency_ms": latency_ms,
            "model_used": used_model,
            "phase_executed": phase,
            "dealguard_audit": dealguard_audit,
            "tactical_advice": tactical_output
        })
    except Exception as parse_err:
        return jsonify({"error": f"Failed to parse model JSON: {str(parse_err)}"}), 500

HTML_UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consigliere AI v5.3 | Prepare · Protect · Debrief</title>
    <style>
        :root {
            --bg-canvas: #f8fafc;
            --card-bg: #ffffff;
            --border-subtle: #e2e8f0;
            --border-hover: #cbd5e1;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --text-label: #334155;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --primary-light: #eff6ff;
            --emerald: #059669;
            --emerald-light: #ecfdf5;
        }

        body {
            background-color: var(--bg-canvas);
            background-image: radial-gradient(ellipse at 50% 0%, rgba(59, 130, 246, 0.08), transparent 60%);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            padding: 36px 20px 60px 20px;
            max-width: 920px;
            margin: auto;
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
        }

        .header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            margin-bottom: 22px;
        }

        .main-title {
            font-size: 24px;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #0f172a;
            margin: 0 0 6px 0;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .badge {
            background: #eff6ff;
            color: #2563eb;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12.5px;
            font-weight: 600;
            border: 1px solid #bfdbfe;
            letter-spacing: 0;
        }

        .subtitle {
            color: var(--text-muted);
            font-size: 13.5px;
            font-weight: 500;
        }

        .lang-switch {
            display: flex;
            background: #e2e8f0;
            padding: 3px;
            border-radius: 8px;
            gap: 2px;
        }

        .lang-btn {
            background: transparent;
            border: none;
            color: #64748b;
            padding: 6px 14px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s ease;
            width: auto;
            margin: 0;
        }

        .lang-btn.active {
            background: #ffffff;
            color: #0f172a;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-subtle);
            border-radius: 14px;
            padding: 22px 24px;
            margin-top: 18px;
            box-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.05), 0 2px 6px -1px rgba(15, 23, 42, 0.02);
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }

        .card:hover {
            border-color: var(--border-hover);
        }

        .card-title {
            font-size: 16px;
            font-weight: 700;
            color: #0f172a;
            display: block;
            margin-bottom: 4px;
            letter-spacing: -0.01em;
        }

        label {
            font-size: 13.5px;
            color: var(--text-label);
            display: block;
            margin-top: 14px;
            margin-bottom: 5px;
            font-weight: 600;
        }

        input, select, textarea {
            background: #f8fafc;
            color: #0f172a;
            border: 1.5px solid #cbd5e1;
            padding: 11px 14px;
            border-radius: 9px;
            width: 100%;
            box-sizing: border-box;
            font-size: 14.5px;
            transition: all 0.2s ease;
            font-family: inherit;
        }

        input:focus, select:focus, textarea:focus {
            background: #ffffff;
            border-color: var(--primary);
            box-shadow: 0 0 0 3.5px rgba(37, 99, 235, 0.12);
            outline: none;
        }

        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }

        .phase-tabs {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 12px;
            margin-top: 14px;
        }

        .phase-tab {
            background: #ffffff;
            border: 1.5px solid #e2e8f0;
            padding: 13px 15px;
            border-radius: 10px;
            cursor: pointer;
            text-align: left;
            transition: all 0.2s ease;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
            margin: 0;
            width: 100%;
        }

        .phase-tab:hover {
            background: #f8fafc;
            border-color: #cbd5e1;
            transform: translateY(-1px);
        }

        .phase-tab.active {
            background: #eff6ff;
            border: 2px solid #2563eb;
            box-shadow: 0 4px 14px rgba(37, 99, 235, 0.12);
        }

        .phase-tab-title {
            font-weight: 700;
            font-size: 14.5px;
            color: #1e293b;
            display: block;
        }

        .phase-tab.active .phase-tab-title {
            color: #1d4ed8;
        }

        .phase-tab-desc {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
            display: block;
            line-height: 1.4;
        }

        .session-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 10px 16px;
            border-radius: 9px;
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 14px;
            flex-wrap: wrap;
            gap: 10px;
        }

        .session-status {
            display: flex;
            gap: 16px;
            align-items: center;
            flex-wrap: wrap;
            font-weight: 500;
        }

        .session-dot {
            font-weight: 600;
        }

        .btn-reset {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            color: #475569;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            width: auto;
            margin: 0;
            transition: all 0.15s ease;
        }

        .btn-reset:hover {
            background: #f1f5f9;
            color: #0f172a;
            border-color: #94a3b8;
        }

        .preset-row {
            display: flex;
            gap: 9px;
            margin-top: 14px;
            flex-wrap: wrap;
        }

        .preset-btn {
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            color: #334155;
            padding: 7px 15px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 9999px;
            cursor: pointer;
            transition: all 0.15s ease;
            width: auto;
        }

        .preset-btn:hover {
            background: #e2e8f0;
            color: #0f172a;
            transform: translateY(-1px);
        }

        .btn-row {
            display: flex;
            gap: 14px;
            margin-top: 16px;
        }

        button.primary {
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff;
            border: none;
            padding: 12px 20px;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
            transition: all 0.2s ease;
            width: 100%;
        }

        button.primary:hover {
            background: linear-gradient(135deg, #1d4ed8, #1e40af);
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(37, 99, 235, 0.35);
        }

        button.mic-btn {
            background: linear-gradient(135deg, #059669, #047857);
            color: #ffffff;
            border: none;
            padding: 12px 20px;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(5, 150, 105, 0.25);
            transition: all 0.2s ease;
            width: 100%;
        }

        button.mic-btn:hover {
            background: linear-gradient(135deg, #047857, #065f46);
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(5, 150, 105, 0.35);
        }

        button.mic-btn.active {
            background: linear-gradient(135deg, #dc2626, #b91c1c);
            animation: pulse-ring 1.5s infinite;
            box-shadow: 0 4px 14px rgba(220, 38, 38, 0.4);
        }

        @keyframes pulse-ring {
            0% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.02); opacity: 0.9; }
            100% { transform: scale(1); opacity: 1; }
        }

        .card.risk-CRITICAL, .card.risk-MEDIUM {
            border-left: 6px solid #ef4444;
            background: #ffffff;
        }

        .card.risk-LOW {
            border-left: 6px solid #f59e0b;
            background: #ffffff;
        }

        .card.risk-SAFE {
            border-left: 6px solid #10b981;
            background: #ffffff;
        }

        .meta {
            font-size: 13.5px;
            color: #065f46;
            background: #f0fdf4;
            padding: 13px 16px;
            border-radius: 9px;
            border: 1px solid #bbf7d0;
            word-break: break-all;
            line-height: 1.6;
        }

        .trap-header {
            font-size: 19px;
            font-weight: 800;
            letter-spacing: -0.01em;
            margin: 16px 0 6px 0;
        }

        .tri-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 14px;
            margin-top: 16px;
        }

        .tri-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 14px 16px;
            border-radius: 10px;
            font-size: 13.5px;
            line-height: 1.6;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
        }

        .tri-title {
            color: #1d4ed8;
            font-weight: 700;
            margin-bottom: 6px;
            font-size: 13.5px;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .counter-banner {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #fffbeb;
            border: 1.5px solid #fde68a;
            border-radius: 10px;
            padding: 14px 18px;
            margin: 16px 0 12px 0;
            flex-wrap: wrap;
            gap: 12px;
        }

        .counter-text {
            font-size: 16px;
            color: #92400e;
            font-weight: 700;
            letter-spacing: -0.01em;
        }

        .draft-container {
            background: #f8fafc;
            border: 1.5px solid #e2e8f0;
            color: #1e293b;
            padding: 18px 20px;
            border-radius: 10px;
            font-size: 14.5px;
            line-height: 1.7;
            white-space: pre-wrap;
            font-family: inherit;
        }

        .action-btns {
            display: flex;
            gap: 10px;
            margin-top: 14px;
            flex-wrap: wrap;
        }

        .action-btn {
            background: #ffffff;
            border: 1.5px solid #cbd5e1;
            color: #1e293b;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
            width: auto;
            margin: 0;
        }

        .action-btn:hover {
            background: #f1f5f9;
            border-color: #94a3b8;
            color: #0f172a;
        }

        .action-btn.primary-action {
            border-color: #2563eb;
            color: #1d4ed8;
            background: #eff6ff;
        }

        .action-btn.primary-action:hover {
            background: #2563eb;
            color: #ffffff;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13.5px;
            margin-top: 12px;
        }

        th, td {
            border: 1px solid #e2e8f0;
            padding: 12px 14px;
            text-align: left;
            line-height: 1.5;
        }

        th {
            background: #f8fafc;
            color: #475569;
            font-weight: 700;
        }

        td {
            color: #334155;
            background: #ffffff;
        }

        @media (max-width: 680px) {
            body { padding: 16px 12px; }
            .grid-2, .tri-grid, .phase-tabs, .btn-row { grid-template-columns: 1fr; flex-direction: column; }
            .card { padding: 18px 16px; }
        }

        /* DealGuard V5 — clear, testable decision layer */
        .dg-hero {background:linear-gradient(120deg,#0b1731 0%,#102d47 57%,#123d43 100%);color:#f8fafc;
            border:1px solid #24425a;border-radius:20px;padding:28px 30px;margin:18px 0 23px;
            box-shadow:0 20px 45px -26px rgba(7,31,47,.8);position:relative;overflow:hidden}
        .dg-hero::after{content:"";position:absolute;right:-68px;top:-102px;width:275px;height:275px;
            border-radius:50%;background:radial-gradient(circle,rgba(57,196,169,.15),transparent 66%);pointer-events:none}
        .dg-kicker{font-size:11px;font-weight:800;letter-spacing:.16em;color:#7dd3c0;text-transform:uppercase;margin-bottom:10px}
        .dg-hero h1{font-size:clamp(24px,4vw,36px);line-height:1.18;letter-spacing:-.03em;margin:0 0 9px;font-weight:800;max-width:690px}
        .dg-subtitle{font-size:14px;line-height:1.65;color:#cedbe6;max-width:720px;margin:0 0 18px}
        .dg-chips{display:flex;gap:9px;flex-wrap:wrap}
        .dg-chip{border:1px solid rgba(192,226,227,.26);background:rgba(255,255,255,.06);
            color:#d8eeee;border-radius:999px;padding:6px 11px;font-size:12px;font-weight:600}
        .dg-panel{background:#fff;border:1px solid #d7e3ed;border-radius:17px;
            padding:22px 24px;box-shadow:0 6px 24px -16px rgba(8,30,48,.20);margin-bottom:22px}
        .dg-panel-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
        .dg-panel h2{font-size:17px;line-height:1.4;margin:0;font-weight:800}
        .dg-panel p{margin:7px 0 14px;font-size:13px;color:#64748b}
        .dg-label{background:#edfdf7;color:#047857;border:1px solid #a7f3d0;border-radius:999px;
            padding:4px 9px;font-size:11px;font-weight:800}
        .dg-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
        .dg-actions button{width:auto;margin:0;padding:11px 15px;border-radius:9px;font-size:13px;font-weight:750}
        .dg-primary{background:#0b6b62;color:#fff;border:1px solid #0b6b62}
        .dg-primary:hover{background:#07534e}
        .dg-secondary{background:#f1f5f9;color:#0f172a;border:1px solid #cbd5e1}
        .dg-secondary:hover{background:#e2e8f0}
        .dg-output{display:none;margin-top:17px;border-top:1px solid #e2e8f0;padding-top:16px}
        .dg-summary{display:flex;align-items:center;justify-content:space-between;gap:9px;flex-wrap:wrap;margin-bottom:11px}
        .dg-status{font-size:13px;font-weight:850;letter-spacing:.02em}
        .dg-status.violation{color:#b91c1c}.dg-status.unknown{color:#a16207}.dg-status.pass{color:#047857}
        .dg-count{font-size:12px;color:#64748b}
        .dg-findings{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}
        .dg-finding{padding:12px;border:1px solid #e2e8f0;border-radius:11px;min-height:86px;background:#f8fafc}
        .dg-finding-title{font-size:12px;font-weight:750;color:#0f172a;margin-bottom:6px}
        .dg-finding-state{font-size:12px;font-weight:750}
        .dg-finding-state.violation{color:#b91c1c}.dg-finding-state.unknown{color:#a16207}.dg-finding-state.pass{color:#047857}
        .dg-finding-evidence{font-size:11px;color:#475569;line-height:1.55;margin-top:6px;overflow-wrap:anywhere}
        .dg-footnote{font-size:11px;color:#64748b;margin-top:12px;line-height:1.6}
        .dg-config{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 16px;margin:14px 0}
        .dg-config label{margin:0 0 5px;font-size:12px}.dg-config select,.dg-config input:not([type=checkbox]){padding:9px 10px;font-size:13px}
        .dg-config input[type=checkbox]{width:22px;height:22px}
        .dg-notice{font-size:12px;color:#64748b}.dg-risk{padding:12px;margin-top:12px;border:1px solid #f3d5a7;border-radius:12px;background:#fffbeb}
        .dg-risk strong{color:#92400e;font-size:13px}.dg-risk p{font-size:12px;margin:6px 0;color:#78350f}
        .dg-step{font-size:11px;color:#0f766e;letter-spacing:.06em;font-weight:800;text-transform:uppercase;margin:16px 0 7px}
        .dg-proposal{min-height:116px;resize:vertical;font-size:14px;line-height:1.7}
        .dg-meta-line{display:flex;justify-content:space-between;gap:12px;font-size:11px;color:#64748b;line-height:1.5;margin:5px 0}
        .dg-meta-line span{overflow-wrap:anywhere}
        .dg-consent{display:flex;align-items:flex-start;gap:10px;margin:16px 0 0;background:#f8fafc;
            border:1px solid #e2e8f0;border-radius:11px;padding:12px;font-size:12px;color:#475569;line-height:1.6;font-weight:500}
        .dg-consent input{width:18px;height:18px;margin-top:2px;flex-shrink:0;accent-color:#0b6b62}
        .dg-action-hint{font-size:12px;color:#64748b;margin:9px 0 0;line-height:1.6}
        .dg-copilot-link{display:none;margin-top:12px;width:auto;border:1px solid #cbd5e1;background:#fff;color:#0f172a}
        .dg-copilot-link:hover{background:#f1f5f9}
        .dg-evidence{margin:14px 0;padding:15px;border:1px solid #d6e9ed;background:#f8fcfc;border-radius:12px}
        .dg-evidence h3{margin:0 0 4px;font-size:14px;color:#154e54}
        .dg-evidence > p{font-size:11px;line-height:1.55;color:#64748b;margin:0 0 11px}
        .dg-term-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
        .dg-term{background:#fff;border:1px solid #dbe7ee;padding:11px;border-radius:10px;overflow-wrap:anywhere;min-height:95px}
        .dg-term strong{font-size:12px;color:#163446;display:block}
        .dg-term em{font-size:11px;font-style:normal;color:#64748b;display:block;margin:5px 0}
        .dg-term q{font-size:11px;line-height:1.65;color:#0f766e;display:block;margin-top:7px;padding:7px;border-left:2px solid #14b8a6;background:#f0fdfa}
        .dg-term .dg-unverified{font-size:11px;color:#a16207;margin-top:7px}
        .dg-panel .dg-danger{color:#b91c1c}
        .dg-result-mode{font-size:11px;color:#64748b;margin:0 0 10px}
        .dg-actions .dg-primary[disabled],.dg-actions .dg-secondary[disabled]{opacity:.55;cursor:not-allowed}
        @media(max-width:680px){.dg-term-grid{grid-template-columns:1fr}.dg-meta-line{flex-wrap:wrap}}
        .workflow-navigation{margin-top:18px}
        .workflow-navigation .card-title{margin-bottom:4px;font-size:18px}
        .stage-intro{font-size:12.5px;color:#64748b;line-height:1.6;margin:7px 0 12px}
        .stage-pane .card{margin-top:16px}
        .stage-pane .dg-panel{margin-top:16px}
        .stage-workspace{border:1px solid #b9d6da}
        .voice-panel{margin-top:16px;padding:14px;background:#f8fafc;border:1px solid #dce8f0;border-radius:12px}
        .voice-panel .stage-intro{margin-bottom:0}
        .voice-header{display:flex;align-items:center;gap:12px;justify-content:space-between;flex-wrap:wrap}
        .voice-header label{margin:0}
        .voice-header select{width:auto;min-width:220px;max-width:100%;font-size:13px}
        .voice-consent,.agent-consent{display:flex;align-items:flex-start;gap:10px;line-height:1.55;
            font-size:12px;color:#475569;font-weight:500;padding:10px 0;margin:7px 0}
        .voice-consent input,.agent-consent input{width:19px;height:19px;margin:1px 0 0;flex:0 0 19px;accent-color:#0b6b62}
        .agent-consent{border-top:1px solid #e2e8f0;margin-top:16px}
        .voice-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:7px}
        .voice-actions #mic_btn{width:auto;min-width:210px;margin:0}
        .voice-status{font-size:12px;color:#0f766e;font-weight:600}
        #stage_live_audit .dg-output{border-top:1px solid #cde2e1}
        .phase-tab.active{border-color:#0b6b62;background:#ecfdf7}
        .phase-tab.active .phase-tab-title{color:#07534e}
        @media(max-width:680px){
            .workflow-navigation .phase-tabs{grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}
            .workflow-navigation .phase-tab{padding:11px 8px}
            .workflow-navigation .phase-tab-title{font-size:12px}
            .workflow-navigation .phase-tab-desc{display:none}
            .voice-header{align-items:stretch}
            .voice-header select{width:100%}
            .voice-actions #mic_btn{width:100%}
        }

        @media(max-width:680px){.dg-config{grid-template-columns:1fr 1fr}
          .dg-hero{padding:23px 19px;border-radius:15px}
          .dg-panel{padding:18px 16px}
          .dg-findings{grid-template-columns:1fr}
          .dg-actions button{flex:1;min-width:140px}
        }
    </style>
</head>
<body>
    <div class="header-row">
        <div>
            <div class="main-title">⚡ Consigliere AI <span class="badge">v5.3 · Unified Negotiation Agent</span></div>
            <div class="subtitle" id="subtitle_text">Set limits · Verify terms · Explore options</div>
        </div>
        <div class="lang-switch">
            <button type="button" class="lang-btn" id="btn_en" onclick="setLanguage('en')">🇺🇸 English</button>
            <button type="button" class="lang-btn" id="btn_zh" onclick="setLanguage('zh')">🇨🇳 中文</button>
        </div>
    </div>


    <!-- One navigation: Prepare → Protect → Debrief. No second numbered journey. -->
    <nav class="card workflow-navigation" aria-label="Negotiation workflow">
        <h2 class="card-title" id="sec2_title">Your three-stage decision workspace</h2>
        <p class="stage-intro" id="workflow_intro">One set of guardrails · One stage input · You control every AI call.</p>
        <div class="phase-tabs">
            <button type="button" class="phase-tab active" id="tab_pre_deal" aria-current="step" onclick="setPhase('pre_deal')">
                <span class="phase-tab-title" id="tab1_t">01 · Prepare — Pre-deal</span>
                <span class="phase-tab-desc" id="tab1_d">Strategy preparation & reminder draft</span>
            </button>
            <button type="button" class="phase-tab" id="tab_in_deal" onclick="setPhase('in_deal')">
                <span class="phase-tab-title" id="tab2_t">02 · Protect — In-deal</span>
                <span class="phase-tab-desc" id="tab2_d">Optional speech transcription & tactical review</span>
            </button>
            <button type="button" class="phase-tab" id="tab_post_deal" onclick="setPhase('post_deal')">
                <span class="phase-tab-title" id="tab3_t">03 · Debrief — Post-deal</span>
                <span class="phase-tab-desc" id="tab3_d">60s Voice Audit vs. Bottom Lines & Follow-Up Email</span>
            </button>
        </div>

        <div class="session-bar">
            <div class="session-status">
                <span id="session_label">🔗 Session Chain:</span>
                <span id="dot_p1" class="session-dot" style="color:#059669;">⚪ T-15m Wargame</span>
                <span id="dot_p2" class="session-dot" style="color:#059669;">⚪ Live In-Deal</span>
                <span id="dot_p3" class="session-dot" style="color:#059669;">⚪ Post-Debrief</span>
            </div>
            <button type="button" class="btn-reset" onclick="resetSessionChain()" id="btn_reset_session">🔄 Reset Session Memory</button>
        </div>


    </nav>

    <!-- 01 PREPARE: goals, preferences and machine-enforced constraints together -->
    <section id="stage_prepare" class="stage-pane" aria-label="Prepare goals and guardrails">
        <div class="card">
            <h2 class="card-title" id="sec1_title">Commercial goals and decision preferences</h2>
        <div class="grid-2">
            <div>
                <label id="lbl_goal">🎯 Core Goal, Budget & Timeline:</label>
                <input id="user_goal" value="Close annual compute supply agreement under $1.2M total budget; legal sign-off by Friday." />
            </div>
            <div>
                <label id="lbl_bottom_line">📝 Other deal notes (not machine-enforced):</label>
                <input id="hard_bottom_line" value="Seller: payment within 45 days; max discount 10%; no exclusivity." />
            </div>
        </div>
        <label id="lbl_risk">📝 User-entered decision preferences & reminders:</label>
        <input id="risk_preference" value="Require written confirmation, time to review, and no unapproved concessions." />
        </div>

        <div class="dg-panel" id="dealguard_panel">
            <div class="dg-panel-head">
                <h2 id="dg_panel_title">Your deal guardrails</h2>
                <span class="dg-label" id="dg_no_llm">SHARED ACROSS ALL THREE STAGES</span>
            </div>
            <p id="dg_panel_desc">These rules carry into Protect and Debrief. Free-text preferences are advisory context only.</p>
        <div class="dg-config">
            <div><label for="dg_role" id="dg_role_label">Deal perspective</label><select id="dg_role"><option value="seller">Seller · getting paid</option><option value="buyer">Buyer · paying</option><option value="unspecified">Unspecified</option></select></div>
            <div><label for="dg_discount" id="dg_discount_label">Maximum discount (%)</label><input type="number" id="dg_discount" min="0" max="100" value="10"></div>
            <div><label for="dg_pay_dir" id="dg_pay_label">Payment term rule</label><select id="dg_pay_dir"><option value="maximum">At most (days)</option><option value="minimum">At least (days)</option><option value="none">No payment rule</option></select></div>
            <div><label for="dg_pay_days" id="dg_days_label">Payment days threshold</label><input type="number" id="dg_pay_days" min="0" max="3650" value="45"></div>
            <div><label for="dg_no_exclusive" id="dg_exclusive_label">Prohibit exclusivity</label><input type="checkbox" id="dg_no_exclusive" checked></div>
        </div>
            <p class="dg-notice" id="dg_config_note">Only structured thresholds are programmatically enforced.</p>
        </div>
    </section>

    <!-- One input, shared across the 3 stages; each stage keeps its draft in memory. -->
    <section class="card stage-workspace" id="stage_input_workspace" aria-label="Current stage input and controls">
        <div class="dg-panel-head">
            <h2 id="dg_proposal_label" class="card-title">Meeting background</h2>
            <span class="dg-label" id="stage_mode_badge">PREPARE</span>
        </div>
        <p class="stage-intro" id="stage_hint">Add fictional meeting context or load an example before requesting a strategy.</p>
        <label id="lbl_input_text" for="input_text">Your current stage notes</label>
        <textarea id="input_text" rows="5" maxlength="3500" spellcheck="true"
            placeholder="Add fictional meeting context…"></textarea>
        <div class="dg-meta-line">
            <span id="dg_source_note">Use fictional examples only. Automated redaction cannot guarantee confidentiality.</span>
            <span id="dg_chars">0 / 3500</span>
        </div>
        <div class="preset-row" id="preset_container"></div>
        <div class="voice-panel">
            <div class="voice-header">
                <label id="lbl_mode" for="voice_lang">Optional speech-to-text (browser-dependent)</label>
                <select id="voice_lang">
                    <option value="en-US" id="opt_lang_en">English speech transcription</option>
                    <option value="zh-CN" id="opt_lang_zh">中文语音转文字</option>
                </select>
            </div>
            <label class="voice-consent" for="mic_consent">
                <input id="mic_consent" type="checkbox">
                <span id="mic_consent_text">I have permission to transcribe this conversation. Speech recognition may use a third-party service.</span>
            </label>
            <div class="voice-actions">
                <button type="button" id="mic_btn" class="mic-btn" onclick="toggleMic()">🎙️ Start transcription</button>
                <span class="voice-status" id="mic_status" role="status" aria-live="polite">Microphone off · transcription only</span>
            </div>
            <p class="stage-intro" id="mic_hint">Transcription is voluntary. Pause or stop at any time; it never automatically starts AI analysis.</p>
        </div>
        <label class="agent-consent" for="agent_consent">
            <input id="agent_consent" type="checkbox">
            <span id="agent_consent_text">I consent to sending sanitized fictional stage notes and decision context to the AI strategy provider.</span>
        </label>
        <div class="btn-row">
            <button type="button" id="run_btn" class="primary" onclick="runAgent()">Generate pre-meeting strategy</button>
        </div>
        <p class="dg-action-hint" id="agent_mode_note">The strategy assistant uses a separate AI call, only after you press the button.</p>
    </section>

    <!-- 02 PROTECT: the same input powers rule-only or source-grounded AI audit. -->
    <section id="stage_live_audit" class="dg-panel stage-pane" style="display:none" aria-label="In-deal evidence and rules">
        <div class="dg-panel-head">
            <h2 id="dg_audit_label">Check the current proposal</h2>
            <span class="dg-label" id="dg_live_label">EVIDENCE → RULES → ACTION</span>
        </div>
        <p class="stage-intro" id="dg_audit_intro">Audit the text above. Your Stage 1 guardrails are reused automatically.</p>
        <div class="dg-actions">
            <button type="button" class="dg-secondary" onclick="loadDealGuardDemo('violation')" id="dg_demo_btn">Load 3-conflict example</button>
            <button type="button" class="dg-secondary" onclick="loadDealGuardDemo('rejected')" id="dg_reject_btn">Load rejected-offer example</button>
        </div>
        <label class="dg-consent" for="dg_consent">
            <input id="dg_consent" type="checkbox"/>
            <span id="dg_consent_text">I consent to the opt-in Gemini extraction. Redaction is incomplete and this is fictional data.</span>
        </label>
        <div class="dg-actions">
            <button type="button" class="dg-primary" onclick="runHybridAudit()" id="dg_hybrid_btn">✦ AI evidence + rule check</button>
            <button type="button" class="dg-secondary" onclick="runDealGuardAudit()" id="dg_check_btn">Rules only · no Gemini</button>
        </div>
        <p class="dg-action-hint" id="dg_mode_hint">Transcription and AI auditing are separate actions; no automatic requests.</p>
        <div id="dg_output" class="dg-output" role="status" aria-live="polite">
            <div class="dg-result-mode" id="dg_mode_used"></div>
            <div class="dg-summary">
                <strong class="dg-status unknown" id="dg_status">NOT YET CHECKED</strong>
                <span class="dg-count" id="dg_counter"></span>
            </div>
            <div class="dg-evidence" id="dg_evidence" style="display:none">
                <h3 id="dg_evidence_title">What the AI extracted</h3>
                <p id="dg_evidence_note">A quote match verifies literal text, not its commercial meaning. Review each term before acting.</p>
                <div class="dg-term-grid" id="dg_extracted_terms"></div>
            </div>
            <div class="dg-findings" id="dg_findings"></div>
            <div class="dg-risk" id="dg_risk" style="display:none"><strong id="dg_risk_title">Commercial risk review — separate from rules</strong><div id="dg_risk_findings"></div></div>
            <div id="dg_rule_warnings" class="dg-footnote"></div>
            <div class="dg-footnote" id="dg_footnote">This is decision support, not a contract certification. Always verify ambiguous terms.</div>
            <button type="button" class="action-btn dg-copilot-link" id="dg_copilot_btn" onclick="sendProposalToCopilot()">Use in 3-stage strategy assistant ↓</button>
        </div>
    </section>

    <!-- Existing tactical response output is reused, never duplicated. -->
    <div id="error_box" class="card" style="display:none; border-color:#f87171; background:#fef2f2; color:#b91c1c;"></div>
    <div id="result" class="card" style="display:none;">
        <div class="meta" id="audit_view"></div>
        <div class="trap-header" id="trap_title"></div>
        <div id="rule_cited" style="font-size:14px; color:#0284c7; font-weight:700; margin-bottom:10px;"></div>

        <div class="tri-grid">
            <div class="tri-box">
                <div class="tri-title" id="t_box1">📌 Pillar 1</div>
                <div id="facts_box"></div>
            </div>
            <div class="tri-box">
                <div class="tri-title" id="t_box2">♟️ Pillar 2</div>
                <div id="inference_box"></div>
            </div>
            <div class="tri-box">
                <div class="tri-title" id="t_box3">❓ Pillar 3</div>
                <div id="unknowns_box"></div>
            </div>
        </div>

        <div class="counter-banner">
            <div class="counter-text" id="counter_q"></div>
            <button type="button" class="action-btn" onclick="copyCounterQuestion()" id="btn_copy_q">📋 Copy Alert</button>
        </div>

        <div class="draft-container" id="draft_box"></div>

        <div class="action-btns">
            <button type="button" class="action-btn primary-action" onclick="copyDraftReply()" id="btn_copy_draft">📋 Copy Full Draft / Email</button>
            <button type="button" class="action-btn" onclick="openMailClient()" id="btn_mail_client">✉️ Open in Mail Client</button>
            <span id="copy_toast" style="color:#059669; font-weight:600; font-size:13px; align-self:center; display:none;">✅ Copied to clipboard!</span>
        </div>
    </div>


    <!-- Technical transparency belongs below the product workflow, not a 'third step'. -->
    <div class="card">
        <strong class="card-title" id="sec3_title">🔍 How it works · privacy · tests</strong>
        <p style="font-size:13.5px; color:#64748b; margin:8px 0 14px 0;" id="privacy_desc"></p>
        <p class="dg-footnote" id="research_note">The deterministic audit and regression tests are in the public repository. Accuracy, latency and retention claims require independent verification.</p><a href="https://github.com/Serein131/Consigliere-ai" target="_blank" rel="noopener noreferrer">Read tests & source</a>
    </div>



    <script>
        let currentLang = 'en';
        let currentPhase = 'pre_deal';
        let latestTacticalOutput = null;
        let isAgentRunning = false;
        let lastExecutionTimestamp = 0;
        let dgRequestInFlight = false;
        let latestDealAuditMode = null;
        let stageDrafts = {pre_deal:'', in_deal:'', post_deal:''};
        let languageInitialized = false;
        let auditInputRevision = 0;
        let activeAgentRequestPhase = null;
        let audioStream = null;
        let silenceTimer = null;

        let sessionMemory = {
            pre_deal: null,
            in_deal: null,
            post_deal: null
        };

        const PROFILES = {
            en: {
                goal: "Close annual compute supply agreement under $1.2M total budget; legal sign-off by Friday.",
                bottom: "Seller: payment within 45 days; max discount 10%; no exclusivity.",
                risk: "Require written confirmation, time to review, and no unapproved concessions."
            },
            zh: {
                goal: "拿下年度算力供应合同，目标总价控制在 120 万以内，本周五前完成法务初审。",
                bottom: "卖方：期望45天内收款；折扣不超过10%；禁止独家合作。",
                risk: "优先书面确认，预留审阅时间；未经同意不作承诺。"
            }
        };

        const STAGE_PRESETS = {
            en: {
                pre_deal: {
                    p1: "Calendar Alert [T-15m]: Meeting with John (john@apexvc.com, +1-415-555-0199) at Apex Ventures regarding $1.2M Contract #AX-901. John is known for last-minute exclusivity traps and dangling $5M Q4 expansion bait.",
                    p2: "Calendar Alert [T-15m]: Renewal call with CloudCorp Procurement VP (dave@cloudcorp.com). Last year we gave a 15% discount under quarter-end pressure; today they want Net-15 payment terms."
                },
                in_deal: {
                    trap: "Apex Ventures partner John (john@apexvc.com, +1-415-555-0199) demands 45-day exclusivity on Term Sheet #TS-8841 with a 25% price cut by 5 PM today, or they cancel next year's $5M order.",
                    safe: "Partner Sarah confirmed: 'We reviewed agreement #AG-2026-9 and fully accept your net-45 payment terms and standard pricing without exclusivity. Legal will send the signed copy at 3 PM.'"
                },
                post_deal: {
                    slippage: "60s Voice Debrief: Just walked out of the room with Apex Ventures (#TS-8841). I successfully rejected exclusivity, but under pressure I verbally hinted we might accept a 15% discount and 30-day payment terms if they sign by tomorrow—which breaches my 10% / 45-day bottom line. Help me fence this in via follow-up email.",
                    clean: "60s Voice Debrief: Meeting with CloudCorp finished. Held firm on 45-day payment terms and 8% volume discount on the $1.15M package. They verbally agreed to introduce us to their APAC division, need to lock that into written milestones."
                }
            },
            zh: {
                pre_deal: {
                    p1: "【日程预警 T-15分钟】：即将与华星科技王总（wang@huaxing.com, 13800138000）洽谈 120 万算力合同 #HX-9921。王总习惯在散会前最后5分钟用“明年500万大单”画饼，逼迫当场答应排他条款与超额降价。",
                    p2: "【日程预警 T-15分钟】：即将与宏达集团采购总监李总会议。对方上季度曾以“内部审批慢”为由压缩账期，本次核心任务是守住 45 天账期底线。"
                },
                in_deal: {
                    trap: "华星科技王总（wang@huaxing.com, 13800138000）要求今天下午5点前签合同 #HX-9921，必须降价 25% 且签独家排他，否则取消明年 500 万美金订单。",
                    safe: "张总确认：我们已经审核完合同 #HX-8802，完全同意贵方 60 天账期和标准报价（无排他条款），法务今天下午会把盖章件发到您的邮箱。"
                },
                post_deal: {
                    slippage: "【战后60秒语音口述】：刚走出华星科技会议室（合同 #HX-9921）。现场我守住了不签排他条款，但被王总逼急了，口头松口说“如果明天打款可以考虑降价15%、账期缩到30天”，这突破了我10%降价和45天账期的底线！急需起草跟进邮件把口头让步附加上严苛对等条件收回来。",
                    clean: "【战后60秒语音口述】：刚结束与宏达集团的谈判，成功守住了 45 天账期和 8% 折扣底线（总价 115 万）。对方口头承诺下季度开放华南区业务，需要发跟进邮件把对方的口头画饼转化为书面里程碑条款。"
                }
            }
        };

        const PILLAR_TITLES = {
            en: {
                pre_deal: ["🎯 Opening Anchor & Frame", "🛡️ Predicted Traps & Cheap Talk", "🚨 Decision reminder"],
                in_deal: ["📌 Verified Facts", "♟️ Strategic Inferences (Game Theory)", "❓ Unknowns to Probe"],
                post_deal: ["✅ Defended Ground", "⚠️ Verbal Slippage & Exposure", "🔒 Quid Pro Quo Conditioning"]
            },
            zh: {
                pre_deal: ["🎯 先发制人开场锚点", "🛡️ 预判陷阱与廉价信号识别", "🚨 决策提醒与待核查事项"],
                in_deal: ["📌 客观事实 (Verified Facts)", "♟️ 博弈推断 (Strategic Inferences)", "❓ 未知盲区 (Unknowns to Probe)"],
                post_deal: ["✅ 成功守住的筹码阵地", "⚠️ 口头妥协漏洞与风险敞口", "🔒 对等交换条件锁定 (Quid Pro Quo)"]
            }
        };


        // DealGuard v5: direct, model-independent rule audit; all displayed results use textContent.
        const DG_LABELS = {
            en: {
                kicker: 'FOUNDER DEALGUARD · DECISION INTELLIGENCE',
                headline: 'Know your red lines before you make a deal.',
                hero: 'A verifiable commitment firewall for founders. Check proposed terms against your own commercial rules — then use Consigliere AI to explore negotiation options.',
                chip1:'✓ Explicit rule checks', chip2:'✓ Evidence, not guesswork', chip3:'✓ Unknown ≠ Safe',
                panel:'Your deal guardrails', label:'SHARED ACROSS ALL STAGES',
                desc:'Set commercial thresholds once. They carry into Protect and Debrief. Notes are context, not enforced rules.',
                check:'Rules only · no Gemini', demo:'Load 3-conflict example', pending:'Checking…',
                notyet:'NOT YET CHECKED', violation:'RULE VIOLATION', unknown:'NEEDS VERIFICATION',
                pass:'NO DETECTED VIOLATION', checks:'checks', failures:'violations',
                foot:'Checks only supported, explicitly stated rules. No detected violation does not mean the deal is commercially or legally safe.',
                error:'Audit failed: ', missing:'Enter a proposal to audit.',
                rules:{maximum_discount_pct:'Maximum discount',payment_days:'Payment days',no_exclusivity:'Exclusivity prohibited'},
                states:{VIOLATION:'VIOLATION',PASS:'PASS',UNKNOWN:'UNKNOWN'},
                observed:'Observed', limit:'Threshold', min:'Minimum', max:'Maximum',
                roleLabel:'Deal perspective',discountLabel:'Maximum discount (%)',payLabel:'Payment rule',
                daysLabel:'Payment threshold (days)',exclusiveLabel:'Prohibit exclusivity',
                configNote:'Only these structured settings determine the audited rules. Free-text notes are context for the AI, not additional checks.',
                riskTitle:'Commercial risk review · separate from rule compliance',
                seller:'Seller · receiving payment',buyer:'Buyer · making payment',unspecified:'Unspecified',
                maximum:'At most (days)',minimum:'At least (days)',noRule:'No payment rule',
                riskTitle:'Commercial risk review · separate from rule compliance',
                reviewText:'Review independently',warningPrefix:'Rules needing clarification: ',
                risks:{long_receivables:'Long receivables / cashflow',short_payables:'Short payables / cashflow',
                    unlimited_liability:'Unlimited liability',auto_renewal:'Auto-renewal',termination_penalty:'Termination penalty'},
                proposalLabel:'02 / Enter the counterparty proposal',proposalPlaceholder:'Use fictional terms: the buyer asks for 15% discount, payment in 90 days and exclusivity.',
                sourceNote:'Use fictional examples only. Regex redaction is incomplete.',
                rejectDemo:'Load rejected-offer example',
                consent:'I understand that AI mode sends masked text to a Gemini provider and redaction is incomplete; I will use fictional data.',
                auditStep:'Review evidence and rule conflicts',hybridButton:'✦ AI evidence + rule audit',
                modeHint:'AI mode extracts cited clauses. Rules-only does not call Gemini.',
                evidenceTitle:'What the AI extracted',
                evidenceNote:'A quote match proves that literal text appears in your input, not that its interpretation is correct.',
                quoteVerified:'Source excerpt found',quoteUnverified:'No verifiable excerpt · review manually',
                sourceStatuses:{proposed:'Proposed',agreed:'Agreed',rejected:'Rejected',historical:'Historical',ambiguous:'Ambiguous',absent:'Not stated',required:'Exclusivity requested',not_required:'Not required',unresolved:'Unresolved'},
                termFields:{discount:'Discount',payment:'Payment days',exclusivity:'Exclusivity'},
                modeHybrid:'Hybrid check · Gemini extraction + rule audit',modeRules:'Rules-only check · no model',
                processing:'Extracting deal terms and checking evidence…',
                giveConsent:'Please confirm the AI-processing notice before sending text to Gemini.',
                invalidSettings:'Configure at least one valid constraint; check payment direction and thresholds.',
                tooLong:'Please shorten the proposal to 3,500 characters.',
                failedInput:'This check could not complete. You can still use Rules-only.',
                errorCodes:{MODEL_QUOTA_OR_RATE_LIMIT:'Gemini rate limit or quota reached. Use Rules-only.',MODEL_TEMPORARILY_UNAVAILABLE:'Gemini temporarily unavailable. Use Rules-only.',MODEL_NOT_CONFIGURED:'Gemini not configured on this deployment. Rules-only works.',MODEL_FORMAT_ERROR:'Gemini returned unreadable terms. Use Rules-only.',MODEL_CONFIGURATION_ERROR:'Gemini model configuration needs checking. Rules-only works.',HYBRID_DISABLED:'AI audit is disabled on this deployment. Rules-only still works.',MODEL_CONSENT_REQUIRED:'Confirm AI-processing notice first.',PROPOSAL_TOO_LONG:'Proposal too long.',NO_CHECKS_CONFIGURED:'Configure at least one constraint.',INVALID_RULES:'Review the rule thresholds.',REQUEST_TOO_LARGE:'Request too large.'},
                copilot:'Continue with an optional tactical response ↑'
            },
            zh: {
                kicker:'FOUNDER DEALGUARD · 创始人交易决策系统',
                headline:'签约之前，先守住你的交易底线。',
                hero:'先设定交易底线，再核对 Gemini 提取的原文与程序审计结果；无法确认的条款需要人工复核。',
                chip1:'✓ 明确规则校验',chip2:'✓ 可核查证据',chip3:'✓ 未知不等于安全',
                panel:'本次交易底线',label:'三阶段共同使用',
                desc:'只需设置一次明确底线，谈判中与谈判后沿用；备注只作背景，不是机器强制规则。',
                check:'仅规则检测 · 无需 Gemini',demo:'加载三项违规示例',pending:'审计中…',
                notyet:'尚未检查',violation:'发现底线违规',unknown:'需要进一步核实',
                pass:'未发现规则冲突',checks:'项检查',failures:'项违规',
                foot:'只检查已支持且能够识别的明确规则。未发现违规不代表交易在法律或商业上安全。',
                error:'审计失败：',missing:'请先填写对方提出的交易条件。',
                rules:{maximum_discount_pct:'最大折扣',payment_days:'付款期限',no_exclusivity:'禁止独家'},
                states:{VIOLATION:'违规',PASS:'符合',UNKNOWN:'未知'},
                observed:'观察值',limit:'阈值',min:'下限',max:'上限',
                roleLabel:'交易视角',discountLabel:'最大允许折扣 (%)',payLabel:'付款期限规则',
                daysLabel:'付款期限阈值（天）',exclusiveLabel:'禁止独家合作',
                configNote:'独立规则审计仅使用上方结构化设置。下方自由文本仅作 AI 分析背景，不会作为额外硬规则。',
                riskTitle:'商业风险审查 · 与规则合规分开',
                seller:'卖方 · 等待收款',buyer:'买方 · 对外付款',unspecified:'不指定',
                maximum:'最多（天）',minimum:'至少（天）',noRule:'不检查付款期限',
                reviewText:'需要单独评估',warningPrefix:'待澄清的规则：',
                risks:{long_receivables:'回款周期长 / 现金流',short_payables:'付款周期短 / 现金流',
                    unlimited_liability:'无限责任',auto_renewal:'自动续约',termination_penalty:'提前解约罚金'},
                proposalLabel:'02 / 输入对方提出的条件',proposalPlaceholder:'请使用虚构交易：客户要求15%折扣、90天付款，并希望签订独家合作协议。',
                sourceNote:'仅输入虚构案例。正则脱敏不能确保所有敏感信息已删除。',
                rejectDemo:'加载已拒绝报价示例',
                consent:'我理解 AI 模式会把脱敏后的文本发送至 Gemini，脱敏仍可能遗漏信息；我仅使用虚构案例。',
                auditStep:'核查证据与底线冲突',hybridButton:'✦ AI 提取证据＋规则核验',
                modeHint:'混合模式会调用 Gemini；仅规则模式不调用大模型。',
                evidenceTitle:'AI 提取的条款和原文',
                evidenceNote:'原文匹配仅证明文本存在，不能证明语义、双方角色或条件状态一定正确。',
                quoteVerified:'原文引用已找到',quoteUnverified:'未找到可验证引用 · 请人工复核',
                sourceStatuses:{proposed:'已提出',agreed:'已同意',rejected:'已拒绝',historical:'历史条件',ambiguous:'仍有歧义',absent:'未提及',required:'要求独家',not_required:'不要求独家',unresolved:'尚未确定'},
                termFields:{discount:'折扣',payment:'付款期限',exclusivity:'独家合作'},
                modeHybrid:'混合核验 · Gemini 提取＋程序审计',modeRules:'仅规则核验 · 不调用模型',
                processing:'正在提取条款并核实原文…',
                giveConsent:'请先勾选同意 AI 文本处理说明。',
                invalidSettings:'请设置至少一条有效底线，并检查付款期限规则。',
                tooLong:'交易文本不得超过3500字。',
                failedInput:'本次核验未完成，可改用仅规则检测。',
                errorCodes:{MODEL_QUOTA_OR_RATE_LIMIT:'Gemini 额度或频率受限，可使用仅规则模式。',MODEL_TEMPORARILY_UNAVAILABLE:'Gemini 暂时不可用，可使用仅规则模式。',MODEL_NOT_CONFIGURED:'当前部署尚未配置 Gemini，仍可使用仅规则模式。',MODEL_FORMAT_ERROR:'Gemini 未返回有效的条款，可使用仅规则模式。',MODEL_CONFIGURATION_ERROR:'Gemini 配置需要检查，仍可使用仅规则模式。',HYBRID_DISABLED:'当前部署已关闭 AI 审计，仍可使用仅规则模式。',MODEL_CONSENT_REQUIRED:'请先同意 AI 文本处理说明。',PROPOSAL_TOO_LONG:'交易文本过长。',NO_CHECKS_CONFIGURED:'请先设定底线。',INVALID_RULES:'请检查底线输入。',REQUEST_TOO_LARGE:'请求内容过长。'},
                copilot:'继续生成当场应对策略 ↑'
            }
        };
        function getStructuredRules() {
            const discount=document.getElementById('dg_discount').value;
            const payDir=document.getElementById('dg_pay_dir').value;
            const payDays=document.getElementById('dg_pay_days').value;
            return {
                role: document.getElementById('dg_role').value,
                discount_max_pct: discount===''?null:Number(discount),
                payment_direction:payDir==='none'?null:payDir,
                payment_days:payDir==='none'||payDays===''?null:Number(payDays),
                prohibit_exclusivity:document.getElementById('dg_no_exclusive').checked
            };
        }
        function updateDealGuardLabels() {
            const l = DG_LABELS[currentLang];
            const ids = {
                dg_kicker:l.kicker,dg_headline:l.headline,dg_hero_desc:l.hero,
                dg_chip1:l.chip1,dg_chip2:l.chip2,dg_chip3:l.chip3,
                dg_panel_title:l.panel,dg_no_llm:l.label,dg_panel_desc:l.desc,
                dg_check_btn:l.check,dg_demo_btn:l.demo,dg_footnote:l.foot,
                dg_role_label:l.roleLabel,dg_discount_label:l.discountLabel,
                dg_pay_label:l.payLabel,dg_days_label:l.daysLabel,
                dg_exclusive_label:l.exclusiveLabel,dg_config_note:l.configNote,
                dg_risk_title:l.riskTitle,dg_proposal_label:l.proposalLabel,
                dg_source_note:l.sourceNote,dg_reject_btn:l.rejectDemo,dg_consent_text:l.consent,
                dg_audit_label:l.auditStep,dg_hybrid_btn:l.hybridButton,dg_mode_hint:l.modeHint,
                dg_evidence_title:l.evidenceTitle,dg_evidence_note:l.evidenceNote,
                dg_copilot_btn:l.copilot
            };
            Object.keys(ids).forEach(id => { document.getElementById(id).textContent = ids[id]; });
            const perspective=document.getElementById('dg_role');
            perspective.options[0].text=l.seller;
            perspective.options[1].text=l.buyer;
            perspective.options[2].text=l.unspecified;
            const direction=document.getElementById('dg_pay_dir');
            direction.options[0].text=l.maximum;
            direction.options[1].text=l.minimum;
            direction.options[2].text=l.noRule;
            document.getElementById('input_text').placeholder=l.proposalPlaceholder;
            document.getElementById('dg_output').style.display='none';
        }
        // Every displayed quote and status is constructed as text, never injected HTML.
        function updateDealCharCount() {
            const el=document.getElementById('input_text');
            document.getElementById('dg_chars').textContent=el.value.length+' / 3500';
        }
        function invalidateDealAudit() {
            auditInputRevision += 1;
            document.getElementById('dg_output').style.display='none';
            document.getElementById('dg_copilot_btn').style.display='none';
            latestDealAuditMode=null;
        }
        function loadDealGuardDemo(kind='violation') {
            // Explicit user action only: load fictional text, do NOT call either model.
            setPhase('in_deal');
            document.getElementById('dg_role').value='seller';
            document.getElementById('dg_discount').value='10';
            document.getElementById('dg_pay_dir').value='maximum';
            document.getElementById('dg_pay_days').value='45';
            document.getElementById('dg_no_exclusive').checked=true;
            const zh=currentLang==='zh';
            const proposal=kind==='rejected'
                ?(zh?'买方先前要求15%折扣，但我们明确拒绝了该条件。双方目前已约定30天付款且无独家条款。'
                    :'The buyer previously requested a 15% discount, which we explicitly rejected. We now agreed net 30 payment and no exclusivity.')
                :(zh?'买方要求15%折扣、90天付款期限，并要求签订12个月独家合作协议。'
                    :'The buyer requests a 15% discount, payment terms of 90 days, and a 12-month exclusivity agreement.');
            document.getElementById('input_text').value=proposal;
            stageDrafts.in_deal=proposal;
            updateDealCharCount();
            invalidateDealAudit();
        }
        function addAuditFinding(parent, finding, l) {
            const card=document.createElement('div');card.className='dg-finding';
            const title=document.createElement('div');title.className='dg-finding-title';
            title.textContent=l.rules[finding.rule] || finding.rule;
            const state=document.createElement('div');
            state.className='dg-finding-state '+(finding.status==='VIOLATION'?'violation':finding.status==='PASS'?'pass':'unknown');
            state.textContent=l.states[finding.status] || l.states.UNKNOWN;
            const evidence=document.createElement('div');evidence.className='dg-finding-evidence';
            const parts=[];
            if(finding.observed!==undefined && finding.observed!==null)parts.push(l.observed+': '+finding.observed);
            if(finding.limit!==undefined && finding.limit!==null)parts.push(l.limit+': '+finding.limit);
            if(finding.minimum!==undefined && finding.minimum!==null)parts.push(l.min+': '+finding.minimum);
            if(finding.maximum!==undefined && finding.maximum!==null)parts.push(l.max+': '+finding.maximum);
            if(finding.evidence && finding.evidence!=='Explicit exclusivity language detected.')parts.push(finding.evidence);
            if(finding.reason)parts.push(finding.reason);
            evidence.textContent=parts.join(' · ');
            card.append(title,state,evidence);parent.appendChild(card);
        }
        function renderExtractedTerms(payload, l) {
            const box=document.getElementById('dg_evidence');
            const parent=document.getElementById('dg_extracted_terms');
            parent.replaceChildren();
            const terms=payload.extraction && Array.isArray(payload.extraction.terms)
                ?payload.extraction.terms:[];
            box.style.display=terms.length?'block':'none';
            terms.forEach(term=>{
                const item=document.createElement('div');item.className='dg-term';
                const heading=document.createElement('strong');
                heading.textContent=l.termFields[term.field]||term.field;
                const subtitle=document.createElement('em');
                subtitle.textContent=(l.sourceStatuses[term.source_status]||term.source_status||l.unknown)
                    +(term.value!==null && term.value!==undefined?' · '+term.value+
                     (term.field==='discount'?'%':term.field==='payment'?(currentLang==='zh'?' 天':' days'):''):'');
                const evidence=document.createElement(term.quote_verified?'q':'div');
                if(!term.quote_verified)evidence.className='dg-unverified';
                evidence.textContent=term.quote_verified?term.evidence:l.quoteUnverified;
                item.append(heading,subtitle,evidence);parent.appendChild(item);
            });
        }
        function renderDealAudit(payload, mode) {
            const l=DG_LABELS[currentLang];
            const audit=mode==='hybrid'?payload.audit:payload;
            if(!audit || !Array.isArray(audit.findings))throw new Error('Malformed audit result');
            const state=audit.assessment||'UNKNOWN';
            const status=document.getElementById('dg_status');
            status.className='dg-status '+(state==='VIOLATION'?'violation':state==='NO_DETECTED_VIOLATION'?'pass':'unknown');
            status.textContent=state==='VIOLATION'?l.violation:state==='NO_DETECTED_VIOLATION'?l.pass:l.unknown;
            document.getElementById('dg_counter').textContent=(audit.configured_checks||0)+' '+l.checks+' · '+
                (audit.violation_count||0)+' '+l.failures;
            document.getElementById('dg_mode_used').textContent=mode==='hybrid'
                ?l.modeHybrid+' · '+(payload.model_used||'Gemini')+' · '+(payload.elapsed_ms||0)+' ms'
                :l.modeRules;
            const findings=document.getElementById('dg_findings');
            findings.replaceChildren();
            audit.findings.forEach(f=>addAuditFinding(findings,f,l));
            if(mode==='hybrid')renderExtractedTerms(payload,l);
            else{
                document.getElementById('dg_extracted_terms').replaceChildren();
                document.getElementById('dg_evidence').style.display='none';
            }
            const risks=audit.commercial_risks||[];
            const riskBox=document.getElementById('dg_risk');
            const riskContent=document.getElementById('dg_risk_findings');
            riskContent.replaceChildren();
            riskBox.style.display=risks.length?'block':'none';
            risks.forEach(r=>{
                const item=document.createElement('p');
                item.textContent=(l.risks[r.code]||r.code)+(r.evidence?' · '+r.evidence:'')+
                    ' — '+l.reviewText;
                riskContent.appendChild(item);
            });
            const warnings=audit.rule_warnings||[];
            document.getElementById('dg_rule_warnings').textContent=
                warnings.length?l.warningPrefix+warnings.join('; '):'';
            document.getElementById('dg_copilot_btn').style.display='inline-block';
            latestDealAuditMode=mode;
        }
        function validateDealInput(mode) {
            const l=DG_LABELS[currentLang];
            if (currentPhase!=='in_deal')return l.invalidSettings;
            const raw=document.getElementById('input_text').value.trim();
            if(!raw)return l.missing;
            if(raw.length>3500)return l.tooLong;
            const rules=getStructuredRules();
            const discount=document.getElementById('dg_discount').value;
            const days=document.getElementById('dg_pay_days').value;
            if(discount!=='' && (!Number.isFinite(rules.discount_max_pct) || rules.discount_max_pct<0 || rules.discount_max_pct>100))return l.invalidSettings;
            if(rules.payment_direction && (days==='' || rules.payment_days<0 || rules.payment_days>3650 || !Number.isFinite(rules.payment_days)))return l.invalidSettings;
            if(discount==='' && rules.payment_direction===null && !rules.prohibit_exclusivity)return l.invalidSettings;
            if(mode==='hybrid' && !document.getElementById('dg_consent').checked)return l.giveConsent;
            return '';
        }
        async function runDealAudit(mode) {
            if(dgRequestInFlight)return;
            if(isListening)stopMicInternal();
            const l=DG_LABELS[currentLang];
            const output=document.getElementById('dg_output'),status=document.getElementById('dg_status');
            output.style.display='block';
            document.getElementById('dg_findings').replaceChildren();
            document.getElementById('dg_extracted_terms').replaceChildren();
            document.getElementById('dg_evidence').style.display='none';
            document.getElementById('dg_risk').style.display='none';
            document.getElementById('dg_copilot_btn').style.display='none';
            document.getElementById('dg_counter').textContent='';
            document.getElementById('dg_rule_warnings').textContent='';
            document.getElementById('dg_mode_used').textContent='';
            const invalid=validateDealInput(mode);
            if(invalid){
                status.className='dg-status unknown';status.textContent=invalid;return;
            }
            dgRequestInFlight=true;
            const requestRevision=auditInputRevision;
            const hybridBtn=document.getElementById('dg_hybrid_btn');
            const ruleBtn=document.getElementById('dg_check_btn');
            hybridBtn.disabled=true;ruleBtn.disabled=true;
            status.className='dg-status unknown';
            status.textContent=mode==='hybrid'?l.processing:l.pending;
            const controller=new AbortController();
            const clock=setTimeout(()=>controller.abort(),mode==='hybrid'?29000:11000);
            try{
                const payload={
                    text:clientSideRedact(document.getElementById('input_text').value).sanitizedText,
                    structured_rules:getStructuredRules()
                };
                if(mode==='hybrid')payload.consent_to_model_processing=true;
                const response=await fetch(mode==='hybrid'?'/hybrid-audit':'/audit',{
                    method:'POST',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(payload),signal:controller.signal
                });
                let data;
                try{data=await response.json();}catch(e){throw new Error('HTTP '+response.status);}
                if(!response.ok || data.error)throw new Error(l.errorCodes[data.error]||data.error||'HTTP '+response.status);
                if(requestRevision!==auditInputRevision || currentPhase!=='in_deal')return;
                renderDealAudit(data,mode);
            }catch(e){
                if(requestRevision!==auditInputRevision || currentPhase!=='in_deal')return;
                status.className='dg-status unknown';
                status.textContent=e.name==='AbortError'?l.failedInput:l.error+e.message;
                document.getElementById('dg_mode_used').textContent=mode==='hybrid'?l.modeHybrid:l.modeRules;
            }finally{
                clearTimeout(clock);
                dgRequestInFlight=false;
                hybridBtn.disabled=false;ruleBtn.disabled=false;
            }
        }
        function runDealGuardAudit(){return runDealAudit('rules');}
        function runHybridAudit(){return runDealAudit('hybrid');}
        function sendProposalToCopilot(){
            // Same source textbox is used by both audit and strategy; no copying needed.
            const button=document.getElementById('run_btn');
            button.scrollIntoView({behavior:'smooth',block:'center'});
            button.focus({preventScroll:true});
        }

        const STAGE_COPY = {
            en:{
                pre_deal:{
                    badge:'01 · PREPARE',title:'Meeting background',
                    hint:'Write fictional meeting context, identify constraints, then request a preparation strategy.',
                    input:'Meeting notes / counterpart background',
                    placeholder:'Who is involved? What decision or deadline is coming up?',
                    action:'Prepare negotiation strategy',
                    note:'Your goals and guardrails stay available in every stage. Strategy analysis requires an explicit click.'
                },
                in_deal:{
                    badge:'02 · PROTECT',title:'Live deal terms / transcript',
                    hint:'Type, paste, or voluntarily transcribe a short negotiation excerpt into this one input.',
                    input:'Current offer, chat excerpt or live transcript',
                    placeholder:'Buyer requests 15% discount, net 90 days and exclusivity…',
                    action:'Generate tactical counter-question',
                    note:'Audit the same text below, then optionally request a separate AI response. No automatic model calls.'
                },
                post_deal:{
                    badge:'03 · DEBRIEF',title:'Post-meeting notes / voice memo',
                    hint:'Recall what was offered, rejected or verbally promised. Compare with the same guardrails.',
                    input:'Debrief notes or 60-second voice memo transcript',
                    placeholder:'We rejected exclusivity, but may have offered a 15% discount. Draft a clarification email…',
                    action:'Review commitments and draft follow-up',
                    note:'The agent can use prior phase summaries if generated earlier. No email is automatically sent.'
                }
            },
            zh:{
                pre_deal:{
                    badge:'01 · 谈判前',title:'本次会议背景',
                    hint:'填写虚构会议背景，确认目标和底线，再主动生成会前准备策略。',
                    input:'会议背景 / 对方情况',
                    placeholder:'即将和谁谈？对方可能提出什么条件？需要守住什么底线？',
                    action:'生成会前谈判策略',
                    note:'目标与底线在三个阶段共享；点击后才会调用 AI 生成会前策略。'
                },
                in_deal:{
                    badge:'02 · 谈判中',title:'实时交易条款 / 语音转写',
                    hint:'手动输入、粘贴或主动开启语音转写，内容共用同一个文本框。',
                    input:'当前报价、聊天片段或谈判转写',
                    placeholder:'买方要求15%折扣、90天付款，以及12个月独家合作……',
                    action:'生成当场反问和谈判建议',
                    note:'在下方用相同文本核验底线，再自主选择生成策略；不自动调用模型。'
                },
                post_deal:{
                    badge:'03 · 谈判后',title:'谈判复盘 / 60秒口述',
                    hint:'回忆哪些条件被提出、拒绝或口头答应，并和之前设定的底线对照。',
                    input:'复盘笔记 / 语音备忘转写',
                    placeholder:'今天拒绝了独家要求，但我可能口头答应了15%折扣，需要邮件澄清……',
                    action:'复盘承诺并生成跟进邮件',
                    note:'如果之前生成过策略，助手会引用阶段摘要；不会自动发送邮件。'
                }
            }
        };

        function refreshStageView() {
            const phase=currentPhase;
            const l=STAGE_COPY[currentLang][phase];
            for (const p of ['pre_deal','in_deal','post_deal']) {
                const button=document.getElementById('tab_'+p);
                button.classList.toggle('active',p===phase);
                if(p===phase)button.setAttribute('aria-current','step');
                else button.removeAttribute('aria-current');
            }
            document.getElementById('stage_prepare').style.display=phase==='pre_deal'?'block':'none';
            document.getElementById('stage_live_audit').style.display=phase==='in_deal'?'block':'none';
            document.getElementById('stage_mode_badge').textContent=l.badge;
            document.getElementById('dg_proposal_label').textContent=l.title;
            document.getElementById('stage_hint').textContent=l.hint;
            document.getElementById('lbl_input_text').textContent=l.input;
            document.getElementById('input_text').placeholder=l.placeholder;
            document.getElementById('run_btn').textContent=l.action;
            document.getElementById('agent_mode_note').textContent=l.note;
            renderPresets();
            updatePillarHeaders();
            updateSessionUI();
            updateDealCharCount();
            if(typeof updateMicUI==='function')updateMicUI();
        }

        function setPhase(phase) {
            if(!['pre_deal','in_deal','post_deal'].includes(phase))return;
            // Stopping transcription on navigation never invokes model inference.
            if(isListening)stopMicInternal();
            const editor=document.getElementById('input_text');
            stageDrafts[currentPhase]=editor.value;
            currentPhase=phase;
            editor.value=stageDrafts[phase]||'';
            invalidateDealAudit();
            document.getElementById('result').style.display='none';
            document.getElementById('error_box').style.display='none';
            refreshStageView();
        }

        function updatePillarHeaders() {
            const titles = PILLAR_TITLES[currentLang][currentPhase];
            document.getElementById('t_box1').innerText = titles[0];
            document.getElementById('t_box2').innerText = titles[1];
            document.getElementById('t_box3').innerText = titles[2];
        }

        function updateSessionUI() {
            const p1Color = sessionMemory.pre_deal ? '#059669' : '#94a3b8';
            const p2Color = sessionMemory.in_deal ? '#059669' : '#94a3b8';
            const p3Color = sessionMemory.post_deal ? '#059669' : '#94a3b8';

            if (currentLang === 'zh') {
                document.getElementById('session_label').innerText = '🔗 全周期会话链路：';
                document.getElementById('dot_p1').innerHTML = `<span style="color:${p1Color}">${sessionMemory.pre_deal ? '🟢' : '⚪'} 战前沙盘预案${sessionMemory.pre_deal ? '（已建立）' : ''}</span>`;
                document.getElementById('dot_p2').innerHTML = `<span style="color:${p2Color}">${sessionMemory.in_deal ? '🟢' : '⚪'} 战中干预记录${sessionMemory.in_deal ? '（已同步）' : ''}</span>`;
                document.getElementById('dot_p3').innerHTML = `<span style="color:${p3Color}">${sessionMemory.post_deal ? '🟢' : '⚪'} 战后复盘闭环${sessionMemory.post_deal ? '（已对账）' : ''}</span>`;
                document.getElementById('btn_reset_session').innerText = '🔄 重置会话链路';
            } else {
                document.getElementById('session_label').innerText = '🔗 Session Memory Chain:';
                document.getElementById('dot_p1').innerHTML = `<span style="color:${p1Color}">${sessionMemory.pre_deal ? '🟢' : '⚪'} T-15m Wargame${sessionMemory.pre_deal ? ' [Ready]' : ''}</span>`;
                document.getElementById('dot_p2').innerHTML = `<span style="color:${p2Color}">${sessionMemory.in_deal ? '🟢' : '⚪'} Live In-Deal${sessionMemory.in_deal ? ' [Logged]' : ''}</span>`;
                document.getElementById('dot_p3').innerHTML = `<span style="color:${p3Color}">${sessionMemory.post_deal ? '🟢' : '⚪'} Post-Debrief${sessionMemory.post_deal ? ' [Closed]' : ''}</span>`;
                document.getElementById('btn_reset_session').innerText = '🔄 Reset Session Memory';
            }
        }

        function resetSessionChain() {
            sessionMemory = { pre_deal: null, in_deal: null, post_deal: null };
            updateSessionUI();
            alert(currentLang === 'zh' ? '会话链路记忆已清空重置。' : 'Session memory chain has been reset.');
        }

        function setLanguage(lang) {
            currentLang = lang;
            updateDealGuardLabels();
            document.getElementById('btn_en').className = 'lang-btn' + (lang === 'en' ? ' active' : '');
            document.getElementById('btn_zh').className = 'lang-btn' + (lang === 'zh' ? ' active' : '');

            // Initialize example text once; language switching must never erase user edits.
            if(!languageInitialized){
                if(lang==='zh'){
                    document.getElementById('user_goal').value=PROFILES.zh.goal;
                    document.getElementById('hard_bottom_line').value=PROFILES.zh.bottom;
                    document.getElementById('risk_preference').value=PROFILES.zh.risk;
                }
                document.getElementById('voice_lang').value=lang==='en'?'en-US':'zh-CN';
                languageInitialized=true;
            }

            if (lang === 'zh') {
                document.getElementById('subtitle_text').innerText = "谈判前准备 · 谈判中守护 · 谈判后复盘";
                document.getElementById('sec1_title').innerText = "🎯 目标、偏好与风险提醒";
                document.getElementById('lbl_goal').innerText = "🎯 核心目标、预算与时间线：";
                document.getElementById('lbl_bottom_line').innerText = "📝 其他交易备注（不自动作为硬规则）：";
                document.getElementById('lbl_risk').innerText = "🧠 自行填写的决策偏好与提醒：";
                document.getElementById('sec2_title').innerText = "你的三阶段谈判工作台";
                document.getElementById('tab1_t').innerText = "01 · Prepare — 谈判前";
                document.getElementById('tab1_d').innerText = "会议策略准备与提醒文本";
                document.getElementById('tab2_t').innerText = "02 · Protect — 谈判中";
                document.getElementById('tab2_d').innerText = "可选语音转写 / 事实·推断·未知拆解";
                document.getElementById('tab3_t').innerText = "03 · Debrief — 谈判后";
                document.getElementById('tab3_d').innerText = "口述得失审计、口头让步找补与跟进邮件";
                document.getElementById('lbl_mode').innerText = "浏览器语音转写（依赖设备及浏览器）：";
                document.getElementById('opt_lang_en').innerText = "🎙️ 麦克风通道：English (US / Global) + Browser-dependent transcription";
                document.getElementById('opt_lang_zh').innerText = "🎙️ 中文语音转写（依赖浏览器）";
                document.getElementById('lbl_input_text').innerText = "当前阶段输入（战前对手背景 / 战中对手发言转写或纪要 / 战后60秒语音口述）：";
                document.getElementById('mic_btn').innerText = "🎤 启动语音转写（须征得同意）";
                document.getElementById('run_btn').innerText = "⚡ 启动全周期博弈推演";
                document.getElementById('btn_copy_q').innerText = "📋 复制反问/提醒草稿";
                document.getElementById('btn_copy_draft').innerText = "📋 复制全文/跟进邮件";
                document.getElementById('btn_mail_client').innerText = "✉️ 唤起本地邮件客户端";

                document.getElementById('sec3_title').innerText = "🔍 工作原理、隐私与测试";
                document.getElementById('privacy_desc').textContent = '本工具仅辅助决策。语音转文字必须主动开启，不会自动触发 AI 分析。浏览器语音识别可能调用外部服务；正则脱敏不完整。仅使用虚构数据并取得适用的录音许可。';
            } else {
                document.getElementById('subtitle_text').innerText = "Prepare · Protect · Debrief";
                document.getElementById('sec1_title').innerText = "🎯 Goals, preferences and reminders";
                document.getElementById('lbl_goal').innerText = "🎯 Core Goal, Budget & Timeline:";
                document.getElementById('lbl_bottom_line').innerText = "📝 Other deal notes (not machine-enforced):";
                document.getElementById('lbl_risk').innerText = "🧠 User-entered decision preferences and reminders:";
                document.getElementById('sec2_title').innerText = "Your three-stage negotiation workspace";
                document.getElementById('tab1_t').innerText = "01 · Prepare — Pre-deal";
                document.getElementById('tab1_d').innerText = "Strategy preparation and reminder draft";
                document.getElementById('tab2_t').innerText = "02 · Protect — In-deal";
                document.getElementById('tab2_d').innerText = "Optional speech transcript and tactical review";
                document.getElementById('tab3_t').innerText = "03 · Debrief — Post-deal";
                document.getElementById('tab3_d').innerText = "60s Voice Audit vs. Bottom Lines & Follow-Up Email";
                document.getElementById('lbl_mode').innerText = "Optional speech transcription (browser-dependent):";
                document.getElementById('opt_lang_en').innerText = "🎙️ English transcription (browser-dependent)";
                document.getElementById('opt_lang_zh').innerText = "🎙️ 中文语音转写（依赖浏览器）";
                document.getElementById('lbl_input_text').innerText = "Stage Input (Meeting Context / Live Opponent Speech / 60s Post-Deal Voice Memo):";
                document.getElementById('mic_btn').innerText = "🎤 Start speech transcription (consent required)";
                document.getElementById('run_btn').innerText = "⚡ Execute Game-Theoretic Engine";
                document.getElementById('btn_copy_q').innerText = "📋 Copy Alert";
                document.getElementById('btn_copy_draft').innerText = "📋 Copy Full Draft / Email";
                document.getElementById('btn_mail_client').innerText = "✉️ Open in Mail Client";

                document.getElementById('sec3_title').innerText = "🔍 How it works · Privacy · Tests";
                document.getElementById('privacy_desc').textContent = 'Decision support only. Transcript capture is user-initiated and does not auto-start AI inference. Browser speech recognition may rely on third parties. Regex redaction is incomplete; use fictional data and obtain applicable recording consent.';
            }

            document.getElementById('workflow_intro').textContent=lang==='zh'
                ?'一组共享底线 · 一个输入框 · 每次 AI 调用由你决定'
                :'One set of guardrails · One input · Every AI call is your choice.';
            document.getElementById('dg_live_label').textContent=lang==='zh'
                ?'证据 → 底线 → 策略':'EVIDENCE → RULES → ACTION';
            document.getElementById('dg_audit_intro').textContent=lang==='zh'
                ?'使用上方同一份文本核验，自动沿用谈判前设定的底线。'
                :'Audit the same text above, with the Stage 1 thresholds automatically reused.';
            document.getElementById('mic_consent_text').textContent=lang==='zh'
                ?'我已获得适用的语音转写许可，理解浏览器语音识别可能由第三方处理。'
                :'I have permission to transcribe this conversation. Browser speech recognition may use third-party services.';
            document.getElementById('mic_hint').textContent=lang==='zh'
                ?'语音仅转为文字，随时可以停止；停顿或停止不会自动调用 Gemini。'
                :'Speech is converted to text only. Pause or stop anytime; no AI call happens automatically.';
            document.getElementById('agent_consent_text').textContent=lang==='zh'
                ?'我同意将脱敏后的虚构阶段文本及决策背景发送至 AI 策略服务（脱敏不保证完整）。'
                :'I consent to sending masked fictional stage notes and decision context to the AI strategy provider; masking is incomplete.';
            document.getElementById('lbl_mode').textContent=lang==='zh'
                ?'可选语音转文字（依赖浏览器支持）':'Optional speech-to-text (browser dependent)';
            document.getElementById('dg_source_note').textContent=lang==='zh'
                ?'仅使用虚构案例，正则脱敏不能保证隐私安全。':'Fictional examples only; regex redaction cannot guarantee confidentiality.';
            updatePillarHeaders();
            updateSessionUI();
            // New workflow has only one editor; never auto-load an example on language changes.
            refreshStageView();
        }

        function renderPresets() {
            const container = document.getElementById('preset_container');
            container.style.display=currentPhase==='in_deal'?'none':'flex';
            if (currentPhase === 'pre_deal') {
                container.innerHTML = currentLang === 'zh'
                    ? `<button type="button" class="preset-btn" onclick="loadPreset('p1')">📅 战前案例 1：强势投资人/客户排他逼签预警</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('p2')">📅 战前案例 2：采购总监压缩账期历史复盘预警</button>`
                    : `<button type="button" class="preset-btn" onclick="loadPreset('p1')">📅 Pre-Deal 1: Hostile VC Exclusivity & Bait Wargame</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('p2')">📅 Pre-Deal 2: Procurement Net-15 Terms Defense</button>`;
            } else if (currentPhase === 'in_deal') {
                // Stage 2 has exactly two audited fictional examples in the Protect panel.
                container.replaceChildren();
            } else {
                container.innerHTML = currentLang === 'zh'
                    ? `<button type="button" class="preset-btn" onclick="loadPreset('slippage')">🚨 战后案例 1：现场口头松口越界（急需邮件附加条件找补）</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('clean')">🏆 战后案例 2：成功守住底线（锁定对方口头画饼为书面条款）</button>`
                    : `<button type="button" class="preset-btn" onclick="loadPreset('slippage')">🚨 Debrief 1: Verbal Slippage Recovery (Conditioning Concessions)</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('clean')">🏆 Debrief 2: Clean Defense (Locking Cheap Talk into Milestones)</button>`;
            }
        }

        function loadPreset(key) {
            const val=STAGE_PRESETS[currentLang][currentPhase][key];
            if(!val)return;
            const editor=document.getElementById('input_text');
            editor.value=val;
            stageDrafts[currentPhase]=val;
            updateDealCharCount();
            invalidateDealAudit();
            document.getElementById('result').style.display='none';
        }

        function clientSideRedact(rawText) {
            let redacted = rawText;
            redacted = redacted.replace(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/g, '[REDACTED_EMAIL]');
            redacted = redacted.replace(/(\+?\d{1,3}[-\s]?)?\(?\d{3}\)?[-\s]?\d{3,4}[-\s]?\d{4}/g, '[REDACTED_PHONE]');
            redacted = redacted.replace(/\b([A-Z]{2,5}-\d{2,6}|\#[A-Za-z0-9]{4,10})\b/g, '[REDACTED_ID]');
            redacted = redacted.replace(/([\$¥￥€£]\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:万美金|万美元|万港币|万元|万|亿|million|billion|k|m|b))?|\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万美金|万美元|万港币|万元|万|亿|美金|美元|港币|元|块|million|billion|k|m|b))/gi, '[REDACTED_VALUE]');
            redacted = redacted.replace(/([A-Za-z0-9\u4e00-\u9fa5]{2,16}(?:公司|集团|科技|资本|银行|厂|Inc\.?|Corp\.?|LLC|Ltd\.?|Ventures|Capital))/g, '[COMPANY_ENTITY]');
            const matches = redacted.match(/\[(?:REDACTED_\w+|COMPANY_ENTITY)\]/g);
            return {
                sanitizedText: redacted,
                redactedCount: matches ? matches.length : 0
            };
        }

        let recognition=null;
        let isListening=false;
        let speechBaseText='';
        let micStartPhase=null;

        function updateMicUI(message) {
            const btn=document.getElementById('mic_btn');
            const status=document.getElementById('mic_status');
            const zh=currentLang==='zh';
            btn.classList.toggle('active',isListening);
            btn.textContent=isListening?(zh?'■ 停止语音转写':'■ Stop transcription')
                :(zh?'🎙️ 开始语音转写':'🎙️ Start transcription');
            status.textContent=message || (isListening
                ?(zh?'麦克风已开启 · 只转写，不自动分析':'Microphone on · text only, no auto-analysis')
                :(zh?'麦克风已关闭 · 请主动点击分析':'Microphone off · press Analyze when ready'));
        }

        async function toggleMic() {
            if(isListening){
                stopMicInternal();
                return;
            }
            const zh=currentLang==='zh';
            if(!document.getElementById('mic_consent').checked){
                updateMicUI(zh?'请先确认已获得适当的转写许可':'Confirm the applicable recording/transcription permission first');
                return;
            }
            const SpeechRecognition=window.SpeechRecognition || window.webkitSpeechRecognition;
            if(!SpeechRecognition){
                updateMicUI(zh?'此浏览器不支持语音识别，请手动输入':'Speech recognition unavailable; please type instead');
                return;
            }
            // Preserve manually typed text when starting a user-controlled transcript.
            const editor=document.getElementById('input_text');
            const previous=editor.value.trim();
            speechBaseText=previous?(previous+'\n'):'';
            micStartPhase=currentPhase;
            try{
                recognition=new SpeechRecognition();
                recognition.lang=document.getElementById('voice_lang').value;
                recognition.continuous=true;
                recognition.interimResults=true;
                recognition.onresult=(event)=>{
                    if(!isListening || currentPhase!==micStartPhase)return;
                    const parts=[];
                    for(let i=0;i<event.results.length;i++){
                        if(event.results[i] && event.results[i][0])
                            parts.push(event.results[i][0].transcript);
                    }
                    const transcript=parts.join(' ').trim();
                    editor.value=(speechBaseText+transcript).slice(0,3500);
                    stageDrafts[currentPhase]=editor.value;
                    updateDealCharCount();
                    invalidateDealAudit();
                };
                recognition.onerror=(event)=>{
                    const kind=event && event.error;
                    stopMicInternal();
                    updateMicUI(kind==='not-allowed'||kind==='service-not-allowed'
                        ?(zh?'麦克风未获授权，请检查浏览器权限':'Microphone permission denied; check browser settings')
                        :(zh?'语音识别已中断，可手动继续输入':'Transcription interrupted; you can keep typing'));
                };
                recognition.onend=()=>{
                    if(isListening){
                        stopMicInternal();
                        updateMicUI(zh?'转写已停止；文字已保留，不会自动分析':'Transcription stopped; text saved, no automatic analysis');
                    }
                };
                recognition.start();
                isListening=true;
                updateMicUI();
            }catch(e){
                stopMicInternal();
                updateMicUI(zh?'语音识别无法启动，请手动输入':'Speech recognition could not start; type instead');
            }
        }

        function stopMicInternal() {
            // Explicit stop, stage switch or browser error never calls /analyze or /hybrid-audit.
            isListening=false;
            if(recognition){
                const previous=recognition;
                recognition=null;
                previous.onresult=null;
                previous.onend=null;
                previous.onerror=null;
                try{previous.stop();}catch(e){}
            }
            if(audioStream){
                audioStream.getTracks().forEach(track=>track.stop());
                audioStream=null;
            }
            if(silenceTimer){
                clearTimeout(silenceTimer);
                silenceTimer=null;
            }
            micStartPhase=null;
            updateMicUI();
        }

        async function runAgent() {
            if (isAgentRunning) return;
            if(isListening)stopMicInternal();
            const requestPhase=currentPhase;
            const requestSource=document.getElementById('input_text').value;
            const errBox=document.getElementById('error_box');
            if(!requestSource.trim()){
                errBox.style.display='block';
                errBox.textContent=currentLang==='zh'?'请先填写当前阶段的虚构文本。':'Enter fictional stage notes before requesting AI strategy.';
                return;
            }
            if(!document.getElementById('agent_consent').checked){
                errBox.style.display='block';
                errBox.textContent=currentLang==='zh'?'请先确认 AI 策略分析的数据处理说明。':'Confirm the AI strategy processing notice before sending text.';
                return;
            }
            const now = Date.now();
            if (now - lastExecutionTimestamp < 1500) {
                return;
            }
            lastExecutionTimestamp = now;

            const resBox = document.getElementById('result');
            const runBtn = document.getElementById('run_btn');
            errBox.style.display = 'none';
            isAgentRunning = true;
            runBtn.disabled = true;
            runBtn.innerText = currentLang === 'zh' ? '⏳ 正在执行全周期博弈推演...' : '⏳ Running Game-Theoretic Deduction...';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 18000);

            try {
                const rawText = document.getElementById('input_text').value;
                const scrubResult = clientSideRedact(rawText);
                const clientScrubbedText = scrubResult.sanitizedText;
                const localRedactedCount = scrubResult.redactedCount;

                const payload = {
                    structured_rules:getStructuredRules(),
                    phase: currentPhase,
                    lang: currentLang,
                    text: clientScrubbedText,
                    user_goal: clientSideRedact(document.getElementById('user_goal').value).sanitizedText,
                    hard_bottom_line: clientSideRedact(document.getElementById('hard_bottom_line').value).sanitizedText,
                    risk_preference: clientSideRedact(document.getElementById('risk_preference').value).sanitizedText,
                    session_context: Object.fromEntries(['pre_deal', 'in_deal']
                        .filter(k => sessionMemory[k])
                        .map(k => [k, {
                            trap: clientSideRedact(sessionMemory[k].trap || '').sanitizedText,
                            rule: clientSideRedact(sessionMemory[k].rule || '').sanitizedText
                        }]))
                };

                const res = await fetch('/analyze', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                    signal: controller.signal
                });

                const rawResponseText = await res.text();
                let data = {};
                try {
                    data = JSON.parse(rawResponseText);
                } catch (jsonErr) {
                    throw new Error(`Server returned non-JSON (HTTP ${res.status}): ${rawResponseText.slice(0, 160)}`);
                }

                if (!res.ok || data.error) {
                    throw new Error(data.error || `Request failed (HTTP ${res.status})`);
                }
                // Do not attach stale strategy to a new phase or changed input.
                if(currentPhase!==requestPhase || document.getElementById('input_text').value!==requestSource)return;

                const t = data.tactical_advice;
                latestTacticalOutput = t;
                sessionMemory[requestPhase] = {
                    trap: t.trap_or_intent,
                    rule: t.triggered_rule,
                    advice: t.counter_question,
                    draft: t.draft_reply
                };
                updateSessionUI();

                resBox.className = 'card risk-' + (t.risk_level || 'MEDIUM');
                resBox.style.display = 'block';
                updatePillarHeaders();

                const auditMsg = currentLang === 'zh'
                    ? `🛡️ <strong>客户端正则脱敏已运行（不能保证覆盖全部敏感信息）：</strong>已在浏览器内存拦截替换 <b>${localRedactedCount}</b> 处敏感实体（无法确保所有敏感信息已删除） | ⏱️ <strong>实测耗时：</strong><b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>发送到分析接口的谈判文本（不含全部上下文）：</strong><code>${data.sanitized_payload_sent_to_llm}</code>`
                    : `🛡️ <strong>Regex-based redaction applied (not a complete privacy guarantee):</strong> <b>${localRedactedCount}</b> possible identifiers replaced by client regex before network request | ⏱️ <strong>Latency:</strong> <b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>Negotiation text excerpt (not full request):</strong> <code>${data.sanitized_payload_sent_to_llm}</code>`;

                const audit = data.dealguard_audit || {};
                const findings = (audit.findings || []).map(f => f.rule + ': ' + f.status +
                    (f.observed === undefined ? '' : ' (observed: ' + f.observed + ')'));
                const auditElement = document.createElement('pre');
                auditElement.style.cssText = 'white-space:pre-wrap;padding:12px;border:1px solid #64748b;border-radius:8px;margin-top:8px';
                auditElement.textContent = 'DealGuard rule audit: ' + (audit.assessment || 'UNKNOWN') +
                    '\n' + findings.join('\n') +
                    '\nCommercial review: '+(audit.commercial_risk_level || 'NOT_ASSESSED')+
                    (audit.commercial_risks || []).map(r=>'\n• '+r.code+': '+(r.evidence||'')).join('')+
                    (audit.rule_warnings || []).map(w=>'\n⚠ '+w).join('');
                const auditView = document.getElementById('audit_view');
                // Escape interpolated payload in HTML before rendering the status message.
                const safeAuditMsg = auditMsg.replace(/<code>([\s\S]*?)<\/code>/g, (whole, content) =>
                    '<code>' + content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</code>');
                auditView.innerHTML = safeAuditMsg;
                auditView.appendChild(auditElement);

                const badgeColor = t.risk_level === 'SAFE' ? '#059669' : (t.risk_level === 'LOW' ? '#d97706' : '#dc2626');
                const riskMapZh = {
                    'CRITICAL': '【严重预警 · 突破底线】',
                    'MEDIUM': '【中度博弈 · 存在诱导】',
                    'LOW': '【轻微试探 · 局部拉锯】',
                    'SAFE': '【安全对齐 · 推进协议】'
                };
                const riskBadgeText = currentLang === 'zh' ? (riskMapZh[t.risk_level] || t.risk_level) : `[${t.risk_level}]`;

                const trapTitleElem = document.getElementById('trap_title');
                trapTitleElem.style.color = badgeColor;
                trapTitleElem.innerText = `${riskBadgeText} ${t.trap_or_intent}`;
                document.getElementById('rule_cited').innerText = (currentLang === 'zh' ? '⚖️ 关联底线与原则锚定：' : '⚖️ Grounded Rule & BATNA: ') + t.triggered_rule;

                document.getElementById('facts_box').innerText = t.box1_text;
                document.getElementById('inference_box').innerText = t.box2_text;
                document.getElementById('unknowns_box').innerText = t.box3_text;

                let counterPrefix = '';
                let draftPrefix = '';
                if (currentPhase === 'pre_deal') {
                    counterPrefix = currentLang === 'zh' ? '📱 会前提醒草稿：' : '📱 Pre-meeting reminder draft: ';
                    draftPrefix = currentLang === 'zh' ? '📋 会前议程设定与先发锚定话术：\n' : '📋 Pre-Meeting Agenda Framing Opener:\n';
                } else if (currentPhase === 'in_deal') {
                    counterPrefix = currentLang === 'zh' ? '🎯 建议当场反问（破局话术）：' : '🎯 Immediate Live Counter-Question: ';
                    draftPrefix = currentLang === 'zh' ? '💬 战中完整回复 / 现场应对建议：\n' : '💬 Live Tactical Reply / Suggested Response:\n';
                } else {
                    counterPrefix = currentLang === 'zh' ? '🔑 战后复盘核心策略定调：' : '🔑 Core Post-Deal Takeaway: ';
                    draftPrefix = currentLang === 'zh' ? '📧 极具博弈分寸感的战后跟进邮件（可直接复制发送）：\n' : '📧 High-Leverage Post-Deal Follow-Up Email (Ready to Send):\n';
                }

                document.getElementById('counter_q').innerText = counterPrefix + '“' + t.counter_question + '”';
                document.getElementById('draft_box').innerText = draftPrefix + t.draft_reply;
            } catch (err) {
                if(currentPhase===requestPhase && document.getElementById('input_text').value===requestSource){
                    errBox.style.display='block';
                    errBox.textContent='⚠️ '+(err.name==='AbortError'
                        ?(currentLang==='zh'?'分析超时，请稍后重试。':'Analysis timed out; please retry.')
                        :err.message);
                    resBox.style.display='none';
                }
            } finally {
                clearTimeout(timeoutId);
                isAgentRunning = false;
                runBtn.disabled = false;
                runBtn.textContent=STAGE_COPY[currentLang][currentPhase].action;
            }
        }

        function showToast(msg) {
            const toast = document.getElementById('copy_toast');
            toast.innerText = msg;
            toast.style.display = 'inline';
            setTimeout(() => { toast.style.display = 'none'; }, 2500);
        }

        function copyCounterQuestion() {
            if (!latestTacticalOutput || !latestTacticalOutput.counter_question) return;
            navigator.clipboard.writeText(latestTacticalOutput.counter_question).then(() => {
                showToast(currentLang === 'zh' ? '✅ 反问或提醒草稿已复制！' : '✅ Alert copied!');
            });
        }

        function copyDraftReply() {
            if (!latestTacticalOutput || !latestTacticalOutput.draft_reply) return;
            navigator.clipboard.writeText(latestTacticalOutput.draft_reply).then(() => {
                showToast(currentLang === 'zh' ? '✅ 跟进邮件/全文草稿已复制！' : '✅ Draft copied to clipboard!');
            });
        }

        function openMailClient() {
            if (!latestTacticalOutput || !latestTacticalOutput.draft_reply) return;
            const subject = currentLang === 'zh' ? '商务洽谈要点复盘与后续流程确认' : 'Executive Summary & Agreed Next Steps';
            const body = latestTacticalOutput.draft_reply;
            const mailtoUrl = 'mailto:?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
            window.location.href = mailtoUrl;
        }

        window.addEventListener('DOMContentLoaded', () => {
            const sysLang=(navigator.language || navigator.userLanguage || '').toLowerCase();
            setLanguage(sysLang.startsWith('en')?'en':'zh');
            const editor=document.getElementById('input_text');
            editor.addEventListener('input',()=>{updateDealCharCount();invalidateDealAudit();});
            ['dg_role','dg_discount','dg_pay_dir','dg_pay_days','dg_no_exclusive'].forEach(id=>{
                const element=document.getElementById(id);
                element.addEventListener('input',invalidateDealAudit);
                element.addEventListener('change',invalidateDealAudit);
            });
            // A previous result must never look current after the input or rule limits change.
            updateDealCharCount();
        });
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_UI)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
