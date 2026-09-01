import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import prepare_known_site_contact_retry_v1 as retry


class PrepareKnownSiteContactRetryTests(unittest.TestCase):
    def test_prepares_exact_bounded_unique_first_party_cohort(self):
        with tempfile.TemporaryDirectory() as temp:
            summary = retry.prepare(retry.SOURCE, retry.MAPPINGS, Path(temp))
            queue = json.loads((Path(temp) / "fetch_queue.json").read_text())
            search_queue = json.loads((Path(temp) / "langsearch_unverified_queue.json").read_text())
        self.assertEqual(summary["businesses"], 15)
        self.assertEqual(summary["domains"], 15)
        self.assertEqual(summary["candidate_requests"], 105)
        self.assertEqual(summary["langsearch_discovery_records"], 425)
        self.assertEqual(len(search_queue), 425)
        self.assertTrue(all(row["reason"] == "no_verified_website" for row in search_queue))
        self.assertEqual([row["directory_record_id"] for row in queue], sorted(row["directory_record_id"] for row in queue))
        self.assertTrue(all(len(row["candidates"]) == 7 for row in queue))
        self.assertTrue(all(row["expected_domain"] in row["source_website"] for row in queue))

    def test_source_drift_and_unsafe_url_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.json"
            source.write_bytes(retry.SOURCE.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "source drift"):
                retry.prepare(source, retry.MAPPINGS, Path(temp) / "out")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            retry.origin("https://user:secret@example.com/")

    def test_preparation_is_reproducible_and_offline(self):
        before = hashlib.sha256(retry.SOURCE.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            retry.prepare(retry.SOURCE, retry.MAPPINGS, Path(one))
            retry.prepare(retry.SOURCE, retry.MAPPINGS, Path(two))
            for name in ("fetch_queue.json", "langsearch_unverified_queue.json", "prepare_summary.json"):
                self.assertEqual((Path(one) / name).read_bytes(), (Path(two) / name).read_bytes())
        self.assertEqual(before, hashlib.sha256(retry.SOURCE.read_bytes()).hexdigest())
        source_text = Path("prepare_known_site_contact_retry_v1.py").read_text()
        for forbidden in ("requests.", "urlopen(", "sqlite3", "psycopg"):
            self.assertNotIn(forbidden, source_text)


if __name__ == "__main__":
    unittest.main()
