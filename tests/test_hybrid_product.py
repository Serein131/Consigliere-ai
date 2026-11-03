"""No-network tests for the live hybrid workflow and privacy/UNKNOWN handling."""
import json
import unittest
from unittest.mock import patch

from app import app
from hybrid_service import (
    HybridError, execute_hybrid, validate_rules, public_extraction
)

RULES = {
    "role": "seller", "discount_max_pct": 10, "payment_direction": "maximum",
    "payment_days": 45, "prohibit_exclusivity": True,
}
FIXTURE = (
    "Buyer demands a 15% discount, payment terms 90 days and an exclusivity agreement."
)
EXTRACTION = {
    "discount": {"status": "proposed", "value_pct": 15, "evidence": "15% discount"},
    "payment": {"status": "proposed", "days": 90, "evidence": "payment terms 90 days"},
    "exclusivity": {"status": "required", "evidence": "exclusivity agreement"},
    "commercial": {},
}


class HybridServiceTests(unittest.TestCase):
    def test_complete_three_rule_hybrid(self):
        report = execute_hybrid(FIXTURE, RULES, "test-only",
                                generator=lambda *args: EXTRACTION)
        self.assertEqual(report["audit"]["violation_count"], 3)
        self.assertEqual(report["audit"]["assessment"], "VIOLATION")
        self.assertEqual(report["audit"]["commercial_risks"][0]["code"], "long_receivables")
        self.assertTrue(all(item["quote_verified"] for item in report["extraction"]["terms"]))
        self.assertEqual(report["mode"], "hybrid")

    def test_invented_discount_quote_does_not_trigger_false_violation(self):
        extracted = dict(EXTRACTION)
        extracted["discount"] = {"status": "proposed", "value_pct": 80,
                                  "evidence": "80% discount"}
        report = execute_hybrid(FIXTURE, RULES, "test-only",
                                generator=lambda *args: extracted)
        discount = report["audit"]["findings"][0]
        self.assertEqual(discount["status"], "UNKNOWN")
        shown = report["extraction"]["terms"][0]
        self.assertFalse(shown["quote_verified"])
        self.assertEqual(shown["evidence"], "")
        self.assertIsNone(shown["value"])

    def test_rejected_term_is_not_current_rule_breach(self):
        source = "We rejected a requested 15% discount."
        terms = {"discount": {"status": "rejected", "value_pct": 15,
                              "evidence": "15% discount"}}
        result = execute_hybrid(source, {"discount_max_pct": 10}, "test-only",
                                generator=lambda *args: terms)
        self.assertEqual(result["audit"]["assessment"], "UNKNOWN")
        self.assertEqual(result["audit"]["violation_count"], 0)

    def test_buyer_minimum_payment_direction(self):
        source = "We agreed payment terms 90 days."
        terms = {"payment": {"status": "agreed", "days": 90,
                             "evidence": "payment terms 90 days"}}
        result = execute_hybrid(source, {
            "role": "buyer", "payment_direction": "minimum",
            "payment_days": 45
        }, "test-only", generator=lambda *args: terms)
        self.assertEqual(result["audit"]["findings"][0]["status"], "PASS")

    def test_false_active_renewal_quote_not_returned(self):
        source = "The deal excludes renewal."
        extraction = {"commercial": {"auto_renewal": {
            "active": True, "evidence": "automatic renewal applies"
        }}}
        result = execute_hybrid(source, {"discount_max_pct": 10},
                                "test-only", generator=lambda *args: extraction)
        self.assertEqual(result["audit"]["commercial_risks"], [])
        self.assertEqual(result["extraction"]["commercial_evidence"], [])

    def test_no_model_key_is_not_silently_succeeded(self):
        with self.assertRaises(HybridError) as caught:
            execute_hybrid(FIXTURE, RULES, "")
        self.assertEqual(caught.exception.code, "MODEL_NOT_CONFIGURED")

    def test_no_rules_or_wrong_direction_rejected(self):
        for value in (
            {}, {"discount_max_pct": -1}, {"payment_days": 45},
            {"payment_days": 45, "payment_direction": "sideways"},
            {"discount_max_pct": True},
        ):
            with self.subTest(value=value):
                with self.assertRaises(HybridError):
                    validate_rules(value)

    def test_empty_and_oversize_text_rejected(self):
        with self.assertRaises(HybridError):
            execute_hybrid("", RULES, "test-only")
        with self.assertRaises(HybridError):
            execute_hybrid("x" * 3501, RULES, "test-only")


class HybridEndpointTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def request(self, **extra):
        payload = {"text": FIXTURE, "structured_rules": RULES,
                   "consent_to_model_processing": True}
        payload.update(extra)
        return self.client.post("/hybrid-audit", json=payload)

    def test_explicit_consent_required_and_no_model_called(self):
        with patch("app.execute_hybrid") as model:
            response = self.request(consent_to_model_processing=False)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json["error"], "MODEL_CONSENT_REQUIRED")
            model.assert_not_called()

    def test_deployment_can_disable_hybrid_without_disabling_rules(self):
        with patch.dict("os.environ", {"ENABLE_HYBRID_AUDIT": "false"}):
            with patch("app.execute_hybrid") as model:
                response = self.request()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json["error"], "HYBRID_DISABLED")
                model.assert_not_called()
        rules_response = self.client.post("/audit", json={
            "text": FIXTURE, "structured_rules": RULES
        })
        self.assertEqual(rules_response.status_code, 200)

    def test_invalid_payload(self):
        response = self.client.post("/hybrid-audit", data="not-json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"], "INVALID_JSON")

    def test_text_redacted_before_gemini(self):
        content = ("Please email bob@example.com about the 15% discount "
                   "and payment terms 90 days.")
        with patch("app.execute_hybrid") as model:
            model.return_value = {"mode": "hybrid", "audit": {"findings": []},
                                  "extraction": {"terms": []}}
            response = self.request(text=content)
        self.assertEqual(response.status_code, 200)
        sent = model.call_args.args[0]
        self.assertIn("15%", sent)
        self.assertIn("90 days", sent)
        self.assertNotIn("bob@example.com", sent)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_response_never_leaks_provider_message(self):
        with patch("app.execute_hybrid") as model:
            model.side_effect = HybridError("MODEL_QUOTA_OR_RATE_LIMIT", 429)
            response = self.request()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json["error"], "MODEL_QUOTA_OR_RATE_LIMIT")
        self.assertNotIn("test-only", response.get_data(as_text=True))

    def test_oversize_input_returns_413(self):
        response = self.request(text="A" * 3501)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json["error"], "PROPOSAL_TOO_LONG")

    def test_original_rules_only_api_still_works(self):
        response = self.client.post("/audit", json={
            "text": FIXTURE, "structured_rules": RULES
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["violation_count"], 3)

    def test_homepage_exposes_unified_three_stages_and_both_audit_modes(self):
        response = self.client.get("/")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        for marker in ("v5.4", 'id="stage_prepare"', 'id="stage_live_audit"',
                       'id="tab_pre_deal"', 'id="tab_in_deal"', 'id="tab_post_deal"',
                       'id="input_text"', 'id="mic_consent"', 'id="agent_consent"',
                       "dg_hybrid_btn", "dg_check_btn", "dg_consent", "dg_evidence",
                       "live_assist_panel", "live_consent", "live_mode", "live_toggle",
                       "runHybridAudit", "toggleMic", "dg_reject_btn"):
            self.assertIn(marker, page)
        self.assertNotIn('id="dg_proposal"', page)
        self.assertEqual(page.count('<textarea '), 1)
        self.assertEqual(page.count('id="input_text"'), 1)

    def test_speech_transcription_does_not_automatically_call_ai(self):
        response = self.client.get("/")
        page = response.get_data(as_text=True)
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        mic = script.split("async function toggleMic()", 1)[1].split(
            "async function runAgent()", 1
        )[0]
        self.assertNotIn("runAgent()", mic)
        self.assertNotIn("runHybridAudit()", mic)
        self.assertNotIn("runDealGuardAudit()", mic)
        self.assertIn("mic_consent", mic)
        self.assertIn("stopMicInternal()", mic)

if __name__ == "__main__":
    unittest.main()
