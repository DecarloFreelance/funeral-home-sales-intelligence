
from datetime import datetime, timedelta

from crm.database import connect


def initialize_queue(db_path=None):

    conn = connect(db_path)

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

    migrate_action_queue(db_path)



def create_action(
    domain,
    action_type,
    priority,
    notes="",
    db_path=None,
):

    conn = connect(db_path)

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
        SELECT id
        FROM action_queue
        WHERE domain=?
          AND action_type=?
          AND status IN ('OPEN', 'IN_PROGRESS')
        ORDER BY id
        LIMIT 1
        """,
        (domain, action_type)
    )

    existing = cur.fetchone()

    if existing:
        conn.close()
        return existing[0]

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

    action_id = cur.lastrowid
    conn.commit()
    conn.close()

    return action_id



def get_open_actions(db_path=None):

    conn = connect(db_path)

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


def migrate_action_queue(db_path=None):
    conn = connect(db_path)
    cur = conn.cursor()


    columns = {
        "started_at": "TEXT",
        "completed_at": "TEXT",
    }


    cur.execute(
        "PRAGMA table_info(action_queue)"
    )

    existing = {
        row[1]
        for row in cur.fetchall()
    }


    for name, dtype in columns.items():

        if name not in existing:

            cur.execute(
                f"""
                ALTER TABLE action_queue
                ADD COLUMN {name} {dtype}
                """
            )


    conn.commit()
    conn.close()
