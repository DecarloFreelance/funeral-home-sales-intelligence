import copy
import json
from pathlib import Path

import pytest

from automation import AgentOrchestrator
from automation.agents import RecordAgent
from automation.orchestrator import AgentExecutionError
from commercial_readiness import build_package as build_commercial
from enrichment.company import enrich_company
from pilot.feasibility import ImplementationFeasibilityAgent, evaluate_with_orchestrator
from pilot.workflow import PilotStore, build_pilot_cohort
from pilot_cli import main as pilot_main


def _page(domain="example.ca", *, hosted=False):
    provider = (
        '<link href="/framework/css/cfs-min.css" rel="stylesheet">'
        '<a href="https://consolidatedfuneralservices.com">CFS</a>'
        '<a href="https://www.tributearchive.com">TA</a>'
        if hosted else ""
    )
    return {
        "url": f"https://{domain}/contact-us",
        "text": "Contact Example Funeral Home.",
        "html": f"<html><body>{provider}<form><input name='name'></form></body></html>",
        "metadata": {}, "discovery": {"queue_domain": domain},
        "crawl": {"observedAt": "2026-08-24T00:00:00Z"},
    }


def _record(domain="example.ca"):
    page = _page(domain)
    profile = {"company": "Example Funeral Home", "province": "AB", "locations": []}
    contacts = {
        "emails": [f"info@{domain}"], "phones": [], "people": [],
        "email_sources": [{"value": f"info@{domain}", "source_url": page["url"], "source_type": "page_text"}],
        "phone_sources": [],
        "email_validation": [{"email": f"info@{domain}", "verification_state": "LOCAL_VALID", "confidence": 90}],
        "phone_verification": [],
    }
    return {
        "domain": domain, "pages": 1, "business_profile": profile,
        "contact_intelligence": contacts,
        "quality_control": {"crm_sync_safe": True, "outreach_ready": True, "findings": []},
        "enrichment": enrich_company(domain, [page], profile, contacts),
    }


def _form(domain="example.ca"):
    return {
        "observation_id": f"form-{domain}", "organization_id": domain,
        "page_id": f"page-{domain}", "page_url": f"https://{domain}/contact-us",
        "form_id": f"html-form-{domain}", "form_type": "CONTACT_ONLY_FORM",
        "action_scope": "SAME_ORIGIN", "visible_field_count": 3,
        "detector": "public_form_intelligence", "detector_version": "1.0.0",
        "observed_at": "2026-08-24T00:00:00Z", "verification_state": "DIRECTLY_OBSERVED",
    }


def _angle(domain="example.ca"):
    return {
        "organization_id": domain, "angle_id": f"{domain}-form-labels-v1",
        "angle_type": "FORM_CLARITY_FIX", "evidence_ids": [f"form-{domain}"],
        "customer_safe_observation": "The public contact form presents prompts without explicit control associations.",
        "proposed_improvement": "Preserve the form while adding explicit prompt and control associations.",
        "safety_classification": "CUSTOMER_SAFE_OBSERVATION",
        "source_identity": {"package_id": "fixture"},
        "draft_preview": {"subject": "A small contact-form detail", "body": "Hello team,\n\nI reviewed the public form. Would it be useful if I sent a short summary?"},
    }


def _store(tmp_path, domain="example.ca"):
    record = _record(domain)
    page = _page(domain)
    commercial = build_commercial([record], [page], shortlist_limit=1, prototype_limit=1)
    cohort = build_pilot_cohort([record], commercial, limit=1)
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(cohort)
    return store, record


def _select(store, record, form):
    return store.select_angle(record["domain"], _angle(record["domain"]), "operator", [record], {"forms": [form]})[0]


def _evaluate(tmp_path, store, record, form, page=None):
    return evaluate_with_orchestrator(
        store, record["domain"], [record], {"forms": [form]}, [page or _page(record["domain"])],
        tmp_path / "state.json", tmp_path / "audit.json",
    )


def test_feasibility_requires_selected_angle_and_creates_no_advisory(tmp_path):
    store, record = _store(tmp_path)
    assert _evaluate(tmp_path, store, record, _form()) is None
    assert not (tmp_path / "state.json").exists()


@pytest.mark.parametrize("failure", ["missing", "foreign"])
def test_missing_or_foreign_evidence_fails_closed(failure):
    record = _record()
    form = _form("sibling.ca") if failure == "foreign" else _form()
    angle = {
        **_angle(), "pilot_id": "pilot", "organization_fingerprint": "wrong",
        "evidence_fingerprint": "wrong",
        "evidence_ids": ["form-sibling.ca" if failure == "foreign" else "missing"],
    }
    output = ImplementationFeasibilityAgent().run({
        "domain": "example.ca", "record": record, "selected_angle": angle,
        "forms": {"forms": [form]}, "pages": [_page()],
    })["implementation_feasibility"]
    assert output["advisory_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert output["implementation_path"] == "UNKNOWN_ACCESS"
    assert output["scope"] == "UNSCOPED"


def test_stale_evidence_and_changed_identity_invalidate_advisory(tmp_path):
    store, record = _store(tmp_path)
    form = _form()
    _select(store, record, form)
    current = _evaluate(tmp_path, store, record, form)
    assert current["advisory_outcome"] == "READY_FOR_DISCOVERY"

    changed_form = {**form, "visible_field_count": 4}
    stale = _evaluate(tmp_path, store, record, changed_form)
    assert stale["advisory_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert any("stale" in value for value in stale["limitations"])

    renamed = copy.deepcopy(record)
    renamed["business_profile"]["company"] = "Different Business"
    changed = _evaluate(tmp_path, store, renamed, form)
    assert changed["advisory_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert any("identity changed" in value for value in changed["limitations"])


def test_expired_selected_fact_is_not_reused_as_current_evidence(tmp_path):
    store, record = _store(tmp_path)
    fact = record["enrichment"]["facts"][0]
    fact["stale_after"] = "2020-01-01T00:00:00Z"
    angle = _angle()
    angle["evidence_ids"] = [fact["id"]]
    store.select_angle("example.ca", angle, "operator", [record], {"forms": []})
    result = evaluate_with_orchestrator(
        store, "example.ca", [record], {"forms": []}, [_page()],
        tmp_path / "state.json", tmp_path / "audit.json",
    )
    assert result["advisory_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert any("evidence is stale" in value for value in result["limitations"])


def test_prearrangement_pathway_review_is_bounded_when_fact_evidence_resolves(tmp_path):
    store, record = _store(tmp_path)
    fact = record["enrichment"]["facts"][0]
    angle = {
        **_angle(),
        "angle_type": "PREARRANGEMENT_PATHWAY_REVIEW",
        "evidence_ids": [fact["id"]],
        "customer_safe_observation": "The public website provides a pre-planning pathway.",
        "proposed_improvement": "Perform a non-submitting review and scope only evidence-supported pathway improvements.",
    }
    store.select_angle("example.ca", angle, "operator", [record], {"forms": []})
    result = evaluate_with_orchestrator(
        store, "example.ca", [record], {"forms": []}, [_page()],
        tmp_path / "state.json", tmp_path / "audit.json",
    )
    assert result["scope"] == "NARROW"
    assert result["advisory_outcome"] == "READY_FOR_DISCOVERY"


def test_provider_positive_unknown_direct_and_conflicting_classification(tmp_path):
    store, record = _store(tmp_path)
    form = _form()
    _select(store, record, form)

    unknown = _evaluate(tmp_path, store, record, form)
    assert (unknown["implementation_path"], unknown["scope"], unknown["advisory_outcome"]) == (
        "UNKNOWN_ACCESS", "NARROW", "READY_FOR_DISCOVERY",
    )

    wordpress = copy.deepcopy(record)
    wordpress["enrichment"]["facts"].append({
        "id": "wordpress-evidence", "field": "technology.platform", "value": "WordPress",
        "source_url": "https://example.ca/contact-us", "observed_at": "2026-08-24T00:00:00Z",
        "stale_after": "2026-11-22T00:00:00Z", "confidence": 0.95,
        "verification_state": "DIRECTLY_OBSERVED",
    })
    still_unknown = _evaluate(tmp_path, store, wordpress, form)
    assert still_unknown["implementation_path"] == "UNKNOWN_ACCESS"

    hosted = _evaluate(tmp_path, store, record, form, _page(hosted=True))
    assert hosted["implementation_path"] == "PROVIDER_CONTROL_LIKELY"
    assert hosted["advisory_outcome"] == "PROVIDER_CONFIRMATION_REQUIRED"
    assert {value["provider"] for value in hosted["provider_signals"]} == {
        "CFS Funeral Home Websites", "Tribute Archive infrastructure",
    }

    tribute_only = copy.deepcopy(_page())
    tribute_only["html"] = '<html><a href="https://www.tributearchive.com">Obituaries</a></html>'
    not_provider_control = _evaluate(tmp_path, store, record, form, tribute_only)
    assert not_provider_control["implementation_path"] == "UNKNOWN_ACCESS"

    managed = copy.deepcopy(record)
    managed["enrichment"]["facts"].append({
        "id": "management-evidence", "field": "technology.management",
        "value": "Organization-managed CMS", "source_url": "https://example.ca/contact-us",
        "observed_at": "2026-08-24T00:00:00Z", "stale_after": "2026-11-22T00:00:00Z",
        "confidence": 0.95, "verification_state": "DIRECTLY_OBSERVED",
    })
    direct = _evaluate(tmp_path, store, managed, form)
    assert direct["implementation_path"] == "DIRECT_EDIT_LIKELY"
    conflicting = _evaluate(tmp_path, store, managed, form, _page(hosted=True))
    assert conflicting["implementation_path"] == "PROVIDER_CONTROL_LIKELY"
    assert conflicting["advisory_outcome"] == "PROVIDER_CONFIRMATION_REQUIRED"


def test_identity_blocker_produces_insufficient_unscoped_advisory(tmp_path):
    store, record = _store(tmp_path)
    form = _form()
    _select(store, record, form)
    record["quality_control"]["findings"] = [{"code": "POSSIBLE_DUPLICATE_ORGANIZATION"}]
    result = _evaluate(tmp_path, store, record, form)
    assert result["advisory_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert result["scope"] == "UNSCOPED"


def test_stable_id_skip_and_targeted_input_invalidation(tmp_path):
    store, record = _store(tmp_path)
    form = _form()
    _select(store, record, form)
    first = _evaluate(tmp_path, store, record, form)
    repeated = _evaluate(tmp_path, store, record, form)
    changed = _evaluate(tmp_path, store, record, {**form, "visible_field_count": 4})
    assert first == repeated
    assert first["feasibility_id"] == changed["feasibility_id"]
    outcomes = [value["outcome"] for value in json.loads((tmp_path / "audit.json").read_text())]
    assert outcomes.count("COMPLETED") == 2
    assert outcomes.count("SKIPPED") == 1


def test_evidence_change_invalidates_only_the_affected_organization(tmp_path):
    records = [_record("one.ca"), _record("two.ca")]
    pages = [_page("one.ca"), _page("two.ca")]
    forms = [_form("one.ca"), _form("two.ca")]
    commercial = build_commercial(records, pages, shortlist_limit=2, prototype_limit=1)
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(build_pilot_cohort(records, commercial, limit=2))
    for record, form in zip(records, forms):
        _select(store, record, form)
        evaluate_with_orchestrator(
            store, record["domain"], records, {"forms": forms}, pages,
            tmp_path / "state.json", tmp_path / "audit.json",
        )
    forms[0] = {**forms[0], "visible_field_count": 4}
    for record in records:
        evaluate_with_orchestrator(
            store, record["domain"], records, {"forms": forms}, pages,
            tmp_path / "state.json", tmp_path / "audit.json",
        )
    events = json.loads((tmp_path / "audit.json").read_text())
    outcomes = [(value["entity"], value["outcome"]) for value in events if value["outcome"] in {"COMPLETED", "SKIPPED"}]
    assert outcomes == [
        ("one.ca", "COMPLETED"), ("two.ca", "COMPLETED"),
        ("one.ca", "COMPLETED"), ("two.ca", "SKIPPED"),
    ]


def test_agent_failure_publishes_no_partial_advisory(tmp_path):
    class FailingFeasibility(RecordAgent):
        name = "implementation_feasibility"
        version = "broken"
        max_attempts = 1

        def fingerprint_payload(self, context):
            return context["domain"]

        def run(self, context):
            context["record"]["implementation_feasibility"] = {"partial": True}
            raise RuntimeError("controlled")

    record = _record()
    runner = AgentOrchestrator(tmp_path / "state.json", tmp_path / "audit.json", [FailingFeasibility()])
    with pytest.raises(AgentExecutionError):
        runner.process({"domain": "example.ca", "record": record})
    state = json.loads((tmp_path / "state.json").read_text())
    assert "output" not in state["tasks"]["example.ca:implementation_feasibility"]


def test_advisory_is_internal_only_and_cannot_mutate_or_leak(tmp_path):
    store, record = _store(tmp_path)
    form = _form()
    _select(store, record, form)
    before_events = (tmp_path / "events.json").read_bytes()
    before_quality = copy.deepcopy(record["quality_control"])
    before_contact = copy.deepcopy(store._prospect("example.ca")["selected_contact"])
    result = _evaluate(tmp_path, store, record, form)
    assert result["internal_only"] is True
    assert set(result["forbidden_authority"]) == {
        "approval", "outreach", "CRM", "lifecycle mutation", "site modification", "pricing",
    }
    assert store.state("example.ca") == "CANDIDATE"
    assert (tmp_path / "events.json").read_bytes() == before_events
    assert record["quality_control"] == before_quality
    assert store._prospect("example.ca")["selected_contact"] == before_contact

    record_with_advisory = {**record, "implementation_feasibility": result}
    customer = build_pilot_cohort(
        [record_with_advisory], build_commercial([record_with_advisory], [_page()], shortlist_limit=1), limit=1,
    )["prospects"][0]["audit_package"]["customer_safe_audit"]
    rendered = json.dumps(customer)
    assert "implementation_feasibility" not in rendered
    assert "PROVIDER_CONTROL_LIKELY" not in rendered


def test_cli_feasibility_prints_internal_advisory_without_pilot_event(tmp_path, capsys):
    store, record = _store(tmp_path)
    form = _form()
    _select(store, record, form)
    results = tmp_path / "results.json"; results.write_text(json.dumps([record]))
    forms = tmp_path / "forms.json"; forms.write_text(json.dumps({"forms": [form]}))
    pages = tmp_path / "pages.json"; pages.write_text(json.dumps([_page()]))
    before = (tmp_path / "events.json").read_bytes()
    pilot_main([
        "--cohort", str(tmp_path / "cohort.json"), "--events", str(tmp_path / "events.json"),
        "feasibility", "example.ca", "--results", str(results), "--forms", str(forms),
        "--pages", str(pages), "--state", str(tmp_path / "feasibility-state.json"),
        "--audit", str(tmp_path / "feasibility-audit.json"),
    ])
    output = json.loads(capsys.readouterr().out)
    assert output["advisory_outcome"] == "READY_FOR_DISCOVERY"
    assert output["internal_only"] is True
    assert (tmp_path / "events.json").read_bytes() == before


@pytest.mark.parametrize(
    ("domain", "hosted", "expected"),
    [
        ("missionview.ca", True, "PROVIDER_CONTROL_LIKELY"),
        ("foothillsmemorialchapel.com", True, "PROVIDER_CONTROL_LIKELY"),
        ("fernhillcemetery.ca", False, "UNKNOWN_ACCESS"),
    ],
)
def test_realistic_pilot_provider_cases_use_evidence_not_domain_special_cases(tmp_path, domain, hosted, expected):
    store, record = _store(tmp_path, domain)
    form = _form(domain)
    _select(store, record, form)
    result = _evaluate(tmp_path, store, record, form, _page(domain, hosted=hosted))
    assert result["implementation_path"] == expected
    if hosted:
        assert {value["provider"] for value in result["provider_signals"]} == {
            "CFS Funeral Home Websites", "Tribute Archive infrastructure",
        }
    else:
        assert result["provider_signals"] == []


def test_agent_has_no_network_send_crm_or_site_write_interface():
    public = {name for name in dir(ImplementationFeasibilityAgent) if not name.startswith("_")}
    assert public == {"fingerprint_payload", "max_attempts", "name", "run", "version"}
