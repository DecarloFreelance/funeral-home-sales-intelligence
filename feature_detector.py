import re


FEATURE_PATTERNS = {

    "contact_form": {
        r"contact\s+us":3,
        r"contact\s+our":3,
        r"contact\s+form":4,
        r"send\s+(a\s+)?message":3,
        r"request\s+(information|a\s+call|callback)":4,
        r"email\s+us":2,
        r"phone\s*[:\-]":2,
        r"call\s+us":2,
    },


    "appointment_booking": {
        r"book\s+(an?\s+)?appointment":5,
        r"schedule\s+(a\s+)?(meeting|consultation)":5,
        r"arrange\s+(a\s+)?meeting":4,
        r"meet\s+with\s+(a\s+)?director":5,
        r"talk\s+with\s+(a\s+)?funeral\s+director":5,
        r"consultation":2,
        r"arrangements?\s+(can\s+be\s+made|appointment)":4,
    },


    "online_planner": {
        r"online\s+(funeral|memorial)\s+planner":5,
        r"plan\s+(a\s+)?funeral\s+online":5,
        r"start\s+(your\s+)?arrangements\s+online":5,
        r"online\s+arrangement":4,
        r"virtual\s+arrangement":4,
    },


    "pricing": {
        r"pricing":5,
        r"price\s+list":5,
        r"cost":3,
        r"fees":3,
        r"fee\s+schedule":5,
        r"packages?":3,
        r"service\s+options":4,
        r"price\s+information":5,
        r"transparent\s+pricing":5,
    },


    "preplanning": {
        r"pre[\s-]?planning":5,
        r"pre[\s-]?arrangement":5,
        r"plan\s+ahead":4,
        r"advance\s+planning":5,
        r"future\s+planning":3,
    },


    "lead_capture": {
        r"newsletter":3,
        r"subscribe":3,
        r"download":2,
        r"request\s+information":5,
        r"free\s+guide":4,
        r"leave\s+your\s+(name|email)":5,
    },


    "chat": {
        r"live\s+chat":5,
        r"chat\s+with\s+us":5,
        r"messenger":4,
        r"virtual\s+assistant":5,
        r"ai\s+assistant":5,
        r"chatbot":5,
    },


    "cremation": {
        r"cremation":3,
        r"cremated":2,
    },


    "burial": {
        r"burial":3,
        r"interment":3,
        r"cemetery":2,
    }
}


def detect_features(text):

    text = text.lower()

    text = re.sub(r"\s+", " ", text)

    scores = {}

    for feature, patterns in FEATURE_PATTERNS.items():

        score = 0

        for pattern, weight in patterns.items():

            if re.search(pattern, text):
                score += weight

        if score:
            scores[feature] = score


    # technical conversion signals
    if re.search(r"<form|wpforms|gravity.?forms|contact.?form", text):
        scores["contact_form"] = max(
        scores.get("contact_form",0),
        3
    )

    if re.search(r"calendly|acuity|booking.?widget|appointment.?widget", text):
        scores["appointment_booking"] = max(
        scores.get("appointment_booking",0),
        4
    )

    if re.search(r"intercom|tidio|drift|livechat|tawk", text):
        scores["chat"] = max(
        scores.get("chat",0),
        4
    )

    if re.search(r"iframe|embedded|online.?planner|planning.?tool", text):
        scores["online_planner"] = max(
        scores.get("online_planner",0),
        4
    )


    return scores
