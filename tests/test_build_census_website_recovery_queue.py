import json
import tempfile
import unittest
from pathlib import Path

from build_census_website_recovery_queue import (
    SourceValidationError,
    build_queue,
    write_queue,
)


def comparison_payload(new_candidates):
    return {"new_candidates": new_candidates}


def candidate(name="New Home", city="City", province="AB", website=""):
    return {"name": name, "city": city, "province": province, "website": website}


class BuildCensusWebsiteRecoveryQueueTests(unittest.TestCase):
    def test_only_candidates_without_a_website_are_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "comparison.json"
            source.write_text(json.dumps(comparison_payload([
                candidate(name="No Website"),
                candidate(name="Has Website", website="https://example.test/"),
            ])), encoding="utf-8")
            queue, summary = build_queue(source)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["company"], "No Website")
            self.assertEqual(summary["candidates_without_website"], 1)

    def test_provisional_ids_are_province_scoped_and_distinct_from_crawl_queue_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "comparison.json"
            source.write_text(json.dumps(comparison_payload([
                candidate(name="A Home", province="AB"),
                candidate(name="B Home", province="AB"),
            ])), encoding="utf-8")
            queue, _ = build_queue(source)
            ids = {row["company"]: row["directory_record_id"] for row in queue}
            self.assertEqual(ids["A Home"], "CENSUS-NOWEB-AB-0001")
            self.assertEqual(ids["B Home"], "CENSUS-NOWEB-AB-0002")

    def test_missing_source_refuses(self):
        with self.assertRaises(SourceValidationError):
            build_queue(Path("does/not/exist.json"))

    def test_write_queue_creates_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "comparison.json"
            source.write_text(json.dumps(comparison_payload([candidate()])), encoding="utf-8")
            output = root / "out" / "queue.json"

            summary = write_queue(source, output)

            self.assertTrue(output.is_file())
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(written), 1)
            self.assertEqual(summary["queue_count"], 1)


if __name__ == "__main__":
    unittest.main()
