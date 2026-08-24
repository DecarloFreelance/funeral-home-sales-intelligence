import json

import pytest

from commercial_readiness import build_package as build_commercial
from enrichment.company import enrich_company
from pilot.workflow import OFFER, PilotStore, build_pilot_cohort
from pilot_cli import main as pilot_main


def _page(domain="example.ca", *, text="Funeral services, obituaries and pre-planning. Contact info@example.ca"):
    return {
        "url": f"https://{domain}/", "markdown": text,
        "html": f"<html><body>{text}</body></html>", "metadata": {},
        "discovery": {"queue_domain": domain},
        "crawl": {"observedAt": "2026-08-24T00:00:00Z"},
    }


def _record(domain="example.ca", *, safe=True, source_domain=None):
    source_domain = source_domain or domain
    contact = {
        "emails": [f"info@{domain}"], "phones": ["+14035550100"], "people": [],
        "email_sources": [{"value": f"info@{domain}", "source_url": f"https://{source_domain}/", "source_type": "page_text"}],
        "phone_sources": [{"value": "+14035550100", "source_url": f"https://{source_domain}/", "source_type": "page_text"}],
        "email_validation": [{"email": f"info@{domain}", "verification_state": "LOCAL_VALID", "confidence": 90}],
        "phone_verification": [{"phone": "+14035550100", "normalized": "+14035550100", "verification_state": "METADATA_VALIDATED", "confidence": 90}],
    }
    profile = {
        "company": f"{domain} Funeral Home", "province": "AB", "locations": [{"city": "Calgary", "province": "AB"}],
        "business_names": [], "sources": [], "provenance": [{"source_url": "https://directory.example/record"}],
    }
    page = _page(source_domain)
    record = {
        "domain": domain, "pages": 1, "business_profile": profile,
        "contact_intelligence": contact,
        "quality_control": {"crm_sync_safe": safe, "outreach_ready": safe},
        "executive_priority_score": 99, "revenue_opportunity_score": 95,
    }
    record["enrichment"] = enrich_company(domain, [page], profile, contact)
    return record, page


def _cohort(records=None, pages=None, limit=10):
    if records is None:
        record, page = _record()
        records, pages = [record], [page]
    commercial = build_commercial(records, pages, shortlist_limit=25, prototype_limit=5)
    return build_pilot_cohort(records, commercial, limit=limit)


def test_only_explicitly_safe_records_enter_pilot_and_missing_state_fails_closed():
    safe, safe_page = _record("safe.ca")
    blocked, blocked_page = _record("blocked.ca", safe=False)
    missing, missing_page = _record("missing.ca")
    missing.pop("quality_control")
    cohort = _cohort([safe, blocked, missing], [safe_page, blocked_page, missing_page])
    assert [item["organization_id"] for item in cohort["prospects"]] == ["safe.ca"]


def test_customer_audit_excludes_internal_scores_and_uses_bounded_wording():
    prospect = _cohort()["prospects"][0]
    customer = prospect["audit_package"]["customer_safe_audit"]
    rendered = json.dumps(customer).lower()
    assert "executive_priority" not in rendered
    assert "revenue_opportunity" not in rendered
    assert "lost revenue" not in rendered
    negatives = [item for item in customer["observations"] if item["observation_type"] == "NOT_DETECTED_IN_SCAN"]
    assert negatives
    assert all(item["statement"].startswith("During our bounded website scan, we did not detect") for item in negatives)
    assert all("you don't" not in item["statement"].lower() for item in negatives)


def test_evidence_references_survive_and_belong_to_same_organization():
    prospect = _cohort()["prospects"][0]
    audit = prospect["audit_package"]
    evidence = audit["evidence_appendix"]
    for section in ("observations", "opportunities", "recommended_actions"):
        for item in audit["customer_safe_audit"][section]:
            assert set(item["evidence_ids"]).issubset(evidence)
    assert audit["customer_safe_audit"]["contact"]["evidence"]["evidence_id"] in evidence


def test_sibling_page_cannot_enter_package():
    record, _ = _record("one.ca")
    sibling = _page("two.ca")
    record["enrichment"] = enrich_company("one.ca", [sibling], record["business_profile"], record["contact_intelligence"])
    record["quality_control"] = {"crm_sync_safe": True, "outreach_ready": True}
    commercial = {
        "shortlist": [{
            "organization_id": "one.ca", "rank_score": 10, "selection_reasons": [],
            "pages_checked": ["https://two.ca/"], "observed_opportunities": [{"field": "digital.online_arrangements"}],
            "page_evidence": [{"organization_id": "two.ca", "url": "https://two.ca/"}],
        }]
    }
    with pytest.raises(ValueError, match="does not belong"):
        build_pilot_cohort([record], commercial)


def test_state_history_is_append_only_and_approval_requires_review(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    record, _ = _record()
    with pytest.raises(ValueError, match="current-evidence"):
        store.transition(identifier, "APPROVED_FOR_CONTACT", "operator")
    store.transition(identifier, "MANUAL_REVIEW", "operator", note="Sources inspected")
    store.approve(identifier, "operator", [record], note="Claims approved")
    history = store.history(identifier)
    assert [item["to_state"] for item in history] == ["MANUAL_REVIEW", "APPROVED_FOR_CONTACT"]
    assert all(item["selected_audit_id"] for item in history)


def test_draft_requires_approval_is_evidence_supported_and_never_sends(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    with pytest.raises(ValueError, match="requires explicit"):
        store.prepare_draft(identifier, "operator")
    record, _ = _record()
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    store.approve(identifier, "operator", [record])
    event, created = store.prepare_draft(identifier, "operator")
    repeated, repeated_created = store.prepare_draft(identifier, "operator")
    appendix = store._prospect(identifier)["audit_package"]["evidence_appendix"]
    assert created is True and repeated_created is False and repeated == event
    assert event["draft"]["status"] == "PREPARED_UNSENT"
    assert event["draft"]["outreach_sent"] is False
    assert set(event["draft"]["supporting_evidence_ids"]).issubset(appendix)
    assert "revenue" not in event["draft"]["body"].lower()


def test_offer_assignment_and_manual_funnel_metrics(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    record, _ = _record()
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    store.approve(identifier, "operator", [record])
    store.prepare_draft(identifier, "operator")
    contacted, _ = store.transition(identifier, "CONTACTED", "operator", note="Manually sent outside system", activity_references=["manual-email-log:1"])
    store.transition(identifier, "REPLIED", "operator", reply_sentiment="POSITIVE")
    store.transition(identifier, "MEETING", "operator")
    store.transition(identifier, "PROPOSAL", "operator")
    store.assign_offer(identifier, "AUDIT_PLUS_FIX", "operator", quoted_amount=1500, accepted_amount=1200)
    store.transition(identifier, "WON", "operator")
    stats = store.stats()
    assert stats["contacted"] == stats["positive_replies"] == stats["meetings"] == stats["proposals"] == stats["wins"] == 1
    assert stats["manual_revenue"] == 1200
    assert stats["rates_percent"]["proposal_to_win"] == 100.0
    assert stats["offer_variants"] == {"AUDIT_PLUS_FIX": 1}
    assert contacted["activity_references"] == ["manual-email-log:1"]
    assert contacted["selected_audit_version"]


def test_negative_offer_amount_and_invalid_progression_are_rejected(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    with pytest.raises(ValueError, match="negative"):
        store.assign_offer(identifier, "AUDIT", "operator", quoted_amount=-1)
    with pytest.raises(ValueError, match="not allowed"):
        store.transition(identifier, "CONTACTED", "operator")


def test_approval_rechecks_current_readiness_and_evidence(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    blocked, _ = _record(safe=False)
    with pytest.raises(ValueError, match="readiness"):
        store.approve(identifier, "operator", [blocked])
    current, _ = _record()
    current["enrichment"]["facts"] = []
    with pytest.raises(ValueError, match="no longer supports"):
        store.approve(identifier, "operator", [current])
    assert store.state(identifier) == "MANUAL_REVIEW"


def test_generation_is_idempotent_and_has_no_external_side_effect_flags(tmp_path):
    cohort = _cohort()
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    assert store.save_cohort(cohort) is True
    before = (tmp_path / "cohort.json").read_bytes()
    assert store.save_cohort(_cohort()) is False
    assert (tmp_path / "cohort.json").read_bytes() == before
    assert not (tmp_path / "events.json").exists()
    assert cohort["safety"] == {"crm_write_performed": False, "network_request_performed": False, "outreach_sent": False}
    preview = cohort["prospects"][0]["guarded_draft_preview"]
    assert preview["sendable"] is False and preview["outreach_sent"] is False
    assert "to" not in preview


def test_cli_list_show_audit_history_stats_and_guarded_draft(tmp_path, capsys):
    records_path, commercial_path = tmp_path / "records.json", tmp_path / "commercial.json"
    record, page = _record()
    commercial = build_commercial([record], [page])
    records_path.write_text(json.dumps([record]))
    commercial_path.write_text(json.dumps(commercial))
    cohort_path, events_path = tmp_path / "cohort.json", tmp_path / "events.json"
    common = ["--cohort", str(cohort_path), "--events", str(events_path)]
    pilot_main([*common, "generate", "--results", str(records_path), "--commercial", str(commercial_path)])
    generated = json.loads(capsys.readouterr().out)
    identifier = json.loads(cohort_path.read_text())["prospects"][0]["pilot_id"]
    assert generated["prospects"] == 1
    pilot_main([*common, "list"]); assert json.loads(capsys.readouterr().out)[0]["current_state"] == "CANDIDATE"
    pilot_main([*common, "show", identifier]); assert json.loads(capsys.readouterr().out)["pilot_id"] == identifier
    pilot_main([*common, "audit", identifier]); assert json.loads(capsys.readouterr().out)["customer_safe_audit"]
    pilot_main([*common, "review", identifier, "--actor", "operator"]); capsys.readouterr()
    pilot_main([*common, "approve", identifier, "--actor", "operator", "--results", str(records_path)]); capsys.readouterr()
    pilot_main([*common, "draft", identifier, "--actor", "operator"]); assert json.loads(capsys.readouterr().out)["outreach_sent"] is False
    pilot_main([*common, "history", identifier]); assert len(json.loads(capsys.readouterr().out)) == 3
    pilot_main([*common, "stats"]); assert json.loads(capsys.readouterr().out)["drafted"] == 1


def test_offer_definition_has_required_internal_variants_and_content_classes():
    assert set(OFFER["variants"]) == {"AUDIT", "AUDIT_PLUS_FIX", "MANAGED"}
    assert set(OFFER["content_classes"]) == {
        "OBSERVED", "NOT_DETECTED_IN_SCAN", "INTERPRETATION", "RECOMMENDED_ACTION", "INTERNAL_ONLY",
    }
