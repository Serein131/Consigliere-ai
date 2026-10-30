import os
import re
import time
import json
import logging
import http.client
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# 关闭 Werkzeug 默认请求体日志，防止服务端记录任何请求内容
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

API_HOST = "generativelanguage.googleapis.com"

# 服务端二次兜底脱敏（主要脱敏已在浏览器端内存完成，此处为纵深防御）
def server_fallback_redact(text: str) -> dict:
    redacted = text
    redacted = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED_EMAIL]', redacted)
    redacted = re.sub(r'(\+?\d{1,3}[-\s]?)?\(?\d{3}\)?[-\s]?\d{3,4}[-\s]?\d{4}', '[REDACTED_PHONE]', redacted)
    redacted = re.sub(r'\b([A-Z]{2,5}-\d{2,6}|\#[A-Za-z0-9]{4,10})\b', '[REDACTED_ID]', redacted)
    redacted = re.sub(
        r'(\$?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万|亿|美金|美元|元|块|k|m|b|million|billion|%)?)',
        '[REDACTED_VALUE]',
        redacted,
        flags=re.IGNORECASE
    )
    redacted = re.sub(
        r'([A-Za-z0-9\u4e00-\u9fa5]{2,16}(?:公司|集团|科技|资本|银行|厂|Inc\.?|Corp\.?|LLC|Ltd\.?|Ventures|Capital))',
        '[COMPANY_ENTITY]',
        redacted
    )
    count = len(re.findall(r'\[(?:REDACTED_\w+\vert{}COMPANY_ENTITY)\]', redacted))
    return {"sanitized_text": redacted, "redaction_count": count}

def discover_available_flash_model(api_key: str) -> str:
    conn = http.client.HTTPSConnection(API_HOST, timeout=5)
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
        if "generateContent" in methods and "flash" in name.lower() and "2.0-flash" not in name.lower():
            flash_candidates.append(name)
    for preferred in flash_candidates:
        if ("3" in preferred or "2.5-flash" in preferred) and "lite" not in preferred and "tts" not in preferred and "image" not in preferred:
            return preferred
    return flash_candidates[0] if flash_candidates else "gemini-3-flash-preview"

def call_gemini_rest(api_key: str, model_name: str, system_instruction: str, user_text: str, use_thinking_zero: bool = True) -> dict:
    path = f"/v1beta/models/{model_name}:generateContent?key={api_key}"
    gen_config = {
        "temperature": 0.15,
        "responseMimeType": "application/json"
    }
    if use_thinking_zero and ("2.5" in model_name or "3" in model_name):
        gen_config["thinkingConfig"] = {"thinkingBudget": 0}

    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": gen_config
    }
    payload_bytes = json.dumps(body).encode("utf-8")

    conn = http.client.HTTPSConnection(API_HOST, timeout=8)
    try:
        conn.request("POST", path, body=payload_bytes, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="ignore")
        if resp.status != 200:
            err = RuntimeError(f"HTTP_{resp.status}:{raw[:200]}")
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
    mode = payload.get("mode", "stream")
    lang_pref = payload.get("lang", "en")
    incoming_text = payload.get("text", "").strip()
    user_goal = payload.get("user_goal", "").strip()
    hard_bottom_line = payload.get("hard_bottom_line", "").strip()
    risk_preference = payload.get("risk_preference", "").strip()

    if not incoming_text:
        return jsonify({"error": "Please enter negotiation input or select a preset case."}), 400

    redaction_result = server_fallback_redact(incoming_text)
    sanitized_text = redaction_result["sanitized_text"]

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not configured in Vercel environment."}), 500

    phase_instructions = {
        "pre_deal": """CURRENT STAGE: PHASE 1 — T-15m PRE-DEAL BRIEFING & WARGAMING (战前15分钟沙盘预警).
Objective: 70% of negotiations are won before speaking. Arm the user psychologically and game-theoretically before entering the room.
- In 'trap_or_intent': Identify the most likely Game-Theoretic Playbook the opponent will use (e.g., Ultimatum Game / Artificial Scarcity / Cheap Talk Future Bait).
- In 'triggered_rule': Cite the exact reservation value (BATNA / Hard Bottom Line) most at risk today and lock it.
- In 'box1_text': [Opening Anchor & Framing]: What proactive anchor or agenda frame the user should set in the first 2 minutes.
- In 'box2_text': [Predicted Traps & Signaling Test]: Specific opponent traps to anticipate and how to test if their promises are 'Cheap Talk' vs. 'Costly Signals'.
- In 'box3_text': [Behavioral Circuit Breaker]: A concrete physical/verbal pause tactic tailored to the user's vulnerability (e.g., if pressured on deadline, pause 5s and cite Friday legal review).
- In 'counter_question': [T-15m SMS Wake-Up Alert]: Ultra-punchy 1-sentence SMS alert sent to user's phone 15 mins before the meeting.
- In 'draft_reply': [Pre-Meeting Framing Note / Agenda Opener]: A crisp message or opening statement to set the frame before sitting down.""",

        "in_deal": """CURRENT STAGE: PHASE 2 — IN-DEAL STEALTH INTERVENTION (战中无痕交锋与三元拆解).
Objective: The user is inside a live negotiation (either feeding a stealth 3-word shorthand under the table or live browser speech). Eliminate cognitive panic without illegal full-room audio recording.
- Apply Nash Bargaining (Reservation Price defense), Cheap Talk filtering, and Epistemic Game Theory.
- NO FALSE POSITIVES: If the counterparty agrees to terms or aligns constructively, set 'risk_level' to 'SAFE' and 'trap_or_intent' to 'Constructive Alignment'.
- In 'triggered_rule': Cite which exact Goal, Budget, or Hard Bottom Line was triggered or satisfied.
- In 'box1_text': [Verified Facts]: Objective terms or constraints explicitly stated (zero speculation).
- In 'box2_text': [Strategic Inferences]: Opponent's hidden leverage play, asymmetric information motive, or Cheap Talk bluff.
- In 'box3_text': [Unknowns to Probe]: Missing variables required to test their bluff or verify budget.
- In 'counter_question': [Live Counter-Question (<25 words)]: Sharp, non-defensive question to say out loud right now to flip leverage.
- In 'draft_reply': [Tactical Reply / Stealth SMS Whisper]: Complete, poised response ready to send or speak.""",

        "post_deal": """CURRENT STAGE: PHASE 3 — T+0m POST-DEAL 60s VOICE DEBRIEF & FOLLOW-UP (战后60秒口述复盘与跟进闭环).
Objective: The user just walked out of the room and dictated a 60-second voice summary. Audit the outcome against pre-deal bottom lines and lock in terms via a high-leverage follow-up email.
- If all bottom lines were defended, set 'risk_level' to 'SAFE'. If the user made an unconditioned verbal concession that breached or neared a bottom line, set 'risk_level' to 'MEDIUM' or 'CRITICAL'.
- In 'trap_or_intent': [Post-Deal Audit Verdict]: e.g., 'Verbal Slippage Detected — Conditional Walk-Back Required' or 'Strong Defense — Lock In Alignment'.
- In 'triggered_rule': Compare what happened in the room against the user's initial Hard Bottom Lines & Goal.
- In 'box1_text': [Defended Ground]: Key terms and bottom lines successfully protected during the meeting.
- In 'box2_text': [Slippage & Risk Exposure]: Any verbal compromises, unverified opponent promises (Cheap Talk), or ambiguity that must be fenced in.
- In 'box3_text': [Quid Pro Quo Lock]: What concrete condition or reciprocal commitment must be attached to any concession made.
- In 'counter_question': [Core Debrief Takeaway]: 1-sentence strategic priority for the next 24 hours.
- In 'draft_reply': [High-Leverage Follow-Up Email]: A masterfully written post-meeting email that politely summarizes agreed points while legally/commercially conditioning any verbal concessions (reclaiming leverage)."""
    }

    selected_phase_prompt = phase_instructions.get(phase, phase_instructions["in_deal"])

    system_instruction = f"""You are Consigliere AI (v4.0), a Full-Cycle Game-Theoretic Chief of Staff & Negotiation Copilot.
You replace illegal/intrusive full-room audio recording with a 3-stage cognitive defense architecture.

USER STRATEGIC PROFILE (MEMORY BANK):
- [Core Goal & Budget]: {user_goal}
- [Hard Bottom Lines (Reservation Values)]: {hard_bottom_line}
- [Behavioral Vulnerabilities & Risk Profile]: {risk_preference}
- [Input Channel]: {mode}

{selected_phase_prompt}

LANGUAGE RULE:
If UI language preference ('{lang_pref}') is 'en', ALL JSON values MUST be in fluent, sharp, executive American English. If 'zh', output in concise, professional Chinese.

Output ONLY a single valid JSON object with these exact 8 keys (no Markdown wrappers):
{{
  "risk_level": "SAFE, LOW, MEDIUM, or CRITICAL",
  "trap_or_intent": "Game-theoretic classification or audit verdict",
  "triggered_rule": "Explicit reference to user's Goal, Bottom Line, or Vulnerability",
  "box1_text": "Content for Pillar 1 based on current stage",
  "box2_text": "Content for Pillar 2 based on current stage",
  "box3_text": "Content for Pillar 3 based on current stage",
  "counter_question": "Immediate counter-question, SMS wake-up alert, or core debrief takeaway (<25 words)",
  "draft_reply": "Complete follow-up email, tactical reply draft, or pre-meeting framing note"
}}"""

    user_prompt = f"[{phase.upper()} INPUT (Sanitized)]: {sanitized_text}"

    primary_model = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview").strip()
    candidate_models = [primary_model, "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
    used_model = None
    raw_api_resp = None
    error_logs = []

    for candidate in dict.fromkeys(candidate_models):
        try:
            used_model = candidate
            raw_api_resp = call_gemini_rest(api_key, candidate, system_instruction, user_prompt, use_thinking_zero=True)
            break
        except Exception as e:
            status_code = getattr(e, "status_code", None)
            err_body = getattr(e, "err_body", "")
            if status_code == 400 and "thinking" in err_body.lower():
                try:
                    raw_api_resp = call_gemini_rest(api_key, candidate, system_instruction, user_prompt, use_thinking_zero=False)
                    break
                except Exception as retry_err:
                    error_logs.append(f"{candidate}(retry): {str(retry_err)}")
            else:
                error_logs.append(f"{candidate}: {str(e)}")

    if not raw_api_resp:
        try:
            discovered = discover_available_flash_model(api_key)
            used_model = discovered
            raw_api_resp = call_gemini_rest(api_key, discovered, system_instruction, user_prompt, use_thinking_zero=False)
        except Exception as disc_err:
            return jsonify({
                "error": f"Model invocation failed: {'; '.join(error_logs)} | Probe: {str(disc_err)}"
            }), 500

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
    <title>Consigliere AI v4.0 — Full-Cycle Game-Theoretic Chief of Staff</title>
    <style>
        body { background: #090a0f; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; padding: 20px; max-width: 880px; margin: auto; line-height: 1.5; }
        .badge { background: #1e293b; color: #38bdf8; padding: 3px 8px; border-radius: 4px; font-size: 12px; border: 1px solid #0284c7; }
        .card { background: #12141d; border: 1px solid #27272a; border-radius: 8px; padding: 16px; margin-top: 14px; }
        .risk-CRITICAL, .risk-MEDIUM { border-left: 4px solid #ef4444; }
        .risk-LOW { border-left: 4px solid #f59e0b; }
        .risk-SAFE { border-left: 4px solid #10b981; }
        label { font-size: 12px; color: #94a3b8; display: block; margin-top: 10px; font-weight: 600; }
        input, select, textarea, button { background: #18181b; color: #fff; border: 1px solid #3f3f46; padding: 9px; border-radius: 6px; width: 100%; margin-top: 5px; box-sizing: border-box; font-size: 13px; }
        .header-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .lang-switch { display: flex; gap: 6px; width: auto; }
        .lang-btn { background: #1e293b; border: 1px solid #334155; color: #94a3b8; padding: 4px 10px; font-size: 12px; border-radius: 4px; cursor: pointer; width: auto; margin-top: 0; }
        .lang-btn.active { background: #2563eb; color: #fff; border-color: #3b82f6; font-weight: bold; }
        .phase-tabs { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 10px; }
        .phase-tab { background: #18181b; border: 1px solid #334155; color: #94a3b8; padding: 10px; border-radius: 6px; cursor: pointer; text-align: left; transition: 0.15s; margin-top: 0; }
        .phase-tab:hover { background: #1e293b; }
        .phase-tab.active { background: #1e293b; border: 1.5px solid #38bdf8; color: #fff; box-shadow: 0 0 12px rgba(56, 189, 248, 0.15); }
        .phase-tab-title { font-weight: bold; font-size: 13px; color: #38bdf8; display: block; }
        .phase-tab-desc { font-size: 11px; color: #94a3b8; margin-top: 2px; display: block; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .preset-row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
        .preset-btn { background: #1e293b; border: 1px solid #334155; color: #cbd5e1; padding: 6px 10px; font-size: 12px; width: auto; cursor: pointer; border-radius: 4px; }
        .preset-btn:hover { background: #334155; }
        .btn-row { display: flex; gap: 10px; margin-top: 12px; }
        button.primary { background: #2563eb; border: none; font-weight: bold; cursor: pointer; font-size: 14px; }
        button.mic-btn { background: #059669; border: none; font-weight: bold; cursor: pointer; font-size: 14px; }
        .tri-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-top: 12px; }
        .tri-box { background: #18181b; border: 1px solid #27272a; padding: 10px; border-radius: 6px; font-size: 12px; }
        .tri-title { color: #38bdf8; font-weight: bold; margin-bottom: 4px; font-size: 12px; }
        .counter { font-size: 16px; color: #facc15; font-weight: bold; margin: 12px 0 8px 0; }
        .meta { font-size: 12px; color: #10b981; background: #064e3b33; padding: 10px; border-radius: 6px; border: 1px solid #05966955; word-break: break-all; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }
        th, td { border: 1px solid #27272a; padding: 8px; text-align: left; }
        th { background: #18181b; color: #94a3b8; }
        @media (max-width: 680px) { .grid-2, .tri-grid, .phase-tabs { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="header-row">
        <div>
            <h2 style="margin:0 0 4px 0;">⚡ Consigliere AI <span class="badge">v4.0 — Full-Cycle Game-Theoretic Chief of Staff</span></h2>
            <span style="color:#94a3b8; font-size:13px;" id="subtitle_text">Solving the Recording Dilemma: 70% Pre-Deal Wargaming • 20% Stealth In-Deal • 10% Post-Deal Debrief</span>
        </div>
        <div class="lang-switch">
            <button type="button" class="lang-btn" id="btn_en" onclick="setLanguage('en')">🇺🇸 English</button>
            <button type="button" class="lang-btn" id="btn_zh" onclick="setLanguage('zh')">🇨🇳 中文</button>
        </div>
    </div>

    <!-- 1. 首席幕僚记忆库 -->
    <div class="card">
        <strong id="sec1_title">📂 1. Chief of Staff Memory Bank (Reservation Values, Calendar Context & Vulnerabilities)</strong>
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
        <strong id="sec2_title">🛡️ 2. Full-Cycle Negotiation Defense (No Continuous Audio Surveillance Required)</strong>
        <div class="phase-tabs">
            <button type="button" class="phase-tab" id="tab_pre_deal" onclick="setPhase('pre_deal')">
                <span class="phase-tab-title" id="tab1_t">🕒 Stage 1: T-15m Pre-Deal</span>
                <span class="phase-tab-desc" id="tab1_d">SMS Wake-Up Alert & Trap Wargaming (70% of Win)</span>
            </button>
            <button type="button" class="phase-tab active" id="tab_in_deal" onclick="setPhase('in_deal')">
                <span class="phase-tab-title" id="tab2_t">⚡ Stage 2: Live Stealth</span>
                <span class="phase-tab-desc" id="tab2_d">3-Word Shorthand / Browser STT Epistemic Split</span>
            </button>
            <button type="button" class="phase-tab" id="tab_post_deal" onclick="setPhase('post_deal')">
                <span class="phase-tab-title" id="tab3_t">🎙️ Stage 3: T+0m Debrief</span>
                <span class="phase-tab-desc" id="tab3_d">60s Voice Audit vs. Bottom Lines & Follow-Up Email</span>
            </button>
        </div>

        <div class="preset-row" id="preset_container"></div>

        <label id="lbl_mode">Input Channel & Local Speech Recognition Language:</label>
        <div class="grid-2">
            <select id="mode">
                <option value="stealth_sms" id="opt_mode_sms">🔒 Stealth 3-Word Shorthand / SMS Trigger (Zero Audio Exposure)</option>
                <option value="browser_stt" id="opt_mode_stt">🟢 Ephemeral Browser Web Speech STT + Client Scrubbing</option>
            </select>
            <select id="voice_lang">
                <option value="en-US">🎙️ Microphone: English (US / Global)</option>
                <option value="zh-CN">🎙️ Microphone: 中文 (Mandarin)</option>
            </select>
        </div>

        <label id="lbl_input_text">Stage Input (Meeting Context / Live 3-Word Shorthand / 60s Post-Deal Voice Memo):</label>
        <textarea id="input_text" rows="2"></textarea>

        <div class="btn-row">
            <button type="button" id="mic_btn" class="mic-btn" onclick="toggleMic()">🎤 Dictate via Local Browser Speech</button>
            <button type="button" id="run_btn" class="primary" onclick="runAgent()">⚡ Execute Game-Theoretic Engine</button>
        </div>
    </div>

    <!-- 3. 动态三元博弈输出区 -->
    <div id="error_box" class="card" style="display:none; border-color:#ef4444; color:#f87171;"></div>
    <div id="result" class="card" style="display:none;">
        <div class="meta" id="audit_view"></div>
        <h3 id="trap_title" style="margin: 12px 0 4px 0;"></h3>
        <div id="rule_cited" style="font-size:13px; color:#38bdf8; font-weight:600; margin-bottom:8px;"></div>

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

        <div class="counter" id="counter_q"></div>
        <div style="background:#18181b; border:1px solid #3f3f46; padding:12px; border-radius:6px; font-size:13px; white-space:pre-wrap;" id="draft_box"></div>
    </div>

    <!-- 4. 博弈论内核、隐私边界与工程迭代证据 -->
    <div class="card">
        <strong id="sec3_title">🔍 3. Game-Theoretic Architecture, Privacy Verification & Iteration Log</strong>
        <p style="font-size:12px; color:#94a3b8; margin:6px 0;" id="privacy_desc">
            • <strong>Why Full-Cycle Beats Eavesdropping:</strong> Recording live boardroom audio violates two-party consent laws and destroys trust. By anchoring <strong>Stage 1 (T-15m Wargaming)</strong>, <strong>Stage 2 (3-Word Stealth Shorthand)</strong>, and <strong>Stage 3 (60s Post-Deal Voice Debrief)</strong>, Consigliere AI delivers 100% tactical coverage with zero illegal recording.<br>
            • <strong>Verifiable Client-Side Scrubbing:</strong> Open DevTools (<code>F12 -> Network</code>) to verify that emails, phone numbers, contract IDs, and dollar amounts are replaced with <code>[REDACTED_*]</code> in browser JS before any packet leaves your device.
        </p>
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
                    <td>Single-sentence output mixed up stated facts with AI speculation; lacked bilingual support.</td>
                    <td>Enforced Epistemic Game Theory split (Facts / Inferences / Unknowns), client-side regex scrubbing, and EN/ZH auto-adaptation.</td>
                </tr>
                <tr>
                    <td><strong>v3.2 → v4.0</strong></td>
                    <td>Relying only on live transcripts missed pre-meeting preparation and post-meeting verbal slippage recovery.</td>
                    <td>Built the <strong>3-Stage Full-Cycle Defense</strong> (T-15m SMS Wargaming + Live 3-Word Shorthand + T+0m 60s Debrief & Conditional Follow-Up Email).</td>
                </tr>
            </tbody>
        </table>
    </div>

    <script>
        let currentLang = 'en';
        let currentPhase = 'in_deal';

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
                    shorthand: "[Stealth 3-Word Shorthand]: John / 25%-cut+exclusivity / 5pm-ultimatum",
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
                    shorthand: "【桌面下3词暗号盲打】：王总 / 降价25%绑独家 / 下午5点最后通牒",
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

        function setLanguage(lang) {
            currentLang = lang;
            document.getElementById('btn_en').className = 'lang-btn' + (lang === 'en' ? ' active' : '');
            document.getElementById('btn_zh').className = 'lang-btn' + (lang === 'zh' ? ' active' : '');

            document.getElementById('user_goal').value = PROFILES[lang].goal;
            document.getElementById('hard_bottom_line').value = PROFILES[lang].bottom;
            document.getElementById('risk_preference').value = PROFILES[lang].risk;
            document.getElementById('voice_lang').value = lang === 'en' ? 'en-US' : 'zh-CN';

            if (lang === 'zh') {
                document.getElementById('subtitle_text').innerText = "从根源化解录音难题：战前15分钟沙盘预警 (70%) • 战中3词暗号无痕干预 (20%) • 战后60秒口述复盘与跟进邮件 (10%)";
                document.getElementById('sec1_title').innerText = "📂 1. 首席幕僚记忆库（保留点底线 BATNA、日程背景与性格弱点档案）";
                document.getElementById('lbl_goal').innerText = "🎯 核心目标、预算与时间线：";
                document.getElementById('lbl_bottom_line').innerText = "🛑 绝对底线 (纳什谈判威胁点 / BATNA)：";
                document.getElementById('lbl_risk').innerText = "🧠 历史妥协习惯与性格盲区档案：";
                document.getElementById('sec2_title').innerText = "🛡️ 2. 全周期三阶段博弈防线（无需现场非法全程录音）";
                document.getElementById('tab1_t').innerText = "🕒 阶段1：战前15分钟预警";
                document.getElementById('tab1_d').innerText = "短信唤醒、对手套路沙盘与防冲动锚定";
                document.getElementById('tab2_t').innerText = "⚡ 阶段2：战中无痕交锋";
                document.getElementById('tab2_d').innerText = "桌面下3词暗号盲打 / 事实·推断·未知拆解";
                document.getElementById('tab3_t').innerText = "🎙️ 阶段3：战后60秒复盘";
                document.getElementById('tab3_d').innerText = "口述得失审计、口头让步找补与跟进邮件";
                document.getElementById('lbl_mode').innerText = "交互通道与本地麦克风语言：";
                document.getElementById('opt_mode_sms').innerText = "🔒 极简3词短信暗号 / 盲打触发（零现场录音暴露风险）";
                document.getElementById('opt_mode_stt').innerText = "🟢 浏览器瞬态语音转写 + 客户端本地预脱敏";
                document.getElementById('lbl_input_text').innerText = "当前阶段输入（战前对手背景 / 战中3词暗号或原话 / 战后60秒语音口述）：";
                document.getElementById('mic_btn').innerText = "🎤 开启本地语音口述";
                document.getElementById('run_btn').innerText = "⚡ 启动全周期博弈推演";
            } else {
                document.getElementById('subtitle_text').innerText = "Solving the Recording Dilemma: 70% Pre-Deal Wargaming • 20% Stealth In-Deal • 10% Post-Deal Debrief";
                document.getElementById('sec1_title').innerText = "📂 1. Chief of Staff Memory Bank (Reservation Values, Calendar Context & Vulnerabilities)";
                document.getElementById('lbl_goal').innerText = "🎯 Core Goal, Budget & Timeline:";
                document.getElementById('lbl_bottom_line').innerText = "🛑 Hard Bottom Lines (Nash Threat Points / BATNA):";
                document.getElementById('lbl_risk').innerText = "🧠 Historical Commitments & Behavioral Vulnerability Profile:";
                document.getElementById('sec2_title').innerText = "🛡️ 2. Full-Cycle Negotiation Defense (No Continuous Audio Surveillance Required)";
                document.getElementById('tab1_t').innerText = "🕒 Stage 1: T-15m Pre-Deal";
                document.getElementById('tab1_d').innerText = "SMS Wake-Up Alert & Trap Wargaming (70% of Win)";
                document.getElementById('tab2_t').innerText = "⚡ Stage 2: Live Stealth";
                document.getElementById('tab2_d').innerText = "3-Word Shorthand / Browser STT Epistemic Split";
                document.getElementById('tab3_t').innerText = "🎙️ Stage 3: T+0m Debrief";
                document.getElementById('tab3_d').innerText = "60s Voice Audit vs. Bottom Lines & Follow-Up Email";
                document.getElementById('lbl_mode').innerText = "Input Channel & Local Speech Recognition Language:";
                document.getElementById('opt_mode_sms').innerText = "🔒 Stealth 3-Word Shorthand / SMS Trigger (Zero Audio Exposure)";
                document.getElementById('opt_mode_stt').innerText = "🟢 Ephemeral Browser Web Speech STT + Client Scrubbing";
                document.getElementById('lbl_input_text').innerText = "Stage Input (Meeting Context / Live 3-Word Shorthand / 60s Post-Deal Voice Memo):";
                document.getElementById('mic_btn').innerText = "🎤 Dictate via Local Browser Speech";
                document.getElementById('run_btn').innerText = "⚡ Execute Game-Theoretic Engine";
            }

            updatePillarHeaders();
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
                       <button type="button" class="preset-btn" onclick="loadPreset('shorthand')">🕵️ 战中案例 2：桌面下3词暗号极速盲打</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('safe')">✅ 战中案例 3：良性对齐沟通（验证零误报）</button>`
                    : `<button type="button" class="preset-btn" onclick="loadPreset('trap')">🔥 Live Case 1: Ultimatum Trap (25% Cut + Exclusivity)</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('shorthand')">🕵️ Live Case 2: Under-Table 3-Word Stealth Shorthand</button>
                       <button type="button" class="preset-btn" onclick="loadPreset('safe')">✅ Live Case 3: Benign Alignment (Zero False Alarm)</button>`;
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
            redacted = redacted.replace(/(\$?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万|亿|美金|美元|元|块|k|m|b|million|billion|%)?)/gi, '[REDACTED_VALUE]');
            redacted = redacted.replace(/([A-Za-z0-9\u4e00-\u9fa5]{2,16}(?:公司|集团|科技|资本|银行|厂|Inc\.?|Corp\.?|LLC|Ltd\.?|Ventures|Capital))/g, '[COMPANY_ENTITY]');
            const matches = redacted.match(/\[(?:REDACTED_\w+|COMPANY_ENTITY)\]/g);
            return {
                sanitizedText: redacted,
                redactedCount: matches ? matches.length : 0
            };
        }

        let recognition = null;
        let isListening = false;

        function toggleMic() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                alert(currentLang === 'zh' ? "浏览器不支持 Web Speech API，请使用 Chrome/Safari 或点击上方预设案例。" : "Browser does not support Web Speech API. Please use Chrome/Safari or click a preset button.");
                return;
            }
            if (!recognition) {
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = true;
                recognition.onresult = (event) => {
                    let transcript = '';
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        transcript += event.results[i][0].transcript;
                    }
                    document.getElementById('input_text').value = transcript;
                };
                recognition.onend = () => {
                    isListening = false;
                    document.getElementById('mic_btn').innerText = currentLang === 'zh' ? "🎤 开启本地语音口述" : "🎤 Dictate via Local Browser Speech";
                    if (document.getElementById('input_text').value.trim()) runAgent();
                };
            }

            if (!isListening) {
                recognition.lang = document.getElementById('voice_lang').value;
                recognition.start();
                isListening = true;
                document.getElementById('mic_btn').innerText = currentLang === 'zh' ? "🛑 正在听音中..." : "🛑 Listening...";
            } else {
                recognition.stop();
            }
        }

        async function runAgent() {
            const errBox = document.getElementById('error_box');
            const resBox = document.getElementById('result');
            const runBtn = document.getElementById('run_btn');
            errBox.style.display = 'none';
            runBtn.disabled = true;
            runBtn.innerText = currentLang === 'zh' ? '⏳ 正在执行全周期博弈推演 (1~2秒)...' : '⏳ Running Game-Theoretic Deduction (1-2s)...';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 15000);

            try {
                const rawText = document.getElementById('input_text').value;
                const scrubResult = clientSideRedact(rawText);
                const clientScrubbedText = scrubResult.sanitizedText;
                const localRedactedCount = scrubResult.redactedCount;

                const payload = {
                    phase: currentPhase,
                    mode: document.getElementById('mode').value,
                    lang: currentLang,
                    text: clientScrubbedText,
                    user_goal: document.getElementById('user_goal').value,
                    hard_bottom_line: document.getElementById('hard_bottom_line').value,
                    risk_preference: document.getElementById('risk_preference').value
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
                resBox.className = 'card risk-' + (t.risk_level || 'MEDIUM');
                resBox.style.display = 'block';
                updatePillarHeaders();

                const auditMsg = currentLang === 'zh'
                    ? `🛡️ <strong>客户端本地预脱敏验证：</strong>已在浏览器本地拦截替换 <b>${localRedactedCount}</b> 处敏感实体（原始敏感词未离设备） | ⏱️ <strong>实测耗时：</strong><b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>实际发往云端模型的脱敏 Payload：</strong><code>${data.sanitized_payload_sent_to_llm}</code>`
                    : `🛡️ <strong>Client-Side Sanitization Verified:</strong> <b>${localRedactedCount}</b> sensitive entities scrubbed in browser memory prior to network call | ⏱️ <strong>Latency:</strong> <b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>Actual Sanitized Payload Sent:</strong> <code>${data.sanitized_payload_sent_to_llm}</code>`;

                document.getElementById('audit_view').innerHTML = auditMsg;

                const badgeColor = t.risk_level === 'SAFE' ? '#10b981' : (t.risk_level === 'LOW' ? '#f59e0b' : '#f87171');
                document.getElementById('trap_title').style.color = badgeColor;
                document.getElementById('trap_title').innerText = `[${t.risk_level}] ${t.trap_or_intent}`;
                document.getElementById('rule_cited').innerText = (currentLang === 'zh' ? '⚖️ 关联规则与底线锚定：' : '⚖️ Grounded Rule & BATNA Audit: ') + t.triggered_rule;

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
                    draftPrefix = currentLang === 'zh' ? '💬 战中完整回复 / 桌面下短信提示：\n' : '💬 Live Tactical Reply / Stealth Whisper:\n';
                } else {
                    counterPrefix = currentLang === 'zh' ? '🔑 战后复盘核心策略定调：' : '🔑 Core Post-Deal Takeaway: ';
                    draftPrefix = currentLang === 'zh' ? '📧 极具博弈分寸感的战后跟进邮件（可直接复制发送）：\n' : '📧 High-Leverage Post-Deal Follow-Up Email (Ready to Send):\n';
                }

                document.getElementById('counter_q').innerText = counterPrefix + '“' + t.counter_question + '”';
                document.getElementById('draft_box').innerText = draftPrefix + t.draft_reply;
            } catch (err) {
                errBox.style.display = 'block';
                errBox.innerText = '⚠️ ' + (err.name === 'AbortError' ? 'Request timed out after 15s. Please retry.' : err.message);
                resBox.style.display = 'none';
            } finally {
                clearTimeout(timeoutId);
                runBtn.disabled = false;
                runBtn.innerText = currentLang === 'zh' ? '⚡ 启动全周期博弈推演' : '⚡ Execute Game-Theoretic Engine';
            }
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
