import unittest

from discovery.research_queue import build_research_queue


class ResearchQueueTests(unittest.TestCase):

    def test_excludes_success_and_enriches_failed_domain(self):
        queue = [
            {"domain": "good.com", "company": "Good Funeral Home"},
            {
                "domain": "failed.com",
                "company": "Failed Funeral Home",
                "locations": [{"city": "Edmonton"}],
                "sources": ["association"],
            },
        ]
        pages = [{
            "url": "https://good.ca/",
            "discovery": {"queue_domain": "good.com"},
        }]
        report = {"leads": [{
            "domain": "failed.com",
            "status": "FAILED",
            "reason": "HTTP_ERROR",
            "attempts": [{"status_code": 403}],
        }]}

        research = build_research_queue(queue, pages, report)

        self.assertEqual(len(research), 1)
        self.assertEqual(research[0]["domain"], "failed.com")
        self.assertEqual(research[0]["locations"][0]["city"], "Edmonton")
        self.assertEqual(research[0]["failure_reason"], "HTTP_ERROR")
        self.assertIn("website", research[0]["recommended_action"].lower())

    def test_historical_pages_match_same_brand_country_redirect(self):
        research = build_research_queue(
            [{"domain": "example.com"}],
            [{"url": "https://www.example.ca/en.html", "discovery": {}}],
        )
        self.assertEqual(research, [])


if __name__ == "__main__":
    unittest.main()
