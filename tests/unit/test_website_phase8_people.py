from canada_funeral_intel.extraction.person_analysis import analyze_person_page
from canada_funeral_intel.normalization.people import (
    normalize_person_name,
    normalize_role_title,
)


def test_phase8_extracts_labeled_staff_card_and_contacts() -> None:
    result = analyze_person_page(
        b"""
        <html><body>
          <section class="team">
            <article class="staff-card">
              <h2>Alice Smith</h2>
              <p>Licensed Funeral Director</p>
              <a href="mailto:ALICE@example.ca">ALICE@example.ca</a>
              <span>403-555-0100</span>
            </article>
          </section>
        </body></html>
        """,
        content_type="text/html; charset=utf-8",
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.observed_name == "Alice Smith"
    assert candidate.normalized_name == "alice smith"
    assert candidate.role_title == "Licensed Funeral Director"
    assert candidate.normalized_role == "licensed funeral director"
    assert candidate.normalized_email == "alice@example.ca"
    assert candidate.normalized_phone == "+14035550100"


def test_phase8_extracts_owner_manager_and_branch_context() -> None:
    result = analyze_person_page(
        b"""
        <div>
          <h2>Bob Jones</h2>
          <p>Owner</p>
          <p>Location: Edmonton</p>
        </div>
        <div>
          <h2>Carol Lee</h2>
          <p>Location Manager</p>
        </div>
        """,
        content_type="text/html",
    )

    assert [(item.observed_name, item.role_title) for item in result.candidates] == [
        ("Bob Jones", "Owner"),
        ("Carol Lee", "Location Manager"),
    ]
    assert result.candidates[0].branch_context == "Edmonton"
    assert result.candidates[1].branch_context is None


def test_phase8_splits_paired_names_with_shared_surname() -> None:
    result = analyze_person_page(
        b"""
        <article class="staff-card">
          <h2>Wade &amp; Kelly Lumbard</h2>
          <p>Funeral Directors</p>
        </article>
        <article class="staff-card">
          <h2>Jack &amp; Joyce Lumbard</h2>
          <p>Vice President</p>
        </article>
        """,
        content_type="text/html",
    )

    assert [(item.observed_name, item.role_title) for item in result.candidates] == [
        ("Wade Lumbard", "Funeral Directors"),
        ("Kelly Lumbard", "Funeral Directors"),
        ("Jack Lumbard", "Vice President"),
        ("Joyce Lumbard", "Vice President"),
    ]


def test_phase8_does_not_include_role_suffix_in_name() -> None:
    result = analyze_person_page(
        b"""
        <article class="staff-card">
          <h2>Patricia A. Sweryd Vice President</h2>
        </article>
        """,
        content_type="text/html",
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].observed_name == "Patricia A. Sweryd"
    assert result.candidates[0].role_title == "Vice President"


def test_phase8_suppresses_negative_and_unlabeled_content() -> None:
    result = analyze_person_page(
        b"""
        <html><body>
          <article class="obituary">
            <h2>Deceased Person</h2><p>Funeral Director</p>
          </article>
          <article class="testimonial">
            <h2>Review Author</h2><p>Funeral Director</p>
          </article>
          <footer>
            <p>Web Design by Vendor Person</p>
            <p>Funeral Director Alice Smith</p>
          </footer>
          <p>Unrelated Human Name</p>
        </body></html>
        """,
        content_type="text/html",
    )

    assert result.candidates == ()


def test_phase8_suppresses_heading_contact_and_article_author_noise() -> None:
    result = analyze_person_page(
        b"""
        <article>
          <h2>Contact Us</h2><p>Funeral Director</p>
        </article>
        <article>
          <h2>Managing Funeral Director</h2><p>Managing Funeral Director</p>
        </article>
        <article>
          <p>By Jane Example Funeral Director</p>
        </article>
        """,
        content_type="text/html",
    )

    assert result.candidates == ()


def test_phase8_ignores_non_html_bodies() -> None:
    result = analyze_person_page(
        b"Alice Smith Funeral Director",
        content_type="application/pdf",
    )
    assert result.candidates == ()


def test_phase8_person_and_role_normalization_is_conservative() -> None:
    assert normalize_person_name("  Alice   Smith  ").value == "alice smith"
    assert normalize_role_title(" Licensed Funeral Director / Embalmer ").value == (
        "licensed funeral director / embalmer"
    )
