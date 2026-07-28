WEIGHTS = {

    # Revenue conversion infrastructure
    "online_planner": 5,
    "appointment_booking": 4,
    "lead_capture": 3,
    "pricing": 2,

    # Engagement helpers
    "chat": 1,
    "preplanning": 1,

    # Basic contact
    "contact_form": 1,

    # Service indicators
    "cremation": 0,
    "burial": 0
}


def calculate_score(found):

    score = sum(
        WEIGHTS.get(x,0)
        for x in found
    )

    return min(score,15)



def calculate_opportunity(missing):

    return min(
        sum(
            WEIGHTS.get(x,0)
            for x in missing
        ),
        15
    )



def priority(score):

    if score >= 10:
        return "Critical"

    if score >= 6:
        return "High"

    if score >= 3:
        return "Medium"

    return "Low"

def lead_value(conversion, opportunity):

    score = (
        opportunity * 2
        +
        conversion
    )

    return min(
        score,
        30
    )


def calculate_revenue_opportunity(
    missing,
    community_fit=0,
    seminar_fit=0,
    education_fit=0,
    contact_quality=0,
    opportunity=0
):

    score = 0
    reasons = []


    # Website revenue gaps
    if "online_planner" in missing:
        score += 15
        reasons.append("Missing online planning system")

    if "lead_capture" in missing:
        score += 10
        reasons.append("Missing lead capture infrastructure")

    if "appointment_booking" in missing:
        score += 10
        reasons.append("Missing consultation booking")


    # Existing website opportunity
    score += min(opportunity * 2, 20)

    if opportunity >= 10:
        reasons.append("High digital conversion opportunity")


    # Relationship intelligence
    if community_fit >= 70:
        score += 15
        reasons.append("Strong community engagement")

    elif community_fit >= 40:
        score += 8


    if seminar_fit >= 70:
        score += 15
        reasons.append("Strong seminar partnership fit")

    elif seminar_fit >= 40:
        score += 8


    if education_fit >= 20:
        score += 5
        reasons.append("Education partnership potential")


    # Contact quality
    if contact_quality >= 70:
        score += 10
        reasons.append("Verified outreach readiness")

    elif contact_quality >= 40:
        score += 5


    score = min(score,100)


    if score >= 75:
        tier = "Tier 1"

    elif score >= 50:
        tier = "Tier 2"

    else:
        tier = "Tier 3"


    return score, tier, reasons

