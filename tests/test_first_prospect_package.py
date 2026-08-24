import json

import pytest

from commercial_readiness import build_package as build_commercial
from pilot.prospect import build_first_prospect_package, write_package
from pilot.workflow import PilotStore, _angle_evidence, build_pilot_cohort
from tests.test_pilot_workflow import _page, _record


def _prepared(tmp_path, domain="example.ca", company=None):
    record, page = _record(domain)
    page["markdown"] += " Cremation services. Online Arrangement Form. Pre-Arrangements Form"
    page["text"] = page["markdown"]
    page["html"] += '<a href="/prearrangements-form">Pre-Arrangements Form</a>'
    if company:
        record["business_profile"]["company"] = company
    record["enrichment"] = __import__("enrichment.company", fromlist=["enrich_company"]).enrich_company(
        domain, [page], record["business_profile"], record["contact_intelligence"],
    )
    commercial = build_commercial([record], [page])
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(build_pilot_cohort([record], commercial))
    return store, record, page


def _preplanning_only(tmp_path, domain="example.ca", company=None):
    store, record, page = _prepared(tmp_path, domain, company)
    record["enrichment"]["facts"] = [
        fact for fact in record["enrichment"]["facts"]
        if fact.get("field") != "digital.online_arrangements"
    ]
    page["markdown"] = page["markdown"].replace(" Online Arrangement Form. Pre-Arrangements Form", "")
    page["text"] = page["markdown"]
    page["html"] = page["html"].replace('<a href="/prearrangements-form">Pre-Arrangements Form</a>', "")
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


@pytest.mark.parametrize(
    ("domain", "company", "subject"),
    [
        ("mccawfuneralservice.com", "McCaw Funeral Service Ltd.", "A small review of McCaw's pre-planning pathway"),
        ("beaverlodgefuneralservice.com", "Beaverlodge Funeral Service", "A small review of Beaverlodge's pre-planning pathway"),
    ],
)
def test_preplanning_only_package_uses_information_pathway_angle(tmp_path, domain, company, subject):
    store, record, page = _preplanning_only(tmp_path, domain, company)
    package = build_first_prospect_package(store, domain, [record], [page])
    angle = package["selected_angles"][0]
    assert angle["angle_type"] == "PREPLANNING_INFORMATION_PATHWAY_REVIEW"
    assert angle["evidence_ids"] == [next(
        fact["id"] for fact in record["enrichment"]["facts"]
        if fact.get("field") == "services.preplanning"
    )]
    assert set(_angle_evidence(record, {"forms": []}, angle["evidence_ids"])) == set(angle["evidence_ids"])
    assert angle["draft_preview"]["subject"] == subject
    assert "already provide pre-planning information" in angle["draft_preview"]["body"]
    assert "online-arrangements" not in angle["draft_preview"]["body"]
    assert "[FULL NAME]" not in angle["draft_preview"]["body"]
    assert angle["draft_preview"]["sendable"] is False
    assert angle["draft_preview"]["outreach_sent"] is False


def test_stronger_angle_wins_when_both_positive_facts_exist(tmp_path):
    store, record, page = _prepared(tmp_path)
    angle = build_first_prospect_package(store, "example.ca", [record], [page])["selected_angles"][0]
    assert angle["angle_type"] == "PREARRANGEMENT_PATHWAY_REVIEW"
    assert {fact["field"] for fact in _angle_evidence(record, {"forms": []}, angle["evidence_ids"]).values()} == {
        "services.preplanning", "digital.online_arrangements",
    }


def test_missing_foreign_or_stale_preplanning_fails_closed(tmp_path):
    for case in ("missing", "foreign", "stale"):
        store, record, page = _preplanning_only(tmp_path / case)
        facts = record["enrichment"]["facts"]
        preplanning = next(fact for fact in facts if fact.get("field") == "services.preplanning")
        if case == "missing":
            facts.remove(preplanning)
        elif case == "foreign":
            preplanning["source_url"] = "https://sibling.example/preplanning"
        else:
            preplanning["stale_after"] = "2020-01-01T00:00:00Z"
        with pytest.raises(ValueError, match="does not support"):
            build_first_prospect_package(store, "example.ca", [record], [page])


def test_bounded_scan_non_detection_is_not_online_arrangements_evidence(tmp_path):
    store, record, page = _preplanning_only(tmp_path)
    prospect = store._prospect("example.ca")
    scan_evidence = prospect["audit_package"]["evidence_appendix"]
    assert any(value.get("qualification") == "Bounded scan scope; non-detection is not proof of absence." for value in scan_evidence.values())
    angle = build_first_prospect_package(store, "example.ca", [record], [page])["selected_angles"][0]
    assert angle["angle_type"] == "PREPLANNING_INFORMATION_PATHWAY_REVIEW"
    assert not any(evidence_id in scan_evidence and scan_evidence[evidence_id].get("qualification") for evidence_id in angle["evidence_ids"])


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


def test_gregory_package_generates_safe_resolvable_pathway_angle_without_form_claim(tmp_path):
    store, record, page = _prepared(
        tmp_path, "gregorysfuneralhomes.com", "Gregory's Funeral Home Inc.",
    )
    package = build_first_prospect_package(
        store, "gregorysfuneralhomes.com", [record], [page], forms={"forms": []},
    )
    angle = package["selected_angles"][0]
    assert angle["organization_id"] == "gregorysfuneralhomes.com"
    assert angle["angle_type"] == "PREARRANGEMENT_PATHWAY_REVIEW"
    assert set(_angle_evidence(record, {"forms": []}, angle["evidence_ids"])) == set(angle["evidence_ids"])
    assert package["form_intelligence"]["forms"] == []
    preview = angle["draft_preview"]
    assert preview["subject"] == "A small review of Gregory's pre-arrangement pathway"
    assert preview["body"].startswith("Hello Gregory's team,")
    assert "Alex De Carlo\nDigital Pathway" in preview["body"]
    sender_placeholders = ("[FULL NAME]", "[BUSINESS NAME]", "[MAILING ADDRESS]", "[PHONE / EMAIL]")
    assert not any(value in draft["body"] for draft in package["drafts"] for value in sender_placeholders)
    assert preview["sendable"] is False and preview["outreach_sent"] is False
    assert all(draft["sendable"] is False and draft["outreach_sent"] is False for draft in package["drafts"])
    rendered = json.dumps({
        "angle": angle,
        "audit": package["customer_safe_mini_audit"],
        "commercial_angle": package["commercial_angle"],
    }).lower()
    assert "non-submitting" in rendered
    assert "no form, usability, accessibility, privacy" in rendered
    for assertion in ("has a broken form", "has a form defect", "has an accessibility defect", "has a privacy defect", "has a conversion defect", "has a usability defect"):
        assert assertion not in rendered


def test_pathway_preview_uses_named_owners_only_with_first_party_support(tmp_path):
    store, record, page = _prepared(
        tmp_path, "gregorysfuneralhomes.com", "Gregory's Funeral Home Inc.",
    )
    record["enrichment"]["facts"].extend([
        {
            "id": "jeremy-owner", "field": "contact.person",
            "value": {"name": "Jeremy Allen", "title": "Owner"},
            "source_url": "https://gregorysfuneralhomes.com/10/Our-Staff.html",
        },
        {
            "id": "bailey-owner", "field": "contact.person",
            "value": {"name": "Bailey Allen", "title": "Owner"},
            "source_url": "https://gregorysfuneralhomes.com/10/Our-Staff.html",
        },
    ])
    package = build_first_prospect_package(store, "gregorysfuneralhomes.com", [record], [page])
    body = package["selected_angles"][0]["draft_preview"]["body"]
    assert body.startswith("Hello Jeremy and Bailey,")
    forbidden = ("defect", "conversion", "revenue", "compliance", "accessibility", "privacy", "security", "abandon", "lost enquiries")
    assert not any(value in body.lower() for value in forbidden)

    for fact in record["enrichment"]["facts"]:
        if fact.get("field") == "contact.person":
            fact["source_url"] = "https://sibling.example/staff"
    neutral = build_first_prospect_package(store, "gregorysfuneralhomes.com", [record], [page])
    assert neutral["selected_angles"][0]["draft_preview"]["body"].startswith("Hello Gregory's team,")

    record["enrichment"]["facts"].append({
        "id": "first-party-non-owner", "field": "contact.person",
        "value": {"name": "Unrelated Staff", "title": "Funeral Director"},
        "source_url": "https://gregorysfuneralhomes.com/10/Our-Staff.html",
    })
    non_owner = build_first_prospect_package(store, "gregorysfuneralhomes.com", [record], [page])
    assert non_owner["selected_angles"][0]["draft_preview"]["body"].startswith("Hello Gregory's team,")


def test_generated_pathway_angle_still_fails_closed_for_foreign_or_missing_evidence(tmp_path):
    store, record, page = _prepared(tmp_path)
    package = build_first_prospect_package(store, "example.ca", [record], [page])
    angle = package["selected_angles"][0]
    with pytest.raises(ValueError, match="another organization"):
        store.select_angle("example.ca", {**angle, "organization_id": "sibling.example"}, "operator", [record], {"forms": []})
    missing = {**angle, "evidence_ids": ["missing-current-evidence"]}
    with pytest.raises(ValueError, match="evidence is missing"):
        store.select_angle("example.ca", missing, "operator", [record], {"forms": []})


def test_pathway_package_generates_v2_for_matching_selected_v1(tmp_path):
    store, record, page = _prepared(
        tmp_path, "gregorysfuneralhomes.com", "Gregory's Funeral Home Inc.",
    )
    first = build_first_prospect_package(store, "gregorysfuneralhomes.com", [record], [page])
    v1 = first["selected_angles"][0]
    selected, _ = store.select_angle(
        "gregorysfuneralhomes.com", v1, "operator", [record], {"forms": []},
    )
    revised = build_first_prospect_package(store, "gregorysfuneralhomes.com", [record], [page])
    v2 = revised["selected_angles"][0]
    assert v2["angle_id"] == "gregorysfuneralhomes.com-prearrangement-pathway-review-v2"
    assert v2["supersedes_angle_id"] == selected["angle_id"]
    assert v2["angle_type"] == selected["angle_type"]
    assert v2["customer_safe_observation"] == selected["customer_safe_observation"]
    assert v2["proposed_improvement"] == selected["proposed_improvement"]
    assert sorted(v2["evidence_ids"]) == selected["evidence_ids"]
