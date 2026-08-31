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
        for path in ("/", "/findings", "/leads", "/quality", "/crm/actions"):
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


if __name__ == "__main__":
    unittest.main()
