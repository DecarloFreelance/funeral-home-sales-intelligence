import unittest

from intelligence.email_intelligence import analyze_email, validate_emails


class EmailIntelligenceTests(unittest.TestCase):

    def test_business_role_address_gets_strong_evidence_score(self):
        result = analyze_email("Info@Example.com", "example.com")

        self.assertEqual(result["email"], "info@example.com")
        self.assertTrue(result["syntax_valid"])
        self.assertTrue(result["domain_match"])
        self.assertTrue(result["role_account"])
        self.assertEqual(result["deliverability"], "NOT_CHECKED")
        self.assertEqual(result["confidence"], 95)

    def test_does_not_present_free_email_as_deliverability_verified(self):
        result = analyze_email("director@gmail.com", "example.com")

        self.assertTrue(result["syntax_valid"])
        self.assertFalse(result["domain_match"])
        self.assertIn("free_email_provider", result["risks"])
        self.assertEqual(result["status"], "VALID_FORMAT")
        self.assertEqual(result["deliverability"], "NOT_CHECKED")

    def test_deduplicates_case_insensitively(self):
        results = validate_emails(
            ["INFO@example.com", "info@example.com"], "example.com"
        )

        self.assertEqual(len(results), 1)

    def test_invalid_address_is_explicit(self):
        result = analyze_email("not-an-email", "example.com")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["confidence"], 0)


if __name__ == "__main__":
    unittest.main()
