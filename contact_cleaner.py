import re


BAD_EMAIL_DOMAINS = [
    "tukios.com",
    "facebook.com",
    "google.com",
    "wordpress.com"
]


def clean_emails(emails, domain):

    cleaned = []

    for email in emails:

        email = email.lower().strip()

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

        digits = re.sub(
            r"\D",
            "",
            phone
        )


        if len(digits) >= 10 and len(digits) <= 15:

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
