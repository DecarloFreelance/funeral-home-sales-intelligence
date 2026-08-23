
from datetime import datetime, timedelta

from crm.database import connect


def execute_next_action(db_path=None):

    conn = connect(db_path)

    cur = conn.cursor()


    cur.execute("""
    SELECT
        id,
        domain,
        action_type,
        priority,
        due_date
    FROM action_queue
    WHERE status='OPEN'
    ORDER BY
        CASE priority
            WHEN 'A1 - Immediate Outreach' THEN 1
            WHEN 'A2 - Priority Outreach' THEN 2
            ELSE 3
        END,
        due_date
    LIMIT 1
    """)


    action = cur.fetchone()


    if not action:
        conn.close()
        return None


    action_id = action[0]
    conn.close()
    return start_action(action_id, db_path)


def start_action(action_id, db_path=None):
    now = datetime.utcnow().isoformat()
    follow_up = (datetime.utcnow() + timedelta(days=3)).date().isoformat()
    conn = connect(db_path)
    try:
        cur = conn.cursor()
        action = cur.execute(
            """SELECT domain, action_type, priority FROM action_queue
               WHERE id=? AND status='OPEN'""",
            (action_id,),
        ).fetchone()
        if not action:
            return None
        domain, action_type, priority = action
        cur.execute(
            """UPDATE action_queue SET status='IN_PROGRESS', started_at=?
               WHERE id=? AND status='OPEN'""",
            (now, action_id),
        )
        cur.execute(
            """UPDATE leads SET pipeline_stage='CONTACTED', attempts=attempts+1,
               next_action=?, follow_up_date=? WHERE domain=?""",
            (action_type, follow_up, domain),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return None
        cur.execute(
            """INSERT INTO crm_events (domain, event_type, notes, created_at)
               VALUES (?, 'ACTION_STARTED', ?, ?)""",
            (domain, f"{action_type} started | {priority}", now),
        )
        conn.commit()
        return {"domain": domain, "action": action_type, "priority": priority}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def complete_action(domain, result, db_path=None, action_id=None):

    conn = connect(db_path)

    cur = conn.cursor()


    try:
        now = datetime.utcnow().isoformat()
        if action_id is None:
            row = cur.execute(
                """SELECT id FROM action_queue WHERE domain=? AND status='IN_PROGRESS'
                   ORDER BY started_at, id LIMIT 1""",
                (domain,),
            ).fetchone()
        else:
            row = cur.execute(
                """SELECT id FROM action_queue
                   WHERE id=? AND domain=? AND status='IN_PROGRESS'""",
                (action_id, domain),
            ).fetchone()
        if not row:
            return False
        cur.execute(
            """UPDATE action_queue SET status='COMPLETED', completed_at=?
               WHERE id=? AND status='IN_PROGRESS'""",
            (now, row[0]),
        )
        cur.execute(
            """INSERT INTO crm_events (domain, event_type, notes, created_at)
               VALUES (?, 'ACTION_COMPLETED', ?, ?)""",
            (domain, result, now),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
