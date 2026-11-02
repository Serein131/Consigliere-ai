# Research cases · Synthetic datasets

All cases are **fictional and AI-assisted**, not real contracts or independent expert-labeled examples.

| Dataset | Size | How to interpret |
|---|---:|---|
| [synthetic_cases.json](synthetic_cases.json) | 60 | Familiar development/regression dataset; DealGuard was fixed using this set. **Not an unbiased holdout.** |
| [challenge_cases.json](challenge_cases.json) | 20 | Older difficult stress cases already inspected; not new holdout. |
| [frozen_holdout_v1.json](frozen_holdout_v1.json) | 40 | Independent of original parser *development* at freeze time; already evaluated on 2026-11-02. |
| [four_arm_frozen_24.json](four_arm_frozen_24.json) | 24 | New four-arm evaluation cases, created and frozen on 2026-11-02 before scoring. |

## Historical paths

The original copies at `research/*.json` are retained to preserve reproducible GitHub Actions, commit links and previous experiment scripts. For navigation, use the copies here. Do not modify expected labels after observing model output; publish a new dataset version instead.

## Evaluation standards

- Score every configured rule and active commercial-review flag; UNKNOWN is not PASS.
- Report explicit false alarms and missed violations, plus exact whole-case agreement.
- Use the same input and configured rule thresholds for every arm.
- OpenAI GPT API requires a separate `OPENAI_API_KEY` GitHub secret; ChatGPT Plus does not provide one automatically.
- User research feedback, when collected, is distinct from these synthetic cases.
