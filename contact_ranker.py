import re


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


    digits = re.sub(
        r"\D",
        "",
        phone
    )


    if len(digits)==10:
        return 100


    if len(digits)==11 and digits.startswith("1"):
        return 90


    return 0



def choose_phone(phones):

    best=""
    confidence=0


    for phone in phones:

        score=score_phone(phone)


        if score > confidence:

            best=phone
            confidence=score


    return best,confidence
