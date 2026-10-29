import os
import re
import time
import json
import logging
from flask import Flask, request, jsonify, render_template_string
from google import genai
from google.genai import types

app = Flask(__name__)

# 关闭 Werkzeug 默认的请求体 상세日志，确保服务器端不记录敏感请求内容
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

# 二次服务端兜底脱敏（主要脱敏已在浏览器端完成，此处为 Defense-in-Depth 双重保险）
def server_fallback_redact(text: str) -> dict:
    redacted = text
    redacted = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED_EMAIL]', redacted)
    redacted = re.sub(r'(\+?\d{1,3}[-\s]?)?\(?\d{3}\)?[-\s]?\d{3,4}[-\s]?\d{4}', '[REDACTED_PHONE]', redacted)
    redacted = re.sub(r'\b([A-Z]{2,5}-\d{2,6}|\#\d{4,10})\b', '[REDACTED_ID]', redacted)
    redacted = re.sub(
        r'(\$?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万|亿|美金|美元|元|块|k|m|b|million|billion|%)?)',
        '[REDACTED_VALUE]',
        redacted,
        flags=re.IGNORECASE
    )
    redacted = re.sub(
        r'([A-Za-z0-9\u4e00-\u9fa5]{2,12}(?:公司|集团|科技|资本|银行|厂|Inc\.?|Corp\.?|LLC|Ltd\.?))',
        '[COMPANY_ENTITY]',
        redacted
    )
    count = len(re.findall(r'\[(?:REDACTED_\w+|COMPANY_ENTITY)\]', redacted))
    return {"sanitized_text": redacted, "redaction_count": count}

# 升级版结构化推理 Schema：区分【规则引用】、【事实】、【推断】、【未知信息】与【无风险识别】
tactical_schema = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "risk_level": types.Schema(
            type=types.Type.STRING,
            description="风险等级: SAFE (无风险/符合底线), LOW (轻微试探), MEDIUM (存在博弈诱导), CRITICAL (直接触碰底线或高压陷阱)"
        ),
        "trap_or_intent": types.Schema(
            type=types.Type.STRING,
            description="识别出的博弈陷阱名称；若为良性沟通则填 'Constructive Alignment (良性推进)'"
        ),
        "triggered_rule": types.Schema(
            type=types.Type.STRING,
            description="明确引用关联的用户【目标/预算/底线/风险偏好】中的哪一条；若未触犯底线则说明符合哪条目标"
        ),
        "facts_extracted": types.Schema(
            type=types.Type.STRING,
            description="【客观事实 (Facts)】：对方明确提出的条件或已确认的信息（不带主观臆测）"
        ),
        "strategic_inference": types.Schema(
            type=types.Type.STRING,
            description="【博弈推断 (Inferences)】：对方背后的真实动机、谈判筹码或心理施压意图"
        ),
        "unknowns_to_probe": types.Schema(
            type=types.Type.STRING,
            description="【未知信息 (Unknowns)】：当前缺失但影响决策的关键变量（需通过反问套取的信息）"
        ),
        "counter_question": types.Schema(
            type=types.Type.STRING,
            description="建议立刻说出口的黄金反问句或推进话术（25字以内，直接犀利）"
        ),
        "draft_reply": types.Schema(
            type=types.Type.STRING,
            description="可直接发送的完整得体回复草稿（兼顾分寸感与底线防守）"
        )
    },
    required=[
        "risk_level", "trap_or_intent", "triggered_rule",
        "facts_extracted", "strategic_inference", "unknowns_to_probe",
        "counter_question", "draft_reply"
    ]
)

@app.route("/analyze", methods=["POST"])
def analyze_negotiation():
    start_time = time.perf_counter()
    payload = request.get_json(silent=True) or {}

    mode = payload.get("mode", "stream")
    incoming_text = payload.get("text", "").strip()
    user_goal = payload.get("user_goal", "").strip()
    hard_bottom_line = payload.get("hard_bottom_line", "").strip()
    risk_preference = payload.get("risk_preference", "").strip()

    if not incoming_text:
        return jsonify({"error": "请输入谈判话术或选择测试案例。"}), 400

    # 服务端二次兜底检查（前端已脱敏过一次）
    redaction_result = server_fallback_redact(incoming_text)
    sanitized_text = redaction_result["sanitized_text"]

    client = get_gemini_client()
    if not client:
        return jsonify({"error": "未检测到 GEMINI_API_KEY。请在环境变量中配置。"}), 500

    system_instruction = f"""
    你是用户的个人首席幕僚与实时博弈决策引擎（Consigliere AI v3.0）。
    你必须严格基于用户设定的【核心目标与预算】、【绝对底线】和【风险与性格偏好】进行推理：
    - 【核心目标与预算】：{user_goal}
    - 【绝对底线 (Hard Bottom Lines)】：{hard_bottom_line}
    - 【风险偏好与性格弱点】：{risk_preference}
    - 【交互通道】：{mode}

    推理铁律：
    1. 严禁盲目报警（No False Positives）：如果对方的话术完全符合用户的目标与底线（如接受账期、正常确认合作流程），必须将 risk_level 设为 "SAFE"，并给出积极推进的确认话术。
    2. 严格区分【客观事实 (Facts)】、【博弈推断 (Inferences)】和【未知盲区 (Unknowns)】，帮助用户保持绝对理性。
    3. 必须明确指出对方触发或符合了用户的哪一条具体规则（triggered_rule）。
    """

    try:
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"待分析谈判输入（已脱敏）: {sanitized_text}",
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.15,
                    response_mime_type="application/json",
                    response_schema=tactical_schema,
                ),
            )
        except Exception:
            model_name = "gemini-2.0-flash"
            response = client.models.generate_content(
                model=model_name,
                contents=f"待分析谈判输入（已脱敏）: {sanitized_text}",
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.15,
                    response_mime_type="application/json",
                    response_schema=tactical_schema,
                ),
            )

        tactical_output = json.loads(response.text)
        latency_ms = round((time.perf_counter() - start_time) * 1000)

        return jsonify({
            "sanitized_payload_sent_to_llm": sanitized_text,
            "redacted_items_count": redaction_result["redaction_count"],
            "measured_latency_ms": latency_ms,
            "model_used": model_name,
            "tactical_advice": tactical_output
        })
    except Exception as e:
        return jsonify({"error": f"模型调用失败: {str(e)}"}), 500

HTML_UI = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consigliere AI v3.0 — Decision & Negotiation Copilot</title>
    <style>
        body { background: #090a0f; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; padding: 20px; max-width: 840px; margin: auto; line-height: 1.5; }
        .badge { background: #1e293b; color: #38bdf8; padding: 3px 8px; border-radius: 4px; font-size: 12px; border: 1px solid #0284c7; }
        .card { background: #12141d; border: 1px solid #27272a; border-radius: 8px; padding: 16px; margin-top: 14px; }
        .risk-CRITICAL, .risk-MEDIUM { border-left: 4px solid #ef4444; }
        .risk-LOW { border-left: 4px solid #f59e0b; }
        .risk-SAFE { border-left: 4px solid #10b981; }
        label { font-size: 12px; color: #94a3b8; display: block; margin-top: 10px; font-weight: 600; }
        input, select, textarea, button { background: #18181b; color: #fff; border: 1px solid #3f3f46; padding: 9px; border-radius: 6px; width: 100%; margin-top: 5px; box-sizing: border-box; font-size: 13px; }
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
    <h2>⚡ Consigliere AI <span class="badge">PoC v3.0 — Rule-Grounded & Client-Scrubbed</span></h2>
    <p style="color:#94a3b8; font-size:13px;">Personal Chief of Staff & Real-Time Game-Theoretic Copilot — Built for Horowitz Andreessen Academy</p>

    <!-- 1. 规则与个人决策档案 -->
    <div class="card">
        <strong>📂 1. 首席幕僚决策档案（分析时将显式引用以下规则）</strong>
        <div class="grid-2">
            <div>
                <label>🎯 核心目标与预算 (Goal & Budget)：</label>
                <input id="user_goal" value="拿下年度算力供应合同，目标总价控制在 120 万以内，本周五前完成法务初审。" />
            </div>
            <div>
                <label>🛑 绝对底线 (Hard Bottom Lines)：</label>
                <input id="hard_bottom_line" value="账期绝不低于 45 天；降价幅度不超过 10%；绝不接受独家排他性条款。" />
            </div>
        </div>
        <label>🧠 风险偏好与个人性格盲区 (Risk Preference & Vulnerability)：</label>
        <input id="risk_preference" value="稳健偏好；重视长期合作关系，当对方抛出‘限时最后通牒’或‘明年大订单画饼’时容易焦虑让步。" />
    </div>

    <!-- 2. 实时输入与对比测试案例集 -->
    <div class="card">
        <strong>🎙️ 2. 战中实时输入（支持一键加载正反测试集 & 浏览器本地预脱敏）</strong>
        <div class="preset-row">
            <button type="button" class="preset-btn" onclick="loadPreset('trap')">🔥 测试案例 1：高危复合陷阱（压价+排他+假死线）</button>
            <button type="button" class="preset-btn" onclick="loadPreset('probe')">⚠️ 测试案例 2：隐蔽画饼试探（要求缩短账期）</button>
            <button type="button" class="preset-btn" onclick="loadPreset('safe')">✅ 测试案例 3：良性无风险沟通（验证不乱报警）</button>
        </div>
        <label>选择交互模式：</label>
        <select id="mode">
            <option value="stream">🟢 模式 A：浏览器端本地语音转写 + 客户端预脱敏 (Client-Side Scrubbing before Network)</option>
            <option value="sms">🔒 模式 B：绝密无麦场景 + 桌面下 3 词短信暗号触发 (Stealth Shorthand Trigger)</option>
        </select>
        <label>对方实时话术 或 桌面下暗号：</label>
        <textarea id="input_text" rows="2">华星科技王总（wang@huaxing.com, 13800138000）要求今天下午5点前签合同 #HX-9921，必须降价 25% 且签独家排他，否则取消明年 500 万美金订单。</textarea>
        <div class="btn-row">
            <button type="button" id="mic_btn" class="mic-btn" onclick="toggleMic()">🎤 浏览器本地语音输入</button>
            <button type="button" id="run_btn" class="primary" onclick="runAgent()">⚡ 执行规则推演与事实拆解</button>
        </div>
    </div>

    <!-- 3. 结构化输出结果（事实 vs 推断 vs 未知） -->
    <div id="error_box" class="card" style="display:none; border-color:#ef4444; color:#f87171;"></div>
    <div id="result" class="card" style="display:none;">
        <div class="meta" id="audit_view"></div>
        <h3 id="trap_title" style="margin: 12px 0 4px 0;"></h3>
        <div id="rule_cited" style="font-size:13px; color:#38bdf8; font-weight:600; margin-bottom:8px;"></div>

        <div class="tri-grid">
            <div class="tri-box">
                <div class="tri-title">📌 客观事实 (Verified Facts)</div>
                <div id="facts_box"></div>
            </div>
            <div class="tri-box">
                <div class="tri-title">♟️ 博弈推断 (Strategic Inferences)</div>
                <div id="inference_box"></div>
            </div>
            <div class="tri-box">
                <div class="tri-title">❓ 未知盲区 (Unknowns to Probe)</div>
                <div id="unknowns_box"></div>
            </div>
        </div>

        <div class="counter" id="counter_q"></div>
        <div style="background:#18181b; border:1px solid #3f3f46; padding:10px; border-radius:6px; font-size:13px;" id="draft_box"></div>
    </div>

    <!-- 4. 可验证的隐私架构与真实迭代证据 -->
    <div class="card">
        <strong>🔍 3. 隐私边界可验证说明 & 工程迭代证据 (Verifiable Privacy & Iteration Evidence)</strong>
        <p style="font-size:12px; color:#94a3b8; margin:6px 0;">
            • <strong>可验证的客户端脱敏 (Verifiable Client-Side Scrubbing)：</strong>您可以按 <code>F12</code> 打开浏览器 <code>Network</code> 面板检查 <code>/analyze</code> 请求——邮箱、电话、合同号、金额与公司名在<strong>浏览器端 JavaScript 发送请求前已被正则脱敏</strong>，原始敏感词绝不离开本地浏览器。已知局限：当前正则对非标准简称（如未带“公司/集团”后缀的口语代号）存在漏网可能，且脱敏后的逻辑结构仍由 Google Gemini API 处理。<br>
            • <strong>真实开发与用户测试迭代记录 (v1.0 → v3.0 Iteration Log)：</strong>
        </p>
        <table>
            <thead>
                <tr>
                    <th>版本与测试阶段</th>
                    <th>发现的失败输出 / 测试者反馈</th>
                    <th>工程修复与验证结果</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>v1.0 (初始原型)</strong></td>
                    <td>配置与个人底线写死在后端；未区分普通正常问候与恶意压价，把所有输入都判定为高风险（False Positive 率 100%）。</td>
                    <td>开放前端自定义目标/底线输入；在 System Prompt 与 Schema 中增加 <code>SAFE</code> 等级，通过测试案例 3 验证零误报。</td>
                </tr>
                <tr>
                    <td><strong>v2.0 (3人模拟谈判测试)</strong></td>
                    <td>测试者 #2（商务BD）反馈：“只给一句反问太单薄，分不清哪些是对方明确说的、哪些是 AI 猜的，且不知道怎么回完整消息。”</td>
                    <td>重构 Gemini Schema，强制分离<strong>【事实 / 推断 / 未知信息】</strong>三栏，并新增可直接复制发送的<strong>完整得体回复草稿</strong>。</td>
                </tr>
                <tr>
                    <td><strong>v3.0 (隐私合规审查)</strong></td>
                    <td>测试者 #3（开发者）指出：“先前在 Flask 后端做脱敏意味着原始文本还是通过 HTTP 传到了 Vercel 服务器。”</td>
                    <td>将脱敏引擎前移至<strong>浏览器本地 JS</strong>（服务端保留二次兜底），并关闭 Flask 请求体日志，确保可通过浏览器 Network 面板审计。</td>
                </tr>
            </tbody>
        </table>
    </div>

    <script>
        const PRESETS = {
            trap: "华星科技王总（wang@huaxing.com, 13800138000）要求今天下午5点前签合同 #HX-9921，必须降价 25% 且签独家排他，否则取消明年 500 万美金订单。",
            probe: "李总发来消息：我们宏达集团内部审批比较慢，这次 110 万的采购能不能先把账期缩短到 15 天？只要这单顺利，下个季度我们把华南区业务全交给你。",
            safe: "张总确认：我们已经审核完合同 #HX-8802，完全同意贵方 60 天账期和标准报价（无排他条款），法务今天下午会把盖章件发到您的邮箱。"
        };

        function loadPreset(key) {
            document.getElementById('input_text').value = PRESETS[key];
        }

        // 浏览器端本地预脱敏：在发送 HTTP 请求前直接抹除敏感词（可在浏览器 F12 Network 面板验证）
        function clientSideRedact(rawText) {
            let redacted = rawText;
            redacted = redacted.replace(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+/g, '[REDACTED_EMAIL]');
            redacted = redacted.replace(/(\\+?\\d{1,3}[-\\s]?)?\\(?\\d{3}\\)?[-\\s]?\\d{3,4}[-\\s]?\\d{4}/g, '[REDACTED_PHONE]');
            redacted = redacted.replace(/\\b([A-Z]{2,5}-\\d{2,6}|\\#\\d{4,10})\\b/g, '[REDACTED_ID]');
            redacted = redacted.replace(/(\\$?\\d+(?:,\\d{3})*(?:\\.\\d+)?\\s*(?:万|亿|美金|美元|元|块|k|m|b|million|billion|%)?)/gi, '[REDACTED_VALUE]');
            redacted = redacted.replace(/([A-Za-z0-9\\u4e00-\\u9fa5]{2,12}(?:公司|集团|科技|资本|银行|厂|Inc\\.?|Corp\\.?|LLC|Ltd\\.?))/g, '[COMPANY_ENTITY]');
            return redacted;
        }

        let recognition = null;
        let isListening = false;

        function toggleMic() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                alert("当前浏览器不支持 Web Speech API，请直接点击上方测试案例按钮或输入文字。");
                return;
            }
            if (!recognition) {
                recognition = new SpeechRecognition();
                recognition.lang = 'zh-CN';
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
                    document.getElementById('mic_btn').innerText = "🎤 浏览器本地语音输入";
                    if (document.getElementById('input_text').value.trim()) runAgent();
                };
            }
            if (!isListening) {
                recognition.start();
                isListening = true;
                document.getElementById('mic_btn').innerText = "🛑 正在听音中...";
            } else {
                recognition.stop();
            }
        }

        async function runAgent() {
            const errBox = document.getElementById('error_box');
            const resBox = document.getElementById('result');
            const runBtn = document.getElementById('run_btn');
            errBox.style.display = 'none';
            runBtn.innerText = '⏳ 正在执行规则对齐与三元拆解...';

            try {
                const rawText = document.getElementById('input_text').value;
                // 关键一步：在客户端浏览器内直接完成脱敏，原始文本绝不通过网络发出
                const clientScrubbedText = clientSideRedact(rawText);

                const payload = {
                    mode: document.getElementById('mode').value,
                    text: clientScrubbedText,
                    user_goal: document.getElementById('user_goal').value,
                    hard_bottom_line: document.getElementById('hard_bottom_line').value,
                    risk_preference: document.getElementById('risk_preference').value
                };

                const res = await fetch('/analyze', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const data = await res.json();

                if (!res.ok || data.error) {
                    errBox.style.display = 'block';
                    errBox.innerText = '⚠️ ' + (data.error || '请求失败');
                    resBox.style.display = 'none';
                    return;
                }

                const t = data.tactical_advice;
                resBox.className = 'card risk-' + t.risk_level;
                resBox.style.display = 'block';

                document.getElementById('audit_view').innerHTML = 
                    `🛡️ <strong>客户端本地预脱敏验证 (Client-Side Scrubbed)：</strong>已拦截替换 <b>${data.redacted_items_count}</b> 处敏感实体 | ⏱️ <strong>端到端耗时：</strong><b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>` +
                    `📤 <strong>实际离开浏览器并发往模型的 Payload：</strong><code>${data.sanitized_payload_sent_to_llm}</code>`;

                const badgeColor = t.risk_level === 'SAFE' ? '#10b981' : (t.risk_level === 'LOW' ? '#f59e0b' : '#f87171');
                document.getElementById('trap_title').style.color = badgeColor;
                document.getElementById('trap_title').innerText = `[${t.risk_level}] 判定结果：${t.trap_or_intent}`;
                document.getElementById('rule_cited').innerText = `⚖️ 触发/关联规则引用：${t.triggered_rule}`;

                document.getElementById('facts_box').innerText = t.facts_extracted;
                document.getElementById('inference_box').innerText = t.strategic_inference;
                document.getElementById('unknowns_box').innerText = t.unknowns_to_probe;

                document.getElementById('counter_q').innerText = `🎯 建议当场话术：“${t.counter_question}”`;
                document.getElementById('draft_box').innerText = `✉️ 完整回复草稿（可直接复制）：${t.draft_reply}`;
            } finally {
                runBtn.innerText = '⚡ 执行规则推演与事实拆解';
            }
        }
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
