
import re


ALBERTA_CODES = {
    "403",
    "587",
    "780",
    "825"
}


CANADA_CODES = {
    "204","226","236","249","250",
    "289","306","343","365",
    "367","387","403","416",
    "418","431","437","438",
    "450","506","514","519",
    "548","579","581","587",
    "604","613","639","647",
    "705","709","742","778",
    "780","782","807","819",
    "825","867","873","879",
    "902","905"
}


def normalize_phone(phone):

    if not phone:
        return ""

    digits = re.sub(
        r"\D",
        "",
        phone
    )

    if len(digits) == 10:
        return "+1" + digits

    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits

    return ""



def phone_region_score(phone):

    normalized = normalize_phone(phone)

    if not normalized:
        return 0

    area = normalized[2:5]

    if area in ALBERTA_CODES:
        return 100

    if area in CANADA_CODES:
        return 70

    return 20



def phone_quality_score(phone):

    normalized = normalize_phone(phone)

    if not normalized:
        return {
            "score": 0,
            "normalized": "",
            "reasons": [
                "Invalid phone format"
            ]
        }


    score = phone_region_score(phone)

    reasons = [
        "Valid NANP phone number"
    ]


    if score == 100:
        reasons.append(
            "Alberta area code"
        )
    elif score == 70:
        reasons.append(
            "Canadian area code"
        )
    else:
        reasons.append(
            "Non-local area code"
        )


    return {
        "score": score,
        "normalized": normalized,
        "reasons": reasons
    }
