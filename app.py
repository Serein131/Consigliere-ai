import os
import re
import gc
import time
import json
from flask import Flask, request, jsonify, render_template_string
from google import genai
from google.genai import types

app = Flask(__name__)

# 1. 初始化 Google GenAI 客户端（使用你从 Google AI Studio 获取的免费 Key）
def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

# 2. 6 维本地隐私脱敏引擎（拦截邮箱、电话、合同号、金额、比例、公司名）
def local_privacy_redact(raw_text: str) -> dict:
    redacted = raw_text
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
    return {
        "sanitized_text": redacted,
        "redaction_count": len(re.findall(r'\[(?:REDACTED_\w+|COMPANY_ENTITY)\]', redacted))
    }

# 3. 定义 Gemini 结构化输出 Schema (Function Calling)
tactical_schema = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "risk_level": types.Schema(type=types.Type.STRING, description="风险等级: LOW, MEDIUM, CRITICAL"),
        "trap_type": types.Schema(type=types.Type.STRING, description="识别出的博弈陷阱名称"),
        "psychological_alert": types.Schema(type=types.Type.STRING, description="结合用户性格弱点的针对性提醒"),
        "counter_question": types.Schema(type=types.Type.STRING, description="建议立刻说出口的反问句（20字以内）"),
        "sms_brief": types.Schema(type=types.Type.STRING, description="模拟发往手机的极简短信提示")
    },
    required=["risk_level", "trap_type", "psychological_alert", "counter_question", "sms_brief"]
)

@app.route("/analyze", methods=["POST"])
def analyze_negotiation():
    start_time = time.perf_counter()
    payload = request.get_json(silent=True) or {}

    mode = payload.get("mode", "stream")
    raw_input = payload.get("text", "").strip()
    user_profile = payload.get("user_profile", "").strip()
    hard_bottom_line = payload.get("hard_bottom_line", "").strip()

    if not raw_input:
        return jsonify({"error": "请输入谈判话术或点击麦克风说话。"}), 400

    # 执行本地正则脱敏
    redaction_result = local_privacy_redact(raw_input)
    sanitized_text = redaction_result["sanitized_text"]
    del raw_input
    gc.collect()

    client = get_gemini_client()
    if not client:
        return jsonify({"error": "未检测到 GEMINI_API_KEY。请在环境变量或 Vercel 设定中配置。"}), 500

    system_instruction = f"""
    你是用户的个人首席幕僚与实时博弈军师（Consigliere AI）。
    【用户自定义性格盲区】：{user_profile}
    【当前会议绝对底线】：{hard_bottom_line}
    【当前交互模式】：{mode}
    请基于已脱敏的文本进行博弈推演，识别对方话术陷阱或用户妥协风险，并严格按要求输出结构化战术。
    """

    try:
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        response = client.models.generate_content(
            model=model_name,
            contents=f"已脱敏输入: {sanitized_text}",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
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
        return jsonify({"error": f"Gemini 模型调用失败: {str(e)}"}), 500

HTML_UI = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consigliere AI — Chief of Staff & Negotiation Copilot</title>
    <style>
        body { background: #090a0f; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, monospace; padding: 20px; max-width: 780px; margin: auto; line-height: 1.5; }
        .badge { background: #1e293b; color: #38bdf8; padding: 3px 8px; border-radius: 4px; font-size: 12px; border: 1px solid #0284c7; }
        .card { background: #12141d; border: 1px solid #27272a; border-radius: 8px; padding: 16px; margin-top: 14px; }
        .critical { border-left: 4px solid #ef4444; }
        label { font-size: 13px; color: #94a3b8; display: block; margin-top: 10px; }
        input, select, textarea, button { background: #18181b; color: #fff; border: 1px solid #3f3f46; padding: 10px; border-radius: 6px; width: 100%; margin-top: 6px; box-sizing: border-box; font-size: 14px; }
        .btn-row { display: flex; gap: 10px; margin-top: 12px; }
        button { background: #2563eb; border: none; font-weight: bold; cursor: pointer; }
        button.mic-btn { background: #059669; }
        button.mic-active { background: #dc2626; animation: pulse 1.2s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }
        .counter { font-size: 19px; color: #facc15; font-weight: bold; margin: 12px 0; }
        .meta { font-size: 12px; color: #10b981; background: #064e3b33; padding: 8px; border-radius: 4px; border: 1px solid #05966955; }
        .note { font-size: 12px; color: #64748b; margin-top: 16px; border-top: 1px solid #1e293b; padding-top: 10px; }
    </style>
</head>
<body>
    <h2>⚡ Consigliere AI <span class="badge">Google Gemini Powered</span></h2>
    <p style="color:#94a3b8; font-size:13px;">Personal Chief of Staff & Real-Time Game-Theoretic Copilot (Native Gemini SDK)</p>

    <div class="card">
        <strong>📂 1. 首席幕僚记忆库（可自由修改测试）</strong>
        <label>我的性格盲区 / 历史妥协习惯 (Behavioral Vulnerability Profile)：</label>
        <input id="user_profile" value="重视长期合作关系；当对方抛出‘战略大饼’或‘限时最后通牒’时容易焦虑并让步。" />
        <label>本场谈判绝对底线 (Hard Bottom Lines)：</label>
        <input id="hard_bottom_line" value="账期绝不低于 45 天；降价幅度不超过 10%；绝不接受排他性条款。" />
    </div>

    <div class="card">
        <strong>🎙️ 2. 战中实时输入（支持浏览器本地麦克风转写 & 短信暗号）</strong>
        <label>选择交互模式：</label>
        <select id="mode">
            <option value="stream">🟢 模式 A：浏览器本地语音转文字 + 敏感实体脱敏 (Client-Side STT + Scrubbing)</option>
            <option value="sms">🔒 模式 B：绝密无麦 + 桌面下 3 词短信暗号模拟 (Stealth SMS Trigger)</option>
        </select>
        <label>对方实时话术 或 桌面下短信暗号：</label>
        <textarea id="input_text" rows="2">华星科技王总（wang@huaxing.com, 13800138000）要求今天下午5点前签合同 #HX-9921，必须降价 25% 且签独家排他，否则取消明年 500 万美金订单。</textarea>
        <div class="btn-row">
            <button type="button" id="mic_btn" class="mic-btn" onclick="toggleMic()">🎤 开启浏览器实时语音识别</button>
            <button type="button" id="run_btn" onclick="runAgent()">⚡ 触发实时博弈干预</button>
        </div>
    </div>

    <div id="error_box" class="card" style="display:none; border-color:#ef4444; color:#f87171;"></div>
    <div id="result" class="card critical" style="display:none;">
        <div class="meta" id="audit_view"></div>
        <h3 id="trap_title" style="color:#f87171; margin: 10px 0 4px 0;"></h3>
        <div id="psych_alert" style="font-size:14px; color:#cbd5e1;"></div>
        <div class="counter" id="counter_q"></div>
        <div style="background:#1e293b; padding:10px; border-radius:6px; font-size:13px;" id="sms_box"></div>
    </div>

    <div class="note">
        <strong>🔍 Technical Boundary Disclosure (PoC vs. Roadmap):</strong><br>
        • <strong>当前 PoC 已实现：</strong>浏览器端 Web Speech API 实时语音转文字、6 类敏感信息正则脱敏审计、可编辑幕僚底线库、Gemini 原生结构化博弈推演及真实毫秒级延迟测算。
    </div>

    <script>
        let recognition = null;
        let isListening = false;

        function toggleMic() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                alert("当前浏览器不支持 Web Speech API，请直接输入文字测试。");
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
                    const btn = document.getElementById('mic_btn');
                    btn.innerText = "🎤 开启浏览器实时语音识别";
                    btn.classList.remove("mic-active");
                    if (document.getElementById('input_text').value.trim()) {
                        runAgent();
                    }
                };
            }
            if (!isListening) {
                recognition.start();
                isListening = true;
                const btn = document.getElementById('mic_btn');
                btn.innerText = "🛑 正在听音中...";
                btn.classList.add("mic-active");
            } else {
                recognition.stop();
            }
        }

        async function runAgent() {
            const errBox = document.getElementById('error_box');
            const resBox = document.getElementById('result');
            const runBtn = document.getElementById('run_btn');
            errBox.style.display = 'none';
            runBtn.innerText = '⏳ 正在推演中...';

            try {
                const payload = {
                    mode: document.getElementById('mode').value,
                    text: document.getElementById('input_text').value,
                    user_profile: document.getElementById('user_profile').value,
                    hard_bottom_line: document.getElementById('hard_bottom_line').value
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
                resBox.style.display = 'block';
                document.getElementById('audit_view').innerHTML = 
                    `🛡️ <strong>隐私脱敏审计：</strong>已拦截替换 <b>${data.redacted_items_count}</b> 处敏感实体 | ⏱️ <strong>实测端到端延迟：</strong><b>${data.measured_latency_ms} ms</b> (${data.model_used})<br>` +
                    `📤 <strong>实际发往 Gemini 的脱敏文本：</strong><code>${data.sanitized_payload_sent_to_llm}</code>`;
                document.getElementById('trap_title').innerText = `⚠️ [${t.risk_level}] 识别陷阱：${t.trap_type}`;
                document.getElementById('psych_alert').innerText = `🧠 幕僚性格预警：${t.psychological_alert}`;
                document.getElementById('counter_q').innerText = `🎯 建议立刻反问：“${t.counter_question}”`;
                document.getElementById('sms_box').innerText = `💬 [SMS 模拟器推送]: ${t.sms_brief}`;
            } finally {
                runBtn.innerText = '⚡ 触发实时博弈干预';
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
