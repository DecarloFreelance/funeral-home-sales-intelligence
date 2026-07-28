import re


def validate_email(email):
    """
    Basic email format validation.
    """

    if not email:
        return False

    pattern = (
        r"^[A-Za-z0-9._%+-]+"
        r"@"
        r"[A-Za-z0-9.-]+"
        r"\.[A-Za-z]{2,}$"
    )

    return bool(
        re.match(
            pattern,
            email
        )
    )


def validate_phone(phone):
    """
    Basic phone validation.

    Accepts:
    +1XXXXXXXXXX
    XXXXXXXXXX
    (XXX) XXX-XXXX
    """

    if not phone:
        return False


    digits = re.sub(
        r"\D",
        "",
        phone
    )


    return len(digits) in [
        10,
        11
    ]


def confidence_adjustment(
    email,
    phone
):

    score = 0


    if validate_email(email):
        score += 50


    if validate_phone(phone):
        score += 50


    return score
