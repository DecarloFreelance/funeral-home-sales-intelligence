
from datetime import datetime, timedelta

from crm.database import connect
from crm.events import add_event


def execute_next_action():

    conn = connect()

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
        return None


    action_id, domain, action_type, priority, due_date = action


    cur.execute("""
    UPDATE action_queue
    SET status='IN_PROGRESS',
        started_at=?
    WHERE id=?
    """,
    (
        datetime.utcnow().isoformat(),
        action_id
    ))


    cur.execute("""
    UPDATE leads
    SET
        pipeline_stage='CONTACTED',
        attempts=attempts+1,
        next_action=?,
        follow_up_date=?
    WHERE domain=?
    """,
    (
        action_type,
        (
            datetime.utcnow()
            + timedelta(days=3)
        ).date().isoformat(),
        domain
    ))


    conn.commit()


    add_event(
        domain,
        "ACTION_STARTED",
        f"{action_type} started | {priority}"
    )


    return {
        "domain": domain,
        "action": action_type,
        "priority": priority
    }



def complete_action(domain, result):

    conn = connect()

    cur = conn.cursor()


    cur.execute("""
    UPDATE action_queue
    SET status='COMPLETED',
        completed_at=?
    WHERE domain=?
    AND status='IN_PROGRESS'
    """,
    (
        datetime.utcnow().isoformat(),
        domain
    ))


    conn.commit()


    add_event(
        domain,
        "ACTION_COMPLETED",
        result
    )
