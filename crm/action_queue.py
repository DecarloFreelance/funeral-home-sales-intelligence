
from datetime import datetime, timedelta

from crm.database import connect


def initialize_queue():

    conn = connect()

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS action_queue (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        domain TEXT,

        action_type TEXT,

        priority TEXT,

        status TEXT,

        due_date TEXT,

        notes TEXT,

        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()



def create_action(
    domain,
    action_type,
    priority,
    notes=""
):

    conn = connect()

    cur = conn.cursor()

    days = {
        "A1 - Immediate Outreach": 0,
        "A2 - Priority Outreach": 2,
        "B1 - Nurture": 7,
        "Research Required": 14
    }

    due = datetime.utcnow() + timedelta(
        days=days.get(priority, 14)
    )

    cur.execute(
        """
        INSERT INTO action_queue
        (
            domain,
            action_type,
            priority,
            status,
            due_date,
            notes,
            created_at
        )

        VALUES (?,?,?,?,?,?,?)
        """,
        (
            domain,
            action_type,
            priority,
            "OPEN",
            due.date().isoformat(),
            notes,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()



def get_open_actions():

    conn = connect()

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            domain,
            action_type,
            priority,
            due_date,
            notes

        FROM action_queue

        WHERE status='OPEN'

        ORDER BY due_date
        """
    )

    rows = cur.fetchall()

    conn.close()

    return rows
