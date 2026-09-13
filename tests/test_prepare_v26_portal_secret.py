import json
import tempfile
import unittest
from pathlib import Path

from prepare_v26_portal_secret import (
    EXPECTED_RECORD_COUNT,
    EXPECTED_VERSION,
    MAX_RENDER_SECRET_BYTES,
    SourceValidationError,
    write_secret_snapshot,
)
import prepare_v26_portal_secret as prep


def valid_payload(record_count=EXPECTED_RECORD_COUNT, version=EXPECTED_VERSION):
    return {
        "records": [
            {"company": f"Home {index}", "city": "City", "province": "ON"}
            for index in range(record_count)
        ],
        "version": version,
        "generated": "2026-09-11T00:00:00Z",
        "summary": {"with_website": 0},
    }


class PrepareV26PortalSecretTests(unittest.TestCase):
    def test_valid_v26_source_produces_deterministic_snapshot_under_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(valid_payload(), indent=2))
            source_bytes_before = source.read_bytes()

            one, two = root / "one.json", root / "two.json"
            first = write_secret_snapshot(source, one)
            second = write_secret_snapshot(source, two)

            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertEqual(first, second)
            self.assertLess(first, MAX_RENDER_SECRET_BYTES)

            payload = json.loads(one.read_text())
            self.assertEqual(payload["version"], EXPECTED_VERSION)
            self.assertEqual(len(payload["records"]), EXPECTED_RECORD_COUNT)

            # The source must never be modified.
            self.assertEqual(source.read_bytes(), source_bytes_before)

    def test_missing_source_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SourceValidationError):
                write_secret_snapshot(root / "missing.json", root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text("{not valid json")
            with self.assertRaises(SourceValidationError):
                write_secret_snapshot(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_wrong_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(valid_payload(version="V20")))
            with self.assertRaises(SourceValidationError):
                write_secret_snapshot(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_wrong_record_count_fails_closed_even_with_correct_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(valid_payload(record_count=1028)))
            with self.assertRaises(SourceValidationError):
                write_secret_snapshot(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_missing_required_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            payload = valid_payload()
            del payload["summary"]
            source.write_text(json.dumps(payload))
            with self.assertRaises(SourceValidationError):
                write_secret_snapshot(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_source_that_is_a_list_not_an_object_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps([{"company": "Home"}]))
            with self.assertRaises(SourceValidationError):
                write_secret_snapshot(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_oversized_compact_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(valid_payload()))
            original_limit = prep.MAX_RENDER_SECRET_BYTES
            prep.MAX_RENDER_SECRET_BYTES = 10
            try:
                with self.assertRaises(SourceValidationError):
                    write_secret_snapshot(source, root / "out.json")
            finally:
                prep.MAX_RENDER_SECRET_BYTES = original_limit
            self.assertFalse((root / "out.json").exists())


if __name__ == "__main__":
    unittest.main()
