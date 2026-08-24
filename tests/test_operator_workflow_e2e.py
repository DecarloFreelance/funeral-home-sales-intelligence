import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from operator_ui import create_app
from operator_ui.outreach_actions import draft_id


class OperatorWorkflowEndToEndTests(unittest.TestCase):
    def test_complete_local_operator_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            (data / "generated/campaign").mkdir(parents=True)
            (data / "generated/platform").mkdir(parents=True)
            database = data / "crm.sqlite"
            self.initialize_crm(database)

            draft = {
                "to": "owner@example.com",
                "subject": "A practical growth system",
                "body": "This remains an unsent test draft.",
            }
            self.write_json(
                data / "generated/platform/platform_candidate_outreach.json", [draft]
            )
            self.write_json(
                data / "generated/platform/platform_candidate_results.json",
                [{"domain": "example.com", "usable_emails": ["owner@example.com"]}],
            )

            def crawl_runner(input_path, output_path, report_path, progress_callback, **options):
                queue = json.loads(input_path.read_text(encoding="utf-8"))
                progress_callback(1, 2, queue[0]["domain"], 1)
                progress_callback(2, 2, queue[1]["domain"], 0)
                self.write_json(output_path, [{
                    "domain": "example.com", "url": "https://example.com/contact",
                    "text": "Jane Smith — Owner — owner@example.com",
                }])
                report = {
                    "queued_domains": 2, "successful_domains": 1,
                    "failed_domains": ["missing.example"], "pages": 1,
                }
                self.write_json(report_path, report)
                self.write_json(data / "research_queue.json", [{
                    "domain": "missing.example", "company": "Missing Home",
                    "failure_reason": "DNS_ERROR", "recommended_action": "Resolve website",
                    "locations": [{"city": "Calgary"}], "sources": ["manual"],
                }])
                self.write_json(data / "generated/campaign/results.json", [{
                    "domain": "example.com",
                    "business_profile": {"company": "Example Funeral Home"},
                    "executive_priority_score": 91,
                    "contact_quality_score": 88,
                    "recommended_contact_method": "Email",
                    "emails_found": ["owner@example.com"],
                    "contact_intelligence": {
                        "completeness_score": 85,
                        "people": [{"name": "Jane Smith", "title": "Owner"}],
                    },
                    "found": ["contact_form"], "missing": ["online_planner"],
                }])
                return report

            app = create_app({
                "TESTING": True, "DATA_ROOT": data, "CRM_DB": database,
                "CRAWL_RUNNER": crawl_runner,
            })
            client = app.test_client()
            csrf = self.csrf(client)

            preview = client.post("/imports/preview", data={
                "csrf_token": csrf, "confirm": "yes", "source_type": "manual",
                "source_file": (io.BytesIO(
                    b"company,website,city,province\n"
                    b"Example Funeral Home,example.com,Edmonton,AB\n"
                    b"Missing Home,missing.example,Calgary,AB\n"
                ), "fixture.csv"),
            }, content_type="multipart/form-data")
            self.assertEqual(preview.status_code, 200)
            import_token = next(iter(app.extensions["import_previews"]))
            self.assertEqual(client.post("/imports/confirm", data={
                "csrf_token": csrf, "confirm": "yes", "preview_token": import_token,
            }).status_code, 302)
            self.assertEqual(len(json.loads((data / "crawl_queue.json").read_text())), 2)

            self.assertEqual(client.post("/crawl/start", data={
                "csrf_token": csrf, "confirm": "yes", "mode": "replace",
                "offset": "0", "limit": "2", "max_pages": "2",
                "max_attempts": "2", "timeout": "5", "delay": "0",
            }).status_code, 302)
            for _ in range(100):
                job = next(iter(app.extensions["crawl_jobs"].values()))
                if job["status"] not in {"QUEUED", "RUNNING"}:
                    break
                time.sleep(0.01)
            self.assertEqual(job["status"], "COMPLETED")
            self.assertIn(b"missing.example", client.get("/research").data)

            resolution_preview = client.post("/research/preview", data={
                "csrf_token": csrf, "confirm": "yes", "old_domain": "missing.example",
                "new_website": "https://replacement.example/",
                "evidence_url": "https://directory.example/missing-home",
                "confidence": "MEDIUM", "notes": "Business name and city match.",
            })
            self.assertEqual(resolution_preview.status_code, 200)
            resolution_token = next(iter(app.extensions["resolution_previews"]))
            self.assertEqual(client.post("/research/confirm", data={
                "csrf_token": csrf, "confirm": "yes", "preview_token": resolution_token,
            }).status_code, 302)
            retry = json.loads((data / "resolved_retry_queue.json").read_text())
            self.assertEqual(retry[0]["domain"], "replacement.example")

            lead_detail = client.get("/leads/example.com")
            self.assertIn(b"Jane Smith", lead_detail.data)
            self.assertIn(b"owner@example.com", lead_detail.data)

            identifier = draft_id(draft)
            self.assertEqual(client.post(f"/drafts/{identifier}/approve", data={
                "csrf_token": csrf, "confirm": "yes",
            }).status_code, 302)
            approval = json.loads(
                (data / "private/outreach_approvals.json").read_text()
            )[0]
            self.assertEqual(approval["status"], "APPROVED_UNSENT")

            self.assertEqual(client.post("/crm/actions", data={
                "csrf_token": csrf, "confirm": "yes", "domain": "example.com",
                "action_type": "email", "priority": "A1 - Immediate Outreach",
            }).status_code, 302)
            self.assertEqual(client.post("/crm/actions/1/start", data={
                "csrf_token": csrf, "confirm": "yes",
            }).status_code, 302)
            self.assertEqual(client.post("/crm/actions/1/complete", data={
                "csrf_token": csrf, "confirm": "yes", "domain": "example.com",
                "result": "Owner requested a follow-up.",
            }).status_code, 302)
            with sqlite3.connect(database) as connection:
                status = connection.execute(
                    "SELECT status FROM action_queue WHERE id=1"
                ).fetchone()[0]
                events = connection.execute(
                    "SELECT event_type FROM crm_events ORDER BY id"
                ).fetchall()
            self.assertEqual(status, "COMPLETED")
            self.assertEqual(events, [("ACTION_STARTED",), ("ACTION_COMPLETED",)])

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def csrf(client):
        client.get("/imports")
        with client.session_transaction() as session:
            return session["csrf_token"]

    @staticmethod
    def initialize_crm(path):
        with sqlite3.connect(path) as connection:
            connection.executescript("""
                CREATE TABLE leads (
                    domain TEXT PRIMARY KEY, pipeline_stage TEXT, attempts INTEGER,
                    next_action TEXT, follow_up_date TEXT,
                    crm_sync_safe INTEGER NOT NULL, outreach_ready INTEGER NOT NULL
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
                INSERT INTO leads VALUES ('example.com', 'NEW', 0, '', '', 1, 1);
            """)


if __name__ == "__main__":
    unittest.main()
