import unittest

from build_platform_outreach import FORBIDDEN_CLIENT_REFERENCES, build_outreach


class BuildPlatformOutreachTests(unittest.TestCase):

    def test_only_builds_draft_for_validated_candidate_email(self):
        rows = build_outreach([{
            "domain": "jasontroyer.com",
            "company": "Jason Troyer",
            "usable_emails": ["drjasontroyer@gmail.com"],
            "priority_score": 94,
            "recommended_motion": "MANAGED_LICENSE",
            "evidence_url": "https://example.com/evidence",
        }])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["to"], "drjasontroyer@gmail.com")
        self.assertIn("grief resources", rows[0]["body"])
        self.assertTrue(rows[0]["body"].endswith("Best,\nAlex"))
        self.assertEqual(set(rows[0]), {"to", "subject", "body"})

    def test_excludes_candidate_when_email_is_not_usable(self):
        rows = build_outreach([{
            "domain": "jasontroyer.com",
            "company": "Jason Troyer",
            "usable_emails": [],
        }])

        self.assertEqual(rows, [])

    def test_excludes_address_recorded_as_sent(self):
        rows = build_outreach([{
            "domain": "jasontroyer.com",
            "company": "Jason Troyer",
            "usable_emails": ["drjasontroyer@gmail.com"],
            "priority_score": 94,
            "recommended_motion": "MANAGED_LICENSE",
            "evidence_url": "https://example.com/evidence",
        }], sent_emails=["DrJasonTroyer@gmail.com"])

        self.assertEqual(rows, [])

    def test_generated_messages_contain_no_client_reference(self):
        rows = build_outreach([{
            "domain": "jasontroyer.com",
            "company": "Jason Troyer",
            "usable_emails": ["drjasontroyer@gmail.com"],
            "priority_score": 94,
            "recommended_motion": "MANAGED_LICENSE",
            "evidence_url": "https://example.com/evidence",
        }])

        message = (rows[0]["subject"] + rows[0]["body"]).lower()
        self.assertFalse(any(term in message for term in FORBIDDEN_CLIENT_REFERENCES))


if __name__ == "__main__":
    unittest.main()
