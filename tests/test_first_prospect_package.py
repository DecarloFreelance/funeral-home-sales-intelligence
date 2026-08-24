import json

import pytest

from commercial_readiness import build_package as build_commercial
from pilot.prospect import build_first_prospect_package, write_package
from pilot.workflow import PilotStore, build_pilot_cohort
from tests.test_pilot_workflow import _page, _record


def _prepared(tmp_path):
    record, page = _record()
    page["markdown"] += " Cremation services. Pre-Arrangements Form"
    page["text"] = page["markdown"]
    page["html"] += '<a href="/prearrangements-form">Pre-Arrangements Form</a>'
    record["enrichment"] = __import__("enrichment.company", fromlist=["enrich_company"]).enrich_company(
        "example.ca", [page], record["business_profile"], record["contact_intelligence"],
    )
    commercial = build_commercial([record], [page])
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(build_pilot_cohort([record], commercial))
    return store, record, page


def test_first_prospect_package_is_evidence_bound_and_never_sends(tmp_path):
    store, record, page = _prepared(tmp_path)
    package = build_first_prospect_package(store, "example.ca", [record], [page])
    assert package["presend_review"]["status"] == "REVIEW_REQUIRED"
    assert package["safety"] == {
        "operator_approval_recorded": False, "contacted_recorded": False,
        "outreach_sent": False, "crm_write_performed": False,
    }
    evidence = package["internal_evidence_appendix"]
    for draft in package["drafts"]:
        assert draft["sendable"] is False and draft["outreach_sent"] is False
        assert "revenue" not in draft["body"].lower()
        assert "online arrangements are absent" not in draft["body"].lower()
        assert set(draft["supporting_evidence_ids"]).issubset(evidence)
    assert package["customer_safe_mini_audit"]["primary_opportunity"]["limitation"]
    assert all(item["organization_id"] == "example.ca" for item in evidence.values())


def test_first_prospect_package_rejects_foreign_contact_or_pages(tmp_path):
    store, record, page = _prepared(tmp_path)
    foreign = dict(page)
    foreign["url"] = "https://sibling.example/"
    with pytest.raises(ValueError, match="No organization-owned"):
        build_first_prospect_package(store, "example.ca", [record], [foreign])

    cohort = store.cohort()
    cohort["prospects"][0]["selected_contact"]["evidence"]["source_url"] = "https://sibling.example/contact"
    store.save_cohort(cohort)
    with pytest.raises(ValueError, match="Selected contact"):
        build_first_prospect_package(store, "example.ca", [record], [page])


def test_first_prospect_generation_is_deterministic(tmp_path):
    store, record, page = _prepared(tmp_path)
    first = build_first_prospect_package(store, "example.ca", [record], [page])
    second = build_first_prospect_package(store, "example.ca", [record], [page])
    assert first == second
    output = tmp_path / "package.json"
    assert write_package(output, first) is True
    assert write_package(output, second) is False
    assert json.loads(output.read_text()) == first
