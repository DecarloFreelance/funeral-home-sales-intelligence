import unittest

from platform_candidate_import import build_candidate_queue


class PlatformCandidateImportTests(unittest.TestCase):

    def test_keeps_platform_candidate_separate_from_campaign_lead(self):
        queue = build_candidate_queue([{
            "company": "Example Educator",
            "website": "https://educator.example/services",
            "candidate_type": "educator_consultant",
            "offers": ["training"],
            "downstream_markets": ["funeral homes"],
            "recommended_motion": "MANAGED_LICENSE",
            "evidence_url": "https://directory.example/educator",
            "evidence": "Provides funeral-home training.",
        }])

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["record_type"], "platform_candidate")
        self.assertEqual(queue[0]["candidate_type"], "educator_consultant")
        self.assertEqual(queue[0]["offers"], ["training"])
        self.assertNotIn("campaign_lead", queue[0].values())


if __name__ == "__main__":
    unittest.main()
