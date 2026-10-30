import os
import re
import time
import json
import logging
import http.client
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# 关闭 Werkzeug 默认的请求体日志，确保服务器端不记录敏感内容
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

API_HOST = "generativelanguage.googleapis.com"

# 二次服务端兜底脱敏（覆盖中英文邮箱、电话、合同ID、金额实体）
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

    mode = payload.get("mode", "stream")
    lang_pref = payload.get("lang", "en")
    incoming_text = payload.get("text", "").strip()
    user_goal = payload.get("user_goal", "").strip()
    hard_bottom_line = payload.get("hard_bottom_line", "").strip()
    risk_preference = payload.get("risk_preference", "").strip()

    if not incoming_text:
        return jsonify({"error": "Please enter negotiation text or select a preset case."}), 400

    redaction_result = server_fallback_redact(incoming_text)
    sanitized_text = redaction_result["sanitized_text"]

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not configured in Vercel environment."}), 500

    # 国际化自适应 System Prompt
    system_instruction = f"""You are Consigliere AI (v3.2), a world-class Chief of Staff and Real-Time Game-Theoretic Copilot for commercial negotiations.
You must ground your analysis on the user's specific strategic profile:
- [Core Goal & Budget]: {user_goal}
- [Hard Bottom Lines]: {hard_bottom_line}
- [Risk Tolerance & Vulnerabilities]: {risk_preference}
- [Interaction Channel]: {mode}

CRITICAL RULES:
1. LANGUAGE ADAPTABILITY: If the input or UI language preference is English ('en'), ALL values in your JSON output MUST be in fluent, professional, concise American English. If Chinese ('zh'), output in concise Chinese.
2. NO FALSE POSITIVES: If the counterparty agrees to all terms or acts constructively, set risk_level to "SAFE" and trap_or_intent to "Constructive Alignment".
3. EPISTEMIC RIGOR: Strictly separate Verified Facts, Strategic Inferences, and Unknowns to Probe.
4. RULE GROUNDING: Explicitly cite which goal, budget, or bottom-line clause was triggered or complied with.

Output ONLY a single valid JSON object with these 8 keys (no Markdown wrappers):
{{
  "risk_level": "SAFE, LOW, MEDIUM, or CRITICAL",
  "trap_or_intent": "Name of the cognitive/game-theoretic trap, or 'Constructive Alignment' if safe",
  "triggered_rule": "Direct reference to the specific rule/bottom-line in user's profile",
  "facts_extracted": "[Facts]: Objective terms or verified constraints explicitly stated",
  "strategic_inference": "[Inferences]: Strategic motive, leverage play, or psychological pressure behind the words",
  "unknowns_to_probe": "[Unknowns]: Critical missing variables that must be clarified before committing",
  "counter_question": "Immediate counter-question or tactical prompt to say right now (< 25 words)",
  "draft_reply": "Complete, polite, and strategically sound response draft ready to send"
}}"""

    user_prompt = f"Sanitized Negotiation Input: {sanitized_text}"

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
            "tactical_advice": tactical_output
        })
    except Exception as parse_err:
        return jsonify({"error": f"Failed to parse model JSON: {str(parse_err)}"}), 500

HTML_UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consigliere AI v3.2 — Real-Time Negotiation Copilot</title>
    <style>
        body { background: #090a0f; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; padding: 20px; max-width: 860px; margin: auto; line-height: 1.5; }
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
        .counter { font-size: 17px; color: #facc15; font-weight: bold; margin: 12px 0 8px 0; }
        .meta { font-size: 12px; color: #10b981; background: #064e3b33; padding: 10px; border-radius: 6px; border: 1px solid #05966955; word-break: break-all; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }
        th, td { border: 1px solid #27272a; padding: 8px; text-align: left; }
        th { background: #18181b; color: #94a3b8; }
        @media (max-width: 640px) { .grid-2, .tri-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="header-row">
        <div>
            <h2 style="margin:0 0 4px 0;">⚡ Consigliere AI <span class="badge">PoC v3.2 — Bilingual & Grounded</span></h2>
            <span style="color:#94a3b8; font-size:13px;" id="subtitle_text">Real-Time Game-Theoretic Copilot for Commercial Negotiations</span>
        </div>
        <div class="lang-switch">
            <button type="button" class="lang-btn" id="btn_en" onclick="setLanguage('en')">🇺🇸 English</button>
            <button type="button" class="lang-btn" id="btn_zh" onclick="setLanguage('zh')">🇨🇳 中文</button>
        </div>
    </div>

    <!-- 1. 决策档案配置 -->
    <div class="card">
        <strong id="sec1_title">📂 1. Chief of Staff Decision Grounding (Rules cited in analysis)</strong>
        <div class="grid-2">
            <div>
                <label id="lbl_goal">🎯 Core Goal & Budget:</label>
                <input id="user_goal" value="Secure annual compute supply contract under $1.2M total budget; legal review by Friday." />
            </div>
            <div>
                <label id="lbl_bottom_line">🛑 Hard Bottom Lines:</label>
                <input id="hard_bottom_line" value="Payment terms >= 45 days; maximum discount <= 10%; strict refusal of exclusive lock-in clauses." />
            </div>
        </div>
        <label id="lbl_risk">🧠 Risk Tolerance & Vulnerabilities:</label>
        <input id="risk_preference" value="Conservative; high relationship value; vulnerable to artificial deadlines or promises of future volume." />
    </div>

    <!-- 2. 输入与案例 -->
    <div class="card">
        <strong id="sec2_title">🎙️ 2. Live Negotiation Input (Presets & Client-Side Scrubbing)</strong>
        <div class="preset-row" id="preset_container"></div>
        
        <label id="lbl_mode">Interaction Mode & Voice Language:</label>
        <div class="grid-2">
            <select id="mode">
                <option value="stream">🟢 Client-Side Speech STT + Scrubbing</option>
                <option value="sms">🔒 Stealth Shorthand Trigger (Simulated)</option>
            </select>
            <select id="voice_lang">
                <option value="en-US">🎙️ Microphone: English (US / Global)</option>
                <option value="zh-CN">🎙️ Microphone: 中文 (Mandarin)</option>
            </select>
        </div>

        <label id="lbl_input_text">Counterparty's Statement or Live Transcript:</label>
        <textarea id="input_text" rows="2">Apex Ventures partner John (john@apexvc.com, +1-415-555-0199) demands 45-day exclusivity on Term Sheet #TS-8841 with a 25% valuation cut by 5 PM today, or they walk away from the $5M lead investment.</textarea>
        
        <div class="btn-row">
            <button type="button" id="mic_btn" class="mic-btn" onclick="toggleMic()">🎤 Start Web Speech Input</button>
            <button type="button" id="run_btn" class="primary" onclick="runAgent()">⚡ Execute Strategic Deduction</button>
        </div>
    </div>

    <!-- 3. 输出卡片 -->
    <div id="error_box" class="card" style="display:none; border-color:#ef4444; color:#f87171;"></div>
    <div id="result" class="card" style="display:none;">
        <div class="meta" id="audit_view"></div>
        <h3 id="trap_title" style="margin: 12px 0 4px 0;"></h3>
        <div id="rule_cited" style="font-size:13px; color:#38bdf8; font-weight:600; margin-bottom:8px;"></div>

        <div class="tri-grid">
            <div class="tri-box">
                <div class="tri-title" id="t_facts">📌 Verified Facts</div>
                <div id="facts_box"></div>
            </div>
            <div class="tri-box">
                <div class="tri-title" id="t_inferences">♟️ Strategic Inferences</div>
                <div id="inference_box"></div>
            </div>
            <div class="tri-box">
                <div class="tri-title" id="t_unknowns">❓ Unknowns to Probe</div>
                <div id="unknowns_box"></div>
            </div>
        </div>

        <div class="counter" id="counter_q"></div>
        <div style="background:#18181b; border:1px solid #3f3f46; padding:10px; border-radius:6px; font-size:13px;" id="draft_box"></div>
    </div>

    <!-- 4. 边界说明与迭代记录 -->
    <div class="card">
        <strong>🔍 3. Verifiable Privacy Architecture & Engineering Iterations</strong>
        <p style="font-size:12px; color:#94a3b8; margin:6px 0;" id="privacy_desc">
            • <strong>Client-Side Scrubbing:</strong> Press <code>F12</code> to open DevTools Network tab. Emails, phone numbers, contract IDs, and valuation values are scrubbed in <strong>browser JavaScript before network transmission</strong>.<br>
            • <strong>Iteration Log (v1.0 → v3.2):</strong>
        </p>
        <table>
            <thead>
                <tr>
                    <th>Version</th>
                    <th>Observed Failure / Tester Feedback</th>
                    <th>Engineering Fix & Outcome</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>v1.0 → v2.0</strong></td>
                    <td>100% false-alarm rate: even standard cordial emails flagged as high risk.</td>
                    <td>Added <code>SAFE</code> baseline & system prompt rewarding constructive alignment.</td>
                </tr>
                <tr>
                    <td><strong>v2.0 → v3.0</strong></td>
                    <td>Single-line response was too shallow; testers mixed up stated facts vs. AI guesses.</td>
                    <td>Restructured schema into 3 boxes (Facts, Inferences, Unknowns) + copy-paste reply draft.</td>
                </tr>
                <tr>
                    <td><strong>v3.0 → v3.2</strong></td>
                    <td>Speech recognition was hardcoded to Chinese; Gemini 2.5 thinking caused latency timeouts.</td>
                    <td>Implemented native HTTPS connection with <code>thinkingBudget: 0</code> (1.5s latency) + bilingual auto-detection.</td>
                </tr>
            </tbody>
        </table>
    </div>

    <script>
        let currentLang = 'en';

        const PRESETS = {
            en: {
                trap: "Apex Ventures partner John (john@apexvc.com, +1-415-555-0199) demands 45-day exclusivity on Term Sheet #TS-8841 with a 25% valuation cut by 5 PM today, or they walk away from the $5M lead investment.",
                probe: "Procurement Director Dave from CloudCorp: 'Internal approval is taking longer. Can you reduce payment terms from 45 to 15 days on this $1.1M deal? In return, we'll give you preferred vendor status next quarter.'",
                safe: "Partner Sarah confirmed: 'We reviewed agreement #AG-2026-9 and fully accept your net-45 payment terms and standard pricing without exclusivity. Our legal team will send the countersigned copy this afternoon.'"
            },
            zh: {
                trap: "华星科技王总（wang@huaxing.com, 13800138000）要求今天下午5点前签合同 #HX-9921，必须降价 25% 且签独家排他，否则取消明年 500 万美金订单。",
                probe: "李总发来消息：我们宏达集团内部审批比较慢，这次 110 万的采购能不能先把账期缩短到 15 天？只要这单顺利，下个季度我们把华南区业务全交给你。",
                safe: "张总确认：我们已经审核完合同 #HX-8802，完全同意贵方 60 天账期和标准报价（无排他条款），法务今天下午会把盖章件发到您的邮箱。"
            }
        };

        const PROFILES = {
            en: {
                goal: "Secure annual compute supply contract under $1.2M total budget; legal review by Friday.",
                bottom: "Payment terms >= 45 days; maximum discount <= 10%; strict refusal of exclusive lock-in clauses.",
                risk: "Conservative; high relationship value; vulnerable to artificial deadlines or promises of future volume."
            },
            zh: {
                goal: "拿下年度算力供应合同，目标总价控制在 120 万以内，本周五前完成法务初审。",
                bottom: "账期绝不低于 45 天；降价幅度不超过 10%；绝不接受独家排他性条款。",
                risk: "稳健偏好；重视长期合作关系，当对方抛出‘限时最后通牒’或‘明年大订单画饼’时容易焦虑让步。"
            }
        };

        function setLanguage(lang) {
            currentLang = lang;
            document.getElementById('btn_en').className = 'lang-btn' + (lang === 'en' ? ' active' : '');
            document.getElementById('btn_zh').className = 'lang-btn' + (lang === 'zh' ? ' active' : '');

            document.getElementById('user_goal').value = PROFILES[lang].goal;
            document.getElementById('hard_bottom_line').value = PROFILES[lang].bottom;
            document.getElementById('risk_preference').value = PROFILES[lang].risk;
            document.getElementById('voice_lang').value = lang === 'en' ? 'en-US' : 'zh-CN';

            renderPresets();
            loadPreset('trap');

            if (lang === 'zh') {
                document.getElementById('subtitle_text').innerText = "商业谈判实时博弈军师与首席幕僚 (内置中英双语自适应)";
                document.getElementById('sec1_title').innerText = "📂 1. 首席幕僚决策档案（分析时将显式引用以下规则）";
                document.getElementById('lbl_goal').innerText = "🎯 核心目标与预算 (Goal & Budget)：";
                document.getElementById('lbl_bottom_line').innerText = "🛑 绝对底线 (Hard Bottom Lines)：";
                document.getElementById('lbl_risk').innerText = "🧠 风险偏好与性格盲区 (Risk Preference & Vulnerability)：";
                document.getElementById('sec2_title').innerText = "🎙️ 2. 战中实时输入（支持一键加载正反测试集 & 浏览器本地预脱敏）";
                document.getElementById('lbl_mode').innerText = "交互模式与听音语言：";
                document.getElementById('lbl_input_text').innerText = "对方实时话术 或 听音转写结果：";
                document.getElementById('mic_btn').innerText = "🎤 浏览器本地语音输入";
                document.getElementById('run_btn').innerText = "⚡ 执行规则推演与事实拆解";
                document.getElementById('t_facts').innerText = "📌 客观事实 (Verified Facts)";
                document.getElementById('t_inferences').innerText = "♟️ 博弈推断 (Strategic Inferences)";
                document.getElementById('t_unknowns').innerText = "❓ 未知盲区 (Unknowns to Probe)";
            } else {
                document.getElementById('subtitle_text').innerText = "Real-Time Game-Theoretic Copilot for High-Stakes Negotiations";
                document.getElementById('sec1_title').innerText = "📂 1. Chief of Staff Decision Grounding (Rules cited in analysis)";
                document.getElementById('lbl_goal').innerText = "🎯 Core Goal & Budget:";
                document.getElementById('lbl_bottom_line').innerText = "🛑 Hard Bottom Lines:";
                document.getElementById('lbl_risk').innerText = "🧠 Risk Tolerance & Vulnerabilities:";
                document.getElementById('sec2_title').innerText = "🎙️ 2. Live Negotiation Input (Presets & Client-Side Scrubbing)";
                document.getElementById('lbl_mode').innerText = "Interaction Mode & Voice Language:";
                document.getElementById('lbl_input_text').innerText = "Counterparty's Statement or Live Transcript:";
                document.getElementById('mic_btn').innerText = "🎤 Start Web Speech Input";
                document.getElementById('run_btn').innerText = "⚡ Execute Strategic Deduction";
                document.getElementById('t_facts').innerText = "📌 Verified Facts";
                document.getElementById('t_inferences').innerText = "♟️ Strategic Inferences";
                document.getElementById('t_unknowns').innerText = "❓ Unknowns to Probe";
            }
        }

        function renderPresets() {
            const container = document.getElementById('preset_container');
            if (currentLang === 'zh') {
                container.innerHTML = `
                    <button type="button" class="preset-btn" onclick="loadPreset('trap')">🔥 案例 1：高危复合陷阱（压价+排他）</button>
                    <button type="button" class="preset-btn" onclick="loadPreset('probe')">⚠️ 案例 2：隐蔽画饼试探（缩短账期）</button>
                    <button type="button" class="preset-btn" onclick="loadPreset('safe')">✅ 案例 3：良性无风险沟通（验证不误报）</button>
                `;
            } else {
                container.innerHTML = `
                    <button type="button" class="preset-btn" onclick="loadPreset('trap')">🔥 Case 1: High-Stakes Trap (Price Cut + Lock-in)</button>
                    <button type="button" class="preset-btn" onclick="loadPreset('probe')">⚠️ Case 2: Bait & Switch Probe (Payment Terms)</button>
                    <button type="button" class="preset-btn" onclick="loadPreset('safe')">✅ Case 3: Benign Alignment (Zero False Alarm)</button>
                `;
            }
        }

        function loadPreset(key) {
            document.getElementById('input_text').value = PRESETS[currentLang][key];
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
                alert(currentLang === 'zh' ? "浏览器不支持 Web Speech API，请使用 Chrome/Safari 或输入文字。" : "Browser does not support Web Speech API. Please use Chrome/Safari or type text.");
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
                    document.getElementById('mic_btn').innerText = currentLang === 'zh' ? "🎤 浏览器本地语音输入" : "🎤 Start Web Speech Input";
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
            runBtn.innerText = currentLang === 'zh' ? '⏳ 正在执行规则推演 (约1~2秒)...' : '⏳ Deducting Strategy (1-2s)...';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 15000);

            try {
                const rawText = document.getElementById('input_text').value;
                const scrubResult = clientSideRedact(rawText);
                const clientScrubbedText = scrubResult.sanitizedText;
                const localRedactedCount = scrubResult.redactedCount;

                const payload = {
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

                const auditMsg = currentLang === 'zh'
                    ? `🛡️ <strong>客户端本地预脱敏验证：</strong>已在浏览器本地拦截替换 <b>${localRedactedCount}</b> 处敏感实体（原始敏感词未离设备） | ⏱️ <strong>端到端耗时：</strong><b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>实际离开浏览器并发往模型的 Payload：</strong><code>${data.sanitized_payload_sent_to_llm}</code>`
                    : `🛡️ <strong>Client-Side Sanitization Verified:</strong> <b>${localRedactedCount}</b> sensitive entities scrubbed in browser memory prior to transmission | ⏱️ <strong>Latency:</strong> <b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>📤 <strong>Actual Payload Transmitted:</strong> <code>${data.sanitized_payload_sent_to_llm}</code>`;

                document.getElementById('audit_view').innerHTML = auditMsg;

                const badgeColor = t.risk_level === 'SAFE' ? '#10b981' : (t.risk_level === 'LOW' ? '#f59e0b' : '#f87171');
                document.getElementById('trap_title').style.color = badgeColor;
                document.getElementById('trap_title').innerText = `[${t.risk_level}] ${t.trap_or_intent}`;
                document.getElementById('rule_cited').innerText = (currentLang === 'zh' ? '⚖️ 关联底线引用：' : '⚖️ Rule Grounded: ') + t.triggered_rule;

                document.getElementById('facts_box').innerText = t.facts_extracted;
                document.getElementById('inference_box').innerText = t.strategic_inference;
                document.getElementById('unknowns_box').innerText = t.unknowns_to_probe;

                document.getElementById('counter_q').innerText = (currentLang === 'zh' ? '🎯 建议当场反问：“' : '🎯 Suggested Live Counter: "') + t.counter_question + '"';
                document.getElementById('draft_box').innerText = (currentLang === 'zh' ? '✉️ 完整回复草稿：' : '✉️ Full Response Draft: ') + t.draft_reply;
            } catch (err) {
                errBox.style.display = 'block';
                errBox.innerText = '⚠️ ' + (err.name === 'AbortError' ? 'Request timed out after 15s. Please retry.' : err.message);
                resBox.style.display = 'none';
            } finally {
                clearTimeout(timeoutId);
                runBtn.disabled = false;
                runBtn.innerText = currentLang === 'zh' ? '⚡ 执行规则推演与事实拆解' : '⚡ Execute Strategic Deduction';
            }
        }

        // 自动根据系统语言初始化（若是英文操作系统则直接默认英文，否则默认中文）
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
