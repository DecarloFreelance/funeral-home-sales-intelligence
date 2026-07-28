import re

from validation.contact_validator import (
    validate_email,
    validate_phone
)

from intelligence.phone_intelligence import (
    phone_region_score
)


FREE_EMAILS = [
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com"
]


BAD_PREFIXES = [
    "privacy",
    "support",
    "help",
    "admin",
    "webmaster",
    "noreply",
    "no-reply"
]



CANADA_AREA_CODES = [
    "204",
    "236",
    "249",
    "250",
    "289",
    "306",
    "343",
    "365",
    "403",
    "416",
    "418",
    "431",
    "437",
    "438",
    "450",
    "506",
    "514",
    "519",
    "548",
    "579",
    "581",
    "587",
    "604",
    "613",
    "639",
    "647",
    "705",
    "709",
    "778",
    "780",
    "782",
    "807",
    "819",
    "825",
    "867",
    "873",
    "879",
    "902",
    "905"
]


BAD_DOMAINS = [
    "tukios.com",
    "frontrunner360.com",
    "tributetech.com",
    "wordpress.com",
    "google.com",
    "facebook.com"
]


def score_email(email, domain):

    if not email:
        return 0

    if not validate_email(email):
        return 0


    email = email.lower().strip()


    if "@" not in email:
        return 0


    local, host = email.split("@",1)


    if host in BAD_DOMAINS:
        return 0


    if local in BAD_PREFIXES:
        return 0


    score = 0


    if host == domain:
        score += 60


    if local in [
        "info",
        "contact",
        "office",
        "director",
        "owner",
        "manager"
    ]:
        score += 25


    if host not in FREE_EMAILS:
        score += 15


    return score



def choose_email(emails, domain):

    ranked=[]


    for email in emails:

        score = score_email(
            email,
            domain
        )

        if score:
            ranked.append(
                (
                    score,
                    email
                )
            )


    if not ranked:
        return "",0


    ranked.sort(
        reverse=True
    )


    return ranked[0][1], ranked[0][0]



def score_phone(phone):

    if not phone:
        return 0

    if not validate_phone(phone):
        return 0


    digits = re.sub(
        r"\D",
        "",
        phone
    )


    if len(digits)==10:

        area = digits[:3]

        if area in CANADA_AREA_CODES:
            return 100

        return 40


    if len(digits)==11 and digits.startswith("1"):

        area = digits[1:4]

        if area in CANADA_AREA_CODES:
            return 90

        return 30


    return 0



def choose_phone(phones):

    ranked = []


    for phone in phones:

        score = score_phone(phone)

        if score:

            regional = phone_region_score(phone)

            final_score = (
                score * 0.7 +
                regional * 0.3
            )

            ranked.append(
                (
                    final_score,
                    phone
                )
            )


    if not ranked:
        return "", 0


    ranked.sort(
        reverse=True
    )


    return (
        ranked[0][1],
        round(ranked[0][0])
    )
