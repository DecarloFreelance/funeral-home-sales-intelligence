import unittest

from intelligence.phone_intelligence import analyze_phone, verify_phones


class PhoneIntelligenceTests(unittest.TestCase):

    def test_normalizes_and_classifies_alberta_number(self):
        result = analyze_phone("(780) 555-9876")

        self.assertEqual(result["normalized"], "+17805559876")
        self.assertEqual(result["region"], "Alberta")
        self.assertEqual(result["confidence"], 100)
        self.assertEqual(result["reachability"], "NOT_CHECKED")
        self.assertEqual(result["line_type"], "UNKNOWN")

    def test_flags_invalid_exchange(self):
        result = analyze_phone("780-155-9876")

        self.assertIn("invalid_exchange", result["risks"])
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["confidence"], 0)

    def test_flags_obvious_placeholder(self):
        result = analyze_phone("403-555-1234")

        self.assertIn("placeholder_pattern", result["risks"])
        self.assertEqual(result["reachability"], "NOT_CHECKED")

    def test_deduplicates_identical_source_values(self):
        results = verify_phones(["780-555-9876", "780-555-9876"])

        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
