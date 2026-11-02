"""Local-only validation for evidence-based hybrid (no model API key required)."""
import unittest
from research.evidence_hybrid import audit_extraction,to_prediction

SELLER={"role":"seller","discount_max_pct":10,
        "payment_direction":"maximum","payment_days":45,"prohibit_exclusivity":True}

class EvidenceHybridTests(unittest.TestCase):
    def test_valid_proposed_discount_and_days(self):
        text="Buyer requests 15% discount, payment terms 90 days and exclusive rights."
        extraction={
            "discount":{"status":"proposed","value_pct":15,"evidence":"15% discount"},
            "payment":{"status":"proposed","days":90,"evidence":"payment terms 90 days"},
            "exclusivity":{"status":"required","evidence":"exclusive rights"},
            "commercial":{}
        }
        report=audit_extraction(text,SELLER,extraction)
        self.assertEqual(report["violation_count"],3)
        self.assertEqual(to_prediction("A",report)["predicted_commercial_risks"],["long_receivables"])
    def test_invalid_hallucinated_number_stays_unknown(self):
        text="Buyer asks for 8% discount."
        ext={"discount":{"status":"proposed","value_pct":15,"evidence":"8% discount"}}
        result=audit_extraction(text,{"discount_max_pct":10},ext)
        self.assertEqual(result["assessment"],"UNKNOWN")
    def test_hallucinated_quote_stays_unknown(self):
        text="No discount terms stated yet."
        ext={"discount":{"status":"proposed","value_pct":15,"evidence":"15% discount"}}
        result=audit_extraction(text,{"discount_max_pct":10},ext)
        self.assertEqual(result["findings"][0]["status"],"UNKNOWN")
    def test_rejected_offer_not_live_violation(self):
        text="We rejected a proposed 20% discount."
        ext={"discount":{"status":"rejected","value_pct":20,"evidence":"20% discount"}}
        result=audit_extraction(text,{"discount_max_pct":10},ext)
        self.assertEqual(result["findings"][0]["status"],"UNKNOWN")
    def test_sourced_no_exclusivity_pass(self):
        text="We do not accept exclusivity."
        ext={"exclusivity":{"status":"rejected","evidence":"do not accept exclusivity"}}
        result=audit_extraction(text,{"prohibit_exclusivity":True},ext)
        self.assertEqual(result["findings"][0]["status"],"PASS")
    def test_unsupported_exclusivity_without_quote_unknown(self):
        result=audit_extraction("We talked.",{"prohibit_exclusivity":True},
                                {"exclusivity":{"status":"required","evidence":"exclusive rights"}})
        self.assertEqual(result["findings"][0]["status"],"UNKNOWN")
    def test_deleted_auto_renewal_not_flagged(self):
        text="Automatic renewal was removed from the contract."
        extraction={"commercial":{"auto_renewal":{"active":False,"evidence":"Automatic renewal"}}}
        self.assertEqual(audit_extraction(text,{},extraction)["commercial_risks"],[])
    def test_unsupported_risk_quote_not_accepted(self):
        result=audit_extraction("Terms reviewed.",{},
                                {"commercial":{"auto_renewal":{"active":True,
                                                               "evidence":"automatic renewal"}}})
        self.assertEqual(result["commercial_risks"],[])
        self.assertTrue(result["rule_warnings"])
    def test_seller_buyer_direction(self):
        text="Payment terms 90 days."
        ext={"payment":{"status":"agreed","days":90,"evidence":"Payment terms 90 days"}}
        s=audit_extraction(text,{"role":"seller","payment_days":45,
                                   "payment_direction":"maximum"},ext)
        b=audit_extraction(text,{"role":"buyer","payment_days":45,
                                   "payment_direction":"minimum"},ext)
        self.assertEqual(s["findings"][0]["status"],"VIOLATION")
        self.assertEqual(b["findings"][0]["status"],"PASS")
    def test_chinese_numeric_evidence(self):
        text="客户要求价格下调十二个百分点。"
        ext={"discount":{"status":"proposed","value_pct":12,"evidence":"下调十二个百分点"}}
        result=audit_extraction(text,{"discount_max_pct":10},ext)
        self.assertEqual(result["findings"][0]["status"],"VIOLATION")
    def test_absent_never_safe(self):
        result=audit_extraction("Let's discuss.",{"discount_max_pct":10},{})
        self.assertEqual(result["assessment"],"UNKNOWN")

if __name__=="__main__":
    unittest.main()
