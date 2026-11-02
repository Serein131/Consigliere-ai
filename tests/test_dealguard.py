"""Regression tests for deterministic decision support. No Gemini calls."""
import unittest
from dealguard import check_deal

FREE = "max discount <=10%; payment terms >=45 days; zero exclusivity"
SELLER = {"role":"seller","discount_max_pct":10,"payment_direction":"maximum",
          "payment_days":45,"prohibit_exclusivity":True}
BUYER = {"role":"buyer","discount_max_pct":10,"payment_direction":"minimum",
         "payment_days":45,"prohibit_exclusivity":True}
def by_rule(result, rule):
    return [f for f in result["findings"] if f["rule"]==rule][0]

class DealGuardTests(unittest.TestCase):
    def check_state(self, proposal, rule, status, rules=SELLER):
        out=check_deal(proposal, structured_rules=rules)
        self.assertEqual(by_rule(out,rule)["status"],status,(proposal,out))
        return out

    def test_three_violations_english(self):
        r=check_deal("15% discount; payment terms 90 days; exclusivity agreement",
                     structured_rules=SELLER)
        self.assertEqual(r["violation_count"],3)
    def test_three_violations_chinese(self):
        r=check_deal("要求15%折扣，付款期限90天，独家合作",
                     structured_rules=SELLER)
        self.assertEqual(r["violation_count"],3)
    def test_three_violations_legacy(self):
        r=check_deal("15% discount; payment terms 30 days; exclusivity agreement",FREE)
        self.assertEqual(r["violation_count"],3)
    def test_old_rule_direction_is_preserved(self):
        r=check_deal("10% discount; payment terms 90 days; no exclusivity",FREE)
        self.assertEqual(r["assessment"],"NO_DETECTED_VIOLATION")
    def test_seller_90_days_is_rule_violation_and_commercial_risk(self):
        r=self.check_state("Payment terms 90 days", "payment_days","VIOLATION")
        self.assertEqual(r["commercial_risk_level"],"REVIEW")
    def test_seller_40_days_passes(self):
        self.check_state("Payment terms 40 days","payment_days","PASS")
    def test_buyer_minimum_90_passes(self):
        self.check_state("Payment terms 90 days","payment_days","PASS",BUYER)
    def test_buyer_short_payables_are_commercial_review(self):
        r=check_deal("payment terms 10 days",structured_rules=BUYER)
        self.assertEqual(r["commercial_risk_level"],"REVIEW")
    def test_discount_at_boundary_pass(self):
        self.check_state("10% discount","maximum_discount_pct","PASS")
    def test_discount_above_boundary_violates(self):
        self.check_state("11% discount","maximum_discount_pct","VIOLATION")
    def test_rejected_discount_not_live_violation(self):
        self.check_state("We rejected the 15% discount.","maximum_discount_pct","UNKNOWN")
    def test_rejected_exclusivity_is_not_violation(self):
        self.check_state("We reject exclusivity.","no_exclusivity","PASS")
    def test_chinese_no_exclusivity(self):
        self.check_state("我们不接受独家合作","no_exclusivity","PASS")
    def test_no_exclusivity_english(self):
        self.check_state("The term sheet has no exclusivity.","no_exclusivity","PASS")
    def test_historical_then_final_discount(self):
        self.check_state("Initially requested 15% discount; finally agreed 8% discount",
                         "maximum_discount_pct","PASS")
    def test_chinese_historical_then_final_discount(self):
        self.check_state("最初要求15%折扣；最终同意8%折扣","maximum_discount_pct","PASS")
    def test_conflicting_live_discount_values_unknown(self):
        self.check_state("We request a 15% discount; we request an 8% discount",
                         "maximum_discount_pct","UNKNOWN")
    def test_missing_information_is_unknown(self):
        r=check_deal("Let's discuss next week.",structured_rules=SELLER)
        self.assertEqual(r["assessment"],"UNKNOWN")
    def test_legacy_chinese_variant_discount(self):
        r=check_deal("要求15%折扣；付款期限30天；独家合作",
                     "降价幅度不超过10%；付款期限至少45天；禁止独家合作")
        self.assertEqual(r["violation_count"],3)
    def test_unspecified_rule_does_not_claim_safe(self):
        r=check_deal("Discount 10%; payment terms 40 days",
                     structured_rules={"role":"seller","payment_direction":"maximum",
                                       "payment_days":45})
        self.assertEqual(r["assessment"],"NO_DETECTED_VIOLATION")
        self.assertEqual(r["configured_checks"],1)
    def test_no_rules_is_unknown(self):
        self.assertEqual(check_deal("15% discount","")["assessment"],"UNKNOWN")
    def test_invalid_payment_direction_unknown(self):
        r=check_deal("Payment 60 days", structured_rules={"payment_days":45,
                      "payment_direction":"neither"})
        self.assertEqual(r["assessment"],"UNKNOWN")
        self.assertTrue(r["rule_warnings"])
    def test_unlimited_liability_separate(self):
        r=check_deal("10% discount; 40 days payment terms; no exclusivity; unlimited liability",
                     structured_rules=SELLER)
        self.assertEqual(r["assessment"],"NO_DETECTED_VIOLATION")
        self.assertEqual(r["commercial_risk_level"],"REVIEW")
    def test_automatic_renewal_separate(self):
        r=check_deal("automatic renewal",structured_rules=SELLER)
        self.assertEqual(r["commercial_risk_level"],"REVIEW")
    def test_chinese_exclusive_demand(self):
        self.check_state("对方要求独家合作","no_exclusivity","VIOLATION")
    def test_chinese_cancel_exclusive(self):
        self.check_state("我们取消独家合作","no_exclusivity","PASS")

if __name__ == "__main__":
    unittest.main()
