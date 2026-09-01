import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reconcile_verified_crawl_evidence import reconcile


class ReconcileVerifiedCrawlEvidenceTests(unittest.TestCase):
    def test_filters_stale_domain_and_attaches_verification(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "queue.json"
            pages = root / "pages.json"
            queue.write_text(json.dumps([{
                "domain": "official.example", "source": "fresh",
                "directory_record_ids": ["CFI-0001"],
                "businesses": [{"directory_record_id": "CFI-0001"}],
            }, {
                "domain": "missing.example", "source": "fresh",
                "directory_record_ids": ["CFI-0002"], "businesses": [],
            }]))
            pages.write_text(json.dumps([
                {"url": "https://official.example/contact", "discovery": {"queue_domain": "official.example"}},
                {"url": "https://stale.example/contact", "discovery": {"queue_domain": "stale.example"}},
            ]))
            summary = reconcile(queue, pages, root / "out")
            accepted = json.loads((root / "out/pages.json").read_text())
            missing = json.loads((root / "out/missing_crawl_queue.json").read_text())
            self.assertEqual(summary["accepted_unique_pages"], 1)
            self.assertEqual(accepted[0]["discovery"]["verification_state"], "fresh_hardened_verified")
            self.assertEqual(missing[0]["domain"], "missing.example")

    def test_cross_domain_page_is_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "queue.json").write_text(json.dumps([{
                "domain": "official.example", "source": "fresh",
                "directory_record_ids": ["CFI-0001"], "businesses": [],
            }]))
            (root / "pages.json").write_text(json.dumps([{
                "url": "https://attacker.example/contact",
                "discovery": {"queue_domain": "official.example"},
            }]))
            summary = reconcile(root / "queue.json", root / "pages.json", root / "out")
            self.assertEqual(summary["accepted_unique_pages"], 0)
            self.assertEqual(summary["rejected_cached_pages"], 1)


if __name__ == "__main__":
    unittest.main()
