import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LeadScoringIntegrationTests(unittest.TestCase):

    def test_discovery_profile_reaches_contact_intelligence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "pages.json"
            output_path = Path(temp_dir) / "results.json"
            input_path.write_text(json.dumps([{
                "url": "https://example.com/",
                "markdown": "Example Funeral Home",
                "metadata": {},
                "discovery": {
                    "company": "Example Funeral Home",
                    "sources": ["association"],
                    "locations": [{
                        "company": "Example Funeral Home",
                        "address": "1 Main Street",
                        "city": "Edmonton",
                        "province": "AB",
                        "country": "Canada",
                        "phone": "780-555-1234",
                        "email": "care@example.com",
                    }],
                },
            }]), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    "lead_scoring.py",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(output_path.read_text(encoding="utf-8"))[0]

        contacts = result["contact_intelligence"]
        self.assertEqual(contacts["emails"], ["care@example.com"])
        self.assertEqual(contacts["phones"], ["780-555-1234"])
        self.assertEqual(contacts["addresses"][0]["city"], "Edmonton")
        self.assertEqual(result["business_profile"]["sources"], ["association"])


if __name__ == "__main__":
    unittest.main()
