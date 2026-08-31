import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persistence.importer import build_bundle, import_bundle
from persistence.coverage import _coverage_sql
from persistence.migrations import migrate
from persistence.postgres import (
    DatabaseCommandError, DatabaseConfigurationError, PostgresConfig, PsqlRunner,
)


class FakeRunner:
    def __init__(self):
        self.sql = []

    def run(self, sql, **kwargs):
        self.sql.append(sql)
        if "to_regclass" in sql:
            return "f"
        return ""


class PostgresPersistenceTests(unittest.TestCase):
    def test_configuration_requires_tls_and_never_needs_a_password_value(self):
        values = {
            "PGHOST": "pooler.example", "PGPORT": "5432", "PGDATABASE": "postgres",
            "PGUSER": "postgres.project", "PGSSLMODE": "require",
        }
        config = PostgresConfig.from_environment(values)
        self.assertEqual(config.sslmode, "require")
        self.assertFalse(hasattr(config, "password"))
        with self.assertRaises(DatabaseConfigurationError):
            PostgresConfig.from_environment({**values, "PGSSLMODE": "disable"})

    @patch("persistence.postgres.shutil.which", return_value="/usr/bin/psql")
    @patch("persistence.postgres.subprocess.run")
    def test_runner_uses_pg_environment_and_no_credential_url(self, run, _which):
        run.return_value.returncode = 0
        run.return_value.stdout = "ok\n"
        run.return_value.stderr = ""
        config = PostgresConfig("pooler.example", 5432, "postgres", "postgres.project", "require")
        with patch.dict(os.environ, {"PGPASSWORD": "runtime-only"}, clear=False):
            output = PsqlRunner(config).run("SELECT 1;")
        self.assertEqual(output, "ok")
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("runtime-only", " ".join(command))
        self.assertNotIn("postgresql://", " ".join(command))
        self.assertEqual(environment["PGSSLMODE"], "require")

    def test_pooler_connection_probe_has_a_no_pg_stat_ssl_fallback(self):
        source = Path("database_cli.py").read_text()
        self.assertIn("server_tls_observed", source)
        self.assertIn("tls_enforced", source)
        self.assertIn("pooler-managed", source)

    def test_migration_is_wrapped_and_recorded_after_schema_sql(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "0001_example.sql").write_text("CREATE SCHEMA IF NOT EXISTS fhsi;\n")
            with patch("persistence.migrations.MIGRATIONS", root):
                # Default arguments bind at definition time; patch the helper instead.
                with patch("persistence.migrations.migration_files", return_value=[root / "0001_example.sql"]):
                    self.assertEqual(migrate(runner), ["0001"])
        applied = runner.sql[-1]
        self.assertTrue(applied.startswith("BEGIN;"))
        self.assertIn("INSERT INTO fhsi.schema_migrations", applied)
        self.assertTrue(applied.rstrip().endswith("COMMIT;"))

    def test_bundle_is_deterministic_and_import_is_one_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "directory.json"
            crm = root / "crm.sqlite"
            rows = []
            for index in range(955):
                record_id = f"CFI-{index + 1:04d}"
                enrichment = {
                    "emails": [], "phones": [], "staff": [], "decision_makers": [],
                    "has_email": False, "has_phone": False, "has_staff": False,
                    "has_decision_maker": False, "has_any_contact": False,
                }
                if index == 0:
                    enrichment["emails"] = [{"value": "info@example.ca", "source_url": "https://example.ca/contact"}]
                    enrichment["staff"] = [{"name": "Alex Example", "title": "Manager", "source_url": "https://example.ca/team", "decision_maker": True}]
                rows.append({
                    "directory_record_id": record_id, "directory_index": index,
                    "company": f"Example {index}", "city": "City", "province": "ON",
                    "website": "https://example.ca/" if index == 0 else "",
                    "website_status": "verified" if index == 0 else "no_signal",
                    "record_type": "Branch", "source": "fixture",
                    "branch_safe_enrichment": enrichment,
                })
            directory.write_text(json.dumps(rows))
            connection = sqlite3.connect(crm)
            connection.execute("""CREATE TABLE leads (
                domain TEXT PRIMARY KEY, company_name TEXT, pipeline_stage TEXT, crm_status TEXT,
                priority_score REAL, priority_level TEXT, contact_method TEXT, primary_email TEXT,
                primary_phone TEXT, attempts INTEGER, next_action TEXT, follow_up_date TEXT,
                crm_sync_safe INTEGER, outreach_ready INTEGER, updated_at TEXT)""")
            connection.execute("INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "example.ca", "Example 0", "NEW", "TEST", 1.0, "LOW", "EMAIL",
                "info@example.ca", "", 0, "", "", 1, 0, "2026-08-31T00:00:00",
            ))
            connection.commit()
            connection.close()
            first = build_bundle(directory, crm)
            second = build_bundle(directory, crm)
            self.assertEqual(first, second)
            self.assertEqual(first.counts()["organizations"], 955)
            self.assertNotIn("organization_websites", first.counts())
            self.assertEqual(first.websites[0][5], "false")
            self.assertEqual(first.counts()["contacts"], 1)
            self.assertEqual(first.counts()["people"], 1)
            self.assertEqual(first.crm_leads[0][1], "CFI-0001")
            runner = FakeRunner()
            import_bundle(runner, first)
            sql = runner.sql[-1]
            self.assertTrue(sql.startswith("BEGIN;"))
            self.assertTrue(sql.rstrip().endswith("COMMIT;"))
            self.assertIn("ON CONFLICT (contact_id) DO UPDATE", sql)
            self.assertIn("organization ID belongs to a different source system", sql)
            self.assertIn("verification_class <> ''", sql)

    def test_coverage_import_is_transactional_and_rejects_unknown_organizations(self):
        names = ("coverage_websites", "crawl_runs", "crawl_targets", "crawl_pages")
        paths = {name: Path("/tmp") / f"safe-{name}.csv" for name in names}
        sql = _coverage_sql(paths)
        self.assertTrue(sql.startswith("BEGIN;"))
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))
        self.assertIn("coverage mapping references an unknown organization", sql)
        self.assertIn("SET is_canonical=false", sql)
        self.assertIn("ON CONFLICT (crawl_page_id) DO UPDATE", sql)
        self.assertNotIn("DROP TABLE fhsi", sql)


if __name__ == "__main__":
    unittest.main()
