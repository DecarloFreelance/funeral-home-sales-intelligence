from datetime import datetime, timezone

from crm.database import connect


def initialize_sync(db_path=None):
    with connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS external_crm_records (
                backend TEXT NOT NULL,
                domain TEXT NOT NULL,
                remote_id TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                PRIMARY KEY (backend, domain)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS external_crm_sync_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backend TEXT NOT NULL,
                domain TEXT NOT NULL,
                status TEXT NOT NULL,
                remote_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL
            )
        """)


def _account_payload(row):
    domain, company, score, level, email, phone, stage, status = row
    return {
        "name": company or domain,
        "website": f"https://{domain}",
        "emailAddress": email or None,
        "phoneNumber": phone or None,
        "description": (
            f"Local pipeline stage: {stage or 'UNKNOWN'}\n"
            f"Local CRM status: {status or 'UNKNOWN'}\n"
            f"Priority: {level or 'UNKNOWN'} ({score or 0})"
        ),
    }


def sync_lead(domain, backend, db_path=None, backend_name="espocrm"):
    """Synchronize one local lead and audit success/failure without changing it."""
    initialize_sync(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT domain, company_name, priority_score, priority_level, primary_email,
                      primary_phone, pipeline_stage, crm_status
               FROM leads WHERE domain=?""",
            (domain,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown local CRM lead: {domain}")
        mapped = conn.execute(
            """SELECT remote_id FROM external_crm_records
               WHERE backend=? AND domain=?""",
            (backend_name, domain),
        ).fetchone()
        remote_id = mapped[0] if mapped else None

    try:
        remote_id = backend.upsert_account(domain, _account_payload(row), remote_id)
    except Exception as error:
        with connect(db_path) as conn:
            conn.execute(
                """INSERT INTO external_crm_sync_events
                   (backend, domain, status, remote_id, error, created_at)
                   VALUES (?, ?, 'FAILED', ?, ?, ?)""",
                (backend_name, domain, remote_id, error.__class__.__name__, now),
            )
        raise

    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO external_crm_records
               (backend, domain, remote_id, synced_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(backend, domain) DO UPDATE SET
                   remote_id=excluded.remote_id, synced_at=excluded.synced_at""",
            (backend_name, domain, remote_id, now),
        )
        conn.execute(
            """INSERT INTO external_crm_sync_events
               (backend, domain, status, remote_id, error, created_at)
               VALUES (?, ?, 'SUCCEEDED', ?, NULL, ?)""",
            (backend_name, domain, remote_id, now),
        )
    return remote_id
