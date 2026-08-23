from typing import Any, Dict, Iterable, List

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


def analyze_email(email: str, business_domain: str = "") -> Dict[str, Any]:
    """Return evidence-based email quality without claiming deliverability."""
    normalized = str(email or "").strip().lower()
    syntax_valid = validate_email(normalized)
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
    score = max(0, min(100, score))

    return {
        "email": normalized,
        "syntax_valid": syntax_valid,
        "domain": host,
        "domain_match": domain_match,
        "role_account": is_role_account,
        "free_provider": is_free_provider,
        "deliverability": "NOT_CHECKED",
        "risks": risks,
        "confidence": score,
        "status": "VALID_FORMAT" if syntax_valid else "INVALID",
    }


def validate_emails(
    emails: Iterable[str], business_domain: str = "", provider=None
) -> List[Dict[str, Any]]:
    unique = dict.fromkeys(str(email).strip().lower() for email in emails if email)
    results = []
    for email in unique:
        result = analyze_email(email, business_domain)
        if provider is not None and result["syntax_valid"]:
            try:
                result.update(provider.verify(result["email"]))
            except VerificationError:
                result.update(
                    deliverability="CHECK_FAILED", provider=provider.__class__.__name__,
                    checked=False,
                )
        results.append(result)
    return results
