
import sqlite3
from datetime import datetime

from crm.database import connect


def initialize_events():

    conn = connect()

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS crm_events (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        domain TEXT,

        event_type TEXT,

        notes TEXT,

        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()



def add_event(
    domain,
    event_type,
    notes=""
):

    conn = connect()

    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO crm_events
        (
            domain,
            event_type,
            notes,
            created_at
        )

        VALUES (?,?,?,?)
        """,
        (
            domain,
            event_type,
            notes,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()



def get_history(domain):

    conn = connect()

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            event_type,
            notes,
            created_at

        FROM crm_events

        WHERE domain=?

        ORDER BY created_at DESC
        """,
        (domain,)
    )

    rows = cur.fetchall()

    conn.close()

    return rows
