from canada_funeral_intel.verification.page_discovery import (
    classify_page,
    extract_links,
    is_business_fact_relevant_page,
    is_excluded_page,
)


def test_phase7_prioritizes_staff_and_team_pages() -> None:
    assert classify_page("https://example.ca/about/our-team") == ("team", 95)

    assert classify_page("https://example.ca/staff") == ("staff", 92)

    assert classify_page("https://example.ca/funeral-directors") == ("directors", 100)


def test_phase10_prioritizes_supported_business_fact_page_patterns() -> None:
    assert classify_page("https://example.ca/services") == ("other", 70)
    assert classify_page("https://example.ca/cremation") == ("other", 74)
    assert classify_page("https://example.ca/pre-planning") == ("other", 72)
    assert classify_page("https://example.ca/facilities") == ("other", 72)
    assert classify_page("https://example.ca/chapel") == ("other", 72)

    assert is_business_fact_relevant_page("/services")
    assert is_business_fact_relevant_page("/cremation")
    assert is_business_fact_relevant_page("/pre-planning")
    assert is_business_fact_relevant_page("/facilities")
    assert is_business_fact_relevant_page("/chapel")
    assert not is_business_fact_relevant_page("/news")


def test_phase7_excludes_obituary_and_login_sections() -> None:
    assert is_excluded_page("https://example.ca/obituaries/jane-doe")
    assert is_excluded_page("https://example.ca/login")
    assert is_excluded_page("https://example.ca/checkout")

    assert not is_excluded_page("https://example.ca/about")


def test_phase7_extracts_normalized_html_links() -> None:
    body = b"""
        <html>
          <body>
            <a href="/team#directors">Our Team</a>
            <a href="https://example.ca/contact">Contact</a>
            <a href="mailto:test@example.ca">Email</a>
          </body>
        </html>
    """

    links = extract_links(
        body,
        base_url="https://example.ca/",
        content_type="text/html; charset=utf-8",
    )

    assert links == (
        (
            "https://example.ca/team",
            "Our Team",
        ),
        (
            "https://example.ca/contact",
            "Contact",
        ),
    )
