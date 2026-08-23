import sqlite3
import tempfile
import unittest
from pathlib import Path

from crm import database
from crm.action_queue import create_action, initialize_queue
from crm.database import initialize, upsert_lead
from crm.events import get_history
from crm.execution import complete_action, execute_next_action, start_action
from intelligence.lead_intelligence import LeadIntelligence


class CrmWorkflowTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db = database.DB
        database.DB = Path(self.temp_dir.name) / "crm.sqlite"
        initialize()
        initialize_queue()

    def tearDown(self):
        database.DB = self.original_db
        self.temp_dir.cleanup()

    def add_lead(self, domain="example.com"):
        upsert_lead({
            "domain": domain,
            "pipeline_stage": "NEW",
            "crm_status": "NEW",
            "priority_score": 190,
            "priority_level": "A1 - Immediate Outreach",
            "contact_method": "email",
            "primary_email": "info@example.com",
            "primary_phone": "780-555-1234",
            "next_action": "Send email outreach",
            "follow_up_date": "2026-08-23",
        })

    def test_initialize_queue_applies_execution_columns(self):
        with sqlite3.connect(database.DB) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(action_queue)")
            }

        self.assertIn("started_at", columns)
        self.assertIn("completed_at", columns)

    def test_initialize_migrates_company_name_for_existing_database(self):
        database.DB.unlink()
        with sqlite3.connect(database.DB) as conn:
            conn.execute("CREATE TABLE leads (domain TEXT PRIMARY KEY)")

        initialize()

        with sqlite3.connect(database.DB) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
        self.assertIn("company_name", columns)

    def test_create_action_reuses_active_action(self):
        first_id = create_action(
            "example.com", "email", "A1 - Immediate Outreach"
        )
        second_id = create_action(
            "example.com", "email", "A1 - Immediate Outreach"
        )

        self.assertEqual(first_id, second_id)

        with sqlite3.connect(database.DB) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM action_queue"
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_action_lifecycle_updates_lead_and_events(self):
        self.add_lead()
        create_action(
            "example.com", "email", "A1 - Immediate Outreach"
        )

        started = execute_next_action()
        self.assertEqual(started["domain"], "example.com")

        with sqlite3.connect(database.DB) as conn:
            action = conn.execute(
                "SELECT status, started_at FROM action_queue"
            ).fetchone()
            lead = conn.execute(
                "SELECT pipeline_stage, attempts FROM leads "
                "WHERE domain='example.com'"
            ).fetchone()

        self.assertEqual(action[0], "IN_PROGRESS")
        self.assertIsNotNone(action[1])
        self.assertEqual(lead, ("CONTACTED", 1))
        self.assertTrue(complete_action("example.com", "Reached owner"))
        self.assertFalse(complete_action("example.com", "Duplicate completion"))

        with sqlite3.connect(database.DB) as conn:
            action = conn.execute(
                "SELECT status, completed_at FROM action_queue"
            ).fetchone()

        self.assertEqual(action[0], "COMPLETED")
        self.assertIsNotNone(action[1])
        self.assertEqual(
            [event[0] for event in get_history("example.com")],
            ["ACTION_COMPLETED", "ACTION_STARTED"]
        )

    def test_empty_queue_returns_none(self):
        self.assertIsNone(execute_next_action())

    def test_start_action_rolls_back_when_lead_is_missing(self):
        action_id = create_action(
            "missing.example", "email", "A1 - Immediate Outreach"
        )

        self.assertIsNone(start_action(action_id))

        with sqlite3.connect(database.DB) as conn:
            status = conn.execute(
                "SELECT status FROM action_queue WHERE id=?", (action_id,)
            ).fetchone()[0]
            events = conn.execute("SELECT COUNT(*) FROM crm_events").fetchone()[0]

        self.assertEqual(status, "OPEN")
        self.assertEqual(events, 0)


class LeadIntelligenceTests(unittest.TestCase):

    def test_crm_state_uses_calculated_outreach_priority(self):
        lead = LeadIntelligence.from_result({
            "domain": "example.com",
            "sales_readiness": 200,
            "emails_found": ["info@example.com"],
            "phones_found": [],
            "outreach_priority": "Research Required",
            "outreach_channel": "research",
        }).to_dict()

        self.assertEqual(
            lead["outreach"]["priority_level"],
            "A1 - Immediate Outreach"
        )
        self.assertEqual(lead["crm"]["pipeline_stage"], "CONTACTED")
        self.assertEqual(
            lead["crm"]["next_action"],
            "Send email outreach"
        )

    def test_preserves_structured_contact_intelligence(self):
        lead = LeadIntelligence.from_result({
            "domain": "example.com",
            "business_profile": {
                "company": "Example Funeral Home",
                "business_names": ["Example Funeral Home"],
                "locations": [{"city": "Edmonton"}],
                "sources": ["association"],
                "provenance": [{"source": "association"}],
            },
            "contact_intelligence": {
                "business_names": ["Example Funeral Home"],
                "addresses": [{"city": "Edmonton"}],
                "people": [{"name": "Jane Smith", "title": "Owner"}],
                "completeness_score": 50,
            },
        }).to_dict()

        self.assertEqual(lead["contacts"]["people"][0]["name"], "Jane Smith")
        self.assertEqual(lead["contacts"]["addresses"][0]["city"], "Edmonton")
        self.assertEqual(lead["contacts"]["completeness_score"], 50)
        self.assertEqual(lead["company"]["name"], "Example Funeral Home")
        self.assertEqual(lead["company"]["sources"], ["association"])


if __name__ == "__main__":
    unittest.main()
