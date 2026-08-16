from __future__ import annotations

import pytest

from canada_funeral_intel.verification.discovery import _is_generic_email_domain


@pytest.mark.parametrize(
    "domain",
    (
        "gmail.com",
        "outlook.com",
        "hotmail.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "yahoo.com",
        "mail.yahoo.com",
        "yahoo.ca",
        "mts.net",
        "mymts.net",
        "shaw.ca",
    ),
)
def test_generic_mail_domains_are_suppressed(domain: str) -> None:
    assert _is_generic_email_domain(domain)


@pytest.mark.parametrize(
    "domain",
    (
        "afh.ca",
        "alternacremation.ca",
        "arbormemorial.com",
        "bardal.ca",
        "braendlebrucefs.ca",
        "carscaddenfc.com",
        "dignitymemorial.com",
        "doylesfuneralhome.ca",
        "ethicaldeathcare.com",
        "wheatlandfs.com",
    ),
)
def test_business_domains_remain_eligible(domain: str) -> None:
    assert not _is_generic_email_domain(domain)
