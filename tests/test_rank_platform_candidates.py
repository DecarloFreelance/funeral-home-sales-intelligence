import unittest

from rank_platform_candidates import rank_candidates


class RankPlatformCandidatesTests(unittest.TestCase):

    def test_verified_educator_ranks_above_unverified_agency(self):
        queue = [
            {"domain": "educator.example", "company": "Educator", "candidate_type": "grief_educator", "recommended_motion": "MANAGED_LICENSE", "offers": ["training"], "downstream_markets": ["funeral homes"]},
            {"domain": "agency.example", "company": "Agency", "candidate_type": "specialist_agency", "recommended_motion": "WHITE_LABEL_PARTNERSHIP", "offers": ["marketing"], "downstream_markets": ["funeral homes"]},
        ]
        pages = [{"url": "https://educator.example/", "text": "Email info@educator.example", "discovery": {"queue_domain": "educator.example"}}]

        ranked = rank_candidates(queue, pages)

        self.assertEqual(ranked[0]["company"], "Educator")
        self.assertEqual(ranked[0]["verification_status"], "SITE_VERIFIED")
        self.assertEqual(ranked[1]["verification_status"], "EVIDENCE_ONLY")

    def test_domain_mismatch_email_is_not_outreach_ready(self):
        queue = [{"domain": "correct.example", "company": "Correct", "candidate_type": "educator_consultant", "recommended_motion": "MANAGED_LICENSE"}]
        pages = [{"url": "https://correct.example/", "text": "wrong@typo.example", "discovery": {"queue_domain": "correct.example"}}]

        result = rank_candidates(queue, pages)[0]

        self.assertEqual(result["usable_emails"], [])
        self.assertEqual(result["outreach_status"], "CONTACT_REVIEW_REQUIRED")
        self.assertIn("Email domain mismatch", result["contact_issues"][0])


if __name__ == "__main__":
    unittest.main()
