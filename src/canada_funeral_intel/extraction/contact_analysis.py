from __future__ import annotations

import re

from canada_funeral_intel.normalization.scalars import (
    normalize_email,
    normalize_phone,
)

_EMAIL_PATTERN = re.compile(r"\b[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+\b")
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?:\s*(?:ext\.?|extension|x)\s*\d+)?(?!\d)",
    re.IGNORECASE,
)


def extract_contact_values(text: str) -> tuple[str | None, str | None, str | None, str | None]:
    email_match = _EMAIL_PATTERN.search(text)
    phone_match = _PHONE_PATTERN.search(text)

    email = email_match.group(0) if email_match else None
    phone = phone_match.group(0) if phone_match else None
    normalized_email = normalize_email(email).value
    normalized_phone = normalize_phone(phone).value
    return email, normalized_email, phone, normalized_phone
