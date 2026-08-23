
import sqlite3
from pathlib import Path
from datetime import datetime


DB = Path("data/crm.sqlite")


def connect(db_path=None):
    path = Path(db_path) if db_path else DB
    path.parent.mkdir(parents=True, exist_ok=True)

    return sqlite3.connect(path)


def initialize():

    from crm.events import initialize_events

    initialize_events()

    conn = connect()

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS leads (

        domain TEXT PRIMARY KEY,

        company_name TEXT,

        pipeline_stage TEXT,
        crm_status TEXT,

        priority_score REAL,
        priority_level TEXT,

        contact_method TEXT,

        primary_email TEXT,
        primary_phone TEXT,

        attempts INTEGER DEFAULT 0,

        next_action TEXT,
        follow_up_date TEXT,

        updated_at TEXT
    )
    """)

    columns = {row[1] for row in cur.execute("PRAGMA table_info(leads)")}
    if "company_name" not in columns:
        cur.execute("ALTER TABLE leads ADD COLUMN company_name TEXT")

    conn.commit()
    conn.close()



def upsert_lead(data):

    conn = connect()

    cur = conn.cursor()


    cur.execute("""
    INSERT INTO leads (

        domain,
        company_name,
        pipeline_stage,
        crm_status,
        priority_score,
        priority_level,
        contact_method,
        primary_email,
        primary_phone,
        next_action,
        follow_up_date,
        updated_at

    )

    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)

    ON CONFLICT(domain)
    DO UPDATE SET

        company_name=excluded.company_name,
        pipeline_stage=excluded.pipeline_stage,
        crm_status=excluded.crm_status,
        priority_score=excluded.priority_score,
        priority_level=excluded.priority_level,
        contact_method=excluded.contact_method,
        primary_email=excluded.primary_email,
        primary_phone=excluded.primary_phone,
        next_action=excluded.next_action,
        follow_up_date=excluded.follow_up_date,
        updated_at=excluded.updated_at

    """,

    (
        data["domain"],
        data.get("company_name", ""),
        data["pipeline_stage"],
        data["crm_status"],
        data["priority_score"],
        data["priority_level"],
        data["contact_method"],
        data["primary_email"],
        data["primary_phone"],
        data["next_action"],
        data["follow_up_date"],
        datetime.utcnow().isoformat()
    ))


    conn.commit()
    conn.close()
