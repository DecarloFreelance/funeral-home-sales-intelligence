from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from automation.metrics import build_metrics, compare_metrics
from generate_gap_metrics import generate


class GapMetricsTests(unittest.TestCase):
    def fixture(self):
        fact = {
            "id": "one", "field": "contact.public_email", "value": "info@example.ca",
            "verification_state": "LOCAL_VALID", "stale_after": "2025-06-01T00:00:00Z",
        }
        results = [{
            "domain": "example.ca", "enrichment": {"facts": [fact], "conflicted_fields": []},
            "quality_control": {"crm_sync_safe": True, "outreach_ready": False},
        }]
        review = [{"domain": "example.ca", "findings": [{"code": "EMAIL_DOMAIN_MISMATCH"}]}]
        state = {"tasks": {"example.ca:enrichment": {"status": "COMPLETED"}}}
        audit = [{"run_id": "one", "outcome": "SKIPPED"}]
        return results, review, state, audit

    def test_builds_coverage_quality_freshness_and_agent_metrics(self):
        metrics = build_metrics(
            *self.fixture(), now=datetime(2025, 7, 1, tzinfo=timezone.utc)
        )
        self.assertEqual(metrics["organizations"], 1)
        self.assertEqual(metrics["contact_coverage"]["email"]["percent"], 100.0)
        self.assertEqual(metrics["stale_facts"], 1)
        self.assertEqual(metrics["quality_findings"], {"EMAIL_DOMAIN_MISMATCH": 1})
        self.assertEqual(metrics["latest_agent_run"]["outcomes"], {"SKIPPED": 1})

    def test_flags_material_regression_not_small_change(self):
        before = build_metrics(*self.fixture(), now=datetime(2025, 5, 1, tzinfo=timezone.utc))
        before["review_rate_percent"] = 0
        after = {**before, "organizations": 0, "facts": 0,
                 "contact_coverage": {key: {"percent": 0} for key in before["contact_coverage"]},
                 "review_rate_percent": 20, "conflict_rate_percent": 0,
                 "latest_agent_run": {"outcomes": {"FAILED": 1}}}
        codes = {item["code"] for item in compare_metrics(before, after)}
        self.assertIn("ORGANIZATION_COUNT_DROP", codes)
        self.assertIn("FACT_COUNT_DROP_GT_10_PERCENT", codes)
        self.assertIn("CONTACT_COVERAGE_DROP", codes)
        self.assertIn("RATE_INCREASE_GT_10_POINTS", codes)
        self.assertIn("AGENT_FAILURES", codes)

    def test_identical_snapshot_is_not_appended_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / name for name in ("results.json", "review.json", "state.json", "audit.json", "metrics.json", "history.json")]
            for path, value in zip(paths[:4], self.fixture()):
                path.write_text(json.dumps(value), encoding="utf-8")
            _, first_count = generate(*paths)
            _, second_count = generate(*paths)
            self.assertEqual((first_count, second_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
