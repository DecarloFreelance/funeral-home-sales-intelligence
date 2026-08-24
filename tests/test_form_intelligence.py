from copy import deepcopy

import pytest

from enrichment.forms import analyze_dataset, analyze_page_forms, classify_semantic


HTML = """
<html><body><a href="/privacy-policy">Privacy Policy</a>
<p>At a minimum, provide your name and telephone number.</p>
<form id="intake" action="https://processor.example/submit" method="post">
  <h3>Personal Information</h3>
  <input type="hidden" name="token" value="secret-runtime-value">
  <label for="name">Full Name</label><input id="name" name="full-name" required value="submitted-name">
  <label>SIN #<input name="sin"></label>
  <label for="treaty">Treaty #</label><input id="treaty" name="treaty-number">
  <label>Date of Birth<input name="date-of-birth"></label>
  <label>Location of Will<input name="location-of-will"></label>
  <label>Disposition Preference<select name="disposition"><option>Burial</option></select></label>
  <label><input type="radio" name="appointment">Contact me to set up an appointment</label>
  <label>Additional instructions<textarea name="instructions"></textarea></label>
  <label><input type="checkbox" name="consent">I agree</label>
  <input type="file" name="attachment"><button type="submit">Send</button>
</form></body></html>
"""


def page(url="https://one.example/preplan", html=HTML):
    return {"url": url, "html": html, "text": "At a minimum, provide your name and telephone number.",
            "metadata": {"title": "Preplan"}, "crawl": {"observedAt": "2026-08-24T00:00:00Z"},
            "discovery": {"queue_domain": "one.example"}}


def test_discovers_form_schema_labels_controls_requirements_without_values_or_submission():
    form = analyze_page_forms("one.example", page())[0]
    assert form["form_method"] == "POST" and form["action_scope"] == "CROSS_ORIGIN"
    assert form["control_count"] == 12 and form["hidden_field_count"] == 1
    assert form["visible_control_count"] == 11 and form["visible_field_count"] == 10
    assert form["section_count"] == 1 and form["section_headings"] == ["Personal Information"]
    assert form["select_count"] == form["textarea_count"] == form["radio_count"] == form["checkbox_count"] == 1
    assert form["file_upload_present"] is True and form["submit_count"] == 1
    assert next(field for field in form["fields"] if field["name"] == "full-name")["label"] == "Full Name"
    assert next(field for field in form["fields"] if field["name"] == "full-name")["requirement_state"] == "HTML_REQUIRED"
    assert next(field for field in form["fields"] if field["name"] == "sin")["requirement_state"] == "UNSPECIFIED"
    assert form["explicit_minimum_fields_text"].lower().startswith("at a minimum")
    assert all("value" not in field for field in form["fields"])
    assert "secret-runtime-value" not in str(form) and "submitted-name" not in str(form)
    assert form["safety"]["form_submitted"] is False and form["safety"]["action_fetched"] is False


@pytest.mark.parametrize(("label", "expected"), [
    ("SIN #", "GOVERNMENT_IDENTIFIER"), ("Treaty #", "INDIGENOUS_OR_TREATY_IDENTIFIER"),
    ("Date of Birth", "DATE_OF_BIRTH"), ("Burial or cremation", "DISPOSITION_PREFERENCE"),
    ("Location of Will", "WILL_OR_ESTATE"), ("Colour preference", "UNKNOWN"),
])
def test_semantics_are_neutral_and_explainable(label, expected):
    assert classify_semantic(label) == expected


def test_form_characteristics_do_not_change_readiness_or_emit_negative_conclusions():
    record = {"domain": "one.example", "quality_control": {"crm_sync_safe": True, "outreach_ready": True}}
    before = deepcopy(record)
    package = analyze_dataset([record], [page()])
    assert record == before
    rendered = str(package).lower()
    for unsupported in ("illegal", "non-compliant", "insecure", "high-friction", "lost revenue", "abandonment risk"):
        assert unsupported not in rendered
    assert package["review_candidates"][0]["status"] == "HUMAN_REVIEW_CANDIDATE_NOT_A_DEFECT"


def test_stable_ids_repeat_and_foreign_ownership_fails_closed():
    retained = page()
    retained["crawl"] = {}
    first = analyze_dataset([{"domain": "one.example"}], [retained], "2026-08-24T00:00:00Z")
    second = analyze_dataset([{"domain": "one.example"}], [retained], "2026-08-24T00:00:00Z")
    assert first == second
    assert first["forms"][0]["form_id"] == second["forms"][0]["form_id"]
    assert first["forms"][0]["observed_at"] == "2026-08-24T00:00:00Z"
    foreign = page("https://sibling.example/form")
    foreign["discovery"] = {}
    with pytest.raises(ValueError, match="does not belong"):
        analyze_page_forms("one.example", foreign)


def test_no_form_is_not_a_defect_and_unknown_stays_unknown():
    package = analyze_dataset([{"domain": "one.example"}], [page(html="<html>No form</html>")])
    assert package["total_forms"] == 0 and package["review_candidates"] == []
