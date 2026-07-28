
from datetime import datetime, timedelta


PIPELINE = [
    "NEW",
    "CONTACTED",
    "RESPONDED",
    "QUALIFIED",
    "OPPORTUNITY",
    "CLOSED"
]


def initial_status(
    priority_level,
    contact_method
):
    """
    Assign initial CRM state.
    """

    if priority_level == "A1 - Immediate Outreach":
        return {
            "crm_status": "NEW",
            "pipeline_stage": "CONTACTED",
            "next_action": f"Send {contact_method} outreach"
        }


    if priority_level == "A2 - Priority Outreach":
        return {
            "crm_status": "NEW",
            "pipeline_stage": "NEW",
            "next_action": f"Prepare {contact_method} sequence"
        }


    return {
        "crm_status": "NURTURE",
        "pipeline_stage": "NEW",
        "next_action": "Research prospect"
    }



def follow_up_schedule(priority_level):

    if priority_level == "A1 - Immediate Outreach":
        days = 2

    elif priority_level == "A2 - Priority Outreach":
        days = 5

    else:
        days = 14


    return (
        datetime.utcnow()
        +
        timedelta(days=days)
    ).strftime("%Y-%m-%d")

