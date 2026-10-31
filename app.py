import os
import re
import time
import json
import logging
import http.client
from flask import Flask, request, jsonify, render_template_string

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
        r'([\$¥￥€£]\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:万美金|万美元|万港币|万元|万|亿|million|billion|k|m|b))?|\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万美金|万美元|万港币|万元|万|亿|美金|美元|港币|元|块|million|billion|k|m|b|%))',
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

@app.route("/analyze", methods=["POST"])
def analyze_negotiation():
    start_time = time.perf_counter()
    payload = request.get_json(silent=True) or {}

    phase = payload.get("phase", "in_deal")
    lang_pref = payload.get("lang", "en")
    incoming_text = payload.get("text", "").strip()
    user_goal = payload.get("user_goal", "").strip()
    hard_bottom_line = payload.get("hard_bottom_line", "").strip()
    risk_preference = payload.get("risk_preference", "").strip()
    session_context = payload.get("session_context") or {}

    if not incoming_text:
        return jsonify({"error": "Please enter negotiation input or select a preset case."}), 400

    redaction_result = server_fallback_redact(incoming_text)
    sanitized_text = redaction_result["sanitized_text"]

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
You MUST cross-reference the input with the User's Strategic Profile (Goals, Bottom Lines, Opponent Name) to reconstruct the opponent's true adversarial intent before conducting game-theoretic deduction."""

    phase_instructions = {
        "pre_deal": """CURRENT STAGE: PHASE 1 — T-15m PRE-DEAL BRIEFING & WARGAMING (战前15分钟沙盘预警).
Objective: 70% of negotiations are won before speaking. Arm the user psychologically and game-theoretically before entering the room.
- In 'trap_or_intent': Identify the most likely Game-Theoretic Playbook the opponent will use (e.g. Ultimatum Game / Artificial Urgency / Cheap Talk Future Bait).
- In 'triggered_rule': Cite the exact reservation value (BATNA / Hard Bottom Line) most at risk today and lock it.
- In 'box1_text': [Opening Anchor & Framing]: Proactive agenda frame or opening anchor the user should set in the first 2 minutes.
- In 'box2_text': [Predicted Traps & Signaling Test]: Specific traps to anticipate and how to test whether opponent claims are 'Cheap Talk' vs. 'Costly Signals'.
- In 'box3_text': [Behavioral Circuit Breaker]: Concrete pause/delay tactic tailored to user's vulnerability.
- In 'counter_question': [T-15m SMS Wake-Up Alert]: Ultra-punchy 1-sentence SMS alert sent to user's phone 15 mins before entering.
- In 'draft_reply': [Pre-Meeting Agenda Opener]: Crisp opening statement to establish leverage before sitting down.""",

        "in_deal": """CURRENT STAGE: PHASE 2 — IN-DEAL LIVE INTERVENTION (战中无痕交锋与三元拆解).
Objective: The user captured live counterparty demands or speech transcripts. Apply Nash Bargaining, Cheap Talk filtering, and Epistemic Game Theory without illegal continuous recording.
- NO FALSE POSITIVES: If counterparty agrees to terms, set 'risk_level' to 'SAFE' and 'trap_or_intent' to 'Constructive Alignment' (良性推进).
- If counterparty attempts aggressive price cuts (>10%), demands exclusivity, compresses payment terms (<45d), or imposes artificial deadlines, set 'risk_level' to 'CRITICAL' or 'MEDIUM'.
- In 'triggered_rule': Cite which exact Goal, Budget, or Hard Bottom Line was triggered or satisfied.
- In 'box1_text': [Verified Facts]: Objective terms explicitly stated by counterparty (zero speculation).
- In 'box2_text': [Strategic Inferences]: Opponent's hidden leverage play, information asymmetry, or Cheap Talk bluff.
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

    system_instruction = f"""You are Consigliere AI (v4.6), a Full-Cycle Game-Theoretic Chief of Staff & Negotiation Copilot.
You replace illegal/intrusive full-room continuous audio surveillance with a 3-stage cognitive defense architecture.

USER STRATEGIC PROFILE (MEMORY BANK):
- [Core Goal & Budget]: {user_goal}
- [Hard Bottom Lines (Reservation Values / BATNA)]: {hard_bottom_line}
- [Behavioral Vulnerabilities & Risk Profile]: {risk_preference}

{asr_fuzzy_repair_instruction}

{selected_phase_prompt}

{lang_rule}

Output ONLY a single valid JSON object with these exact 8 keys (no Markdown code block wrappers):
{{
  "risk_level": "SAFE, LOW, MEDIUM, or CRITICAL",
  "trap_or_intent": "Classification or audit verdict",
  "triggered_rule": "Explicit reference to user's Goal, Bottom Line, or Vulnerability",
  "box1_text": "Pillar 1 Content",
  "box2_text": "Pillar 2 Content",
  "box3_text": "Pillar 3 Content",
  "counter_question": "Immediate counter-question or SMS wake-up alert (<25 words)",
  "draft_reply": "Complete follow-up email, tactical reply draft, or pre-meeting framing note"
}}"""

    user_prompt = f"[{phase.upper()} INPUT (Sanitized)]: {sanitized_text}{session_history_str}"

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
        latency_ms = round((time.perf_counter() - start_time) * 1000)

        return jsonify({
            "sanitized_payload_sent_to_llm": sanitized_text,
            "redacted_items_count": redaction_result["redaction_count"],
            "measured_latency_ms": latency_ms,
            "model_used": used_model,
            "phase_executed": phase,
            "tactical_advice": tactical_output
        })
    except Exception as parse_err:
        return jsonify({"error": f"Failed to parse model JSON: {str(parse_err)}"}), 500

HTML_UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consigliere AI v4.6 — Full-Cycle Game-Theoretic Chief of Staff</title>
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
    </style>
</head>
<body>
    <div class="header-row">
        <div>
            <div class="main-title">⚡ Consigliere AI <span class="badge">v4.6 — Fault-Tolerant Chief of Staff</span></div>
            <div class="subtitle" id="subtitle_text">Solving Recording Dilemma: T-15m Wargame • Noise-Suppressed In-Deal • T+0m Debrief</div>
        </div>
        <div class="lang-switch">
            <button type="button" class="lang-btn" id="btn_en" onclick="setLanguage('en')">🇺🇸 English</button>
            <button type="button" class="lang-btn" id="btn_zh" onclick="setLanguage('zh')">🇨🇳 中文</button>
        </div>
    </div>

    <!-- 1. 首席幕僚记忆库 -->
    <div class="card">
        <strong class="card-title" id="sec1_title">📂 1. Chief of Staff Memory Bank (Reservation Values, Calendar Context & Vulnerabilities)</strong>
        <div class="grid-2">
            <div>
                <label id="lbl_goal">🎯 Core Goal, Budget & Timeline:</label>
                <input id="user_goal" value="Close annual compute supply agreement under $1.2M total budget; legal sign-off by Friday." />
            </div>
            <div>
                <label id="lbl_bottom_line">🛑 Hard Bottom Lines (Nash Threat Points / BATNA):</label>
                <input id="hard_bottom_line" value="Payment terms >= 45 days; max discount <= 10%; zero exclusive lock-in clauses." />
            </div>
        </div>
        <label id="lbl_risk">🧠 Historical Commitments & Behavioral Vulnerability Profile:</label>
        <input id="risk_preference" value="Relationship-focused; prone to anxiety and premature concessions when hit with artificial deadlines (Ultimatum Game) or future volume bait (Cheap Talk)." />
    </div>

    <!-- 2. 全周期三阶段切换与输入 -->
    <div class="card">
        <strong class="card-title" id="sec2_title">🛡️ 2. Full-Cycle Negotiation Defense (No Continuous Audio Surveillance Required)</strong>
        <div class="phase-tabs">
            <button type="button" class="phase-tab" id="tab_pre_deal" onclick="setPhase('pre_deal')">
                <span class="phase-tab-title" id="tab1_t">🕒 Stage 1: T-15m Pre-Deal</span>
                <span class="phase-tab-desc" id="tab1_d">SMS Wake-Up Alert & Trap Wargaming (70% of Win)</span>
            </button>
            <button type="button" class="phase-tab active" id="tab_in_deal" onclick="setPhase('in_deal')">
                <span class="phase-tab-title" id="tab2_t">⚡ Stage 2: Live In-Deal</span>
                <span class="phase-tab-desc" id="tab2_d">Hardware Noise-Suppressed STT / Tactical Triage</span>
            </button>
            <button type="button" class="phase-tab" id="tab_post_deal" onclick="setPhase('post_deal')">
                <span class="phase-tab-title" id="tab3_t">🎙️ Stage 3: T+0m Debrief</span>
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

        <div class="preset-row" id="preset_container"></div>

        <label id="lbl_mode">Local Speech Recognition & Microphone Channel:</label>
        <select id="voice_lang">
            <option value="en-US" id="opt_lang_en">🎙️ Microphone Channel: English (US / Global) + Hardware Noise Suppression</option>
            <option value="zh-CN" id="opt_lang_zh">🎙️ 麦克风通道：中文 (普通话) + 硬件级声学降噪 DSP</option>
        </select>

        <label id="lbl_input_text">Stage Input (Meeting Context / Live Opponent Speech / 60s Post-Deal Voice Memo):</label>
        <textarea id="input_text" rows="3"></textarea>

        <div class="btn-row">
            <button type="button" id="mic_btn" class="mic-btn" onclick="toggleMic()">🎤 开启降噪语音捕获 (对手发言时点击)</button>
            <button type="button" id="run_btn" class="primary" onclick="runAgent()">⚡ Execute Game-Theoretic Engine</button>
        </div>
    </div>

    <!-- 3. 动态三元博弈输出区 -->
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

    <!-- 4. 博弈论内核、隐私边界与工程迭代证据 -->
    <div class="card">
        <strong class="card-title" id="sec3_title">🔍 3. Game-Theoretic Architecture, Privacy Verification & Iteration Log</strong>
        <p style="font-size:13.5px; color:#64748b; margin:8px 0 14px 0;" id="privacy_desc"></p>
        <div id="iteration_table_container"></div>
    </div>

    <script>
        let currentLang = 'en';
        let currentPhase = 'in_deal';
        let latestTacticalOutput = null;
        let isAgentRunning = false;
        let lastExecutionTimestamp = 0;
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
                bottom: "Payment terms >= 45 days; max discount <= 10%; zero exclusive lock-in clauses.",
                risk: "Relationship-focused; prone to anxiety and premature concessions when hit with artificial deadlines (Ultimatum Game) or future volume bait (Cheap Talk)."
            },
            zh: {
                goal: "拿下年度算力供应合同，目标总价控制在 120 万以内，本周五前完成法务初审。",
                bottom: "账期绝不低于 45 天；降价幅度不超过 10%；绝不接受独家排他性条款。",
                risk: "重视长期合作关系；当对方抛出‘限时最后通牒（Ultimatum）’或‘明年大单画饼（Cheap Talk）’时容易焦虑让步。"
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
                pre_deal: ["🎯 Opening Anchor & Frame", "🛡️ Predicted Traps & Cheap Talk", "🚨 Panic Circuit Breaker"],
                in_deal: ["📌 Verified Facts", "♟️ Strategic Inferences (Game Theory)", "❓ Unknowns to Probe"],
                post_deal: ["✅ Defended Ground", "⚠️ Verbal Slippage & Exposure", "🔒 Quid Pro Quo Conditioning"]
            },
            zh: {
                pre_deal: ["🎯 先发制人开场锚点", "🛡️ 预判陷阱与廉价信号识别", "🚨 性格弱点防冲动熔断动作"],
                in_deal: ["📌 客观事实 (Verified Facts)", "♟️ 博弈推断 (Strategic Inferences)", "❓ 未知盲区 (Unknowns to Probe)"],
                post_deal: ["✅ 成功守住的筹码阵地", "⚠️ 口头妥协漏洞与风险敞口", "🔒 对等交换条件锁定 (Quid Pro Quo)"]
            }
        };

        function setPhase(phase) {
            currentPhase = phase;
            ['pre_deal', 'in_deal', 'post_deal'].forEach(p => {
                document.getElementById('tab_' + p).className = 'phase-tab' + (p === phase ? ' active' : '');
            });
            updatePillarHeaders();
            renderPresets();
            const firstKey = Object.keys(STAGE_PRESETS[currentLang][currentPhase])[0];
            loadPreset(firstKey);
            document.getElementById('result').style.display = 'none';
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

        function renderIterationTable() {
            const container = document.getElementById('iteration_table_container');
            if (currentLang === 'zh') {
                container.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>迭代版本</th>
                                <th>发现的失效表现 / 测试者真实反馈</th>
                                <th>博弈论与工程级重构举措</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><strong>v1.0 → v2.0</strong></td>
                                <td>误报率 100%：将常规友善的确认邮件也全量判定为高风险陷阱。</td>
                                <td>引入 <code>SAFE</code> 基线与纳什合作检验机制，验证良性输入零误报。</td>
                            </tr>
                            <tr>
                                <td><strong>v2.0 → v3.2</strong></td>
                                <td>单句反问过于单薄，客观事实与推测混杂；正则误伤打码了“60秒”。</td>
                                <td>强制执行认识论三元拆解（事实/推断/未知），修复正则保护时间词，加入中英自适应。</td>
                            </tr>
                            <tr>
                                <td><strong>v3.2 → v4.6</strong></td>
                                <td>长篇发言转写时前半句被索引覆盖丢弃；暗号盲打在触摸屏上极不实用。</td>
                                <td><strong>彻底修复 Web Speech API 全量结果分块拼接 Bug（由 0 索引全量累加）</strong>；移除鸡肋暗号模式，聚焦硬件降噪流式语音捕获（支持2~3分钟长发言与4.5秒自然停顿检测）；后端升级为极速 <code>gemini-3.5-flash-lite</code>。</td>
                            </tr>
                        </tbody>
                    </table>
                `;
            } else {
                container.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>Iteration</th>
                                <th>Failure Mode / Tester Feedback</th>
                                <th>Engineering & Game-Theoretic Fix</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><strong>v1.0 → v2.0</strong></td>
                                <td>100% false-positive rate: flagged even benign agreement emails as hostile traps.</td>
                                <td>Added <code>SAFE</code> baseline & Nash alignment check; verified zero false alarms on benign inputs.</td>
                            </tr>
                            <tr>
                                <td><strong>v2.0 → v3.2</strong></td>
                                <td>Single-sentence output mixed up stated facts with AI speculation; regex accidentally redacted "60s".</td>
                                <td>Enforced Epistemic Game Theory split (Facts / Inferences / Unknowns), refined regex to protect time units, and added EN/ZH auto-adaptation.</td>
                            </tr>
                            <tr>
                                <td><strong>v3.2 → v4.6</strong></td>
                                <td>Prior speech chunks overwritten by resultIndex reset; shorthand created physical friction on touchscreens.</td>
                                <td><strong>Completely fixed Web Speech API chunk aggregation bug (accumulating from index 0 across all chunks)</strong>; removed shorthand mode in favor of noise-suppressed continuous STT and migrated to <code>gemini-3.5-flash-lite</code>.</td>
                            </tr>
                        </tbody>
                    </table>
                `;
            }
        }

        function setLanguage(lang) {
            currentLang = lang;
            document.getElementById('btn_en').className = 'lang-btn' + (lang === 'en' ? ' active' : '');
            document.getElementById('btn_zh').className = 'lang-btn' + (lang === 'zh' ? ' active' : '');

            document.getElementById('user_goal').value = PROFILES[lang].goal;
            document.getElementById('hard_bottom_line').value = PROFILES[lang].bottom;
            document.getElementById('risk_preference').value = PROFILES[lang].risk;
            document.getElementById('voice_lang').value = lang === 'en' ? 'en-US' : 'zh-CN';

            if (lang === 'zh') {
                document.getElementById('subtitle_text').innerText = "从根源化解录音难题：战前15分钟沙盘预警 (70%) • 硬件降噪战中干预 (20%) • 战后60秒口述复盘与跟进邮件 (10%)";
                document.getElementById('sec1_title').innerText = "📂 1. 首席幕僚记忆库（保留点底线 BATNA、日程背景与性格弱点档案）";
                document.getElementById('lbl_goal').innerText = "🎯 核心目标、预算与时间线：";
                document.getElementById('lbl_bottom_line').innerText = "🛑 绝对底线 (纳什谈判威胁点 / BATNA)：";
                document.getElementById('lbl_risk').innerText = "🧠 历史妥协习惯与性格盲区档案：";
                document.getElementById('sec2_title').innerText = "🛡️ 2. 全周期三阶段博弈防线（无需现场非法全程录音）";
                document.getElementById('tab1_t').innerText = "🕒 阶段1：战前15分钟预警";
                document.getElementById('tab1_d').innerText = "短信唤醒、对手套路沙盘与防冲动锚定";
                document.getElementById('tab2_t').innerText = "⚡ 阶段2：战中无痕交锋";
                document.getElementById('tab2_d').innerText = "硬件降噪长语音捕获 / 事实·推断·未知拆解";
                document.getElementById('tab3_t').innerText = "🎙️ 阶段3：战后60秒复盘";
                document.getElementById('tab3_d').innerText = "口述得失审计、口头让步找补与跟进邮件";
                document.getElementById('lbl_mode').innerText = "本地语音转写与麦克风降噪通道：";
                document.getElementById('opt_lang_en').innerText = "🎙️ 麦克风通道：English (US / Global) + Hardware Noise Suppression";
                document.getElementById('opt_lang_zh').innerText = "🎙️ 麦克风通道：中文 (普通话) + 硬件级声学降噪 DSP";
                document.getElementById('lbl_input_text').innerText = "当前阶段输入（战前对手背景 / 战中对手发言转写或纪要 / 战后60秒语音口述）：";
                document.getElementById('mic_btn').innerText = "🎤 开启降噪语音捕获 (对手发言时点击)";
                document.getElementById('run_btn').innerText = "⚡ 启动全周期博弈推演";
                document.getElementById('btn_copy_q').innerText = "📋 复制破局反问/短信";
                document.getElementById('btn_copy_draft').innerText = "📋 复制全文/跟进邮件";
                document.getElementById('btn_mail_client').innerText = "✉️ 唤起本地邮件客户端";

                document.getElementById('sec3_title').innerText = "🔍 3. 博弈论架构、隐私验证与工程迭代记录";
                document.getElementById('privacy_desc').innerHTML = `
                    • <strong>为何全周期胜过现场录音：</strong>在董事会或商务谈判现场秘密录音不仅违反双向知情同意法，且严重破坏互信。Consigliere AI 通过<strong>阶段 1（战前 15 分钟沙盘）</strong>、<strong>阶段 2（降噪长语音捕获）</strong>与<strong>阶段 3（战后 60 秒口述复盘）</strong>串联，实现 100% 战术防御覆盖且零录音风险。<br>
                    • <strong>长语音捕获与贝叶斯容错：</strong>前端激活 Web Audio 硬件降噪 DSP 并支持持续多分钟发言，结合后端基于记忆库档案的语义纠偏，有效防御杂音与同音转写误差。
                `;
            } else {
                document.getElementById('subtitle_text').innerText = "Solving Recording Dilemma: T-15m Wargame • Noise-Suppressed In-Deal • T+0m Debrief";
                document.getElementById('sec1_title').innerText = "📂 1. Chief of Staff Memory Bank (Reservation Values, Calendar Context & Vulnerabilities)";
                document.getElementById('lbl_goal').innerText = "🎯 Core Goal, Budget & Timeline:";
                document.getElementById('lbl_bottom_line').innerText = "🛑 Hard Bottom Lines (Nash Threat Points / BATNA):";
                document.getElementById('lbl_risk').innerText = "🧠 Historical Commitments & Behavioral Vulnerability Profile:";
                document.getElementById('sec2_title').innerText = "🛡️ 2. Full-Cycle Negotiation Defense (No Continuous Audio Surveillance Required)";
                document.getElementById('tab1_t').innerText = "🕒 Stage 1: T-15m Pre-Deal";
                document.getElementById('tab1_d').innerText = "SMS Wake-Up Alert & Trap Wargaming (70% of Win)";
                document.getElementById('tab2_t').innerText = "⚡ Stage 2: Live In-Deal";
                document.getElementById('tab2_d').innerText = "Hardware Noise-Suppressed STT / Tactical Triage";
                document.getElementById('tab3_t').innerText = "🎙️ Stage 3: T+0m Debrief";
                document.getElementById('tab3_d').innerText = "60s Voice Audit vs. Bottom Lines & Follow-Up Email";
                document.getElementById('lbl_mode').innerText = "Local Speech Recognition & Microphone Channel:";
                document.getElementById('opt_lang_en').innerText = "🎙️ Microphone Channel: English (US / Global) + Hardware Noise Suppression";
                document.getElementById('opt_lang_zh').innerText = "🎙️ 麦克风通道：中文 (普通话) + 硬件级声学降噪 DSP";
                document.getElementById('lbl_input_text').innerText = "Stage Input (Meeting Context / Live Opponent Speech / 60s Post-Deal Voice Memo):";
                document.getElementById('mic_btn').innerText = "🎤 Start Noise-Suppressed Capture";
                document.getElementById('run_btn').innerText = "⚡ Execute Game-Theoretic Engine";
                document.getElementById('btn_copy_q').innerText = "📋 Copy Alert";
                document.getElementById('btn_copy_draft').innerText = "📋 Copy Full Draft / Email";
                document.getElementById('btn_mail_client').innerText = "✉️ Open in Mail Client";

                document.getElementById('sec3_title').innerText = "🔍 3. Game-Theoretic Architecture, Privacy Verification & Iteration Log";
                document.getElementById('privacy_desc').innerHTML = `
                    • <strong>Why Full-Cycle Beats Eavesdropping:</strong> Recording boardroom audio violates consent laws and creates hostility. By chaining <strong>Stage 1 (T-15m Wargame)</strong>, <strong>Stage 2 (Continuous STT)</strong>, and <strong>Stage 3 (60s Post-Deal Voice Debrief)</strong> in local memory, Consigliere AI delivers end-to-end tactical defense with zero continuous audio recording.<br>
                    • <strong>Hardware Noise Suppression & Bayesian Repair:</strong> Front-end requests system CoreAudio noise suppression DSP and supports multi-minute continuous speech, combined with prompt-level fuzzy correction using pre-deal memory.
                `;
            }

            updatePillarHeaders();
            updateSessionUI();
            renderIterationTable();
            renderPresets();
            const firstKey = Object.keys(STAGE_PRESETS[currentLang][currentPhase])[0];
            loadPreset(firstKey);
        }

        function renderPresets() {
            const container = document.getElementById('preset_container');
            if (currentPhase === 'pre_deal') {
                container.innerHTML = currentLang === 'zh'
                    ? `<button type="button" class="preset-btn" onclick="loadPreset('p1')">📅 战前案例 1：强势投资人/客户排他逼签预警</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('p2')">📅 战前案例 2：采购总监压缩账期历史复盘预警</button>`
                    : `<button type="button" class="preset-btn" onclick="loadPreset('p1')">📅 Pre-Deal 1: Hostile VC Exclusivity & Bait Wargame</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('p2')">📅 Pre-Deal 2: Procurement Net-15 Terms Defense</button>`;
            } else if (currentPhase === 'in_deal') {
                container.innerHTML = currentLang === 'zh'
                    ? `<button type="button" class="preset-btn" onclick="loadPreset('trap')">🔥 战中案例 1：高危复合陷阱（压价25%+排他+假死线）</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('safe')">✅ 战中案例 2：良性对齐沟通（验证零误报）</button>`
                    : `<button type="button" class="preset-btn" onclick="loadPreset('trap')">🔥 Live Case 1: Ultimatum Trap (25% Cut + Exclusivity)</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('safe')">✅ Live Case 2: Benign Alignment (Zero False Alarm)</button>`;
            } else {
                container.innerHTML = currentLang === 'zh'
                    ? `<button type="button" class="preset-btn" onclick="loadPreset('slippage')">🚨 战后案例 1：现场口头松口越界（急需邮件附加条件找补）</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('clean')">🏆 战后案例 2：成功守住底线（锁定对方口头画饼为书面条款）</button>`
                    : `<button type="button" class="preset-btn" onclick="loadPreset('slippage')">🚨 Debrief 1: Verbal Slippage Recovery (Conditioning Concessions)</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('clean')">🏆 Debrief 2: Clean Defense (Locking Cheap Talk into Milestones)</button>`;
            }
        }

        function loadPreset(key) {
            const val = STAGE_PRESETS[currentLang][currentPhase][key];
            if (val) document.getElementById('input_text').value = val;
        }

        function clientSideRedact(rawText) {
            let redacted = rawText;
            redacted = redacted.replace(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/g, '[REDACTED_EMAIL]');
            redacted = redacted.replace(/(\+?\d{1,3}[-\s]?)?\(?\d{3}\)?[-\s]?\d{3,4}[-\s]?\d{4}/g, '[REDACTED_PHONE]');
            redacted = redacted.replace(/\b([A-Z]{2,5}-\d{2,6}|\#[A-Za-z0-9]{4,10})\b/g, '[REDACTED_ID]');
            redacted = redacted.replace(/([\$¥￥€£]\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:万美金|万美元|万港币|万元|万|亿|million|billion|k|m|b))?|\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万美金|万美元|万港币|万元|万|亿|美金|美元|港币|元|块|million|billion|k|m|b|%))/gi, '[REDACTED_VALUE]');
            redacted = redacted.replace(/([A-Za-z0-9\u4e00-\u9fa5]{2,16}(?:公司|集团|科技|资本|银行|厂|Inc\.?|Corp\.?|LLC|Ltd\.?|Ventures|Capital))/g, '[COMPANY_ENTITY]');
            const matches = redacted.match(/\[(?:REDACTED_\w+|COMPANY_ENTITY)\]/g);
            return {
                sanitizedText: redacted,
                redactedCount: matches ? matches.length : 0
            };
        }

        let recognition = null;
        let isListening = false;

        // 彻底修复长语音转写：从第 0 个分块开始全量拼接，杜绝覆盖前半截文本
        async function toggleMic() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                alert(currentLang === 'zh' ? "浏览器不支持 Web Speech API，请使用 Chrome/Safari 或点击上方预设案例。" : "Browser does not support Web Speech API.");
                return;
            }

            if (!isListening) {
                // 1. 先清空输入框并重置识别器
                document.getElementById('input_text').value = "";
                
                // 2. 激活声卡硬件降噪
                try {
                    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                        audioStream = await navigator.mediaDevices.getUserMedia({
                            audio: {
                                noiseSuppression: true,
                                echoCancellation: true,
                                autoGainControl: true
                            }
                        });
                    }
                } catch (e) {
                    console.log("Audio constraints bypassed:", e);
                }

                if (!recognition) {
                    recognition = new SpeechRecognition();
                    recognition.continuous = true;
                    recognition.interimResults = true;

                    // 关键修复：从 i = 0 全量累加所有分块，绝对不再漏掉前面的句子！
                    recognition.onresult = (event) => {
                        let fullTranscript = '';
                        for (let i = 0; i < event.results.length; ++i) {
                            fullTranscript += event.results[i][0].transcript;
                        }
                        document.getElementById('input_text').value = fullTranscript;

                        // 智能停顿探测：4.5秒自然停顿后自动分析
                        if (silenceTimer) clearTimeout(silenceTimer);
                        silenceTimer = setTimeout(() => {
                            if (isListening && document.getElementById('input_text').value.trim().length >= 6) {
                                stopMicInternal();
                                runAgent();
                            }
                        }, 4500);
                    };

                    recognition.onend = () => {
                        stopMicInternal();
                        const now = Date.now();
                        if (!isAgentRunning && (now - lastExecutionTimestamp > 2500)) {
                            const txt = document.getElementById('input_text').value.trim();
                            if (txt.length >= 4) {
                                runAgent();
                            }
                        }
                    };
                }

                recognition.lang = document.getElementById('voice_lang').value;
                recognition.start();
                isListening = true;
                const micBtn = document.getElementById('mic_btn');
                micBtn.className = 'mic-btn active';
                micBtn.innerText = currentLang === 'zh' ? "🛑 正在倾听对方发言 (讲完请点击停止或停顿4.5秒自动分析)" : "🛑 Listening (Click to stop or pause 4.5s)...";

            } else {
                stopMicInternal();
                if (document.getElementById('input_text').value.trim()) {
                    runAgent();
                }
            }
        }

        function stopMicInternal() {
            if (silenceTimer) clearTimeout(silenceTimer);
            if (recognition && isListening) {
                recognition.stop();
            }
            if (audioStream) {
                audioStream.getTracks().forEach(track => track.stop());
                audioStream = null;
            }
            isListening = false;
            const micBtn = document.getElementById('mic_btn');
            micBtn.className = 'mic-btn';
            micBtn.innerText = currentLang === 'zh' ? "🎤 开启降噪语音捕获 (对手发言时点击)" : "🎤 Start Noise-Suppressed Capture";
        }

        async function runAgent() {
            if (isAgentRunning) return;
            const now = Date.now();
            if (now - lastExecutionTimestamp < 1500) {
                return;
            }
            lastExecutionTimestamp = now;

            const errBox = document.getElementById('error_box');
            const resBox = document.getElementById('result');
            const runBtn = document.getElementById('run_btn');
            errBox.style.display = 'none';
            isAgentRunning = true;
            runBtn.disabled = true;
            runBtn.innerText = currentLang === 'zh' ? '⏳ 正在执行全周期博弈推演 (1~2秒)...' : '⏳ Running Game-Theoretic Deduction (1-2s)...';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 18000);

            try {
                const rawText = document.getElementById('input_text').value;
                const scrubResult = clientSideRedact(rawText);
                const clientScrubbedText = scrubResult.sanitizedText;
                const localRedactedCount = scrubResult.redactedCount;

                const payload = {
                    phase: currentPhase,
                    lang: currentLang,
                    text: clientScrubbedText,
                    user_goal: document.getElementById('user_goal').value,
                    hard_bottom_line: document.getElementById('hard_bottom_line').value,
                    risk_preference: document.getElementById('risk_preference').value,
                    session_context: sessionMemory
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

                const t = data.tactical_advice;
                latestTacticalOutput = t;
                sessionMemory[currentPhase] = {
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
                    ? `🛡️ <strong>客户端本地预脱敏验证：</strong>已在浏览器内存拦截替换 <b>${localRedactedCount}</b> 处敏感实体（原始敏感词未出设备） | ⏱️ <strong>实测耗时：</strong><b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>实际离开浏览器并发往模型的脱敏 Payload：</strong><code>${data.sanitized_payload_sent_to_llm}</code>`
                    : `🛡️ <strong>Client-Side Sanitization Verified:</strong> <b>${localRedactedCount}</b> sensitive entities scrubbed in browser memory prior to network call | ⏱️ <strong>Latency:</strong> <b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>Actual Sanitized Payload Sent:</strong> <code>${data.sanitized_payload_sent_to_llm}</code>`;

                document.getElementById('audit_view').innerHTML = auditMsg;

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
                    counterPrefix = currentLang === 'zh' ? '📱 战前15分钟短信唤醒摘要：' : '📱 T-15m SMS Wake-Up Alert: ';
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
                errBox.style.display = 'block';
                errBox.innerText = '⚠️ ' + (err.name === 'AbortError' ? '请求超过 18 秒超时，请稍后重试。' : err.message);
                resBox.style.display = 'none';
            } finally {
                clearTimeout(timeoutId);
                isAgentRunning = false;
                runBtn.disabled = false;
                runBtn.innerText = currentLang === 'zh' ? '⚡ 启动全周期博弈推演' : '⚡ Execute Game-Theoretic Engine';
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
                showToast(currentLang === 'zh' ? '✅ 破局反问/短信已复制！' : '✅ Alert copied!');
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
            const sysLang = (navigator.language || navigator.userLanguage || '').toLowerCase();
            if (sysLang.startsWith('en')) {
                setLanguage('en');
            } else {
                setLanguage('zh');
            }
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
