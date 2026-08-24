import json

import pytest

from commercial_readiness import build_package as build_commercial
from enrichment.company import enrich_company
from pilot.prospect import build_first_prospect_package
from pilot.workflow import OFFER, PRESEND_CHECKS, PilotStore, build_pilot_cohort
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


def _complete_presend(store, identifier, *, actor="operator"):
    return store.record_presend_review(
        identifier, "PUBLICATION_EVIDENCE_PRESENT", actor,
        business_relevance="Website-path review is relevant to the published business contact.",
        note="Human checked the cited publication and message requirements.",
        checks=PRESEND_CHECKS,
    )


def _selected_angle(record, *, organization_id="example.ca", evidence_ids=None):
    facts = (record.get("enrichment") or {}).get("facts") or []
    evidence_ids = evidence_ids or [facts[0]["id"]]
    return {
        "angle_id": "homepage-form-labels", "organization_id": organization_id,
        "angle_type": "FORM_CLARITY_FIX", "evidence_ids": evidence_ids,
        "customer_safe_observation": "The homepage form identifies its fields with placeholder text rather than persistent labels.",
        "proposed_improvement": "Add persistent associated labels and verify the result.",
        "safety_classification": "CUSTOMER_SAFE_OBSERVATION",
        "source_identity": {"package_id": "evaluation-1"},
        "draft_preview": {
            "subject": "A small issue on the homepage enquiry form",
            "body": "Hello team,\n\nI reviewed the public homepage form. Its fields are identified with placeholder text rather than persistent field labels. Would it be useful if I sent the one-page summary?\n\n[SENDER IDENTIFICATION]\n\nReply ‘unsubscribe’ and I will stop.",
        },
    }


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
    _complete_presend(store, identifier)
    store.approve(identifier, "operator", [record], note="Claims approved")
    history = store.history(identifier)
    assert [item.get("to_state") for item in history if item["event_type"] == "STATE_TRANSITION"] == ["MANUAL_REVIEW", "APPROVED_FOR_CONTACT"]
    assert all(item["selected_audit_id"] for item in history if item["event_type"] == "STATE_TRANSITION")


def test_draft_requires_approval_is_evidence_supported_and_never_sends(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    before = store.effective()[0]
    assert before["draft_status"] == "BLOCKED_PENDING_MANUAL_REVIEW_AND_APPROVAL"
    assert before["guarded_draft_preview"]["sendable"] is False
    assert before["guarded_draft_preview"]["status"] != "PREPARED_UNSENT"
    with pytest.raises(ValueError, match="requires explicit"):
        store.prepare_draft(identifier, "operator")
    record, _ = _record()
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    _complete_presend(store, identifier)
    store.approve(identifier, "operator", [record])
    approved = store.effective()[0]
    assert approved["current_state"] == "APPROVED_FOR_CONTACT"
    assert approved["draft_status"] == "BLOCKED_PENDING_MANUAL_REVIEW_AND_APPROVAL"
    assert approved["guarded_draft_preview"]["status"] != "PREPARED_UNSENT"
    event, created = store.prepare_draft(identifier, "operator")
    repeated, repeated_created = store.prepare_draft(identifier, "operator")
    appendix = store._prospect(identifier)["audit_package"]["evidence_appendix"]
    assert created is True and repeated_created is False and repeated == event
    assert event["draft"]["status"] == "PREPARED_UNSENT"
    assert event["draft"]["outreach_sent"] is False
    assert set(event["draft"]["supporting_evidence_ids"]).issubset(appendix)
    assert "revenue" not in event["draft"]["body"].lower()
    effective = store.effective()[0]
    assert effective["current_state"] == "CONTACT_PREPARED"
    assert effective["draft_status"] == "PREPARED_UNSENT"
    assert effective["guarded_draft_preview"] == event["draft"]


def test_selected_angle_is_canonical_preview_then_prepared_unsent(tmp_path):
    record, _ = _record()
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort([record], [_page()]))
    identifier = store.effective()[0]["pilot_id"]
    selected, created = store.select_angle(identifier, _selected_angle(record), "operator", [record], {"forms": []})
    assert created is True
    assert selected["draft_preview"]["status"] == "PREVIEW_ONLY_NOT_PREPARED"
    assert store.state(identifier) == "CANDIDATE"
    assert not any(event.get("draft", {}).get("status") == "PREPARED_UNSENT" for event in store.history(identifier))
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    _complete_presend(store, identifier)
    store.approve(identifier, "operator", [record], forms={"forms": []})
    event, created = store.prepare_draft(identifier, "operator", records=[record], forms={"forms": []})
    assert created is True and event["draft"]["status"] == "PREPARED_UNSENT"
    assert event["draft"]["subject"] == "A small issue on the homepage enquiry form"
    assert "placeholder text rather than persistent field labels" in event["draft"]["body"]
    assert event["draft"]["supporting_evidence_ids"] == selected["evidence_ids"]
    assert event["draft"]["outreach_sent"] is False and event["draft"]["sendable"] is False
    effective = store.effective()[0]
    assert effective["guarded_draft_preview"] == event["draft"]
    assert effective["guarded_draft_preview"] != store._prospect(identifier)["guarded_draft_preview"]
    assert effective["guarded_draft_preview"]["selected_angle_id"] == selected["angle_id"]
    rendered = json.dumps(event["draft"]).lower()
    assert all(term not in rendered for term in ("internal score", "lost revenue", "compliance", "conversion loss"))


def test_selected_angle_fails_closed_without_fallback_on_foreign_missing_stale_or_identity_evidence(tmp_path):
    record, _ = _record()
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort([record], [_page()]))
    identifier = store.effective()[0]["pilot_id"]
    foreign = _selected_angle(record, organization_id="foreign.ca")
    with pytest.raises(ValueError, match="another organization"):
        store.select_angle(identifier, foreign, "operator", [record], {"forms": []})
    missing = _selected_angle(record, evidence_ids=["missing"])
    with pytest.raises(ValueError, match="evidence is missing"):
        store.select_angle(identifier, missing, "operator", [record], {"forms": []})
    store.select_angle(identifier, _selected_angle(record), "operator", [record], {"forms": []})
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    _complete_presend(store, identifier)
    changed = json.loads(json.dumps(record))
    changed["enrichment"]["facts"][0]["value"] = "materially changed"
    with pytest.raises(ValueError, match="stale or materially changed"):
        store.approve(identifier, "operator", [changed], forms={"forms": []})
    renamed = json.loads(json.dumps(record))
    renamed["business_profile"]["company"] = "Different Organization"
    with pytest.raises(ValueError, match="organization identity changed"):
        store.approve(identifier, "operator", [renamed], forms={"forms": []})
    assert store.state(identifier) == "MANUAL_REVIEW"


def test_selected_angle_rejects_foreign_form_and_unsafe_content(tmp_path):
    record, _ = _record()
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort([record], [_page()]))
    identifier = store.effective()[0]["pilot_id"]
    angle = _selected_angle(record, evidence_ids=["form-observation"])
    forms = {"forms": [{"observation_id": "form-observation", "organization_id": "sibling.ca"}]}
    with pytest.raises(ValueError, match="another organization"):
        store.select_angle(identifier, angle, "operator", [record], forms)
    unsafe = _selected_angle(record)
    unsafe["draft_preview"]["body"] = "This form causes conversion loss."
    with pytest.raises(ValueError, match="unsupported customer claim"):
        store.select_angle(identifier, unsafe, "operator", [record], {"forms": []})


def test_selected_angle_form_evidence_is_idempotent_and_stale_changes_fail_closed(tmp_path):
    record, _ = _record()
    fact_ids = [fact["id"] for fact in record["enrichment"]["facts"][:2]]
    form = {"observation_id": "form-observation", "organization_id": "example.ca", "visible_field_count": 4}
    forms = {"forms": [form]}
    angle = _selected_angle(record, evidence_ids=[*fact_ids, "form-observation"])
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort([record], [_page()]))
    identifier = store.effective()[0]["pilot_id"]
    selected, created = store.select_angle(identifier, angle, "operator", [record], forms)
    repeated, repeated_created = store.select_angle(identifier, angle, "operator", [record], forms)
    assert created is True and repeated_created is False and repeated == selected
    changed_forms = {"forms": [{**form, "visible_field_count": 5}]}
    with pytest.raises(ValueError, match="stale or materially changed"):
        store.validate_selected_angle(identifier, [record], changed_forms)
    with pytest.raises(ValueError, match="evidence is missing"):
        store.validate_selected_angle(identifier, [record], {"forms": []})


def test_selected_angle_revision_supersedes_append_only_and_drives_future_draft(tmp_path):
    record, _ = _record()
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort([record], [_page()]))
    identifier = store.effective()[0]["pilot_id"]
    v1_payload = _selected_angle(record)
    v1_payload["angle_id"] = "homepage-form-labels-v1"
    v1, created = store.select_angle(identifier, v1_payload, "operator", [record], {"forms": []})
    assert created is True

    v2_payload = {
        **v1_payload,
        "angle_id": "homepage-form-labels-v2",
        "supersedes_angle_id": v1["angle_id"],
        "draft_preview": {
            **v1_payload["draft_preview"],
            "subject": "A revised homepage form review",
            "body": v1_payload["draft_preview"]["body"].replace(
                "I reviewed", "I completed a revised review of",
            ),
        },
    }
    v2, v2_created = store.select_angle(identifier, v2_payload, "operator", [record], {"forms": []})
    repeated, repeated_created = store.select_angle(identifier, v2_payload, "operator", [record], {"forms": []})
    selected_events = [event for event in store.history(identifier) if event["event_type"] == "COMMERCIAL_ANGLE_SELECTED"]
    assert v2_created is True and repeated_created is False and repeated == v2
    assert [event["angle_id"] for event in selected_events] == [v1["angle_id"], v2["angle_id"]]
    assert selected_events[0] == v1
    assert v2["supersedes_angle_id"] == v1["angle_id"]
    assert v2["evidence_ids"] == v1["evidence_ids"]
    assert v2["evidence_fingerprint"] == v1["evidence_fingerprint"]
    assert store.selected_angle(identifier) == v2
    assert store.validate_selected_angle(identifier, [record], {"forms": []}) == v2

    store.transition(identifier, "MANUAL_REVIEW", "operator")
    _complete_presend(store, identifier)
    store.approve(identifier, "operator", [record], forms={"forms": []})
    prepared, _ = store.prepare_draft(identifier, "operator", records=[record], forms={"forms": []})
    assert prepared["draft"]["selected_angle_id"] == v2["angle_id"]
    assert prepared["draft"]["subject"] == v2_payload["draft_preview"]["subject"]
    assert prepared["draft"]["body"] == v2_payload["draft_preview"]["body"]
    assert prepared["draft"]["sendable"] is False
    assert prepared["draft"]["outreach_sent"] is False


def test_selected_angle_revision_rejects_foreign_missing_and_stale_supersession(tmp_path):
    record, _ = _record()
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort([record], [_page()]))
    identifier = store.effective()[0]["pilot_id"]
    v1_payload = _selected_angle(record)
    v1_payload["angle_id"] = "homepage-form-labels-v1"
    v1, _ = store.select_angle(identifier, v1_payload, "operator", [record], {"forms": []})
    revision = {
        **v1_payload,
        "angle_id": "homepage-form-labels-v2",
        "supersedes_angle_id": v1["angle_id"],
        "draft_preview": {**v1_payload["draft_preview"], "subject": "Revised subject"},
    }
    with pytest.raises(ValueError, match="must supersede the current angle"):
        store.select_angle(identifier, {**revision, "supersedes_angle_id": "foreign-angle-v1"}, "operator", [record], {"forms": []})
    with pytest.raises(ValueError, match="evidence is missing"):
        store.select_angle(identifier, {**revision, "evidence_ids": ["missing"]}, "operator", [record], {"forms": []})
    changed = json.loads(json.dumps(record))
    changed["enrichment"]["facts"][0]["value"] = "materially changed"
    with pytest.raises(ValueError, match="stale or materially changed"):
        store.select_angle(identifier, revision, "operator", [changed], {"forms": []})
    assert store.selected_angle(identifier) == v1
    assert len([event for event in store.history(identifier) if event["event_type"] == "COMMERCIAL_ANGLE_SELECTED"]) == 1


def test_selected_angle_does_not_bypass_do_not_contact_and_generic_remains_supported(tmp_path):
    record, _ = _record()
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort([record], [_page()]))
    identifier = store.effective()[0]["pilot_id"]
    store.select_angle(identifier, _selected_angle(record), "operator", [record], {"forms": []})
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    _complete_presend(store, identifier)
    store.approve(identifier, "operator", [record], forms={"forms": []})
    store.record_presend_review(identifier, "DO_NOT_CONTACT", "operator")
    with pytest.raises(ValueError, match="pre-send"):
        store.prepare_draft(identifier, "operator", records=[record], forms={"forms": []})

    generic = PilotStore(tmp_path / "generic.json", tmp_path / "generic-events.json")
    generic.save_cohort(_cohort([record], [_page()]))
    generic_id = generic.effective()[0]["pilot_id"]
    generic.transition(generic_id, "MANUAL_REVIEW", "operator")
    _complete_presend(generic, generic_id)
    generic.approve(generic_id, "operator", [record])
    event, _ = generic.prepare_draft(generic_id, "operator")
    assert event["draft"]["status"] == "PREPARED_UNSENT"


def test_offer_assignment_and_manual_funnel_metrics(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    record, _ = _record()
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    _complete_presend(store, identifier)
    store.approve(identifier, "operator", [record])
    prepared, _ = store.prepare_draft(identifier, "operator")
    contacted, _ = store.transition(identifier, "CONTACTED", "operator", note="Manually sent outside system", activity_references=["manual-email-log:1"])
    effective = store.effective()[0]
    assert effective["current_state"] == "CONTACTED"
    assert effective["draft_status"] == "PREPARED_UNSENT"
    assert effective["guarded_draft_preview"] == prepared["draft"]
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
    _complete_presend(store, identifier)
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
    checks = [item for check in sorted(PRESEND_CHECKS) for item in ("--check", check)]
    pilot_main([*common, "presend", identifier]); assert json.loads(capsys.readouterr().out)["status"] == "REVIEW_REQUIRED"
    pilot_main([*common, "presend-review", identifier, "PUBLICATION_EVIDENCE_PRESENT", "--actor", "operator", "--business-relevance", "Relevant website review", *checks]); capsys.readouterr()
    pilot_main([*common, "approve", identifier, "--actor", "operator", "--results", str(records_path)]); capsys.readouterr()
    pilot_main([*common, "draft", identifier, "--actor", "operator"])
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["outreach_sent"] is False
    pilot_main([*common, "show", identifier])
    shown = json.loads(capsys.readouterr().out)
    assert shown["current_state"] == "CONTACT_PREPARED"
    assert shown["draft_status"] == "PREPARED_UNSENT"
    assert shown["guarded_draft_preview"]["subject"] == prepared["draft"]["subject"]
    assert shown["guarded_draft_preview"]["body"] == prepared["draft"]["body"]
    pilot_main([*common, "history", identifier]); assert len(json.loads(capsys.readouterr().out)) == 4
    pilot_main([*common, "stats"]); assert json.loads(capsys.readouterr().out)["drafted"] == 1


def test_offer_definition_has_required_internal_variants_and_content_classes():
    assert set(OFFER["variants"]) == {"AUDIT", "AUDIT_PLUS_FIX", "MANAGED"}
    assert set(OFFER["content_classes"]) == {
        "OBSERVED", "NOT_DETECTED_IN_SCAN", "INTERPRETATION", "RECOMMENDED_ACTION", "INTERNAL_ONLY",
    }


def test_presend_defaults_fail_closed_and_public_or_dns_email_is_not_approval(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    review = store.presend_review(identifier)
    assert review["status"] == "REVIEW_REQUIRED"
    assert review["outreach_authorized"] is False
    assert review["source_url"] == "https://example.ca/"
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    with pytest.raises(ValueError, match="pre-send"):
        store.approve(identifier, "operator", [_record()[0]])


def test_presend_requires_relevance_all_checks_and_same_organization(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    with pytest.raises(ValueError, match="business-relevance"):
        store.record_presend_review(identifier, "PUBLICATION_EVIDENCE_PRESENT", "operator", checks=PRESEND_CHECKS)
    with pytest.raises(ValueError, match="every pre-send"):
        store.record_presend_review(identifier, "PUBLICATION_EVIDENCE_PRESENT", "operator", business_relevance="Relevant")

    checks_without_sender = PRESEND_CHECKS - {"sender_identification_ready"}
    with pytest.raises(ValueError, match="every pre-send"):
        store.record_presend_review(
            identifier, "PUBLICATION_EVIDENCE_PRESENT", "operator",
            business_relevance="Relevant", checks=checks_without_sender,
        )
    assert store.presend_review(identifier)["status"] == "REVIEW_REQUIRED"
    assert store.state(identifier) == "CANDIDATE"

    foreign, foreign_page = _record("one.ca", source_domain="two.ca")
    foreign["enrichment"] = enrich_company("one.ca", [foreign_page], foreign["business_profile"], foreign["contact_intelligence"])
    commercial = {
        "shortlist": [{"organization_id": "one.ca", "rank_score": 10, "selection_reasons": [],
            "pages_checked": ["https://one.ca/"], "observed_opportunities": [{"field": "digital.online_arrangements"}],
            "page_evidence": [{"organization_id": "one.ca", "url": "https://one.ca/"}]}]
    }
    foreign_store = PilotStore(tmp_path / "foreign.json", tmp_path / "foreign-events.json")
    foreign_store.save_cohort(build_pilot_cohort([foreign], commercial))
    with pytest.raises(ValueError, match="same organization"):
        foreign_store.record_presend_review("one.ca", "DO_NOT_CONTACT", "operator")


def test_do_not_contact_and_insufficient_evidence_block_approval(tmp_path):
    for status in ("DO_NOT_CONTACT", "INSUFFICIENT_EVIDENCE"):
        store = PilotStore(tmp_path / f"{status}.json", tmp_path / f"{status}-events.json")
        store.save_cohort(_cohort())
        identifier = store.effective()[0]["pilot_id"]
        store.transition(identifier, "MANUAL_REVIEW", "operator")
        store.record_presend_review(identifier, status, "operator", note="Human disposition")
        with pytest.raises(ValueError, match="pre-send"):
            store.approve(identifier, "operator", [_record()[0]])
        assert store.state(identifier) == "MANUAL_REVIEW"


def test_presend_history_is_idempotent_auditable_and_stale_evidence_blocks(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    first, created = _complete_presend(store, identifier)
    repeated, repeated_created = _complete_presend(store, identifier)
    assert created is True and repeated_created is False and repeated == first
    conflicting, conflicting_created = store.record_presend_review(
        identifier, "INSUFFICIENT_EVIDENCE", "second-operator", note="Current publication could not be confirmed",
    )
    assert conflicting_created is True and conflicting["event_id"] != first["event_id"]
    assert [item["status"] for item in store.history(identifier) if item["event_type"] == "PRESEND_REVIEW"] == [
        "PUBLICATION_EVIDENCE_PRESENT", "INSUFFICIENT_EVIDENCE",
    ]

    # A later affirmative review still cannot approve if the current fact's
    # observation context has drifted from the reviewed publication record.
    _complete_presend(store, identifier, actor="third-operator")
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    record, _ = _record()
    selected_id = store._prospect(identifier)["selected_contact"]["evidence"]["evidence_id"]
    next(fact for fact in record["enrichment"]["facts"] if fact["id"] == selected_id)["observed_at"] = "2026-08-25T00:00:00Z"
    with pytest.raises(ValueError, match="stale"):
        store.approve(identifier, "operator", [record])
    assert store.state(identifier) == "MANUAL_REVIEW"


def test_prearrangements_form_prevents_false_online_arrangement_negative():
    record, page = _record()
    page["html"] = '<a href="/prearrangements-form">Pre-Arrangements Form</a>'
    page["markdown"] = "Pre-Arrangements Form"
    package = build_commercial([record], [page])
    fields = {item["field"] for item in package["shortlist"][0]["observed_opportunities"]}
    assert "digital.online_arrangements" not in fields


def test_human_form_observation_is_append_only_bound_and_does_not_change_state(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    event, created = store.annotate(identifier, "FORM_SOURCE_REVIEW", "human-operator",
        source_urls=["https://example.ca/preplan", "https://example.ca/form"],
        observations=["Detailed public form observed", "No defect established"],
        note="Interpretation remains review required")
    repeated, repeated_created = store.annotate(identifier, "FORM_SOURCE_REVIEW", "human-operator",
        source_urls=["https://example.ca/form", "https://example.ca/preplan"],
        observations=["No defect established", "Detailed public form observed"],
        note="Interpretation remains review required")
    assert created is True and repeated_created is False and repeated == event
    assert store.state(identifier) == "CANDIDATE"
    assert event["interpretation_status"] == "REVIEW_REQUIRED"
    assert not any(event["safety"].values())
    with pytest.raises(ValueError, match="same organization"):
        store.annotate(identifier, "FORM_SOURCE_REVIEW", "human-operator",
            source_urls=["https://sibling.example/form"], observations=["Foreign form"])


def test_external_send_reconciliation_records_contact_without_backfilled_gates(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]

    store.transition(identifier, "MANUAL_REVIEW", "operator")

    event, created = store.record_external_send(
        identifier,
        "operator",
        recipient="office@example.com",
        subject="A small detail",
        note="Actually sent outside guarded workflow.",
        activity_references=["manual-email:test-1"],
    )

    assert created is True
    assert event["event_type"] == "EXTERNAL_SEND_RECONCILIATION"
    assert event["from_state"] == "MANUAL_REVIEW"
    assert event["to_state"] == "CONTACTED"
    assert event["outreach_sent"] is True
    assert event["normal_presend_gates_completed_before_send"] is False
    assert event["reconciliation_reason"] == "OUTREACH_SENT_OUTSIDE_GUARDED_WORKFLOW"
    assert event["activity_references"] == ["manual-email:test-1"]
    assert store.state(identifier) == "CONTACTED"

    effective = store.effective()[0]
    assert effective["current_state"] == "CONTACTED"
    assert effective["draft_status"] == "BLOCKED_PENDING_MANUAL_REVIEW_AND_APPROVAL"
    assert effective["guarded_draft_preview"] == store._prospect(identifier)["guarded_draft_preview"]
    assert effective["guarded_draft_preview"]["status"] != "PREPARED_UNSENT"

    stats = store.stats()
    assert stats["current_states"] == {"CONTACTED": 1}
    assert stats["contacted"] == 1
    assert stats["approved"] == 0
    assert stats["drafted"] == 0
    assert stats["rates_percent"]["contact_to_reply"] == 0.0

    history = store.history(identifier)
    transitions = [
        value for value in history
        if value.get("event_type") == "STATE_TRANSITION"
    ]

    assert [value["to_state"] for value in transitions] == ["MANUAL_REVIEW"]
    assert not any(
        value.get("to_state") in {"APPROVED_FOR_CONTACT", "CONTACT_PREPARED"}
        for value in transitions
    )


def test_reconciled_external_send_supports_reply_metrics_and_contact_denominator(tmp_path):
    records_and_pages = [_record("external.ca"), _record("normal.ca")]
    records = [value[0] for value in records_and_pages]
    pages = [value[1] for value in records_and_pages]
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort(records, pages))
    identifiers = {
        item["organization_id"]: item["pilot_id"]
        for item in store.cohort()["prospects"]
    }

    external = identifiers["external.ca"]
    store.transition(external, "MANUAL_REVIEW", "operator")
    store.record_external_send(
        external,
        "operator",
        recipient="office@external.ca",
        subject="A small detail",
        activity_references=["manual-email:external-1"],
    )
    assert store.state(external) == "CONTACTED"
    store.transition(external, "REPLIED", "operator", reply_sentiment="POSITIVE")

    normal = identifiers["normal.ca"]
    normal_record = next(record for record in records if record["domain"] == "normal.ca")
    store.transition(normal, "MANUAL_REVIEW", "operator")
    _complete_presend(store, normal)
    store.approve(normal, "operator", [normal_record])
    store.prepare_draft(normal, "operator")
    store.transition(
        normal,
        "CONTACTED",
        "operator",
        activity_references=["manual-email:normal-1"],
    )

    stats = store.stats()
    assert stats["current_states"] == {"CONTACTED": 1, "REPLIED": 1}
    assert stats["contacted"] == 2
    assert stats["replies"] == stats["positive_replies"] == 1
    assert stats["rates_percent"]["contact_to_reply"] == 50.0
    assert stats["rates_percent"]["contact_to_positive_reply"] == 50.0
    assert stats["approved"] == stats["drafted"] == 1


def test_external_send_reconciliation_is_idempotent(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]

    store.transition(identifier, "MANUAL_REVIEW", "operator")

    kwargs = dict(
        recipient="office@example.com",
        subject="A small detail",
        note="Actually sent outside guarded workflow.",
        activity_references=["manual-email:test-1"],
    )

    first, created = store.record_external_send(identifier, "operator", **kwargs)
    assert created is True

    # Once reconciled, a second reconciliation must not create another
    # contacted event.
    try:
        store.record_external_send(identifier, "operator", **kwargs)
    except ValueError as exc:
        assert "already-contacted state" in str(exc)
    else:
        raise AssertionError("duplicate external-send reconciliation was accepted")

    assert store.state(identifier) == "CONTACTED"
    assert len([
        value for value in store.history(identifier)
        if value.get("event_type") == "EXTERNAL_SEND_RECONCILIATION"
    ]) == 1


@pytest.mark.parametrize("final_state", ["CONTACTED", "REPLIED", "MEETING"])
def test_next_unsent_excludes_contact_transition_and_later_states(tmp_path, final_state):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    _complete_presend(store, identifier)
    record, _ = _record()
    store.approve(identifier, "operator", [record])
    store.prepare_draft(identifier, "operator")
    store.transition(identifier, "CONTACTED", "operator")
    if final_state in {"REPLIED", "MEETING"}:
        store.transition(identifier, "REPLIED", "operator", reply_sentiment="POSITIVE")
    if final_state == "MEETING":
        store.transition(identifier, "MEETING", "operator")

    assert store.state(identifier) == final_state
    assert store.contact_history(identifier)["ever_contacted"] is True
    assert store.next_unsent(limit=5) == []


def test_next_unsent_ranks_only_never_contacted_candidate_and_manual_review(tmp_path):
    pairs = [_record("high.ca"), _record("review.ca"), _record("sent.ca")]
    cohort = _cohort([pair[0] for pair in pairs], [pair[1] for pair in pairs])
    scores = {"high.ca": 120, "review.ca": 110, "sent.ca": 200}
    for prospect in cohort["prospects"]:
        prospect["selection_score_internal"] = scores[prospect["organization_id"]]
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(cohort)
    store.transition("review.ca", "MANUAL_REVIEW", "operator")
    store.transition("sent.ca", "MANUAL_REVIEW", "operator")
    store.record_external_send(
        "sent.ca", "operator", recipient="office@sent.ca", subject="Subject",
        activity_references=["gmail:sent"],
    )

    result = store.next_unsent(limit=5)
    assert [item["organization_id"] for item in result] == ["high.ca", "review.ca"]
    assert [item["current_state"] for item in result] == ["CANDIDATE", "MANUAL_REVIEW"]
    assert result[0]["score"] == 120
    assert set(result[0]) >= {
        "organization_name", "pilot_id", "contact_channel", "contact_value",
        "selected_angle_status", "presend_status",
    }


def test_external_reconciliation_and_duplicate_attempt_never_restore_unsent_eligibility(tmp_path):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    identifier = store.effective()[0]["pilot_id"]
    store.transition(identifier, "MANUAL_REVIEW", "operator")
    kwargs = {
        "recipient": "office@example.ca", "subject": "Subject",
        "activity_references": ["gmail:gregory-style"],
    }
    store.record_external_send(identifier, "operator", **kwargs)
    with pytest.raises(ValueError, match="already-contacted"):
        store.record_external_send(identifier, "operator", **kwargs)
    assert store.next_unsent(limit=5) == []
    assert store.contact_history(identifier)["reasons"][0]["reason"] == "EXTERNAL_SEND_RECONCILIATION"
    record, page = _record()
    with pytest.raises(ValueError, match="prior external contact"):
        build_first_prospect_package(store, identifier, [record], [page])


@pytest.mark.parametrize("malformed", [
    {"event_id": "bad-contact-state", "event_type": "STATE_TRANSITION"},
    {
        "event_id": "unknown-contact-event", "event_type": "STATE_TRNSITION",
        "to_state": "CONTACTED", "outreach_sent": False,
    },
])
def test_malformed_contact_history_fails_closed_and_blocks_initial_preparation(tmp_path, malformed):
    store = PilotStore(tmp_path / "cohort.json", tmp_path / "events.json")
    store.save_cohort(_cohort())
    prospect = store.effective()[0]
    malformed_event = {
        **malformed,
        "pilot_id": prospect["pilot_id"], "organization_id": prospect["organization_id"],
    }
    store.events_path.write_text(json.dumps([malformed_event]), encoding="utf-8")

    assessment = store.contact_history(prospect["pilot_id"])
    assert assessment["ambiguous"] is True
    assert assessment["eligible_as_unsent"] is False
    assert store.next_unsent(limit=5) == []
    with pytest.raises(ValueError, match="ambiguous contact history"):
        store.prepare_draft(prospect["pilot_id"], "operator")


def test_next_unsent_cli_is_read_only(tmp_path, capsys):
    cohort_path = tmp_path / "cohort.json"
    events_path = tmp_path / "events.json"
    store = PilotStore(cohort_path, events_path)
    store.save_cohort(_cohort())
    events_path.write_text("[]\n", encoding="utf-8")
    before_cohort = cohort_path.read_bytes()
    before_events = events_path.read_bytes()

    pilot_main([
        "--cohort", str(cohort_path), "--events", str(events_path),
        "next-unsent", "--limit", "5",
    ])
    output = json.loads(capsys.readouterr().out)
    assert len(output) == 1
    assert cohort_path.read_bytes() == before_cohort
    assert events_path.read_bytes() == before_events
