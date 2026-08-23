import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class VerifyAuditCliTests(unittest.TestCase):
    def test_accepts_explicit_crawl_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "pages.json"
            source.write_text(json.dumps([{
                "url": "https://example.com/contact",
                "markdown": "Contact us to discuss cremation and pre-planning.",
            }]), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "verify_audit.py", "--input", str(source)],
                cwd=Path(__file__).resolve().parents[1],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("example.com", result.stdout)
        self.assertIn("contact_form", result.stdout)

    def test_missing_input_fails_with_actionable_message(self):
        result = subprocess.run(
            [sys.executable, "verify_audit.py", "--input", "/tmp/not-present-audit.json"],
            cwd=Path(__file__).resolve().parents[1],
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("crawl input does not exist", result.stderr)

    def test_does_not_report_below_threshold_keyword_as_feature(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "pages.json"
            source.write_text(json.dumps([{
                "url": "https://example.com/",
                "markdown": "Appointments are discussed in this article.",
            }]), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "verify_audit.py", "--input", str(source)],
                cwd=Path(__file__).resolve().parents[1],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("appointment_booking", result.stdout)
        self.assertIn("No conversion signals detected", result.stdout)


if __name__ == "__main__":
    unittest.main()
