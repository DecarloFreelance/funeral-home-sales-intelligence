import json
import sqlite3

from canada_funeral_intel.agent_pipeline import _approved_website_ids


def test_approved_website_ids_applies_confidence_threshold(tmp_path):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE website_review_queue (id INTEGER PRIMARY KEY, website_id INTEGER, status TEXT)"
    )
    connection.executemany(
        "INSERT INTO website_review_queue(id, website_id, status) VALUES (?, ?, ?)",
        [(10, 101, "approved"), (11, 102, "approved"), (12, 103, "deferred")],
    )
    artifact = tmp_path / "review.json"
    artifact.write_text(
        json.dumps(
            {
                "recommendations": [
                    {"queue_id": 10, "decision": "approved", "confidence": 0.9},
                    {"queue_id": 11, "decision": "approved", "confidence": 0.8},
                    {"queue_id": 12, "decision": "approved", "confidence": 0.99},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _approved_website_ids(connection, artifact, 0.85) == [101]


def test_approved_website_ids_deduplicates_websites(tmp_path):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE website_review_queue (id INTEGER PRIMARY KEY, website_id INTEGER, status TEXT)"
    )
    connection.executemany(
        "INSERT INTO website_review_queue(id, website_id, status) VALUES (?, ?, ?)",
        [(20, 201, "approved"), (21, 201, "approved")],
    )
    artifact = tmp_path / "review.json"
    artifact.write_text(
        json.dumps(
            {
                "recommendations": [
                    {"queue_id": 20, "decision": "approved", "confidence": 0.95},
                    {"queue_id": 21, "decision": "approved", "confidence": 0.95},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _approved_website_ids(connection, artifact, 0.85) == [201]
