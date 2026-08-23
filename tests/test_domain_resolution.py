import unittest

from discovery.resolution import apply_resolutions


class DomainResolutionTests(unittest.TestCase):

    def test_builds_retry_record_with_evidence_and_original_locations(self):
        retry, summary = apply_resolutions(
            [{
                "domain": "old.example",
                "company": "Example Funeral Home",
                "locations": [{"city": "Edmonton"}],
                "sources": ["association"],
                "provenance": [{"source": "association"}],
            }],
            [{
                "old_domain": "old.example",
                "new_website": "https://new.example/about",
                "confidence": "HIGH",
                "evidence_url": "https://directory.example/listing",
            }],
        )

        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0]["domain"], "new.example")
        self.assertEqual(retry[0]["previous_domain"], "old.example")
        self.assertEqual(retry[0]["locations"][0]["city"], "Edmonton")
        self.assertIn("web_resolution", retry[0]["sources"])
        self.assertEqual(summary["unresolved_domains"], 0)
        self.assertEqual(summary["remaining_domains"], 1)

    def test_does_not_retry_replacement_already_present_in_crawl(self):
        retry, summary = apply_resolutions(
            [{"domain": "old.com", "company": "Old"}],
            [{
                "old_domain": "old.com",
                "new_website": "https://current.ca/",
                "confidence": "HIGH",
                "evidence_url": "https://current.ca/",
            }],
            [{"url": "https://www.current.com/about"}],
        )

        self.assertEqual(retry, [])
        self.assertEqual(len(summary["resolved_existing"]), 1)
        self.assertEqual(summary["remaining_domains"], 0)

    def test_corporate_domain_requires_matching_location_path(self):
        retry, summary = apply_resolutions(
            [{"domain": "old.com", "company": "Old"}],
            [{
                "old_domain": "old.com",
                "new_website": "https://corporate.com/en/location-a/about.html",
                "confidence": "HIGH",
                "evidence_url": "https://corporate.com/en/location-a/about.html",
            }],
            [{"url": "https://corporate.com/en/location-b.html"}],
        )

        self.assertEqual(len(retry), 1)
        self.assertEqual(summary["resolved_existing"], [])

    def test_ignores_unreviewed_or_low_confidence_resolution(self):
        retry, summary = apply_resolutions(
            [{"domain": "old.com", "company": "Old"}],
            [{
                "old_domain": "old.com",
                "new_website": "https://maybe.com/",
                "confidence": "LOW",
            }],
        )

        self.assertEqual(retry, [])
        self.assertEqual(summary["unresolved_domains"], 1)


if __name__ == "__main__":
    unittest.main()
