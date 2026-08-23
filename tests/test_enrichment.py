from datetime import datetime, timezone
import unittest

from enrichment.company import enrich_company


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


class EnrichmentTests(unittest.TestCase):
    def test_extracts_direct_and_derived_facts_with_provenance(self):
        pages = [{
            "url": "https://example.ca/about",
            "text": "Cremation, burial and pre-planning. Jane Smith Owner.",
            "html": '<a href="https://facebook.com/example">Facebook</a><a href="/careers">Careers</a><script src="/wp-content/app.js"></script>',
            "metadata": {"jsonLd": [{
                "@type": "FuneralHome", "name": "Example Funeral Home",
                "foundingDate": "1985", "sameAs": "https://instagram.com/example",
            }]},
        }]
        result = enrich_company(
            "example.ca", pages, {"company": "Example Funeral Home"},
            {"people": [{"name": "Jane Smith", "title": "Owner", "source_url": pages[0]["url"]}],
             "email_sources": [{"value": "owner@example.ca", "source_url": pages[0]["url"], "source_type": "page_text"}],
             "email_validation": [{"email": "owner@example.ca", "verification_state": "DNS_VALID", "confidence": 95}],
             "phone_sources": [{"value": "780-555-9876", "source_url": pages[0]["url"], "source_type": "page_text"}],
             "phone_verification": [{"phone": "780-555-9876", "normalized": "+17805559876", "verification_state": "METADATA_VALIDATED", "confidence": 100}]},
            observed_at=NOW,
        )

        fields = {item["field"] for item in result["facts"]}
        self.assertIn("services.cremation", fields)
        self.assertIn("business.careers_page", fields)
        self.assertIn("organization.social_profile", fields)
        self.assertIn("technology.platform", fields)
        email = next(item for item in result["facts"] if item["field"] == "contact.public_email")
        phone = next(item for item in result["facts"] if item["field"] == "contact.public_phone")
        self.assertEqual(email["verification_state"], "DNS_VALID")
        self.assertEqual(phone["verification_state"], "METADATA_VALIDATED")
        role = next(item for item in result["facts"] if item["field"] == "contact.role_category")
        self.assertTrue(role["derived"])
        self.assertEqual(role["verification_state"], "INFERRED")
        self.assertEqual(role["source_url"], "https://example.ca/about")
        self.assertEqual(role["observed_at"], "2026-08-23T12:00:00Z")
        self.assertTrue(all(set(("id", "evidence", "stale_after", "detector_version")) <= item.keys()
                            for item in result["facts"]))

    def test_stable_ids_corroboration_and_conflicts_preserve_sources(self):
        pages = [
            {"url": "https://example.ca/", "text": "", "html": "", "metadata": {"jsonLd": [{"@type": "FuneralHome", "name": "Alpha"}]}},
            {"url": "https://example.ca/about", "text": "", "html": "", "metadata": {"jsonLd": [{"@type": "FuneralHome", "name": "Alpha"}]}},
        ]
        first = enrich_company("example.ca", pages, {}, {}, observed_at=NOW)
        later = enrich_company("example.ca", pages, {}, {}, observed_at=datetime(2027, 1, 1, tzinfo=timezone.utc))
        alpha = [item for item in first["facts"] if item["field"] == "organization.business_name"]
        self.assertEqual({item["verification_state"] for item in alpha}, {"CORROBORATED"})
        self.assertEqual({item["id"] for item in first["facts"]}, {item["id"] for item in later["facts"]})

        candidates = enrich_company("example.ca", pages, {"company": "Beta"}, {}, observed_at=NOW)
        self.assertNotIn("organization.canonical_name", candidates["conflicted_fields"])
        canonical = [item for item in candidates["facts"] if item["field"] == "organization.canonical_name"]
        observed = [item for item in candidates["facts"] if item["field"] == "organization.business_name"]
        self.assertEqual([item["value"] for item in canonical], ["Beta"])
        self.assertEqual({item["value"] for item in observed}, {"Alpha"})

    def test_multi_value_fields_are_not_misclassified_as_conflicts(self):
        pages = [{
            "url": "https://example.ca/", "text": "", "metadata": {},
            "html": '<a href="https://facebook.com/example">Facebook</a><a href="https://instagram.com/example">Instagram</a>',
        }]
        result = enrich_company("example.ca", pages, {
            "locations": [{"address": "1 Main"}, {"address": "2 Main"}],
        }, {}, observed_at=NOW)
        self.assertNotIn("organization.social_profile", result["conflicted_fields"])
        self.assertNotIn("organization.location", result["conflicted_fields"])

    def test_rejects_malformed_or_non_social_profile_references(self):
        page = {
            "url": "https://example.ca/", "text": "", "html": "",
            "metadata": {"jsonLd": [{"@type": "FuneralHome", "sameAs": [
                "javascript:alert(1)", "https://unrelated.example/profile",
                "https://www.linkedin.com/company/example",
            ]}]},
        }
        result = enrich_company("example.ca", [page], {}, {}, observed_at=NOW)
        profiles = [item["value"] for item in result["facts"] if item["field"] == "organization.social_profile"]
        self.assertEqual(profiles, ["https://www.linkedin.com/company/example"])

    def test_page_facts_retain_crawl_observation_time(self):
        page = {
            "url": "https://example.ca/", "text": "Cremation services", "html": "",
            "metadata": {}, "crawl": {"observedAt": "2025-03-04T05:06:07Z"},
        }
        result = enrich_company("example.ca", [page], {}, {}, observed_at=NOW)
        service = next(item for item in result["facts"] if item["field"] == "services.cremation")
        self.assertEqual(service["observed_at"], "2025-03-04T05:06:07Z")
        self.assertEqual(result["generated_at"], "2026-08-23T12:00:00+00:00")

    def test_extracts_explicit_parent_relationship_without_inferring_from_staff(self):
        pages = [
            {"url": "https://one.ca/staff", "text": "One Funeral Home — A Division of Swan City Funeral Services Ltd.", "html": "", "metadata": {}},
            {"url": "https://one.ca/footer", "text": "Swan City Funeral Service LTD. operating as One Funeral Home", "html": "", "metadata": {}},
            {"url": "https://one.ca/team", "text": "Chris Clements Funeral Director", "html": "", "metadata": {}},
            {"url": "https://one.ca/network", "text": "Dignity Memorial is a division of Service Corporation International (Canada), ULC.", "html": "", "metadata": {}},
        ]
        result = enrich_company("one.ca", pages, {}, {}, observed_at=NOW)
        parents = [item for item in result["facts"] if item["field"] == "organization.parent_organization"]
        self.assertEqual({item["value"].casefold() for item in parents}, {
            "swan city funeral services ltd", "swan city funeral service ltd",
            "service corporation international (canada), ulc",
        })
        self.assertTrue(all(item["source_url"].startswith("https://one.ca/") for item in parents))

        unrelated = enrich_company("two.ca", [{
            "url": "https://two.ca/team", "text": "Chris Clements Funeral Director",
            "html": "", "metadata": {},
        }], {}, {}, observed_at=NOW)
        self.assertFalse(any(item["field"] == "organization.parent_organization" for item in unrelated["facts"]))


if __name__ == "__main__":
    unittest.main()
