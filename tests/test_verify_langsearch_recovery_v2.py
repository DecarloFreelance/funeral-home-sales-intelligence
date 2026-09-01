import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_langsearch_recovery_v2 as verifier
from verify_955_websites import province_present, verification_score


class VerifyLangSearchRecoveryV2Tests(unittest.TestCase):
    def test_ontario_code_does_not_match_common_word_on(self):
        self.assertFalse(province_present("ON", "Plan ahead on your schedule in Tacoma"))
        self.assertTrue(province_present("ON", "Serving families across Ontario"))

    def test_exact_generic_name_without_geography_is_not_verified(self):
        result = verification_score(
            {"company": "Scott Funeral Home", "city": "Mississauga", "province": "ON"},
            {"name": "Scott Funeral Home", "snippet": "", "url": "https://scottfuneralhometacoma.com/"},
            {"html": "<title>Scott Funeral Home</title><p>Funeral services in Tacoma</p>",
             "final_url": "https://scottfuneralhometacoma.com/"},
            {"score": 90, "reasons": []},
        )
        self.assertFalse(result["province_match"])
        self.assertFalse(result["city_match"])
        self.assertFalse(result["verified"])

    def test_uses_cached_results_and_persists_verified_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); queue = root / "queue.json"; search = root / "search.json"; out = root / "out"
            queue.write_text(json.dumps([{"directory_record_id": "CFI-0001", "directory_index": 0, "company": "Example Funeral Home", "city": "Town", "province": "ON"}]))
            search.write_text(json.dumps([{"directory_record_id": "CFI-0001", "status": "OK", "results": [{"url": "https://example.test/"}]}]))
            returned = {"directory_record_id": "CFI-0001", "directory_index": 0, "company": "Example Funeral Home", "city": "Town", "province": "ON", "status": "VERIFIED_HIGH", "website": "https://example.test/", "confidence": "HIGH", "verification_score": .95, "evidence": {"host_overlap": 1.0, "reasons": []}}
            with patch.object(verifier, "verify_record", return_value=returned) as mocked:
                summary = verifier.verify(queue, search, out, workers=1)
            self.assertEqual(mocked.call_args.args[1]["candidate_results"], [{"url": "https://example.test/"}])
            self.assertEqual(summary["verified_records"], 1)
            self.assertEqual(json.loads((out / "verified_source.json").read_text())[0]["directory_record_id"], "CFI-0001")

    def test_accepts_current_resolver_search_results_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); queue = root / "queue.json"; search = root / "search.json"; out = root / "out"
            queue.write_text(json.dumps([{"directory_record_id": "CFI-0001", "directory_index": 0, "company": "Example Funeral Home", "city": "Town", "province": "ON"}]))
            search.write_text(json.dumps([{"directory_record_id": "CFI-0001", "status": "OK", "search_results": [{"url": "https://example.test/"}]}]))
            returned = {"directory_record_id": "CFI-0001", "directory_index": 0, "company": "Example Funeral Home", "city": "Town", "province": "ON", "status": "VERIFIED_HIGH", "website": "https://example.test/", "confidence": "HIGH", "verification_score": .95, "evidence": {"host_overlap": 1.0, "reasons": []}}
            with patch.object(verifier, "verify_record", return_value=returned) as mocked:
                verifier.verify(queue, search, out, workers=1)
            self.assertEqual(mocked.call_args.args[1]["candidate_results"], [{"url": "https://example.test/"}])

    def test_matching_third_party_text_cannot_become_verified_website(self):
        result = {"status": "VERIFIED_HIGH", "company": "Example Funeral Home", "website": "https://directory.invalid/listing", "domain": "directory.invalid", "confidence": "HIGH", "evidence": {"host": "directory.invalid", "host_overlap": 0, "reasons": ["exact_company_phrase_on_page"]}}
        guarded = verifier.enforce_first_party(result)
        self.assertEqual(guarded["status"], "REVIEW")
        self.assertEqual(guarded["website"], "")
        self.assertEqual(guarded["first_party_guard"], "rejected_no_domain_identity_support")

    def test_company_token_in_official_domain_is_first_party_support(self):
        result = {"status": "VERIFIED_HIGH", "company": "Alan R. Barker Funeral Home", "website": "https://barkerfh.com/", "domain": "barkerfh.com", "confidence": "HIGH", "evidence": {"host": "barkerfh.com", "host_overlap": 0}}
        self.assertEqual(verifier.enforce_first_party(result)["status"], "VERIFIED_HIGH")

    def test_candidate_prefilter_prefers_company_domain_over_directory_slug(self):
        row = {"company": "Alan R. Barker Funeral Home"}
        candidates = [{"url": "https://barkerfh.com/contact"}, {"url": "https://directory.invalid/alan-barker-funeral-home"}]
        self.assertEqual(verifier.first_party_candidates(row, candidates), candidates[:1])

    def test_geographic_company_word_does_not_make_newspaper_first_party(self):
        row = {"company": "Bocchinfuso Funeral Home (Niagara) Inc."}
        candidates = [{"url": "https://obituaries.niagarafallsreview.ca/example"}]
        self.assertEqual(verifier.first_party_candidates(row, candidates), [])

    def test_verified_obituary_url_on_company_domain_is_canonicalized(self):
        result = {"status": "VERIFIED_HIGH", "company": "Basic Funerals", "website": "https://basicfunerals.ca/obituaries/example", "domain": "basicfunerals.ca", "confidence": "HIGH", "evidence": {"host": "basicfunerals.ca", "host_overlap": 1}}
        self.assertEqual(verifier.enforce_first_party(result)["website"], "https://basicfunerals.ca/")

    def test_generic_first_token_cannot_match_different_business(self):
        row = {"company": "First Memorial Funeral Services"}
        self.assertEqual(verifier.first_party_candidates(row, [{"url": "https://familiesfirst.ca/"}]), [])

    def test_directory_host_is_denied_even_when_it_contains_company_token(self):
        row = {"company": "Eston-Snipe Lake Funeral Chapel"}
        self.assertEqual(verifier.first_party_candidates(row, [{"url": "https://eston.infoisinfo-ca.com/"}]), [])

    def test_company_name_buried_in_domreaper_subdomain_is_not_first_party(self):
        result = {
            "status": "VERIFIED_HIGH",
            "company": "Heritage Funeral Centre",
            "website": "http://heritagefuneralcentre.ca.domreaper.com/",
            "domain": "heritagefuneralcentre.ca.domreaper.com",
            "confidence": "HIGH",
            "evidence": {
                "host": "heritagefuneralcentre.ca.domreaper.com",
                "host_overlap": 0,
            },
        }
        guarded = verifier.enforce_first_party(result)
        self.assertEqual(guarded["status"], "REVIEW")
        self.assertEqual(guarded["website"], "")

    def test_domreaper_candidate_with_company_subdomain_is_filtered(self):
        row = {"company": "Island Funeral Home"}
        candidates = [
            {"url": "https://www.islandfuneralhome.ca/about-us"},
            {"url": "http://islandfuneralhome.ca.domreaper.com/"},
        ]
        self.assertEqual(
            verifier.first_party_candidates(row, candidates),
            candidates[:1],
        )

    def test_identity_domain_label_ignores_deceptive_subdomain(self):
        self.assertEqual(
            verifier.identity_domain_label(
                "heritagefuneralcentre.ca.domreaper.com"
            ),
            "domreaper",
        )
        self.assertEqual(
            verifier.identity_domain_label(
                "www.heritagefuneralcentre.ca"
            ),
            "heritagefuneralcentre",
        )

    def test_errors_and_unknown_records_are_not_fetched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); queue = root / "queue.json"; search = root / "search.json"
            queue.write_text(json.dumps([{"directory_record_id": "CFI-0001"}]))
            search.write_text(json.dumps([{"directory_record_id": "CFI-0001", "status": "ERROR"}, {"directory_record_id": "CFI-9999", "status": "OK"}]))
            with patch.object(verifier, "verify_record") as mocked:
                summary = verifier.verify(queue, search, root / "out", workers=1)
            mocked.assert_not_called()
            self.assertEqual(summary["completed_records"], 0)

    def test_reconciles_only_successful_evidence_that_passes_current_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); queue = root / "queue.json"; search = root / "search.json"; evidence = root / "bounded.json"
            queue.write_text(json.dumps([
                {"directory_record_id": "CFI-0001", "directory_index": 0, "company": "Heritage Funeral Centre", "city": "Toronto", "province": "ON"},
                {"directory_record_id": "CFI-0002", "directory_index": 1, "company": "Island Funeral Home", "city": "Town", "province": "ON"},
            ]))
            search.write_text("[]")
            base = {"status": "VERIFIED_HIGH", "confidence": "HIGH", "verification_score": .97,
                    "evidence": {"fetch_ok": True, "status_code": 200, "verified": True, "host_overlap": 0}}
            evidence.write_text(json.dumps([
                {**base, "directory_record_id": "CFI-0001", "directory_index": 0, "company": "Heritage Funeral Centre", "city": "Toronto", "province": "ON", "website": "https://www.heritagefuneralcentre.ca/", "evidence": {**base["evidence"], "host": "heritagefuneralcentre.ca"}},
                {**base, "directory_record_id": "CFI-0002", "directory_index": 1, "company": "Island Funeral Home", "city": "Town", "province": "ON", "website": "http://islandfuneralhome.ca.domreaper.com/", "evidence": {**base["evidence"], "host": "islandfuneralhome.ca.domreaper.com"}},
            ]))
            summary = verifier.verify(queue, search, root / "out", workers=1, reconcile_evidence=evidence)
            rows = json.loads((root / "out/verified_websites.json").read_text())
            self.assertEqual(summary["verified_records"], 1)
            self.assertEqual([row["directory_record_id"] for row in rows], ["CFI-0001"])
            self.assertTrue(rows[0]["reconciliation_provenance"]["current_first_party_guard_passed"])


if __name__ == "__main__":
    unittest.main()
