import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from extract_census_enrichment import ExtractionError, build_enrichment

OBSERVED_AT = datetime(2026, 9, 12, tzinfo=timezone.utc)


def queue_row(directory_record_id, company, city, province, domain, website=None):
    return {
        "directory_record_id": directory_record_id,
        "company": company,
        "city": city,
        "province": province,
        "website": website or f"https://{domain}/",
        "domain": domain,
        "queue_reason": "CENSUS_NEW_CANDIDATE_WITH_WEBSITE",
    }


def page(domain, url, json_ld=None):
    return {
        "domain": domain,
        "url": url,
        "metadata": {"jsonLd": [json_ld] if json_ld else []},
    }


def local_business(city, province, email="info@example.com", phone="+15551234567"):
    return {
        "@type": "LocalBusiness",
        "email": email,
        "telephone": phone,
        "address": {"@type": "PostalAddress", "addressLocality": city, "addressRegion": province},
    }


class ExtractCensusEnrichmentTests(unittest.TestCase):
    def test_every_shared_domain_queue_entry_gets_its_own_record(self):
        # Three candidates sharing one domain -- the whole point of this
        # script over extract_v26_enrichment.py's per-domain report loop.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = [
                queue_row("CENSUS-BC-0001", "Assoc Funeral Services", "Richmond", "BC", "shared.example"),
                queue_row("CENSUS-BC-0002", "Assoc Funeral Services", "Burnaby", "BC", "shared.example"),
                queue_row("CENSUS-BC-0003", "Assoc Funeral Services", "Surrey", "BC", "shared.example"),
            ]
            pages = [
                page("shared.example", "https://shared.example/richmond", local_business("Richmond", "BC")),
                page("shared.example", "https://shared.example/burnaby", local_business("Burnaby", "BC")),
                page("shared.example", "https://shared.example/surrey", local_business("Surrey", "BC")),
            ]
            report = {"leads": [{"domain": "shared.example", "status": "SUCCESS"}]}

            queue_path, pages_path, report_path = root / "q.json", root / "p.json", root / "r.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            pages_path.write_text(json.dumps(pages), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")

            result = build_enrichment(pages_path, report_path, queue_path, observed_at=OBSERVED_AT)

            self.assertEqual(result["summary"]["records_total"], 3)
            ids = {r["directory_record_id"] for r in result["records"]}
            self.assertEqual(ids, {"CENSUS-BC-0001", "CENSUS-BC-0002", "CENSUS-BC-0003"})
            # Each is independently VERIFIED against ITS OWN city/province.
            for record in result["records"]:
                self.assertEqual(record["qc_status"], "VERIFIED")

    def test_shared_domain_entry_with_no_matching_address_falls_to_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = [
                queue_row("CENSUS-ON-0001", "Home A", "Ottawa", "ON", "shared.example"),
                queue_row("CENSUS-ON-0002", "Home B", "Kingston", "ON", "shared.example"),
            ]
            pages = [page("shared.example", "https://shared.example/", local_business("Ottawa", "ON"))]
            report = {"leads": [{"domain": "shared.example", "status": "SUCCESS"}]}

            queue_path, pages_path, report_path = root / "q.json", root / "p.json", root / "r.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            pages_path.write_text(json.dumps(pages), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")

            result = build_enrichment(pages_path, report_path, queue_path, observed_at=OBSERVED_AT)
            by_id = {r["directory_record_id"]: r for r in result["records"]}
            self.assertEqual(by_id["CENSUS-ON-0001"]["qc_status"], "VERIFIED")
            self.assertEqual(by_id["CENSUS-ON-0002"]["qc_status"], "REVIEW")
            self.assertIn("shared_domain_address_mismatch", by_id["CENSUS-ON-0002"]["qc_reasons"])

    def test_failed_crawl_is_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = [queue_row("CENSUS-AB-0001", "Home", "City", "AB", "down.example")]
            report = {"leads": [{"domain": "down.example", "status": "FAILED"}]}

            queue_path, pages_path, report_path = root / "q.json", root / "p.json", root / "r.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            pages_path.write_text(json.dumps([]), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")

            result = build_enrichment(pages_path, report_path, queue_path, observed_at=OBSERVED_AT)
            self.assertEqual(result["records"][0]["qc_status"], "UNRESOLVED")
            self.assertEqual(result["summary"]["unresolved"], 1)

    def test_missing_artifact_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ExtractionError):
                build_enrichment(root / "missing_pages.json", root / "missing_report.json", root / "missing_queue.json")


if __name__ == "__main__":
    unittest.main()
