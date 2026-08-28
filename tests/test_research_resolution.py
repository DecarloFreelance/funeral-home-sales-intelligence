import json
from pathlib import Path
import tempfile
import unittest

from research.resolution import ResearchResolutionAgent, build_resolution_queue
from run_research_resolution import run


def no_website_finding():
    return {
        "id": "finding-1", "code": "NO_USABLE_WEBSITE_EVIDENCE",
        "evidence": {"pages": 0},
    }


class ResearchResolutionTests(unittest.TestCase):
    def test_direct_identity_and_city_matching_redirect_resolves_location_page(self):
        item = {
            "domain": "examplefuneralhome.ca", "company": "Example Funeral Home",
            "locations": [{"city": "Calgary", "source_url": "https://association.example/1"}],
            "attempts": [{
                "url": "http://examplefuneralhome.ca/", "outcome": "CROSS_DOMAIN_REDIRECT",
                "final_url": "https://network.example/locations/calgary/example-funeral-home/42",
            }],
        }
        output = ResearchResolutionAgent().run({
            "domain": item["domain"], "research_item": item,
            "findings": [no_website_finding()],
        })["research_resolution"]
        outcome = output["questions"][0]["outcome"]
        self.assertEqual(outcome["outcome"], "LOCATION_PAGE_CONFIRMED")
        self.assertEqual(outcome["verification_state"], "CORROBORATED")
        self.assertEqual(outcome["website_scope"], "LOCATION")
        queue = build_resolution_queue([{**item, "research_resolution": output}])
        self.assertEqual(queue[0]["domain"], "examplefuneralhome.ca")
        self.assertEqual(queue[0]["url"], outcome["official_website"])

    def test_same_business_homepage_domain_migration_resolves(self):
        cases = [
            (
                {
                    "domain": "cochranecountryfuneralhome.com",
                    "company": "Cochrane Country Funeral Home",
                    "locations": [{"city": "Cochrane"}],
                    "attempts": [{
                        "url": "http://cochranecountryfuneralhome.com/",
                        "outcome": "CROSS_DOMAIN_REDIRECT",
                        "final_url": "https://www.cochranecountryfuneral.ca/",
                    }],
                },
                "https://www.cochranecountryfuneral.ca/",
            ),
            (
                {
                    "domain": "countryhillscares.ca",
                    "company": "Country Hill Crematorium",
                    "locations": [{"city": "Calgary"}],
                    "attempts": [{
                        "url": "http://countryhillscares.ca/",
                        "outcome": "CROSS_DOMAIN_REDIRECT",
                        "final_url": "https://www.countryhillscrematorium.ca/",
                    }],
                },
                "https://www.countryhillscrematorium.ca/",
            ),
        ]
        for item, expected in cases:
            output = ResearchResolutionAgent().run({
                "domain": item["domain"],
                "research_item": item,
                "findings": [no_website_finding()],
            })["research_resolution"]
            outcome = output["questions"][0]["outcome"]
            self.assertTrue(outcome["resolved"])
            self.assertEqual(outcome["outcome"], "LOCATION_PAGE_CONFIRMED")
            self.assertEqual(outcome["official_website"], expected)

    def test_pluralized_name_token_and_city_resolve_network_location(self):
        item = {
            "domain": "assmansfuneralchapel.com",
            "company": "Assman Funeral Chapel",
            "locations": [{"city": "Prince George"}],
            "attempts": [{
                "url": "http://assmansfuneralchapel.com/",
                "outcome": "CROSS_DOMAIN_REDIRECT",
                "final_url": (
                    "https://www.dignitymemorial.com/en-ca/funeral-homes/"
                    "british-columbia/prince-george/assmans-funeral-chapel/3736"
                ),
            }],
        }
        output = ResearchResolutionAgent().run({
            "domain": item["domain"],
            "research_item": item,
            "findings": [no_website_finding()],
        })["research_resolution"]
        outcome = output["questions"][0]["outcome"]
        self.assertTrue(outcome["resolved"])
        self.assertEqual(outcome["outcome"], "LOCATION_PAGE_CONFIRMED")
        self.assertIn("assman", outcome["evidence"]["matched_name_tokens"])
        self.assertIn("prince", outcome["evidence"]["matched_city_tokens"])
        self.assertIn("george", outcome["evidence"]["matched_city_tokens"])

    def test_one_hostname_name_token_does_not_resolve_homepage(self):
        item = {
            "domain": "example.ca",
            "company": "Example Funeral Home",
            "locations": [{"city": "Calgary"}],
            "attempts": [{
                "url": "http://example.ca/",
                "outcome": "CROSS_DOMAIN_REDIRECT",
                "final_url": "https://examplememorial.ca/",
            }],
        }
        output = ResearchResolutionAgent().run({
            "domain": item["domain"],
            "research_item": item,
            "findings": [no_website_finding()],
        })["research_resolution"]
        self.assertFalse(output["questions"][0]["outcome"]["resolved"])

    def test_weak_or_non_homepage_redirect_refuses_resolution(self):
        for attempt in [
            {"url": "http://example.ca/contact", "outcome": "CROSS_DOMAIN_REDIRECT",
             "final_url": "https://directory.example/listing/123"},
            {"url": "http://example.ca/", "outcome": "CROSS_DOMAIN_REDIRECT",
             "final_url": "https://directory.example/listing/123"},
        ]:
            item = {"domain": "example.ca", "company": "Example Funeral Home", "attempts": [attempt]}
            result = ResearchResolutionAgent().run({
                "domain": item["domain"], "research_item": item,
                "findings": [no_website_finding()],
            })["research_resolution"]
            self.assertEqual(result["questions"][0]["outcome"]["outcome"], "REQUIRES_REVIEW")

    def test_generic_parent_overview_without_location_identifier_stays_ambiguous(self):
        item = {
            "domain": "brand.ca", "company": "Collins Clarke Funeral Home",
            "locations": [{"city": "Montreal"}],
            "attempts": [{"url": "https://brand.ca/", "outcome": "CROSS_DOMAIN_REDIRECT",
                "final_url": "https://network.example/funeral-homes/collins-clarke"}],
        }
        result = ResearchResolutionAgent().run({
            "domain": item["domain"], "research_item": item,
            "findings": [no_website_finding()],
        })["research_resolution"]
        self.assertFalse(result["questions"][0]["outcome"]["resolved"])

    def test_similarly_named_sibling_location_is_not_resolved_by_numeric_id(self):
        item = {
            "domain": "fletcherfuneralchapel.ca", "company": "Fletcher Funeral Chapels",
            "locations": [{"city": "Radville"}],
            "attempts": [{
                "url": "http://fletcherfuneralchapel.ca/", "outcome": "CROSS_DOMAIN_REDIRECT",
                "final_url": (
                    "https://www.dignitymemorial.com/en-ca/funeral-homes/saskatchewan/"
                    "weyburn/fletcher-funeral-chapel-cremation-services/3867"
                ),
            }],
        }
        result = ResearchResolutionAgent().run({
            "domain": item["domain"], "research_item": item,
            "findings": [no_website_finding()],
        })["research_resolution"]

        self.assertEqual(result["questions"][0]["outcome"]["outcome"], "REQUIRES_REVIEW")
        self.assertFalse(result["questions"][0]["outcome"]["resolved"])

    def test_runner_persists_questions_and_skips_unchanged_second_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / f"{name}.json" for name in (
                "research", "review", "output", "queue", "state", "audit",
            )}
            paths["research"].write_text(json.dumps([{
                "domain": "example.ca", "company": "Example Funeral Home",
                "locations": [{"city": "Calgary", "source_url": "https://association.example/1"}],
                "attempts": [{"url": "https://example.ca/", "outcome": "CROSS_DOMAIN_REDIRECT",
                    "final_url": "https://parent.ca/calgary/example-funeral-home/1"}],
            }]))
            paths["review"].write_text(json.dumps([{
                "domain": "example.ca", "findings": [no_website_finding()],
            }]))
            args = tuple(paths[name] for name in ("research", "review", "output", "queue", "state", "audit"))
            self.assertEqual(run(*args)["resolved"], 1)
            self.assertEqual(run(*args)["resolved"], 1)
            outcomes = [event["outcome"] for event in json.loads(paths["audit"].read_text())]
            self.assertEqual(outcomes.count("COMPLETED"), 1)
            self.assertEqual(outcomes.count("SKIPPED"), 1)

    def test_runner_queues_quality_review_entity_without_website_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / f"{name}.json" for name in (
                "research", "review", "output", "queue", "state", "audit",
            )}
            paths["research"].write_text("[]")
            paths["review"].write_text(json.dumps([{
                "domain": "example.ca", "findings": [{
                    "id": "email-1", "code": "EMAIL_DOMAIN_MISMATCH",
                    "evidence": {"email": "person@parent.example"},
                }],
            }]))

            summary = run(*(paths[name] for name in (
                "research", "review", "output", "queue", "state", "audit",
            )))
            output = json.loads(paths["output"].read_text())

            self.assertEqual(summary["candidates"], 1)
            self.assertEqual(summary["questions"], 1)
            self.assertEqual(output[0]["research_resolution"]["questions"][0]["finding_code"], "EMAIL_DOMAIN_MISMATCH")

    def test_existing_first_party_email_confirmation_is_structured_resolution(self):
        result = ResearchResolutionAgent().run({
            "domain": "example.ca", "research_item": {"domain": "example.ca"},
            "findings": [{
                "id": "email-1", "code": "EMAIL_DOMAIN_FIRST_PARTY_CONFIRMED",
                "evidence": {"email": "person@alternate.example", "source_type": "first_party_website"},
            }],
        })["research_resolution"]["questions"][0]["outcome"]
        self.assertTrue(result["resolved"])
        self.assertEqual(result["outcome"], "FIRST_PARTY_ORGANIZATION_DOMAIN")


if __name__ == "__main__":
    unittest.main()
