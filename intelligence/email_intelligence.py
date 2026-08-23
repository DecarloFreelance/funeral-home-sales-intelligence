from typing import Any, Dict, Iterable, List

from email_validator import (
    EmailNotValidError,
    EmailUndeliverableError,
    validate_email as validate_email_address,
)

from validation.contact_validator import validate_email
from intelligence.external_verification import VerificationError


FREE_PROVIDERS = {
    "gmail.com", "hotmail.com", "icloud.com", "outlook.com", "yahoo.com",
}
ROLE_ACCOUNTS = {
    "care", "contact", "director", "info", "manager", "office", "owner",
    "preplanning", "reception",
}
RISKY_ACCOUNTS = {
    "admin", "help", "no-reply", "noreply", "privacy", "support", "webmaster",
}


def analyze_email(
    email: str, business_domain: str = "", check_dns: bool = False,
    dns_resolver=None,
) -> Dict[str, Any]:
    """Return evidence-based email quality without claiming deliverability."""
    source = str(email or "").strip()
    normalized = source.lower()
    syntax_valid = False
    dns_valid = None
    mx_available = None
    dns_error = ""
    try:
        validated = validate_email_address(
            source, check_deliverability=check_dns, dns_resolver=dns_resolver,
        )
        normalized = validated.normalized.lower()
        syntax_valid = True
        if check_dns:
            mx = getattr(validated, "mx", None)
            mx_fallback = getattr(validated, "mx_fallback_type", None)
            mx_available = True if mx else (False if mx_fallback else None)
            dns_valid = True if (mx or mx_fallback) else None
    except EmailUndeliverableError as error:
        # Syntax is valid even when the domain has definitive negative DNS evidence.
        syntax_valid = validate_email(normalized)
        dns_valid = False if check_dns and syntax_valid else None
        mx_available = False if dns_valid is False else None
        dns_error = str(error)
    except EmailNotValidError as error:
        dns_error = str(error)
    local, host = (normalized.split("@", 1) if syntax_valid else ("", ""))
    business_domain = str(business_domain or "").lower().removeprefix("www.")
    domain_match = bool(host and business_domain and (
        host == business_domain or host.endswith("." + business_domain)
    ))
    is_free_provider = host in FREE_PROVIDERS
    is_role_account = local in ROLE_ACCOUNTS
    risks = []
    if not syntax_valid:
        risks.append("invalid_syntax")
    if dns_valid is False:
        risks.append("mail_domain_unavailable")
    if local in RISKY_ACCOUNTS:
        risks.append("non_sales_mailbox")
    if is_free_provider:
        risks.append("free_email_provider")
    if syntax_valid and business_domain and not domain_match and not is_free_provider:
        risks.append("external_domain")

    score = 0
    if syntax_valid:
        score = 45
        score += 35 if domain_match else 0
        score += 15 if is_role_account else 0
        score -= 25 if "non_sales_mailbox" in risks else 0
        score -= 10 if is_free_provider else 0
        score -= 10 if "external_domain" in risks else 0
        score -= 30 if "mail_domain_unavailable" in risks else 0
    score = max(0, min(100, score))

    verification_state = "INVALID"
    if syntax_valid:
        verification_state = "DNS_VALID" if dns_valid else "LOCAL_VALID"
    return {
        "email": normalized,
        "syntax_valid": syntax_valid,
        "domain": host,
        "domain_match": domain_match,
        "role_account": is_role_account,
        "free_provider": is_free_provider,
        "deliverability": "NOT_CHECKED",
        "dns_checked": check_dns,
        "dns_valid": dns_valid,
        "mx_available": mx_available,
        "dns_error": dns_error,
        "dns_status": (
            "VALID" if dns_valid is True else
            "INVALID" if dns_valid is False else
            "INDETERMINATE" if check_dns else "NOT_CHECKED"
        ),
        "risks": risks,
        "confidence": score,
        "status": verification_state,
        "verification_state": verification_state,
    }


def validate_emails(
    emails: Iterable[str], business_domain: str = "", provider=None,
    check_dns: bool = False, dns_resolver=None,
) -> List[Dict[str, Any]]:
    unique = dict.fromkeys(str(email).strip().lower() for email in emails if email)
    results = []
    for email in unique:
        result = analyze_email(email, business_domain, check_dns, dns_resolver)
        if provider is not None and result["syntax_valid"]:
            try:
                result.update(provider.verify(result["email"]))
                if result.get("checked"):
                    result["verification_state"] = "EXTERNALLY_VERIFIED"
            except VerificationError:
                result.update(
                    deliverability="CHECK_FAILED", provider=provider.__class__.__name__,
                    checked=False,
                )
        results.append(result)
    return results
