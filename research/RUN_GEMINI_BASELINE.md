# 如何运行真实的 Gemini 对照实验（iPad 操作）

你之前的 Vercel 网站能够调用 Gemini，但 **Vercel 环境变量不会自动同步到 GitHub Actions**。2026-11-02 首次检查 GitHub Actions 时，仓库未配置 `GEMINI_API_KEY`，因此 Gemini 推理阶段被跳过，没有得到任何模型对照分数。

## 一次性的安全配置

1. 打开 [Google AI Studio API Keys](https://aistudio.google.com/api-keys)，找到你有权使用的 Gemini API Key。可以新建一个仅供实验使用的 Key，并在 Google Cloud/AI Studio 配置适当的配额及账单控制。
2. 打开 [项目 GitHub Actions secrets 设置](https://github.com/Serein131/Consigliere-ai/settings/secrets/actions)；如 iPad 显示不全，可在浏览器中切换“请求桌面网站”。
3. 点击 **New repository secret**。Name 填写：`GEMINI_API_KEY`；Secret 填写从 AI Studio 复制的真实 Key，点击 **Add secret**。
4. **不要**把 API Key 粘贴到 ChatGPT 对话、Issue、README、CSV、前端代码、GitHub 普通变量或公开截图里。GitHub Actions Secrets 与 Variables 是不同功能，应该使用 **Secrets**。
5. 进入 [Gemini Baseline Comparison 工作流](https://github.com/Serein131/Consigliere-ai/actions/workflows/gemini-baseline.yml)，点击 **Run workflow**，Branch 选择 `main`，先选择 `10`，确认模型调用正常；之后可以再选 `60`。
6. 进入运行详情。如果成功，会生成 **measured-gemini-vs-dealguard** 附件：包含 Gemini 每一题的预测、Gemini 评分、DealGuard 在相同题目的评分。
7. 如果出现429、余额不足或模型不可用，工作流会失败或说明未能完成，不会把不完整结果当成正式对照。

## 实验要点

- 本流程使用 **Gemini 3.5 Flash-Lite** 和**相同的结构化规则、相同的案例**，对比“只有模型判断”与“DealGuard 的程序化规则判断”。
- 模型对照提示词包含任务说明和用户设定的规则，但不包含 DealGuard 的源码或预测结果。
- 这些60题是合成案例，而且其中部分曾用于修复 DealGuard。它们适合检查已知模式，不构成独立盲测或真实交易准确率。20题困难案例可作为后续独立实验，但预设标签也需要人工复核。
- API 调用可能使用额度或产生费用；第一次建议只跑10题。

## 结果怎样看

重点比较：每题完整匹配、违规检出 precision/recall、PASS/VIOLATION/UNKNOWN 状态，以及各自失败案例。不要只比较一个总分。普通 Gemini 的实验结果只有在工作流成功、附件确实包含预测后才算已执行。

**如果运行按钮不可见：** 确认工作流已合并到 `main`，并且你登录了拥有仓库权限的 GitHub 账号。
