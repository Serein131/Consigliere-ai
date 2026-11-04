"""Tests for reproducible, privacy-minimal evaluation without model calls."""
import json
import unittest

from research.continuous_eval import evaluate, error_for

RULES = {"discount_max_pct": 10}


class ContinuousEvaluationTests(unittest.TestCase):
    def test_error_taxonomy(self):
        self.assertEqual(error_for("risk", "NO_DETECTED_VIOLATION"), "MISSED_RISK_AS_PASS")
        self.assertEqual(error_for("risk", "UNKNOWN"), "MISSED_RISK_AS_UNKNOWN")
        self.assertEqual(error_for("benign", "VIOLATION"), "FALSE_ALERT")
        self.assertEqual(error_for("unknown", "NO_DETECTED_VIOLATION"), "UNSUPPORTED_CERTAINTY")
        self.assertEqual(error_for("benign", "UNKNOWN"), "OVER_ABSTENTION")
        self.assertIsNone(error_for("risk", "VIOLATION"))

    def test_metrics_and_outputs_never_repeat_source_text(self):
        suite = {"rules": RULES, "cases": [
            {"id": "R1", "category": "risk", "expected": "risk",
             "text": "Alice's offer: discount 15%"},
            {"id": "B1", "category": "benign", "expected": "benign",
             "text": "Ben offers discount 5%"},
            {"id": "U1", "category": "uncertain", "expected": "unknown",
             "text": "Charlie is considering unspecified terms"},
        ]}
        result = evaluate(suite)
        self.assertEqual(result["summary"]["count"], 3)
        self.assertEqual(result["summary"]["tp"], 1)
        self.assertEqual(result["summary"]["fn"], 0)
        self.assertEqual(result["summary"]["fp"], 0)
        self.assertEqual(result["summary"]["unsafe_pass_count"], 0)
        for secret in ("Alice", "Ben offers", "Charlie"):
            self.assertNotIn(secret, json.dumps(result))
        self.assertIn("unknown_abstention_rate", result["summary"])

    def test_duplicate_ids_and_missing_labels_rejected(self):
        case = {"id": "S1", "category": "test", "expected": "risk", "text": "discount 15%"}
        with self.assertRaises(ValueError):
            evaluate({"rules": RULES, "cases": [case, dict(case)]})
        with self.assertRaises(ValueError):
            evaluate({"rules": RULES, "cases": [dict(case, expected="SAFE")]})

    def test_failures_retain_review_fields_not_fake_root_causes(self):
        suite = {"rules": RULES, "cases": [
            {"id": "U1", "expected": "risk", "category": "paraphrase",
             "text": "A 25% rebate is requested."},
        ]}
        outcome = evaluate(suite)
        self.assertEqual(outcome["summary"]["fn"], 1)
        issue = outcome["failures"][0]
        self.assertEqual(issue["root_cause_confirmed"], "")
        self.assertTrue(issue["hypothesis_only"])
        self.assertEqual(issue["error_code"], "MISSED_RISK_AS_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
