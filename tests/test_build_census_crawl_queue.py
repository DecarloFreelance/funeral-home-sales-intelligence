import json
import tempfile
import unittest
from pathlib import Path

from build_census_crawl_queue import (
    QUEUE_REASON,
    SourceValidationError,
    build_queue,
    write_queue,
)


def comparison_payload(new_candidates):
    return {
        "summary": {},
        "domain_matches": [],
        "namecity_matches": [],
        "new_candidates": new_candidates,
    }


def candidate(name="New Home", city="City", province="AB", website="https://example.test/", domain="example.test"):
    return {"name": name, "city": city, "province": province, "website": website, "domain": domain}


class BuildCensusCrawlQueueTests(unittest.TestCase):
    def test_only_candidates_with_a_website_and_domain_are_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "comparison.json"
            source.write_text(json.dumps(comparison_payload([
                candidate(name="Has Website"),
                candidate(name="No Website", website="", domain=""),
            ])), encoding="utf-8")
            queue, summary = build_queue(source)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["company"], "Has Website")
            self.assertEqual(summary["candidates_with_website"], 1)

    def test_provisional_ids_are_province_scoped_and_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "comparison.json"
            source.write_text(json.dumps(comparison_payload([
                candidate(name="A Home", province="AB"),
                candidate(name="B Home", province="AB"),
                candidate(name="C Home", province="BC"),
            ])), encoding="utf-8")
            queue, _ = build_queue(source)
            ids = {row["company"]: row["directory_record_id"] for row in queue}
            self.assertEqual(ids["A Home"], "CENSUS-AB-0001")
            self.assertEqual(ids["B Home"], "CENSUS-AB-0002")
            self.assertEqual(ids["C Home"], "CENSUS-BC-0001")

    def test_queue_reason_is_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "comparison.json"
            source.write_text(json.dumps(comparison_payload([candidate()])), encoding="utf-8")
            queue, _ = build_queue(source)
            self.assertEqual(queue[0]["queue_reason"], QUEUE_REASON)

    def test_missing_source_refuses(self):
        with self.assertRaises(SourceValidationError):
            build_queue(Path("does/not/exist.json"))

    def test_non_list_new_candidates_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "comparison.json"
            payload = comparison_payload([])
            payload["new_candidates"] = "not-a-list"
            source.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(SourceValidationError):
                build_queue(source)

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
