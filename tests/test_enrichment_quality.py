import unittest
from datetime import datetime, timezone

from enrichment.quality import evaluate_dataset_quality, evaluate_quality


class EnrichmentQualityTests(unittest.TestCase):
    def test_first_party_published_cross_domain_email_is_retained_without_review(self):
        result = evaluate_quality({
            "domain": "branch.ca", "pages": 1, "enrichment": {"facts": []},
            "contact_intelligence": {
                "email_validation": [{"email": "care@parent.ca", "verification_state": "DNS_VALID"}],
                "email_sources": [{"value": "care@parent.ca", "source_type": "page_text",
                    "source_url": "https://branch.ca/contact"}],
            },
        })
        finding = next(item for item in result["findings"] if item["code"] == "EMAIL_DOMAIN_FIRST_PARTY_CONFIRMED")
        self.assertFalse(finding["requires_review"])
        self.assertTrue(result["outreach_ready"])

    def test_multi_location_domain_requires_crm_identity_review(self):
        result = evaluate_quality({
            "domain": "network.ca", "pages": 1, "enrichment": {"facts": []},
            "business_profile": {"locations": [
                {"company": "Network North", "city": "North"},
                {"company": "Network South", "city": "South"},
            ]},
        })
        self.assertIn("MULTI_LOCATION_ACCOUNT_REVIEW", {item["code"] for item in result["findings"]})
        self.assertFalse(result["crm_sync_safe"])

    def test_reports_semantic_overclaims_and_attribution_risk_without_mutation(self):
        record = {
            "domain": "example.ca",
            "contact_intelligence": {
                "email_validation": [{
                    "email": "person@other.ca", "verification_state": "DNS_VALID",
                    "deliverability": "DELIVERABLE",
                }],
                "phone_verification": [{
                    "phone": "780-555-9876", "verification_state": "METADATA_VALIDATED",
                    "reachability": "REACHABLE",
                }],
            },
            "enrichment": {"facts": [], "conflicted_fields": []},
        }
        original = repr(record)
        quality = evaluate_quality(record)
        codes = {item["code"] for item in quality["findings"]}

        self.assertEqual(quality["status"], "NEEDS_REVIEW")
        self.assertIn("EMAIL_DOMAIN_MISMATCH", codes)
        self.assertIn("DNS_CLAIMED_DELIVERABLE", codes)
        self.assertIn("METADATA_CLAIMED_REACHABLE", codes)
        self.assertTrue(quality["crm_sync_safe"] is False)
        self.assertTrue(quality["outreach_ready"] is False)
        self.assertEqual(repr(record), original)

    def test_reports_conflict_and_inference_without_provenance(self):
        record = {
            "domain": "example.ca",
            "enrichment": {
                "conflicted_fields": ["organization.canonical_name"],
                "facts": [{"id": "bad", "verification_state": "INFERRED", "derived": False}],
            },
        }
        quality = evaluate_quality(record)
        codes = {item["code"] for item in quality["findings"]}
        self.assertIn("MISSING_PROVENANCE", codes)
        self.assertIn("INFERENCE_MARKED_OBSERVED", codes)
        self.assertIn("CONFLICTING_FACTS", codes)

    def test_detects_stale_facts_and_cross_entity_ambiguity(self):
        fact = {
            "id": "fact", "field": "organization.location", "value": "1 Main",
            "source": "directory", "source_url": "https://directory.example/1",
            "source_type": "directory", "observed_at": "2025-01-01T00:00:00Z",
            "stale_after": "2025-05-01T00:00:00Z", "detector": "fixture",
            "detector_version": "1", "confidence": 0.7,
            "verification_state": "DISCOVERED", "evidence": "1 Main", "derived": False,
        }
        quality = evaluate_quality(
            {"domain": "one.ca", "enrichment": {"facts": [fact]}},
            evaluated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIn("STALE_ENRICHMENT", {item["code"] for item in quality["findings"]})

        records = [
            {"domain": "one.ca", "business_profile": {"company": "Shared Home", "locations": [{"address": "1 Main", "city": "Town"}]}},
            {"domain": "two.ca", "business_profile": {"company": "Shared Home", "locations": [{"address": "1 Main", "city": "Town"}]}},
        ]
        findings = evaluate_dataset_quality(records)
        codes = {item["code"] for item in findings["one.ca"]}
        self.assertEqual(codes, {"POSSIBLE_DUPLICATE_ORGANIZATION", "SHARED_ADDRESS_REVIEW"})

    def test_detects_material_website_identity_mismatch_but_not_name_variant(self):
        def record(discovered, observed, prospect_type="Funeral Industry Prospect"):
            return {
                "domain": "example.ca", "prospect_type": prospect_type,
                "business_profile": {"company": discovered},
                "enrichment": {"facts": [{
                    "field": "organization.business_name", "value": observed,
                    "source": "schema.org", "source_url": "https://example.ca/",
                }]},
            }
        mismatch = evaluate_quality(record(
            "Martin Bros. Funeral Chapels", "Martin Bros. Distributing Co. Inc."
        ))
        self.assertIn("ORGANIZATION_WEBSITE_MISMATCH", {item["code"] for item in mismatch["findings"]})
        variant = evaluate_quality(record(
            "Connelly-McKinley Ltd", "Connelly-McKinley Downtown"
        ))
        self.assertNotIn("ORGANIZATION_WEBSITE_MISMATCH", {item["code"] for item in variant["findings"]})

    def test_non_identity_attribution_review_blocks_outreach_but_not_account_sync(self):
        quality = evaluate_quality({
            "domain": "example.ca",
            "contact_intelligence": {"email_validation": [{
                "email": "office@other.ca", "verification_state": "LOCAL_VALID",
            }]},
            "enrichment": {"facts": []},
        })
        self.assertTrue(quality["crm_sync_safe"])
        self.assertFalse(quality["outreach_ready"])
        self.assertEqual(quality["outreach_blocking_reasons"], ["EMAIL_DOMAIN_MISMATCH"])


if __name__ == "__main__":
    unittest.main()
