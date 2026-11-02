# Consigliere AI — User Test Kit (November 2026)

## First, the distinction that matters
A **usability study** asks whether non-experts can understand, navigate and interpret the interface. These participants do not need negotiation experience. A **domain validation study** asks whether contract interpretation and strategic advice are correct, which requires people with relevant professional experience.

**Never describe volunteers without domain experience as commercial experts. Never invent users, outcomes, ratings, signatures, or testimonials.**

## A feasible first study with 0 existing industry contacts

Aim for **3–5 voluntary testers**, not a statistically representative sample. They may be students, recent graduates, freelancers, product builders, or online community volunteers. Keep professional reviewers as a separate future goal. Do not require participants to have real contracts or private company information.

If recruited on Reddit/Indie Hackers or startup communities, first read their promotion/research rules. Ask for permission and avoid unsolicited mass DMs. Participation must be optional and can be withdrawn at any time.

## Participant recruitment and consent (copy into message or survey)

"Hi! I made an early prototype that checks a startup deal proposal against a user's stated boundaries. I'm testing whether first-time users can understand it. Would you be willing to try **two entirely fictional scenarios** for 5–8 minutes? No business knowledge required. Please don't submit any personal, confidential, or client information. I will record only your voluntary answers, not your identity. You can skip any question or stop at any time. I won't use your quotes publicly without asking separately."

If someone declines, do not follow up repeatedly.

## 5–8 minute protocol (same for everyone)

1. Tell the participant: "This is an early prototype, not a legal advisor. Please use the fictional scenarios only."
2. Show the deployed app. Do **not** demonstrate the interface first; note whether they find the audit controls themselves.
3. Task A (obvious violation): Select Seller, max discount 10%, at most 45 payment days, prohibit exclusivity. Enter: "Customer asks for 15% discount, 90-day payment, and 12-month exclusivity." Ask: "How many clear rule conflicts did you find? Why?"
4. Task B (not a violation, but a commercial consideration): Seller, maximum 120 payment days, 10% max discount, no exclusivity. Enter: "Customer asks for 8% discount, 90-day payment, and no exclusivity." Ask: "Would you sign without further checks? What does the product actually say?"
5. Task C (negation): "We rejected the proposed 15% discount; we do not agree to exclusivity." Ask whether these terms should be flagged as current accepted obligations. Distinguish UNKNOWN vs VIOLATION.
6. Ask the questions below, recording their exact words (with consent, removing identifiers). Do not teach the answers before collecting responses.

## Five questions for each participant

1. On a 1–5 scale, how easy was it to understand the product's primary purpose?
2. Without help, could you set the maximum discount and payment direction? (Yes / Partly / No)
3. Did you understand the difference between "rule violation" and "commercial risk"? (Yes / Partly / No). Ask them to explain in one sentence.
4. What was the **most confusing** control, term, or result?
5. Would you consider using something like this again, and for which fictional or real workflow? (Optional open text; this is **not evidence of willingness to pay**.)

Record completion time if feasible, but don't start timing until participant has consented.

## Data to store

Use `feedback_template.csv`. Give testers randomized anonymous codes, e.g. P01, P02. Record date, expertise self-description (layperson / founder / sales / purchasing / legal / other; optional), task success separately, 1–5 clarity rating, the most confusing item, exact quote with explicit permission, and requested improvement.

Only include aggregate counts in public HAA materials. Remove direct identifiers and don't publish full raw feedback without consent. Avoid recording any personal contacts, company names, deal texts or screen recordings.

## Example reporting format (fill only after real participants)

"Usability pilot (n=__ consenting volunteers, __ had relevant business experience): __/__ correctly identified the violation case without help; __/__ distinguished compliance from commercial review. Most common confusion: __. We changed __ in response."

If fewer than 3 real testers are recruited, report the exact number and describe the evidence as preliminary.

## How to recruit with no existing network

- Start with product-builder communities where feedback threads are explicitly permitted; ask for *usability* feedback, not a contract-law endorsement.
- Ask whether members can give 5 minutes in return for testing their own projects later (do not offer a positive review in exchange).
- Reach out individually to a few people openly discussing startup procurement, founder finance, B2B sales or contract workflows. Ask courteously, no mass spam.
- If no one responds by the deadline, present the synthetic test benchmark plus a **planned** user study. Do not present simulated testers or AI comments as real-user evidence.

## Ethics / boundaries

- Do not recruit minors without appropriate approval or consent.
- Do not ask for screenshots, financial figures, names, actual contracts or sensitive negotiations.
- The site relies on regex redaction and external model APIs; it is NOT suitable for real confidential contracts yet.
- AI-generated test persons, ratings or comments may be useful for internal walkthroughs, **but they must be explicitly labeled synthetic** and excluded from real-user counts.
