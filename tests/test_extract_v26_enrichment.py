import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from extract_v26_enrichment import (
    DETECTOR_JSONLD,
    DETECTOR_ROLE_CONTEXT,
    DETECTOR_STATIC_TEXT,
    build_enrichment,
    classify_record,
    extract_breadcrumb_navigation,
    extract_jsonld_business_facts,
    extract_text_and_role_facts,
)

FIXED_NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)

# Modeled directly on the real serenity.ca page captured in the validated
# 50-site batch (see the conversation's thin-domain inspection): a
# JS-shell homepage whose static HTML still carries a full LocalBusiness
# JSON-LD block plus an SEO breadcrumb trail.
SERENITY_PAGE = {
    "url": "https://www.serenity.ca/",
    "domain": "serenity.ca",
    "markdown": "Funeral Homes in Edmonton & AB | Serenity Funeral Service",
    "metadata": {
        "title": "Funeral Homes in Edmonton & AB | Serenity Funeral Service",
        "description": None,
        "canonicalUrl": None,
        "jsonLd": [
            {
                "@context": "https://schema.org", "@type": "BreadcrumbList",
                "name": "Site Navigation",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1,
                     "item": "https://www.serenity.ca/contact/contact-us", "name": "Contact"},
                    {"@type": "ListItem", "position": 2,
                     "item": "https://www.serenity.ca/about/about-us", "name": "About"},
                ],
            },
            {
                "@context": "https://schema.org", "@type": "LocalBusiness",
                "name": "Serenity Funeral Service",
                "address": {
                    "@type": "PostalAddress", "addressCountry": "Canada",
                    "addressLocality": "Edmonton", "addressRegion": "AB",
                    "postalCode": "T6E 6E2", "streetAddress": "5311 - 91 Street NW",
                },
                "email": "info@serenity.ca",
                "telephone": "780-450-0101",
                "geo": {"@type": "GeoCoordinates", "latitude": "53.49", "longitude": "-113.47"},
            },
        ],
    },
    "discovery": {"queue_domain": "serenity.ca", "source": None, "email": None, "locations": None},
    "crawl": {"observedAt": "2026-09-12T00:00:00.000000Z"},
}

# Modeled on a plain page containing a footer phone/email and a name+title
# on adjacent lines, with no JSON-LD at all -- the static_text_pattern /
# page_role_context case.
TEXT_ONLY_PAGE = {
    "url": "https://www.example-text.ca/contact",
    "domain": "example-text.ca",
    "markdown": (
        "Contact Us\n"
        "Call us at (204) 555-0199 or email info@example-text.ca\n"
        "Jane Smith\n"
        "Licensed Funeral Director\n"
        "Just a random visitor name with no role nearby: John Doe\n"
    ),
    "metadata": {"title": "Contact", "description": None, "canonicalUrl": None, "jsonLd": None},
    "discovery": {},
    "crawl": {"observedAt": "2026-09-12T00:00:00.000000Z"},
}

# Modeled on Arbor Memorial's real corporate Organization JSON-LD: a phone
# number but no real address -- shared across multiple branch records.
ARBOR_PAGE = {
    "url": "https://www.arbormemorial.ca/en.html",
    "domain": "arbormemorial.com",
    "markdown": "Arbor Memorial: Canada's Leading Cemetery, Funeral & Cremation Provider",
    "metadata": {
        "title": "Arbor Memorial", "description": None, "canonicalUrl": None,
        "jsonLd": [{
            "@context": "http://schema.org", "@type": "Organization",
            "name": "Arbor Memorial", "url": "https://www.arbormemorial.ca/en.html",
            "contactPoint": [{"@type": "ContactPoint", "telephone": "1-888-700-7766", "contactType": "General"}],
            "address": {"@type": "PostalAddress", "addressLocality": "", "addressRegion": "CA",
                        "postalCode": "", "streetAddress": ""},
        }],
    },
    "discovery": {},
    "crawl": {"observedAt": "2026-09-12T00:00:00.000000Z"},
}


def queue_row(record_id, index, city, province, domain, enrichment_status="pending"):
    return {
        "directory_record_id": record_id, "directory_index": index,
        "company": f"Company {record_id}", "city": city, "province": province,
        "website": f"https://{domain}/", "domain": domain,
        "enrichment_status": enrichment_status, "queue_reason": "KNOWN_WEBSITE_NO_CONTACT_EVIDENCE",
    }


def lead_report(directory_record_id, domain, status, city, province, reused=False):
    return {
        "domain": domain, "status": status, "attempts": [], "pages": 1, "duration_ms": 1,
        "queue_entry": queue_row(directory_record_id, 0, city, province, domain),
        "reused_crawl": reused,
    }


class JsonLdExtractionTests(unittest.TestCase):
    def test_localbusiness_jsonld_extracts_email(self):
        facts = extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
        emails = [f for f in facts if f["field"] == "email"]
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0]["value"], "info@serenity.ca")

    def test_localbusiness_jsonld_extracts_phone(self):
        facts = extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
        phones = [f for f in facts if f["field"] == "phone"]
        self.assertEqual(len(phones), 1)
        self.assertEqual(phones[0]["value"], "780-450-0101")

    def test_localbusiness_jsonld_extracts_address(self):
        facts = extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
        addresses = [f for f in facts if f["field"] == "address"]
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0]["value"]["city"], "Edmonton")
        self.assertEqual(addresses[0]["value"]["province"], "AB")

    def test_jsonld_evidence_gets_structured_direct_confidence(self):
        facts = extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
        self.assertTrue(facts)
        self.assertTrue(all(f["verification_state"] == "STRUCTURED_DIRECT" for f in facts))
        self.assertTrue(all(f["detector"] == DETECTOR_JSONLD for f in facts))

    def test_breadcrumb_produces_navigation_not_a_fact(self):
        navigation = extract_breadcrumb_navigation("AB-1067", [SERENITY_PAGE])
        self.assertEqual(len(navigation), 2)
        self.assertEqual(navigation[0]["breadcrumb_label"], "Contact")
        self.assertEqual(navigation[0]["breadcrumb_url"], "https://www.serenity.ca/contact/contact-us")
        # Breadcrumbs never appear as business facts, from either detector.
        facts = extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
        self.assertFalse(any(f["field"] == "breadcrumb" for f in facts))


class TextAndRoleExtractionTests(unittest.TestCase):
    def test_static_text_extraction_is_lower_confidence_than_structured(self):
        facts = extract_text_and_role_facts("XX-0001", "example-text.ca", [TEXT_ONLY_PAGE], FIXED_NOW)
        text_facts = [f for f in facts if f["detector"] == DETECTOR_STATIC_TEXT]
        self.assertTrue(text_facts)
        self.assertTrue(all(f["verification_state"] == "DISCOVERED" for f in text_facts))
        structured_confidence = 0.9
        self.assertTrue(all(f["confidence"] < structured_confidence for f in text_facts))
        values = {f["value"] for f in text_facts}
        self.assertIn("info@example-text.ca", values)

    def test_role_context_extraction_remains_conservative(self):
        facts = extract_text_and_role_facts("XX-0001", "example-text.ca", [TEXT_ONLY_PAGE], FIXED_NOW)
        role_facts = [f for f in facts if f["detector"] == DETECTOR_ROLE_CONTEXT]
        names = {f["value"]["name"] for f in role_facts}
        # Jane Smith sits on the line directly above "Licensed Funeral
        # Director" and is correctly attributed...
        self.assertIn("Jane Smith", names)
        # ...but "John Doe" appears with no role anywhere nearby and must
        # not be inferred as an employee.
        self.assertNotIn("John Doe", names)
        self.assertTrue(all(f["verification_state"] == "DISCOVERED" for f in role_facts))


class QcClassificationTests(unittest.TestCase):
    def test_matching_city_province_permits_verified(self):
        facts = extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
        qc = classify_record(facts, "SUCCESS", shared_domain=False, record_city="Edmonton", record_province="AB")
        self.assertEqual(qc["status"], "VERIFIED")

    def test_mismatching_city_province_produces_review(self):
        facts = extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
        qc = classify_record(facts, "SUCCESS", shared_domain=False, record_city="Calgary", record_province="AB")
        self.assertEqual(qc["status"], "REVIEW")
        self.assertIn("address_city_province_mismatch", qc["reasons"])

    def test_shared_corporate_evidence_does_not_auto_verify_every_branch(self):
        facts = extract_jsonld_business_facts("MB-0145", "arbormemorial.com", [ARBOR_PAGE], FIXED_NOW)
        self.assertTrue(any(f["field"] == "phone" for f in facts))  # real structured evidence exists
        for city in ("Winnipeg", "West St. Paul", "Selkirk"):
            qc = classify_record(facts, "SUCCESS", shared_domain=True, record_city=city, record_province="MB")
            self.assertEqual(qc["status"], "REVIEW", f"branch in {city} must not auto-verify")

    def test_crawl_failure_produces_unresolved(self):
        qc = classify_record([], "FAILED", shared_domain=False, record_city="X", record_province="Y")
        self.assertEqual(qc["status"], "UNRESOLVED")
        self.assertIn("crawl_failed", qc["reasons"])

    def test_successful_crawl_with_no_facts_produces_unresolved(self):
        qc = classify_record([], "SUCCESS", shared_domain=False, record_city="X", record_province="Y")
        self.assertEqual(qc["status"], "UNRESOLVED")
        self.assertIn("crawl_succeeded_zero_facts", qc["reasons"])


class FactProvenanceTests(unittest.TestCase):
    def test_every_fact_has_complete_provenance_fields(self):
        facts = (
            extract_jsonld_business_facts("AB-1067", "serenity.ca", [SERENITY_PAGE], FIXED_NOW)
            + extract_text_and_role_facts("XX-0001", "example-text.ca", [TEXT_ONLY_PAGE], FIXED_NOW)
        )
        required = {
            "directory_record_id", "field", "value", "source_url", "evidence",
            "observed_at", "detector", "detector_version", "confidence",
            "verification_state", "direct_or_derived", "stale_after",
        }
        self.assertTrue(facts)
        for f in facts:
            missing = required - f.keys()
            self.assertFalse(missing, f"fact missing fields {missing}: {f}")


class BuildEnrichmentIntegrationTests(unittest.TestCase):
    def _write_fixture(self, root: Path, pages, leads, queue_rows):
        pages_path, report_path, queue_path = root / "pages.json", root / "report.json", root / "queue.json"
        pages_path.write_text(json.dumps(pages))
        report_path.write_text(json.dumps({"leads": leads}))
        queue_path.write_text(json.dumps(queue_rows))
        return pages_path, report_path, queue_path

    def test_shared_domain_records_remain_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leads = [
                lead_report("MB-0145", "arbormemorial.com", "SUCCESS", "Winnipeg", "MB"),
                lead_report("MB-0215", "arbormemorial.com", "SUCCESS", "West St. Paul", "MB", reused=True),
            ]
            queue_rows = [
                queue_row("MB-0145", 0, "Winnipeg", "MB", "arbormemorial.com"),
                queue_row("MB-0215", 1, "West St. Paul", "MB", "arbormemorial.com"),
            ]
            pages_path, report_path, queue_path = self._write_fixture(root, [ARBOR_PAGE], leads, queue_rows)

            result = build_enrichment(pages_path, report_path, queue_path, observed_at=FIXED_NOW)

            ids = sorted(r["directory_record_id"] for r in result["records"])
            self.assertEqual(ids, ["MB-0145", "MB-0215"])
            # Both independently classified, both correctly refused VERIFIED.
            self.assertTrue(all(r["qc_status"] == "REVIEW" for r in result["records"]))
            self.assertTrue(all(r["crawl_linkage"]["shared_domain"] for r in result["records"]))

    def test_extraction_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leads = [lead_report("AB-1067", "serenity.ca", "SUCCESS", "Edmonton", "AB")]
            queue_rows = [queue_row("AB-1067", 0, "Edmonton", "AB", "serenity.ca")]
            pages_path, report_path, queue_path = self._write_fixture(root, [SERENITY_PAGE], leads, queue_rows)

            first = build_enrichment(pages_path, report_path, queue_path, observed_at=FIXED_NOW)
            second = build_enrichment(pages_path, report_path, queue_path, observed_at=FIXED_NOW)

            self.assertEqual(
                json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True),
            )

    def test_source_artifact_hashes_are_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leads = [lead_report("AB-1067", "serenity.ca", "SUCCESS", "Edmonton", "AB")]
            queue_rows = [queue_row("AB-1067", 0, "Edmonton", "AB", "serenity.ca")]
            pages_path, report_path, queue_path = self._write_fixture(root, [SERENITY_PAGE], leads, queue_rows)

            result = build_enrichment(pages_path, report_path, queue_path, observed_at=FIXED_NOW)
            self.assertIsNotNone(result["input"]["pages_sha256"])
            self.assertEqual(len(result["input"]["pages_sha256"]), 64)


class SourceIntegrityTests(unittest.TestCase):
    def test_v26_source_file_remains_byte_for_byte_unchanged(self):
        source = Path("data/portal_findings.json")
        if not source.is_file():
            self.skipTest("data/portal_findings.json not present in this checkout")
        before = source.read_bytes()

        pages_path = Path("data/generated/enrichment/v26_crawl_batch50_pages.json")
        report_path = Path("data/generated/enrichment/v26_crawl_batch50_pages_report.json")
        queue_path = Path("data/generated/enrichment/v26_crawl_batch50_queue.json")
        if pages_path.is_file() and report_path.is_file() and queue_path.is_file():
            build_enrichment(pages_path, report_path, queue_path, observed_at=FIXED_NOW)

        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
