import json
from pathlib import Path

import pytest

from automation.agents import RecordAgent
from automation.orchestrator import AgentExecutionError, AgentOrchestrator
from commercial_readiness import build_package
from run_enrichment import run as run_enrichment
from run_research_resolution import run as run_research


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _page(domain="example.ca", url=None, text="Funeral services and cremation. Contact info@example.ca or 403-555-0100"):
    return {
        "url": url or f"https://{domain}/",
        "markdown": text,
        "html": f"<html><body>{text}</body></html>",
        "metadata": {},
        "discovery": {"queue_domain": domain},
        "crawl": {"observedAt": "2026-08-24T00:00:00Z"},
    }


def _record(domain="example.ca", *, safe=True):
    return {
        "domain": domain,
        "pages": 1,
        "business_profile": {
            "company": "Example Funeral Home", "province": "AB", "locations": [],
            "business_names": [], "sources": [],
            "provenance": [{"source_url": "https://directory.example/record"}],
        },
        "contact_intelligence": {
            "emails": [f"info@{domain}"], "phones": ["+14035550100"], "people": [],
            "email_sources": [{"value": f"info@{domain}", "source_url": f"https://{domain}/", "source_type": "page_text"}],
            "phone_sources": [{"value": "+14035550100", "source_url": f"https://{domain}/", "source_type": "page_text"}],
            "email_validation": [{"email": f"info@{domain}", "verification_state": "LOCAL_VALID", "confidence": 90}],
            "phone_verification": [{"phone": "+14035550100", "normalized": "+14035550100", "verification_state": "METADATA_VALIDATED", "confidence": 90}],
        },
        "quality_control": {"crm_sync_safe": safe, "outreach_ready": safe},
    }


def test_canonical_agents_persist_outputs_consumed_by_downstream(tmp_path):
    pages = _write(tmp_path / "pages.json", [_page()])
    results = _write(tmp_path / "results.json", [_record()])
    output, state, audit, review = (tmp_path / name for name in ("output.json", "state.json", "audit.json", "review.json"))

    summary = run_enrichment(pages, results, output, state, audit, review)
    persisted = json.loads(output.read_text())[0]
    tasks = json.loads(state.read_text())["tasks"]

    assert summary == {"records": 1, "needs_review": 0}
    assert set(tasks) == {"example.ca:enrichment", "example.ca:quality_control"}
    assert persisted["enrichment"] == tasks["example.ca:enrichment"]["output"]["enrichment"]
    assert persisted["quality_control"]["crm_sync_safe"] is True
    assert all(fact["source_url"] and fact["observed_at"] for fact in persisted["enrichment"]["facts"])

    package = build_package([persisted], [_page()], shortlist_limit=1, prototype_limit=1)
    assert package["shortlist"][0]["organization_id"] == "example.ca"
    assert package["shortlist"][0]["evidence_references"]


def test_research_agent_persists_unresolved_not_confirmed(tmp_path):
    research = _write(tmp_path / "research.json", [{
        "domain": "branch.example", "company": "Branch Funeral Home", "attempts": [], "locations": [],
    }])
    finding = {"id": "finding-1", "code": "NO_USABLE_WEBSITE_EVIDENCE", "evidence": {"pages": 0}}
    review = _write(tmp_path / "review.json", [{"domain": "branch.example", "findings": [finding]}])
    paths = [tmp_path / name for name in ("output.json", "queue.json", "state.json", "audit.json")]

    summary = run_research(research, review, *paths)
    persisted = json.loads(paths[0].read_text())[0]
    outcome = persisted["research_resolution"]["questions"][0]["outcome"]

    assert summary["ambiguous"] == 1
    assert outcome["resolved"] is False
    assert outcome["verification_state"] == "UNRESOLVED"
    assert json.loads(paths[1].read_text()) == []


class _PublishingAgent(RecordAgent):
    name = "publisher"
    version = "1"

    def fingerprint_payload(self, context):
        return context["record"]

    def run(self, context):
        return {"unsafe": True}


class _FailingAgent(_PublishingAgent):
    name = "failure"

    def run(self, context):
        raise RuntimeError("injected")


def test_partial_agent_failure_is_visible_and_never_returns_partial_publication(tmp_path):
    orchestrator = AgentOrchestrator(tmp_path / "state.json", tmp_path / "audit.json", [_PublishingAgent(), _FailingAgent()])

    with pytest.raises(AgentExecutionError):
        orchestrator.process({"domain": "example.ca", "record": {}})

    state = json.loads((tmp_path / "state.json").read_text())["tasks"]
    events = json.loads((tmp_path / "audit.json").read_text())
    assert state["example.ca:publisher"]["status"] == "COMPLETED"
    assert state["example.ca:failure"]["status"] == "FAILED"
    assert events[-1]["outcome"] == "FAILED"


def test_commercial_package_fails_closed_and_does_not_cross_sibling_evidence():
    first = _record("one.example")
    second = _record("two.example")
    unsafe = _record("blocked.example", safe=False)
    pages = [_page("one.example"), _page("two.example"), _page("blocked.example")]

    # Enrich separately, proving organization-specific page ownership before presentation.
    from enrichment.company import enrich_company
    for record, page in zip((first, second, unsafe), pages):
        record["enrichment"] = enrich_company(record["domain"], [page], record["business_profile"], record["contact_intelligence"])
    package = build_package([first, second, unsafe], pages)

    assert [item["organization_id"] for item in package["shortlist"]] == ["one.example", "two.example"]
    assert all(
        all(url.startswith(f"https://{item['organization_id']}") for url in item["pages_checked"])
        for item in package["shortlist"]
    )
    assert package["safety"] == {"outreach_performed": False, "crm_write_performed": False}


def test_commercial_generation_is_deterministic():
    record = _record()
    from enrichment.company import enrich_company
    record["enrichment"] = enrich_company("example.ca", [_page()], record["business_profile"], record["contact_intelligence"])
    first = build_package([record], [_page()])
    second = build_package([record], [_page()])
    assert first == second
