import sqlite3
import tempfile
import unittest
from pathlib import Path

import requests

from crm import database
from crm.database import initialize, upsert_lead
from crm.espocrm import EspoCRMBackend, EspoCRMError
from crm.sync import sync_lead


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("failed")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


class FakeBackend:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def upsert_account(self, domain, payload, remote_id=None):
        self.calls.append((domain, payload, remote_id))
        if self.error:
            raise self.error
        return remote_id or "remote-1"


class EspoCRMBackendTests(unittest.TestCase):
    def test_requires_tls_for_non_local_api_key_transport(self):
        with self.assertRaises(ValueError):
            EspoCRMBackend("http://crm.example", "private-key")

    def test_finds_existing_account_before_create_for_retry_idempotency(self):
        session = FakeSession([
            FakeResponse({"list": [{"id": "remote-existing"}], "total": 1}),
            FakeResponse({"id": "remote-existing"}),
        ])
        backend = EspoCRMBackend(
            "https://crm.example", "private-key", session=session, retries=0,
        )

        result = backend.upsert_account("example.ca", {"name": "Example"})

        self.assertEqual(result, "remote-existing")
        self.assertEqual([call[0] for call in session.calls], ["GET", "PUT"])
        self.assertEqual(
            session.calls[0][2]["params"]["where[0][value]"],
            "https://example.ca",
        )

    def test_uses_api_key_and_updates_known_record(self):
        session = FakeSession([FakeResponse({"id": "remote-1"})])
        backend = EspoCRMBackend(
            "https://crm.example", "private-key", session=session, retries=0,
        )

        result = backend.upsert_account(
            "example.ca", {"name": "Example"}, "remote-1",
        )

        self.assertEqual(result, "remote-1")
        method, url, options = session.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "https://crm.example/api/v1/Account/remote-1")
        self.assertEqual(options["headers"]["X-Api-Key"], "private-key")

    def test_escapes_remote_id_and_accepts_boolean_update_response(self):
        session = FakeSession([FakeResponse(True)])
        backend = EspoCRMBackend(
            "https://crm.example", "private-key", session=session, retries=0,
        )

        result = backend.upsert_account(
            "example.ca", {"name": "Example"}, "remote/id",
        )

        self.assertEqual(result, "remote/id")
        self.assertTrue(session.calls[0][1].endswith("/Account/remote%2Fid"))

    def test_failure_does_not_expose_api_key(self):
        backend = EspoCRMBackend(
            "https://crm.example", "private-key",
            session=FakeSession([FakeResponse({}, 500)]), retries=0,
        )
        with self.assertRaises(EspoCRMError) as caught:
            backend.upsert_account("example.ca", {"name": "Example"})
        self.assertNotIn("private-key", str(caught.exception))


class EspoCRMSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db = database.DB
        database.DB = Path(self.temp_dir.name) / "crm.sqlite"
        initialize()
        upsert_lead({
            "domain": "example.ca", "pipeline_stage": "NEW", "crm_status": "NEW",
            "priority_score": 150, "priority_level": "A2 - Priority Outreach",
            "contact_method": "email", "primary_email": "info@example.ca",
            "primary_phone": "+14035551234", "next_action": "Review",
            "follow_up_date": "2026-08-23",
        })

    def tearDown(self):
        database.DB = self.original_db
        self.temp_dir.cleanup()

    def test_reuses_remote_mapping_and_audits_each_success(self):
        backend = FakeBackend()

        self.assertEqual(sync_lead("example.ca", backend), "remote-1")
        self.assertEqual(sync_lead("example.ca", backend), "remote-1")

        self.assertIsNone(backend.calls[0][2])
        self.assertEqual(backend.calls[1][2], "remote-1")
        self.assertEqual(backend.calls[0][1]["emailAddress"], "info@example.ca")
        with sqlite3.connect(database.DB) as conn:
            events = conn.execute(
                "SELECT status FROM external_crm_sync_events ORDER BY id"
            ).fetchall()
        self.assertEqual(events, [("SUCCEEDED",), ("SUCCEEDED",)])

    def test_remote_failure_does_not_change_local_lead_or_store_secret(self):
        backend = FakeBackend(RuntimeError("secret-value"))

        with self.assertRaises(RuntimeError):
            sync_lead("example.ca", backend)

        with sqlite3.connect(database.DB) as conn:
            lead = conn.execute(
                "SELECT pipeline_stage, crm_status FROM leads WHERE domain='example.ca'"
            ).fetchone()
            event = conn.execute(
                "SELECT status, error FROM external_crm_sync_events"
            ).fetchone()
        self.assertEqual(lead, ("NEW", "NEW"))
        self.assertEqual(event, ("FAILED", "RuntimeError"))


if __name__ == "__main__":
    unittest.main()
