import json
from pathlib import Path
import tempfile
import threading
import unittest

from automation import AgentOrchestrator, EnrichmentAgent, QualityControlAgent
from automation.agents import RecordAgent
from run_enrichment import run


class AlwaysFails(RecordAgent):
    name = "failure_test"
    version = "1"
    max_attempts = 2

    def fingerprint_payload(self, context):
        return context["domain"]

    def run(self, context):
        raise RuntimeError("controlled failure")


class AgentOrchestrationTests(unittest.TestCase):
    @staticmethod
    def fixture_paths(root):
        paths = tuple(root / name for name in ("pages.json", "results.json", "output.json", "state.json", "audit.json", "review.json"))
        paths[0].write_text(json.dumps([{
            "url": "https://example.ca/", "text": "Cremation services.", "html": "",
            "metadata": {}, "discovery": {"queue_domain": "example.ca"},
        }]), encoding="utf-8")
        paths[1].write_text(json.dumps([{
            "domain": "example.ca", "business_profile": {"company": "Example"},
            "contact_intelligence": {"emails": [], "phones": [], "people": []},
        }]), encoding="utf-8")
        return paths

    def test_real_agents_run_end_to_end_then_skip_unchanged_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pages = root / "pages.json"
            results = root / "results.json"
            output = root / "output.json"
            state = root / "state.json"
            audit = root / "audit.json"
            review = root / "review.json"
            pages.write_text(json.dumps([{
                "url": "https://example.ca/about", "text": "Cremation and burial services.",
                "html": "", "metadata": {"jsonLd": [{"@type": "FuneralHome", "name": "Example"}]},
                "discovery": {"queue_domain": "example.ca"},
            }]), encoding="utf-8")
            results.write_text(json.dumps([{
                "domain": "example.ca", "business_profile": {"company": "Example"},
                "contact_intelligence": {"emails": [], "phones": [], "people": []},
                "executive_priority_score": 20,
            }]), encoding="utf-8")

            self.assertEqual(run(pages, results, output, state, audit, review), {"records": 1, "needs_review": 0})
            first = json.loads(output.read_text())[0]
            first_ids = {item["id"] for item in first["enrichment"]["facts"]}
            self.assertIn("quality_control", first)
            self.assertTrue(first_ids)

            run(pages, results, output, state, audit, review)
            second = json.loads(output.read_text())[0]
            self.assertEqual(first_ids, {item["id"] for item in second["enrichment"]["facts"]})
            events = json.loads(audit.read_text())
            self.assertEqual(sum(item["outcome"] == "COMPLETED" for item in events), 2)
            self.assertEqual(sum(item["outcome"] == "SKIPPED" for item in events), 2)

    def test_interrupted_state_recovers_and_failures_stop_at_retry_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state.json"
            audit = root / "audit.json"
            state.write_text(json.dumps({"schema_version": 1, "tasks": {
                "example.ca:failure_test": {"status": "RUNNING", "attempts": 0,
                    "input_fingerprint": "old"}
            }}), encoding="utf-8")
            runner = AgentOrchestrator(state, audit, [AlwaysFails()])
            runner.process({"domain": "example.ca", "record": {}})
            runner.process({"domain": "example.ca", "record": {}})
            runner.process({"domain": "example.ca", "record": {}})
            task = json.loads(state.read_text())["tasks"]["example.ca:failure_test"]
            self.assertEqual(task["status"], "FAILED")
            self.assertEqual(task["attempts"], 2)
            self.assertFalse(task["retryable"])
            self.assertEqual(json.loads(audit.read_text())[-1]["outcome"], "BLOCKED")

    def test_concurrent_pipeline_invocations_are_serialized(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture_paths(Path(temporary))
            errors = []

            def invoke():
                try:
                    run(*paths)
                except Exception as error:  # pragma: no cover - asserted below
                    errors.append(error)

            threads = [threading.Thread(target=invoke) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertFalse(errors)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(json.loads(paths[2].read_text())), 1)
            events = json.loads(paths[4].read_text())
            self.assertEqual(sum(item["outcome"] == "COMPLETED" for item in events), 2)
            self.assertEqual(sum(item["outcome"] == "SKIPPED" for item in events), 2)

    def test_identity_conflict_blocks_crm_sync_in_review_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture_paths(Path(temporary))
            records = json.loads(paths[1].read_text())
            records[0]["business_profile"]["company"] = "Discovery Name"
            paths[1].write_text(json.dumps(records), encoding="utf-8")
            pages = json.loads(paths[0].read_text())
            pages[0]["metadata"] = {"jsonLd": [{"@type": "FuneralHome", "name": "Different Name"}]}
            paths[0].write_text(json.dumps(pages), encoding="utf-8")

            run(*paths)
            review = json.loads(paths[5].read_text())
            self.assertEqual(review[0]["findings"][0]["code"], "CONFLICTING_FACTS")
            self.assertFalse(review[0]["crm_sync_safe"])


if __name__ == "__main__":
    unittest.main()
