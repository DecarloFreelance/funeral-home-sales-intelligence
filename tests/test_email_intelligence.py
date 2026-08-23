import unittest
from types import SimpleNamespace
from unittest.mock import patch

from email_validator import EmailUndeliverableError

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
        self.assertEqual(result["status"], "LOCAL_VALID")
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

    @patch("intelligence.email_intelligence.validate_email_address")
    def test_dns_evidence_has_distinct_non_mailbox_state(self, validator):
        validator.return_value = SimpleNamespace(
            normalized="Info@Example.ca", mx=[(10, "mail.example.ca")],
            mx_fallback_type=None,
        )

        result = validate_emails(["Info@Example.ca"], check_dns=True)[0]

        self.assertEqual(result["email"], "info@example.ca")
        self.assertTrue(result["dns_valid"])
        self.assertTrue(result["mx_available"])
        self.assertEqual(result["dns_status"], "VALID")
        self.assertEqual(result["verification_state"], "DNS_VALID")
        self.assertEqual(result["deliverability"], "NOT_CHECKED")

    @patch("intelligence.email_intelligence.validate_email_address")
    def test_unavailable_mail_domain_is_not_a_mailbox_verdict(self, validator):
        validator.side_effect = EmailUndeliverableError("domain rejects mail")

        result = validate_emails(["info@example.com"], check_dns=True)[0]

        self.assertEqual(result["dns_status"], "INVALID")
        self.assertEqual(result["verification_state"], "LOCAL_VALID")
        self.assertEqual(result["deliverability"], "NOT_CHECKED")
        self.assertIn("mail_domain_unavailable", result["risks"])


if __name__ == "__main__":
    unittest.main()
