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
