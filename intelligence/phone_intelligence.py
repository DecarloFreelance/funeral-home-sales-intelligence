
import re
from typing import Any, Dict, Iterable, List

import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType

from validation.contact_validator import validate_phone
from intelligence.external_verification import VerificationError


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

    try:
        parsed = phonenumbers.parse(str(phone), "CA")
    except phonenumbers.NumberParseException:
        return ""
    if not phonenumbers.is_possible_number(parsed):
        return ""
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)



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


def analyze_phone(phone: str) -> Dict[str, Any]:
    """Return local phone evidence without claiming carrier reachability."""
    raw = str(phone or "").strip()
    normalized = normalize_phone(raw)
    parsed = None
    try:
        parsed = phonenumbers.parse(raw, "CA")
    except phonenumbers.NumberParseException:
        pass
    possible = bool(parsed and phonenumbers.is_possible_number(parsed))
    metadata_valid = bool(parsed and phonenumbers.is_valid_number(parsed))
    format_valid = validate_phone(raw) and possible and bool(normalized)
    area_code = normalized[2:5] if normalized else ""
    exchange = normalized[5:8] if normalized else ""
    subscriber = normalized[8:] if normalized else ""
    risks = []

    if not format_valid:
        risks.append("invalid_format")
    if format_valid and exchange[:1] in {"0", "1"}:
        risks.append("invalid_exchange")
    if format_valid and len(set(area_code + exchange + subscriber)) <= 2:
        risks.append("repetitive_digits")
    if subscriber in {"0000", "1111", "1234"}:
        risks.append("placeholder_pattern")

    if area_code in ALBERTA_CODES:
        region = "Alberta"
        region_confidence = 100
    elif area_code in CANADA_CODES:
        region = "Canada"
        region_confidence = 70
    elif area_code:
        region = "NANP outside Canada or unknown"
        region_confidence = 20
    else:
        region = "Unknown"
        region_confidence = 0

    number_type = "UNKNOWN"
    country = ""
    if parsed:
        type_value = phonenumbers.number_type(parsed)
        number_type = next(
            (name for name, value in vars(PhoneNumberType).items()
             if name.isupper() and value == type_value),
            "UNKNOWN",
        )
        country = phonenumbers.region_code_for_number(parsed) or ""
    if possible and not metadata_valid:
        risks.append("metadata_invalid")

    usable = format_valid and metadata_valid and not risks
    confidence = region_confidence if usable else 0
    return {
        "phone": raw,
        "normalized": normalized,
        "format_valid": format_valid,
        "possible": possible,
        "metadata_valid": metadata_valid,
        "country": country,
        "area_code": area_code,
        "region": region,
        "reachability": "NOT_CHECKED",
        "line_type": number_type,
        "carrier": "NOT_CHECKED",
        "risks": risks,
        "confidence": confidence,
        "status": "METADATA_VALIDATED" if usable else "REVIEW_REQUIRED",
        "verification_state": "METADATA_VALIDATED" if usable else "DISCOVERED",
    }


def verify_phones(phones: Iterable[str], provider=None) -> List[Dict[str, Any]]:
    unique = dict.fromkeys(str(phone).strip() for phone in phones if phone)
    results = []
    for phone in unique:
        result = analyze_phone(phone)
        if provider is not None and result["format_valid"]:
            try:
                result.update(provider.verify(result["normalized"]))
                if result.get("checked"):
                    result["verification_state"] = "EXTERNALLY_VERIFIED"
            except VerificationError:
                result.update(
                    reachability="CHECK_FAILED", line_type="UNKNOWN",
                    carrier="CHECK_FAILED", provider=provider.__class__.__name__,
                    checked=False,
                )
        results.append(result)
    return results
