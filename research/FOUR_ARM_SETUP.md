# Run four research arms safely on an iPad

The GitHub workflow [Four-Arm Evidence-Grounded Negotiation Study](https://github.com/Serein131/Consigliere-ai/actions/workflows/four-arm-research.yml) runs the *actual* model endpoints on fictional synthetic case texts. No client contracts or actual negotiation files are needed.

## What already exists

- `GEMINI_API_KEY`: configured previously and used in successful GitHub Actions experiments. Arm A and Arm D rely on it.
- `OPENAI_API_KEY`: **now present in GitHub Secrets**, but the real inference request returned HTTP 429 with `credit_balance_exhausted`, confirmed by [one safe diagnostic run](https://github.com/Serein131/Consigliere-ai/actions/runs/41427929940). A key alone does not fund OpenAI Platform usage. Do not send a key through ChatGPT.
- Arm C is a deterministic Python program and needs no provider key.

## Current action: verify API billing before retrying

1. Open [OpenAI Platform Billing](https://platform.openai.com/settings/organization/billing/overview) and check your **prepaid API credit balance** and payment status. The ChatGPT Plus subscription does not supply API credits.
2. If the balance is exhausted, add an amount you approve (billing costs are under your control). Confirm the payment/credit balance appears before starting the experiment.
3. Check [organization/project limits](https://platform.openai.com/settings/organization/limits) if billing has a positive balance but quota errors persist.
4. To avoid rerunning A/C/D, launch **[GPT-only completion](https://github.com/Serein131/Consigliere-ai/actions/workflows/gpt-only-completion.yml)**, choose `main`, then **Run workflow**. It imports the exact prior 24-case A/C/D predictions from GitHub Actions artifact `13132523079` and calls **only GPT**.
5. Do not repeat the first failed run just to test whether credits exist: its job already attempted the API repeatedly. The billing-aware runner now exits immediately on credit exhaustion.
6. If the saved GitHub artifact expires (30 days), the GPT-only workflow cannot reuse it; instead run the full four-arm workflow after credits are available.

**Do not send your API key or payment details into this chat, a GitHub issue, or the public repository.**

## Configure GPT experiment (user-owned credentials)

1. Visit [OpenAI Platform API Keys](https://platform.openai.com/api-keys), create an API key in an account/project with API access and suitable spend controls.
2. Open [GitHub Actions Secrets](https://github.com/Serein131/Consigliere-ai/settings/secrets/actions); sign in with the repository owner's account.
3. Create a **repository secret** named `OPENAI_API_KEY` with the key value. Use **Secrets**, not public Variables.
4. Do **not** paste your key into any public code, Issue, Pull Request, discussion, Vercel frontend, test case or chat message. Replace or revoke compromised keys promptly.
5. Go to [Four-Arm Study workflow](https://github.com/Serein131/Consigliere-ai/actions/workflows/four-arm-research.yml), select branch `main`, choose **Run workflow**, then open the results. On iPad you may need browser 'Request Desktop Site'.

## Results, scope and pricing

- The workflow runs 24 **fictional** bilingual scenarios. Google Gemini and OpenAI GPT can incur usage charges or use free quota. Model names are recorded in the workflow. OpenAI model default: `gpt-6-luna`; Gemini default: `gemini-3.5-flash-lite`.
- Four arms: A = Gemini direct judgments; B = GPT direct judgments with the same task prompt; C = existing DealGuard deterministic; D = Gemini fact extraction followed by evidence validation and deterministic checks.
- An OpenAI key has now been configured, but the attempted call encountered `credit_balance_exhausted`. GPT remains `NOT_RUN` until 24 real predictions are completed. Do **not** claim GPT was evaluated.
- Failed/incomplete runs are also marked, not silently graded as zero or successfully evaluated.
- Download and preserve artifacts (provider predictions, source quotes, case-by-case CSV, JSON and Markdown). GitHub Actions retention is finite.
- This is a new, frozen **AI-authored synthetic** 24-case set, not legal verification, independent expert labels or real-user feedback.
- Hybrid is currently a separate research module, **not a production website upgrade**.

## Research ethics

Keep raw participant feedback private. The public file `feedback_template.csv` is blank. Do not invent or publish user interviews. Do not change gold labels after seeing outcomes; any code revision requires a new held-out set for claims of improvement.
