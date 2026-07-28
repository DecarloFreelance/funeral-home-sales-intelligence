import re


def validate_email(email):
    """
    Basic email validation.
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
    Validate business phone numbers.

    Accepts:
    - 10 digit North American numbers
    - 11 digit North American numbers starting with 1

    Rejects:
    - timestamps
    - scraped IDs
    - impossible area codes
    """

    if not phone:
        return False


    digits = re.sub(
        r"\D",
        "",
        phone
    )


    # Reject timestamps / IDs
    if digits.startswith(
        (
            "19",
            "20"
        )
    ):
        return False


    # Normalize country code
    if len(digits) == 11:

        if not digits.startswith("1"):
            return False

        digits = digits[1:]


    if len(digits) != 10:
        return False


    area_code = digits[:3]


    # North American area codes cannot start with 0 or 1
    if area_code[0] in ("0", "1"):
        return False


    return True
