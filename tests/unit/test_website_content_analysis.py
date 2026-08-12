from __future__ import annotations

from canada_funeral_intel.verification.content_analysis import (
    analyze_website_content,
)


def test_soft_404_detected_only_on_success_html() -> None:
    analysis = analyze_website_content(
        b"<html><body>404 Not Found - the page does not exist</body></html>",
        content_type="text/html",
        status_code=200,
        expected_business_name=None,
    )
    assert analysis.soft_404 is True

    real_404 = analyze_website_content(
        b"<html><body>404 Not Found</body></html>",
        content_type="text/html",
        status_code=404,
        expected_business_name=None,
    )
    assert real_404.soft_404 is False


def test_parked_domain_phrase_is_detected() -> None:
    analysis = analyze_website_content(
        b"<html><body>This domain is for sale</body></html>",
        content_type="text/html; charset=utf-8",
        status_code=200,
        expected_business_name=None,
    )
    assert analysis.parked_or_for_sale is True


def test_identity_score_uses_distinctive_business_tokens() -> None:
    analysis = analyze_website_content(
        b"<html><body>Welcome to Prairie Rose Funeral Home</body></html>",
        content_type="text/html",
        status_code=200,
        expected_business_name="Prairie Rose Funeral Home Ltd.",
    )
    assert analysis.identity_score == 1.0


def test_identity_score_detects_clear_mismatch() -> None:
    analysis = analyze_website_content(
        b"<html><body>Mountain View Plumbing and Heating</body></html>",
        content_type="text/html",
        status_code=200,
        expected_business_name="Prairie Rose Funeral Home",
    )
    assert analysis.identity_score == 0.0


def test_non_html_content_is_not_classified() -> None:
    analysis = analyze_website_content(
        b"404 not found - this domain is for sale",
        content_type="application/pdf",
        status_code=200,
        expected_business_name="Prairie Rose Funeral Home",
    )
    assert analysis.soft_404 is False
    assert analysis.parked_or_for_sale is False
    assert analysis.identity_score == 0.0
