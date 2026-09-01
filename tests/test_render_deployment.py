import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from export_portal_findings import MAX_RENDER_SECRET_BYTES, build, write_snapshot


class RenderDeploymentTests(unittest.TestCase):
    def fixture(self, root):
        records = []
        for index in range(955):
            records.append({
                "directory_record_id": f"CFI-{index + 1:04d}", "company": f"Home {index}",
                "city": "City", "province": "ON",
                "branch_safe_enrichment": {
                    "emails": [], "phones": [], "staff": [], "decision_makers": [],
                    "has_any_contact": False,
                },
            })
        source, summary = root / "source.json", root / "summary.json"
        source.write_text(json.dumps(records)); summary.write_text(json.dumps({"after": {"named_staff": 0}}))
        return source, summary

    def test_portal_snapshot_is_deterministic_minimal_and_under_render_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, summary = self.fixture(root)
            one, two = root / "one.json", root / "two.json"
            first = write_snapshot(source, summary, one, None)
            second = write_snapshot(source, summary, two, None)
            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertEqual(first, second)
            self.assertLess(first, MAX_RENDER_SECRET_BYTES)
            payload = json.loads(one.read_text())
            self.assertEqual(payload["version"], "V17")
            self.assertEqual(len(payload["records"]), 955)
            self.assertNotIn("source_text_sha256", one.read_text())
            self.assertEqual(oct(one.stat().st_mode & 0o777), "0o600")

    def test_repository_surfaces_snapshot_version_for_truthful_frontend_label(self):
        from operator_ui.repository import OperatorRepository
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); findings = root / "findings.json"
            findings.write_text(json.dumps({"version": "V16", "records": [], "summary": {}}))
            _records, summary = OperatorRepository(root, findings_path=findings).findings()
            self.assertEqual(summary["version"], "V16")

    def test_production_wsgi_fails_closed_without_secrets(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("OPERATOR_UI_") and key != "PORTAL_FINDINGS_PATH"}
        result = subprocess.run(
            [sys.executable, "-c", "import operator_ui.wsgi"],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing required portal configuration", result.stderr)

    def test_production_wsgi_rebuilds_auth_and_protects_findings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, summary = self.fixture(root)
            findings, auth = root / "findings.json", root / "auth.sqlite"
            write_snapshot(source, summary, findings, None)
            environment = os.environ.copy()
            environment.update({
                "OPERATOR_UI_SECRET_KEY": "stable-test-key",
                "OPERATOR_UI_BOOTSTRAP_PASSWORD": "test-password",
                "PORTAL_FINDINGS_PATH": str(findings),
                "OPERATOR_UI_AUTH_DB": str(auth),
            })
            script = (
                "from operator_ui.wsgi import app; "
                "c=app.test_client(); "
                "print(c.get('/healthz').status_code, c.get('/findings').status_code)"
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                env=environment, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "200 302")
            self.assertTrue(auth.is_file())

    def test_repository_blueprint_uses_only_free_service_and_secret_placeholders(self):
        blueprint = Path("render.yaml").read_text()
        self.assertIn("plan: free", blueprint)
        self.assertIn("sync: false", blueprint)
        self.assertIn("generateValue: true", blueprint)
        self.assertNotIn("funeral\n", blueprint)
        self.assertNotIn("rnd_", blueprint)


if __name__ == "__main__":
    unittest.main()
