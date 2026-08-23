import unittest
from datetime import datetime, timezone

from enrichment.quality import evaluate_dataset_quality, evaluate_quality


class EnrichmentQualityTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
