import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RenderDeploymentTests(unittest.TestCase):
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
        self.assertIn("PORTAL_FINDINGS_PATH is required", result.stderr)

    def test_production_wsgi_rebuilds_auth_and_protects_findings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            findings, auth = root / "findings.json", root / "auth.sqlite"
            findings.write_text(json.dumps({"version": "V26", "records": [], "summary": {}}))
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
            self.assertTrue(result.stdout.strip().endswith("200 302"))
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
