import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.resolution import ResearchResolutionAgent
from review.manual import (
    ManualReviewStore, build_review_items, effective_review_queue, review_metrics,
)


def finding(code="ORGANIZATION_WEBSITE_MISMATCH", identifier="finding-1", severity="HIGH", evidence=None):
    return {
        "id": identifier, "code": code, "severity": severity,
        "message": "Ambiguous identity", "evidence": evidence or {"source_url": "https://evidence.example/1"},
        "recommended_action": "Review evidence", "requires_review": True,
    }


def fixture(code="ORGANIZATION_WEBSITE_MISMATCH", evidence=None):
    item = finding(code, evidence=evidence)
    review = [{"domain": "one.example", "findings": [item], "crm_sync_safe": False, "outreach_ready": False}]
    research = [{"domain": "one.example", "research_resolution": {"questions": [{
        "finding_id": item["id"], "finding_code": code, "question": "Is this relationship valid?",
        "candidate_sources": ["first_party_website"],
        "outcome": {"outcome": "REQUIRES_REVIEW", "confidence": 0,
                    "reason": "Evidence is insufficient."},
    }]}}]
    records = [{"domain": "one.example", "business_profile": {"company": "One Home", "locations": [{
        "address": "1 Main St", "city": "Calgary", "province": "AB",
    }]}}]
    return review, research, records


class ManualReviewTests(unittest.TestCase):
    def store(self, root):
        return ManualReviewStore(root / "queue.json", root / "decisions.json")

    def test_stable_identity_and_refresh_idempotency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); store = self.store(root)
            first = store.refresh(*fixture())
            second = store.refresh(*fixture())
            self.assertEqual(first, second)
            self.assertEqual(first[0]["review_id"], second[0]["review_id"])
            self.assertEqual(first[0]["province"], "AB")

    def test_decision_is_append_only_idempotent_and_conflicts_remain_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); store = self.store(root); item = store.refresh(*fixture())[0]
            first, created = store.decide(item["review_id"], "CONFIRM_CURRENT_RELATIONSHIP", "operator",
                evidence_references=["https://evidence.example/official"])
            repeated, repeated_created = store.decide(item["review_id"], "CONFIRM_CURRENT_RELATIONSHIP", "operator",
                evidence_references=["https://evidence.example/official"])
            deferred, deferred_created = store.decide(item["review_id"], "DEFER", "operator", note="reconsider")
            history = store.decisions()
            self.assertTrue(created); self.assertFalse(repeated_created); self.assertTrue(deferred_created)
            self.assertEqual(first, repeated)
            self.assertEqual(len(history), 2)
            self.assertEqual(deferred["previous_decision_id"], first["decision_id"])
            self.assertEqual(review_metrics(store.items(), history)["deferred"], 1)

    def test_duplicate_confirmation_never_merges_or_unblocks_crm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); store = self.store(root)
            item = store.refresh(*fixture("POSSIBLE_DUPLICATE_ORGANIZATION", {
                "domains": ["one.example", "two.example"],
            }))[0]
            decision, _ = store.decide(item["review_id"], "CONFIRM_DUPLICATE", "operator",
                evidence_references=["https://registry.example/record"])
            applied = effective_review_queue(store.items(), store.decisions())[0]
            self.assertFalse(decision["safety"]["entity_merge_performed"])
            self.assertFalse(decision["safety"]["page_or_contact_reassignment_performed"])
            self.assertEqual(applied["status"], "NEEDS_REVIEW")
            self.assertFalse(applied["crm_sync_safe"])

    def test_explicit_supported_decision_alone_changes_effective_eligibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); store = self.store(root); item = store.refresh(*fixture())[0]
            before = effective_review_queue(store.items(), store.decisions())[0]
            self.assertFalse(before["crm_sync_safe"]); self.assertFalse(before["outreach_ready"])
            store.decide(item["review_id"], "CONFIRM_CURRENT_RELATIONSHIP", "operator",
                evidence_references=["https://official.example/location"])
            after = effective_review_queue(store.items(), store.decisions())[0]
            self.assertEqual(after["status"], "MANUALLY_RESOLVED")
            self.assertTrue(after["crm_sync_safe"]); self.assertTrue(after["outreach_ready"])

    def test_relationship_confirmation_without_pages_or_crm_scope_stays_blocked(self):
        for code, decision_type, expected in [
            ("NO_USABLE_WEBSITE_EVIDENCE", "CONFIRM_CURRENT_RELATIONSHIP", "CONFIRMED_RELATIONSHIP_PENDING_RECRAWL"),
            ("MULTI_LOCATION_ACCOUNT_REVIEW", "CONFIRM_BRANCH_RELATIONSHIP", "CONFIRMED_RELATIONSHIP_PENDING_MAPPING"),
        ]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); store = self.store(root); item = store.refresh(*fixture(code))[0]
                store.decide(item["review_id"], decision_type, "operator",
                    evidence_references=["https://official.example/evidence"])
                applied = effective_review_queue(store.items(), store.decisions())[0]
                self.assertEqual(applied["items"][0]["disposition"], expected)
                self.assertEqual(applied["status"], "NEEDS_REVIEW")
                self.assertFalse(applied["crm_sync_safe"])
                self.assertFalse(applied["outreach_ready"])

    def test_sibling_rejection_does_not_change_resolver_or_move_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); store = self.store(root); item = store.refresh(*fixture())[0]
            store.decide(item["review_id"], "REJECT_CANDIDATE", "operator", note="different branch")
            context = {
                "domain": "radville.example",
                "research_item": {"domain": "radville.example", "company": "Fletcher Funeral Chapels",
                    "locations": [{"city": "Radville"}], "attempts": [{
                        "url": "https://radville.example/", "outcome": "CROSS_DOMAIN_REDIRECT",
                        "final_url": "https://network.example/saskatchewan/weyburn/fletcher-funeral-chapel/3867",
                    }]},
                "findings": [finding("NO_USABLE_WEBSITE_EVIDENCE")],
            }
            outcome = ResearchResolutionAgent().run(context)["research_resolution"]["questions"][0]["outcome"]
            self.assertFalse(outcome["resolved"])
            self.assertEqual(effective_review_queue(store.items(), store.decisions())[0]["status"], "NEEDS_REVIEW")

    def test_cli_refresh_list_show_decide_history_stats_and_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / f"{name}.json" for name in ("review", "research", "records", "queue", "decisions", "applied")}
            for name, value in zip(("review", "research", "records"), fixture()):
                paths[name].write_text(json.dumps(value))
            base = [sys.executable, "review_cli.py", "--queue", str(paths["queue"]), "--decisions", str(paths["decisions"])]
            def run(*args):
                result = subprocess.run([*base, *args], cwd=Path(__file__).parents[1], text=True,
                    capture_output=True, check=True)
                return json.loads(result.stdout)
            self.assertEqual(run("refresh", "--review", str(paths["review"]), "--research", str(paths["research"]), "--records", str(paths["records"]))["review_items"], 1)
            listed = run("list", "--status", "UNRESOLVED"); review_id = listed[0]["review_id"]
            self.assertEqual(run("show", review_id)["organization_id"], "one.example")
            self.assertTrue(run("decide", review_id, "DEFER", "--actor", "operator")["created"])
            self.assertFalse(run("decide", review_id, "DEFER", "--actor", "operator")["created"])
            self.assertEqual(len(run("history", review_id)), 1)
            self.assertEqual(run("stats")["deferred"], 1)
            self.assertEqual(run("apply", "--output", str(paths["applied"]))["organizations"], 1)
            self.assertTrue(paths["applied"].is_file())


if __name__ == "__main__":
    unittest.main()
