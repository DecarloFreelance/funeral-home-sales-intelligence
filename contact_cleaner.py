import re

from validation.contact_validator import (
    validate_email,
    validate_phone
)


BAD_EMAIL_DOMAINS = [
    "tukios.com",
    "facebook.com",
    "google.com",
    "wordpress.com"
]
BAD_EMAIL_ADDRESSES = {"filler@godaddy.com"}


def clean_emails(emails, domain):

    cleaned = []

    for email in emails:

        email = email.lower().strip()

        if email in BAD_EMAIL_ADDRESSES:
            continue


        if not validate_email(email):
            continue


        if any(
            bad in email
            for bad in BAD_EMAIL_DOMAINS
        ):
            continue


        if email.endswith(
            "@" + domain
        ):
            cleaned.insert(
                0,
                email
            )

        else:
            cleaned.append(
                email
            )


    return list(
        dict.fromkeys(cleaned)
    )



def clean_phones(phones):

    cleaned = []


    for phone in phones:

        if not validate_phone(phone):
            continue


        digits = re.sub(
            r"\D",
            "",
            phone
        )


        # Reject obvious scraped IDs/timestamps
        if digits.startswith(
            (
                "202",
                "190"
            )
        ):
            continue


        cleaned.append(
            phone.strip()
        )


    return list(
        dict.fromkeys(cleaned)
    )



def clean_contact_data(
    emails,
    phones,
    domain=None
):

    if domain:

        emails = clean_emails(
            emails,
            domain
        )


    phones = clean_phones(
        phones
    )


    return {
        "emails": emails,
        "phones": phones
    }
