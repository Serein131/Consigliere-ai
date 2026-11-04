import os
import unittest
from unittest.mock import patch

from app import app
from dealguard import check_deal

RULES = dict(role="seller", discount_max_pct=8, payment_direction="maximum",
             payment_days=45, prohibit_exclusivity=True)
OFFER = "Our final offer requires a 9% discount, payment within 60 days, and exclusivity for one year."
REJECTED = "We rejected the 9% discount, 60-day payment and exclusivity. No agreement was reached."


class GuardrailContinuity(unittest.TestCase):
    def test_three_conflicts_and_payment_boundary(self):
        self.assertEqual(check_deal(OFFER, structured_rules=RULES)["violation_count"], 3)
        for days, expected in [(44, "PASS"), (45, "PASS"), (46, "VIOLATION"), (60, "VIOLATION"), (None, "UNKNOWN")]:
            with self.subTest(days=days):
                text = f"payment within {days} days" if days else "Payment is under discussion."
                findings = check_deal(text, structured_rules=RULES)["findings"]
                self.assertEqual(next(f["status"] for f in findings if f["rule"] == "payment_days"), expected)

    def test_exclusivity_resolution(self):
        for text, expected in [(REJECTED, "PASS"), ("We accepted exclusivity.", "VIOLATION"),
                               (REJECTED + " We then accepted exclusivity.", "VIOLATION"),
                               ("We rejected the discount and accepted exclusivity.", "VIOLATION")]:
            with self.subTest(text=text):
                audit = check_deal(text, structured_rules=RULES)
                self.assertEqual(audit["findings"][-1]["status"], expected)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fixture"})
    def test_strategy_reuses_signed_hybrid_audit_only_for_same_context(self):
        client = app.test_client()
        source = "Funds will arrive two months after invoicing."
        payload = dict(text=source, structured_rules=RULES)
        audit = check_deal("payment within 60 days", structured_rules=RULES)
        with patch("app.execute_hybrid", return_value={"audit": audit}):
            receipt = client.post("/hybrid-audit", json=dict(payload, consent_to_model_processing=True)).json["audit_receipt"]
        payload.update(phase="in_deal", audit_receipt=receipt)
        response = {"candidates": [{"content": {"parts": [{"text": '{"risk_level":"MEDIUM"}'}]}}]}
        with patch("app.call_gemini_rest", return_value=response) as model:
            self.assertEqual(client.post("/analyze", json=payload).json["dealguard_audit"], audit)
            for change in [dict(text="new proposal"), dict(structured_rules=dict(RULES, payment_days=90)),
                           dict(audit_receipt="invalid")]:
                self.assertEqual(client.post("/analyze", json={**payload, **change}).status_code, 409)
            self.assertEqual(model.call_count, 1)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fixture"})
    def test_copyable_replies_cannot_offer_a_limit_exception(self):
        unsafe = '{"counter_question":"Accept 9%?","draft_reply":"Approve 9% for exclusivity."}'
        model = {"candidates": [{"content": {"parts": [{"text": unsafe}]}}]}
        with patch("app.call_gemini_rest", return_value=model):
            for lang in ("zh", "en"):
                for direction, days in [("maximum", 60), ("minimum", 30)]:
                    source = OFFER.replace("60 days", f"{days} days")
                    response = app.test_client().post("/analyze", json=dict(
                        text=source, phase="in_deal", lang=lang, disclose_limits=True,
                        structured_rules=dict(RULES, payment_direction=direction)))
                    advice = response.json["tactical_advice"]
                    for key in ("counter_question", "draft_reply"):
                        reply = advice[key]
                        self.assertNotIn("9%", reply)
                        self.assertIn("8%", reply)
                        self.assertIn("45", reply)
                        self.assertIn("排他" if lang == "zh" else "non-exclusive", reply)
                        if direction == "minimum":
                            self.assertIn("至少" if lang == "zh" else "at least", reply)

    def test_bilingual_terms_and_ledger(self):
        for phrase, expected in [("Net 45.", "PASS"), ("Net 46", "VIOLATION"), ("60天内付款", "VIOLATION"), ("账期待定", "UNKNOWN")]:
            audit = check_deal(phrase, structured_rules=RULES)
            self.assertEqual(audit["findings"][1]["status"], expected)
        for phrase, status in [("a non-exclusive agreement", "PASS"), ("We require exclusivity", "VIOLATION"), ("terms pending", "UNKNOWN")]:
            self.assertEqual(check_deal(phrase, structured_rules=RULES)["findings"][2]["status"], status)
        for phrase, state in [(OFFER, "proposed"), ("We accepted a 9% discount.", "agreed")]:
            self.assertEqual({m["state"] for m in check_deal(phrase, structured_rules=RULES)["term_mentions"]}, {state})

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fixture"})
    def test_default_replies_keep_limits_private(self):
        model = {"candidates": [{"content": {"parts": [{"text": '{"draft_reply":"Our limit is 8%."}'}]}}]}
        with patch("app.call_gemini_rest", return_value=model):
            for lang in ("en", "zh"):
                s = app.test_client().post("/analyze", json=dict(text=OFFER, phase="in_deal", lang=lang, structured_rules=RULES)).json
                self.assertEqual(s["dealguard_audit"]["violation_count"], 3)
                for key in ("counter_question", "draft_reply"):
                    self.assertNotRegex(s["tactical_advice"][key], r"\d")

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fixture"})
    def test_post_deal_email_disclosure_is_independent(self):
        model = {"candidates": [{"content": {"parts": [{"text": '{"draft_reply":"Internal: 8%, 45 days, private budget", "box1_text":"internal review"}'}]}}]}
        with patch("app.call_gemini_rest", return_value=model):
            for lang in ("zh", "en"):
                for flag in (False, True):
                    data = app.test_client().post("/analyze", json=dict(phase="post_deal", text=REJECTED, structured_rules=RULES,
                                                                      lang=lang, disclose_limits=flag)).json["tactical_advice"]
                    self.assertEqual("8%" in data["draft_reply"], flag)
                    self.assertEqual("45" in data["draft_reply"], flag)
                    self.assertNotIn("private budget", data["draft_reply"])
                    self.assertEqual(data["box1_text"], "internal review")
