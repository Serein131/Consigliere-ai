"""Run: python -m unittest discover -s tests -v"""
import unittest
from dealguard import check_deal

RULES="max discount <=10%; payment terms >=45 days; zero exclusivity"
class DealGuardTests(unittest.TestCase):
    def test_violation(self):
        r=check_deal("We need a 15% discount, payment terms 30 days and exclusivity agreement.",RULES)
        self.assertEqual(r["violation_count"],3)
    def test_payment_direction(self):
        r=check_deal("10% discount; payment terms 90 days; no exclusivity.",RULES)
        self.assertEqual(r["assessment"],"NO_DETECTED_VIOLATION")
    def test_missing_information_is_unknown(self):
        r=check_deal("We should align our teams next month.",RULES)
        self.assertEqual(r["assessment"],"UNKNOWN")
    def test_chinese(self):
        r=check_deal("需要15%折扣，付款期限30天，独家合作。","最大折扣10%；付款期限至少45天；禁止独家合作")
        self.assertEqual(r["violation_count"],3)
    def test_no_rules(self):
        self.assertEqual(check_deal("15% discount","")["assessment"],"UNKNOWN")
if __name__=="__main__":
    unittest.main()
