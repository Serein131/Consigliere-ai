"""v5.5: traceability regression, not a contract accuracy study."""
import unittest
from unittest.mock import patch

from app import app
from dealguard import check_deal, extract_term_mentions

RULES = {
    "role":"seller","discount_max_pct":10,
    "payment_direction":"maximum","payment_days":45,
    "prohibit_exclusivity":True
}
CASE_DESIGNER = (
    "客户最初要求20%折扣和90天付款，我已明确拒绝。"
    "双方最终同意5%折扣、30天付款，非独家合作。"
)
CASE_BUYER = "供应商要求我们在15天内付款，并签署独家采购协议。没有提出折扣。"
CASE_DISTRIBUTOR = (
    "The distributor requests a 12% discount and payment in 75 days. "
    "They want to be the only reseller in the region."
)


class EvidenceLedgerTests(unittest.TestCase):
    def test_rejected_and_current_terms_both_visible_without_claiming_legal_status(self):
        mentions=extract_term_mentions(CASE_DESIGNER)
        old=[m for m in mentions if m["state"]=="rejected"]
        active=[m for m in mentions if m["state"]=="agreed"]
        self.assertTrue(any(m["field"]=="discount" and m["value"]==20 for m in old))
        self.assertTrue(any(m["field"]=="payment" and m["value"]==90 for m in old))
        self.assertTrue(any(m["field"]=="discount" and m["value"]==5 for m in active))
        self.assertTrue(any(m["field"]=="payment" and m["value"]==30 for m in active))
        self.assertTrue(any(m["state"]=="not_required" and m["field"]=="exclusivity"
                            for m in mentions))
        self.assertTrue(all(len(m["evidence"])<=190 for m in mentions))

    def test_payment_within_15_days_is_visible_to_human_even_if_rule_engine_unknown(self):
        mentions=extract_term_mentions(CASE_BUYER)
        self.assertTrue(any(m["field"]=="payment" and m["value"]==15 for m in mentions))
        self.assertTrue(any(m["field"]=="exclusivity" for m in mentions))

    def test_only_reseller_surface_wording_is_visible(self):
        mentions=extract_term_mentions(CASE_DISTRIBUTOR)
        self.assertTrue(any(m["field"]=="exclusivity" and "only reseller" in m["evidence"]
                            for m in mentions))
        self.assertTrue(any(m["field"]=="payment" and m["value"]==75 for m in mentions))

    def test_no_inferred_agreement_on_ambiguous_or_absent_terms(self):
        mentions=extract_term_mentions("The client may ask for a discount if approved.")
        self.assertTrue(all(m["state"]!="agreed" for m in mentions))
        self.assertEqual(extract_term_mentions("Nothing has been proposed."), [])

    def test_default_rule_audit_keeps_existing_verdict_and_adds_ledger(self):
        source="Buyer demands a 15% discount, payment terms 90 days and exclusivity."
        baseline=check_deal(source,structured_rules=RULES)
        self.assertEqual(baseline["violation_count"],3)
        self.assertIn("term_mentions",baseline)
        self.assertTrue(baseline["term_mentions"])

    def test_rules_endpoint_has_redacted_ledger(self):
        app.config["TESTING"]=True
        response=app.test_client().post("/audit",json={
            "text":"Email bob@example.com: Buyer requests a 15% discount.",
            "structured_rules":RULES
        })
        self.assertEqual(response.status_code,200)
        self.assertIn("term_mentions",response.json)
        self.assertNotIn("bob@example.com",str(response.json))

    def test_rules_endpoint_isolates_sentences_and_agrees_with_nonexclusive_ledger(self):
        app.config["TESTING"] = True
        response = app.test_client().post("/audit", json={
            "text": "We rejected a 15% discount. We request a 12% discount. A non-exclusive agreement.",
            "structured_rules": RULES
        })
        self.assertEqual(response.status_code, 200)
        findings = {f["rule"]: f for f in response.json["findings"]}
        self.assertEqual(findings["maximum_discount_pct"]["status"], "VIOLATION")
        self.assertEqual(findings["maximum_discount_pct"]["observed"], 12)
        self.assertEqual(findings["no_exclusivity"]["status"], "PASS")
        self.assertEqual(response.json["violation_count"], 1)
        self.assertTrue(any(m["field"] == "exclusivity" and m["state"] == "not_required"
                            for m in response.json["term_mentions"]))

    def test_hybrid_endpoint_sends_masked_mentions_without_another_ai_call(self):
        app.config["TESTING"]=True
        with patch("app.execute_hybrid") as fake:
            fake.return_value={"mode":"hybrid","model_used":"test-stub",
                               "audit":{"assessment":"UNKNOWN","findings":[]},
                               "extraction":{"terms":[]}}
            response=app.test_client().post("/hybrid-audit",json={
                "text":CASE_DESIGNER,"structured_rules":RULES,
                "consent_to_model_processing":True
            })
            self.assertEqual(response.status_code,200)
            self.assertEqual(fake.call_count,1)
            self.assertTrue(response.json["term_mentions"])
            self.assertEqual(response.headers["Cache-Control"],"no-store, private")


if __name__=="__main__":
    unittest.main()
