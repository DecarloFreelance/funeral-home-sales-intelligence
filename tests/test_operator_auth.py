import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from operator_ui import create_app
from operator_ui.auth import AuthStore


class OperatorAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.auth_db = self.root / "auth.sqlite"
        AuthStore(self.auth_db).initialize("test-password")
        self.app = create_app({
            "TESTING": True, "AUTH_REQUIRED": True, "AUTH_DB": self.auth_db,
            "DATA_ROOT": self.data, "SECRET_KEY": "test-session-key",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def csrf(self):
        self.client.get("/login")
        with self.client.session_transaction() as state:
            return state["csrf_token"]

    def login(self, username="Alex", password="test-password", next_path=""):
        return self.client.post("/login", data={
            "csrf_token": self.csrf(), "username": username,
            "password": password, "next": next_path,
        })

    def test_every_data_route_requires_login_and_static_assets_remain_public(self):
        for path in ("/", "/findings", "/findings/export.csv", "/leads", "/quality", "/crm/actions"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertTrue(response.headers["Location"].startswith("/login?next="))
        self.assertEqual(self.client.get("/static/app.css").status_code, 200)

    def test_exactly_alex_and_todd_can_authenticate_case_insensitively(self):
        self.assertEqual(AuthStore(self.auth_db).users(), ["Alex", "Todd"])
        for username, display in (("alex", "Alex"), ("Todd", "Todd")):
            client = self.app.test_client()
            client.get("/login")
            with client.session_transaction() as state:
                token = state["csrf_token"]
            response = client.post("/login", data={
                "csrf_token": token, "username": username,
                "password": "test-password",
            })
            self.assertEqual(response.status_code, 302)
            with client.session_transaction() as state:
                self.assertEqual(state["authenticated_user"], display)

    def test_passwords_are_hashed_and_invalid_credentials_use_generic_failure(self):
        with sqlite3.connect(self.auth_db) as connection:
            rows = connection.execute("SELECT username_key, password_hash FROM users").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotIn("test-password", repr(rows))
        for username, password in (("Alex", "wrong"), ("Unknown", "test-password")):
            response = self.login(username, password)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Invalid username or password", response.data)
            self.assertNotIn(b"Unknown user", response.data)

    def test_repeated_login_failures_are_throttled(self):
        for _ in range(5):
            self.assertEqual(self.login("Alex", "wrong").status_code, 200)
        self.assertEqual(self.login("Alex", "wrong").status_code, 429)

    def test_login_rejects_external_redirect_and_logout_requires_csrf(self):
        response = self.login(next_path="https://attacker.example/")
        self.assertEqual(response.headers["Location"], "/findings")
        self.assertEqual(self.client.post("/logout", data={}).status_code, 400)
        with self.client.session_transaction() as state:
            token = state["csrf_token"]
        self.assertEqual(self.client.post("/logout", data={"csrf_token": token}).status_code, 302)
        self.assertEqual(self.client.get("/findings").status_code, 302)

    def test_authenticated_findings_view_reads_v15_without_mutation(self):
        directory = self.data / "generated/directory_955/full_955_enrichment_v15"
        directory.mkdir(parents=True)
        record = {
            "directory_record_id": "CFI-0753", "company": "Roadhouse & Rose Funeral Home",
            "city": "Newmarket", "province": "ON",
            "branch_safe_enrichment": {
                "emails": [{"value": "wes@example.test"}], "phones": [],
                "staff": [{"name": "Wes Playter", "title": "Owner"}],
                "decision_makers": [{"name": "Wes Playter", "title": "Owner"}],
                "has_any_contact": True,
            },
        }
        source = directory / "full_955_enrichment.json"
        source.write_text(json.dumps([record]))
        (directory / "summary.json").write_text(json.dumps({"after": {"named_staff": 1}}))
        before = source.read_bytes()
        self.login()
        response = self.client.get("/findings")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Roadhouse &amp; Rose Funeral Home", response.data)
        self.assertIn(b"Wes Playter", response.data)
        self.assertEqual(source.read_bytes(), before)

    def test_finding_detail_is_protected_escaped_and_unknown_ids_are_404(self):
        directory = self.data / "generated/directory_955/full_955_enrichment_v15"
        directory.mkdir(parents=True)
        (directory / "full_955_enrichment.json").write_text(json.dumps([{
            "directory_record_id": "CFI-0001", "company": "<script>alert(1)</script>",
            "city": "City", "province": "ON", "branch_safe_enrichment": {
                "emails": [{"value": "safe@example.test", "source_url": "https://example.test/contact"}],
                "phones": [], "staff": [], "decision_makers": [], "has_any_contact": True,
            },
        }]))
        (directory / "summary.json").write_text("{}")
        self.login()
        detail = self.client.get("/findings/CFI-0001")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", detail.data)
        self.assertNotIn(b"<script>alert(1)</script>", detail.data)
        self.assertIn(b"safe@example.test", detail.data)
        self.assertEqual(self.client.get("/findings/CFI-9999").status_code, 404)

    def test_findings_filters_compose_and_csv_export_matches_with_formula_safety(self):
        directory = self.data / "generated/directory_955/full_955_enrichment_v17"
        directory.mkdir(parents=True)
        records = [
            {"directory_record_id": "CFI-0001", "company": "=Unsafe Home", "city": "Calgary", "province": "AB", "website": "https://unsafe.test/", "branch_safe_enrichment": {"emails": [{"value": "info@unsafe.test"}], "phones": [], "staff": [], "decision_makers": [], "has_any_contact": True}},
            {"directory_record_id": "CFI-0002", "company": "Ontario Home", "city": "Ottawa", "province": "ON", "website": "", "branch_safe_enrichment": {"emails": [], "phones": [], "staff": [], "decision_makers": [], "has_any_contact": False}},
        ]
        (directory / "full_955_enrichment.json").write_text(json.dumps(records))
        (directory / "summary.json").write_text(json.dumps({"version": "V17"}))
        self.login()
        response = self.client.get("/findings?province=AB&contact=yes&website=yes&q=unsafe")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"=Unsafe Home", response.data)
        self.assertIn(b"https://unsafe.test/", response.data)
        self.assertNotIn(b"Ontario Home", response.data)
        self.assertIn(b"=Unsafe Home", self.client.get("/findings?q=unsafe.test").data)
        exported = self.client.get("/findings/export.csv?province=AB&contact=yes&website=yes&q=unsafe")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported.content_type)
        self.assertIn("'=Unsafe Home", exported.get_data(as_text=True))
        self.assertNotIn("Ontario Home", exported.get_data(as_text=True))
        self.assertEqual(self.client.get("/findings?province=XX").status_code, 400)
        self.assertEqual(self.client.get("/findings/export.csv?contact=maybe").status_code, 400)

    def test_findings_never_link_or_export_unsafe_website_schemes(self):
        directory = self.data / "generated/directory_955/full_955_enrichment_v17"
        directory.mkdir(parents=True)
        (directory / "full_955_enrichment.json").write_text(json.dumps([{
            "directory_record_id": "CFI-0001", "company": "Unsafe Link", "city": "City", "province": "ON",
            "website": "javascript:alert(1)", "branch_safe_enrichment": {
                "emails": [], "phones": [], "staff": [], "decision_makers": [], "has_any_contact": False,
            },
        }]))
        (directory / "summary.json").write_text("{}")
        self.login()
        listing = self.client.get("/findings")
        detail = self.client.get("/findings/CFI-0001")
        exported = self.client.get("/findings/export.csv").get_data(as_text=True)
        self.assertNotIn(b'href="javascript:', listing.data)
        self.assertNotIn(b'href="javascript:', detail.data)
        self.assertNotIn("javascript:alert", exported)
        self.assertNotIn("Unsafe Link", self.client.get("/findings?website=yes").get_data(as_text=True))

    def test_findings_counters_ignore_stale_summary_and_use_displayed_evidence(self):
        directory = self.data / "generated/directory_955/full_955_enrichment_v17"
        directory.mkdir(parents=True)
        records = [
            {"directory_record_id": "CFI-0001", "company": "Staff Only", "city": "Calgary", "province": "AB", "branch_safe_enrichment": {"emails": [], "phones": [], "staff": [{"name": "Alex Owner", "title": "Owner"}], "decision_makers": [{"name": "Alex Owner", "title": "Owner"}], "has_any_contact": False}},
            {"directory_record_id": "CFI-0002", "company": "Stale Flag", "city": "Ottawa", "province": "ON", "branch_safe_enrichment": {"emails": [], "phones": [], "staff": [], "decision_makers": [], "has_any_contact": True}},
        ]
        (directory / "full_955_enrichment.json").write_text(json.dumps(records))
        (directory / "summary.json").write_text(json.dumps({"after": {"businesses_with_any_safe_contact": 999, "businesses_with_decision_maker": 999, "named_staff": 999}}))
        self.login()
        response = self.client.get("/findings")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("999", body)
        self.assertIn("Safe contact or staff</span><strong>1</strong>", body)
        self.assertIn("With decision maker</span><strong>1</strong>", body)
        self.assertIn("Named decision makers</span><strong>1</strong>", body)
        self.assertIn("Named staff</span><strong>1</strong>", body)
        self.assertIn("Staff Only", self.client.get("/findings?contact=yes").get_data(as_text=True))
        self.assertNotIn("Stale Flag", self.client.get("/findings?contact=yes").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
