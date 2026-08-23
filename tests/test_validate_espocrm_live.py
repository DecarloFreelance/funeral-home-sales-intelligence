import unittest

from validate_espocrm_live import select_scale_sample


class EspoCRMLiveSampleTests(unittest.TestCase):
    def test_sample_spans_scores_and_excludes_unsafe_or_uncrawled_records(self):
        records = [
            {"domain": f"safe-{score}.ca", "pages": 1, "executive_priority_score": score,
             "quality_control": {"crm_sync_safe": True}}
            for score in (10, 30, 50, 70, 90)
        ] + [
            {"domain": "blocked.ca", "pages": 1, "executive_priority_score": 100,
             "quality_control": {"crm_sync_safe": False}},
            {"domain": "uncrawled.ca", "pages": 0, "executive_priority_score": 0,
             "quality_control": {"crm_sync_safe": True}},
        ]
        self.assertEqual(
            [item["domain"] for item in select_scale_sample(records, 3)],
            ["safe-10.ca", "safe-50.ca", "safe-90.ca"],
        )


if __name__ == "__main__":
    unittest.main()
