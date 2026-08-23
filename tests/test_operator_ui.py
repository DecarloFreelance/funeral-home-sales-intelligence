import json
import io
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from operator_ui import create_app
from operator_ui.outreach_actions import draft_id
from operator_ui.research_actions import apply_reviewed_resolution


class OperatorUiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        (self.data / "generated/campaign").mkdir(parents=True)
        (self.data / "generated/platform").mkdir(parents=True)
        self.app = create_app({"TESTING": True, "DATA_ROOT": self.data})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def write_json(self, relative, value):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_all_views_have_safe_empty_states(self):
        for path in ["/", "/queues", "/imports", "/crawl", "/research", "/leads", "/quality", "/candidates", "/drafts", "/crm/actions"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_dashboard_and_queue_render_fixture_counts(self):
        self.write_json("crawl_queue.json", [{"company": "Example Home", "domain": "example.com"}])
        self.write_json("research_queue.json", [{"domain": "missing.example"}])
        response = self.client.get("/")
        self.assertIn(b"Queued domains", response.data)
        self.assertIn(b"Research items", response.data)
        queue = self.client.get("/queues")
        self.assertIn(b"Example Home", queue.data)
        self.assertIn(b"example.com", queue.data)

    def test_lead_list_links_to_escaped_detail(self):
        self.write_json("generated/campaign/results.json", [{
            "domain": "example.com",
            "business_profile": {"company": "Example <Home>"},
            "executive_priority_score": 88,
            "contact_intelligence": {"people": [{"name": "Jane Smith", "title": "Owner"}]},
            "emails_found": ["info@example.com"],
        }])
        listing = self.client.get("/leads")
        self.assertIn(b"Example &lt;Home&gt;", listing.data)
        detail = self.client.get("/leads/example.com")
        self.assertIn(b"Jane Smith", detail.data)
        self.assertIn(b"CRM sync:</strong> not checked", detail.data)
        self.assertEqual(self.client.get("/leads/not-found.example").status_code, 404)

    def test_enrichment_and_quality_uncertainty_are_visible(self):
        self.write_json("generated/enrichment/results.json", [{
            "domain": "example.com", "business_profile": {"company": "Example"},
            "enrichment": {"detector": "fixture", "detector_version": "1", "facts": [{
                "field": "contact.role_category", "value": {"role": "OWNER"},
                "verification_state": "INFERRED", "derived": True,
                "source_url": "https://example.com/team", "observed_at": "2026-08-23T00:00:00Z",
                "confidence": 0.9, "evidence": "Derived from observed title: Owner",
            }]},
            "quality_control": {"status": "NEEDS_REVIEW", "findings": [{
                "severity": "MEDIUM", "code": "CONFLICTING_FACTS",
                "message": "Sources disagree.", "recommended_action": "Research both sources.",
            }], "crm_sync_safe": False, "outreach_ready": False,
                "crm_blocking_reasons": ["CONFLICTING_FACTS"]},
        }])
        self.write_json("generated/enrichment/review_queue.json", [{
            "domain": "example.com", "status": "NEEDS_REVIEW", "crm_sync_safe": False,
            "findings": [{"severity": "MEDIUM", "code": "CONFLICTING_FACTS",
                "message": "Sources disagree.", "recommended_action": "Research both sources."}],
        }])

        detail = self.client.get("/leads/example.com")
        self.assertIn(b"INFERRED", detail.data)
        self.assertIn(b"Derived from observed title", detail.data)
        self.assertIn(b"CRM sync:</strong> blocked", detail.data)
        listing = self.client.get("/leads")
        self.assertIn(b"Blocked by quality", listing.data)
        review = self.client.get("/quality")
        self.assertIn(b"CONFLICTING_FACTS", review.data)
        self.assertIn(b"CRM sync safe: no", review.data)

    def test_crm_actions_are_read_from_configured_database(self):
        database = self.data / "custom.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("""CREATE TABLE action_queue (
                id INTEGER PRIMARY KEY, domain TEXT, action_type TEXT, priority TEXT,
                status TEXT, due_date TEXT, notes TEXT, created_at TEXT,
                started_at TEXT, completed_at TEXT)""")
            connection.execute("INSERT INTO action_queue VALUES (1, 'example.com', 'email', 'A1', 'OPEN', '2026-08-22', '', '', NULL, NULL)")
        app = create_app({"TESTING": True, "DATA_ROOT": self.data, "CRM_DB": database})
        response = app.test_client().get("/crm/actions")
        self.assertIn(b"example.com", response.data)
        self.assertIn(b"OPEN", response.data)

    def create_crm_database(self):
        database = self.data / "workflow.sqlite"
        with sqlite3.connect(database) as connection:
            connection.executescript("""
                CREATE TABLE leads (
                    domain TEXT PRIMARY KEY, pipeline_stage TEXT, attempts INTEGER,
                    next_action TEXT, follow_up_date TEXT
                );
                CREATE TABLE action_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT,
                    action_type TEXT, priority TEXT, status TEXT, due_date TEXT,
                    notes TEXT, created_at TEXT, started_at TEXT, completed_at TEXT
                );
                CREATE TABLE crm_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT,
                    event_type TEXT, notes TEXT, created_at TEXT
                );
                INSERT INTO leads VALUES ('example.com', 'NEW', 0, '', '');
            """)
        return database

    def csrf(self, client):
        client.get("/crm/actions")
        with client.session_transaction() as session:
            return session["csrf_token"]

    def test_crm_posts_require_csrf_and_confirmation(self):
        database = self.create_crm_database()
        app = create_app({"TESTING": True, "DATA_ROOT": self.data, "CRM_DB": database})
        client = app.test_client()

        self.assertEqual(client.post("/crm/actions", data={}).status_code, 400)
        token = self.csrf(client)
        response = client.post("/crm/actions", data={"csrf_token": token})
        self.assertEqual(response.status_code, 400)

        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM action_queue").fetchone()[0], 0)

    def test_crm_action_lifecycle_through_confirmed_posts(self):
        database = self.create_crm_database()
        app = create_app({"TESTING": True, "DATA_ROOT": self.data, "CRM_DB": database})
        client = app.test_client()
        token = self.csrf(client)

        created = client.post("/crm/actions", data={
            "csrf_token": token, "confirm": "yes", "domain": "example.com",
            "action_type": "email", "priority": "A1 - Immediate Outreach",
        })
        self.assertEqual(created.status_code, 302)
        started = client.post("/crm/actions/1/start", data={"csrf_token": token, "confirm": "yes"})
        self.assertEqual(started.status_code, 302)
        completed = client.post("/crm/actions/1/complete", data={
            "csrf_token": token, "confirm": "yes", "domain": "example.com",
            "result": "Reached owner",
        })
        self.assertEqual(completed.status_code, 302)

        with sqlite3.connect(database) as connection:
            status = connection.execute("SELECT status FROM action_queue WHERE id=1").fetchone()[0]
            attempts = connection.execute("SELECT attempts FROM leads WHERE domain='example.com'").fetchone()[0]
            events = connection.execute("SELECT event_type FROM crm_events ORDER BY id").fetchall()
        self.assertEqual(status, "COMPLETED")
        self.assertEqual(attempts, 1)
        self.assertEqual(events, [("ACTION_STARTED",), ("ACTION_COMPLETED",)])

    def test_crm_action_rejects_unknown_lead_without_mutation(self):
        database = self.create_crm_database()
        app = create_app({"TESTING": True, "DATA_ROOT": self.data, "CRM_DB": database})
        client = app.test_client()
        token = self.csrf(client)
        response = client.post("/crm/actions", data={
            "csrf_token": token, "confirm": "yes", "domain": "unknown.example",
            "action_type": "email", "priority": "A1 - Immediate Outreach",
        })
        self.assertEqual(response.status_code, 400)
        with sqlite3.connect(database) as connection:
            count = connection.execute("SELECT COUNT(*) FROM action_queue").fetchone()[0]
        self.assertEqual(count, 0)

    def test_import_preview_does_not_write_until_confirmed(self):
        client = self.app.test_client()
        token = self.csrf(client)
        response = client.post("/imports/preview", data={
            "csrf_token": token, "confirm": "yes", "source_type": "manual",
            "source_file": (io.BytesIO(
                b"company,website,city,province\nExample Home,example.com,Edmonton,AB\n"
            ), "leads.csv"),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"1 unique domains", response.data)
        self.assertFalse((self.data / "crawl_queue.json").exists())

        with client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        preview_token = next(iter(self.app.extensions["import_previews"]))
        confirmed = client.post("/imports/confirm", data={
            "csrf_token": csrf_token, "confirm": "yes", "preview_token": preview_token,
        })
        self.assertEqual(confirmed.status_code, 302)
        queue = json.loads((self.data / "crawl_queue.json").read_text())
        self.assertEqual(queue[0]["domain"], "example.com")

        reused = client.post("/imports/confirm", data={
            "csrf_token": csrf_token, "confirm": "yes", "preview_token": preview_token,
        })
        self.assertEqual(reused.status_code, 409)

    def test_invalid_import_never_changes_existing_queue(self):
        original = [{"domain": "keep.example"}]
        self.write_json("crawl_queue.json", original)
        client = self.app.test_client()
        token = self.csrf(client)
        response = client.post("/imports/preview", data={
            "csrf_token": token, "confirm": "yes", "source_type": "manual",
            "source_file": (io.BytesIO(b"company,website\nBroken,not-a-domain\n"), "bad.csv"),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads((self.data / "crawl_queue.json").read_text()), original)

    def test_confirmed_crawl_runs_with_bounded_options(self):
        self.write_json("crawl_queue.json", [{"domain": "example.com"}])
        called = {}

        def runner(input_path, output_path, **options):
            called.update(options)
            options["progress_callback"](1, 1, "example.com", 2)
            output_path.write_text("[]", encoding="utf-8")
            return {"queued_domains": 1, "successful_domains": 1, "pages": 2}

        app = create_app({"TESTING": True, "DATA_ROOT": self.data, "CRAWL_RUNNER": runner})
        client = app.test_client()
        token = self.csrf(client)
        response = client.post("/crawl/start", data={
            "csrf_token": token, "confirm": "yes", "mode": "resume",
            "offset": "2", "limit": "3", "max_pages": "4", "max_attempts": "5",
            "timeout": "6", "delay": "0.1",
        })
        self.assertEqual(response.status_code, 302)
        for _ in range(100):
            job = next(iter(app.extensions["crawl_jobs"].values()))
            if job["status"] not in {"QUEUED", "RUNNING"}:
                break
            time.sleep(0.01)
        self.assertEqual(job["status"], "COMPLETED")
        self.assertTrue(called["append"])
        self.assertEqual(called["offset"], 2)
        self.assertEqual(called["limit"], 3)
        self.assertEqual(job["pages"], 2)

    def test_crawl_rejects_invalid_options_without_starting(self):
        self.write_json("crawl_queue.json", [{"domain": "example.com"}])
        client = self.app.test_client()
        token = self.csrf(client)
        response = client.post("/crawl/start", data={
            "csrf_token": token, "confirm": "yes", "mode": "replace",
            "offset": "0", "limit": "999", "max_pages": "5",
            "max_attempts": "5", "timeout": "10", "delay": "0.25",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.app.extensions["crawl_jobs"], {})

    def test_only_one_crawl_can_run_at_a_time(self):
        self.write_json("crawl_queue.json", [{"domain": "example.com"}])
        release = threading.Event()

        def runner(*args, **kwargs):
            release.wait(2)
            return {"queued_domains": 1, "successful_domains": 1, "pages": 1}

        app = create_app({"TESTING": True, "DATA_ROOT": self.data, "CRAWL_RUNNER": runner})
        client = app.test_client()
        token = self.csrf(client)
        form = {
            "csrf_token": token, "confirm": "yes", "mode": "resume", "offset": "0",
            "limit": "1", "max_pages": "1", "max_attempts": "1",
            "timeout": "1", "delay": "0",
        }
        self.assertEqual(client.post("/crawl/start", data=form).status_code, 302)
        self.assertEqual(client.post("/crawl/start", data=form).status_code, 409)
        release.set()

    def test_reviewed_resolution_preview_and_confirmation(self):
        self.write_json("research_queue.json", [{
            "domain": "old.example", "company": "Example Home",
            "locations": [{"city": "Edmonton"}], "sources": ["association"],
        }])
        self.write_json("discovered_leads.json", [])
        self.write_json("seeds/domain_resolutions.json", [])
        client = self.app.test_client()
        token = self.csrf(client)
        preview = client.post("/research/preview", data={
            "csrf_token": token, "confirm": "yes", "old_domain": "old.example",
            "new_website": "https://new.example/about",
            "evidence_url": "https://directory.example/listing",
            "confidence": "HIGH", "notes": "Company and address match.",
        })
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"RETRY_READY", preview.data)
        self.assertFalse((self.data / "resolved_retry_queue.json").exists())

        preview_token = next(iter(self.app.extensions["resolution_previews"]))
        confirmed = client.post("/research/confirm", data={
            "csrf_token": token, "confirm": "yes", "preview_token": preview_token,
        })
        self.assertEqual(confirmed.status_code, 302)
        ledger = json.loads((self.data / "seeds/domain_resolutions.json").read_text())
        retry = json.loads((self.data / "resolved_retry_queue.json").read_text())
        self.assertEqual(ledger[0]["old_domain"], "old.example")
        self.assertEqual(retry[0]["domain"], "new.example")
        self.assertEqual(client.post("/research/confirm", data={
            "csrf_token": token, "confirm": "yes", "preview_token": preview_token,
        }).status_code, 409)

    def test_invalid_resolution_does_not_write_ledger(self):
        self.write_json("research_queue.json", [{
            "domain": "old.example", "company": "Example Home",
        }])
        client = self.app.test_client()
        token = self.csrf(client)
        response = client.post("/research/preview", data={
            "csrf_token": token, "confirm": "yes", "old_domain": "old.example",
            "new_website": "javascript:alert(1)",
            "evidence_url": "https://evidence.example/item",
            "confidence": "HIGH", "notes": "Looks similar.",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.data / "seeds/domain_resolutions.json").exists())

    def test_resolution_file_failure_rolls_back_every_output(self):
        self.write_json("research_queue.json", [{
            "domain": "old.example", "company": "Original",
        }])
        self.write_json("seeds/domain_resolutions.json", [])
        self.write_json("resolved_retry_queue.json", [{"domain": "keep.example"}])
        self.write_json("resolution_summary.json", {"original": True})
        original = {
            path: (self.data / path).read_bytes()
            for path in [
                "research_queue.json", "seeds/domain_resolutions.json",
                "resolved_retry_queue.json", "resolution_summary.json",
            ]
        }
        calls = 0

        def fail_on_third(source, target):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("simulated replacement failure")
            source.replace(target)

        with self.assertRaisesRegex(OSError, "simulated"):
            apply_reviewed_resolution(self.data, {
                "old_domain": "old.example", "new_website": "https://new.example/",
                "confidence": "HIGH", "evidence_url": "https://evidence.example/",
                "notes": "Reviewed match",
            }, replace=fail_on_third)

        for path, content in original.items():
            self.assertEqual((self.data / path).read_bytes(), content)

    def test_usable_draft_can_be_approved_but_is_never_changed(self):
        draft = {"to": "info@example.com", "subject": "Hello", "body": "Draft body"}
        self.write_json("generated/platform/platform_candidate_outreach.json", [draft])
        self.write_json("generated/platform/platform_candidate_results.json", [{
            "domain": "example.com", "usable_emails": ["info@example.com"],
        }])
        client = self.app.test_client()
        token = self.csrf(client)
        identifier = draft_id(draft)
        response = client.post(f"/drafts/{identifier}/approve", data={
            "csrf_token": token, "confirm": "yes",
        })
        self.assertEqual(response.status_code, 302)
        approvals = json.loads((self.data / "private/outreach_approvals.json").read_text())
        self.assertEqual(approvals[0]["status"], "APPROVED_UNSENT")
        self.assertEqual(approvals[0]["draft_id"], identifier)
        current_drafts = json.loads(
            (self.data / "generated/platform/platform_candidate_outreach.json").read_text()
        )
        self.assertEqual(current_drafts, [draft])

        duplicate = client.post(f"/drafts/{identifier}/approve", data={
            "csrf_token": token, "confirm": "yes",
        })
        self.assertEqual(duplicate.status_code, 302)
        approvals = json.loads((self.data / "private/outreach_approvals.json").read_text())
        self.assertEqual(len(approvals), 1)

    def test_draft_with_unusable_email_cannot_be_approved(self):
        draft = {"to": "wrong@elsewhere.example", "subject": "Hello", "body": "Draft"}
        self.write_json("generated/platform/platform_candidate_outreach.json", [draft])
        self.write_json("generated/platform/platform_candidate_results.json", [{
            "domain": "example.com", "usable_emails": ["info@example.com"],
        }])
        client = self.app.test_client()
        token = self.csrf(client)
        response = client.post(f"/drafts/{draft_id(draft)}/approve", data={
            "csrf_token": token, "confirm": "yes",
        })
        self.assertEqual(response.status_code, 409)
        self.assertFalse((self.data / "private/outreach_approvals.json").exists())


if __name__ == "__main__":
    unittest.main()
