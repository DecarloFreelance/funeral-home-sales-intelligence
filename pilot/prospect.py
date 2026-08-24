from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

from automation.orchestrator import AgentOrchestrator
from pilot.workflow import PRESEND_CHECKS, PilotStore


def _host(value: Any) -> str:
    parsed = urlsplit(str(value or ""))
    return (parsed.hostname or "").lower().removeprefix("www.")


def _page_id(organization_id: str, url: str) -> str:
    return hashlib.sha256(f"{organization_id}\0{url}".encode()).hexdigest()[:24]


def _owned_pages(pages: Iterable[Dict[str, Any]], organization_id: str) -> List[Dict[str, Any]]:
    return sorted(
        (page for page in pages if _host(page.get("url")) == organization_id),
        key=lambda page: str(page.get("url") or ""),
    )


def _facts(record: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    return [fact for fact in (record.get("enrichment") or {}).get("facts") or [] if fact.get("field") == field]


def _fact_refs(facts: Iterable[Dict[str, Any]], organization_id: str) -> List[Dict[str, Any]]:
    return [{
        "evidence_id": fact["id"], "organization_id": organization_id,
        "source_url": fact.get("source_url"), "detector": fact.get("detector"),
        "detector_version": fact.get("detector_version"), "confidence": fact.get("confidence"),
        "verification_state": fact.get("verification_state"), "observed_at": fact.get("observed_at"),
        "semantic_value": fact.get("value"), "evidence": fact.get("evidence"),
    } for fact in facts]


def build_first_prospect_package(store: PilotStore, identifier: str,
                                 records: Iterable[Dict[str, Any]], pages: Iterable[Dict[str, Any]],
                                 research: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    prospect = store._prospect(identifier)
    organization_id = prospect["organization_id"]
    record = next((item for item in records if item.get("domain") == organization_id), None)
    if not record:
        raise ValueError("Current organization record is unavailable")
    owned_pages = _owned_pages(pages, organization_id)
    if not owned_pages:
        raise ValueError("No organization-owned page evidence is available")
    page_urls = [str(page.get("url") or "") for page in owned_pages]
    if any(_host(url) != organization_id for url in page_urls):
        raise ValueError("Cross-organization page evidence is not permitted")

    preplanning = _facts(record, "services.preplanning")
    obituaries = _facts(record, "services.obituaries")
    cremation = _facts(record, "services.cremation")
    websites = _facts(record, "organization.website")
    contacts = _facts(record, "contact.public_email")
    form_page = next((page for page in owned_pages if re.search(r"\bpre[ -]?arrangements?\s+form\b", str(page.get("text") or page.get("markdown") or ""), re.I)), None)
    if not all((websites, preplanning, obituaries, cremation, contacts, form_page)):
        raise ValueError("Current evidence does not support the Foothills first-prospect package")
    form_ref = {
        "evidence_id": _page_id(organization_id, form_page["url"]),
        "organization_id": organization_id, "source_url": form_page["url"],
        "page_title": (form_page.get("metadata") or {}).get("title"),
        "detector": "first_prospect_page_review", "detector_version": "1.0.0",
        "confidence": 0.95, "verification_state": "DIRECTLY_OBSERVED",
        "observed_at": preplanning[0].get("observed_at"),
        "semantic_value": "A first-party navigation link labelled Pre-Arrangements Form was retained in the bounded scan.",
        "limitation": "The linked form was not submitted and its completion experience was not tested.",
    }
    evidence = [
        *_fact_refs(websites, organization_id), *_fact_refs(preplanning, organization_id),
        *_fact_refs(obituaries, organization_id), *_fact_refs(cremation, organization_id),
        *_fact_refs(contacts, organization_id), form_ref,
    ]
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    selected = prospect["selected_contact"]
    selected_ref = evidence_by_id.get((selected.get("evidence") or {}).get("evidence_id"))
    if (not selected_ref or _host(selected_ref.get("source_url")) != organization_id
            or (selected.get("evidence") or {}).get("source_url") != selected_ref.get("source_url")):
        raise ValueError("Selected contact is not supported by organization-owned publication evidence")

    related = []
    for item in research:
        if item.get("domain") == organization_id:
            continue
        attempts = item.get("attempts") or []
        if any(_host(attempt.get("final_url")) == organization_id for attempt in attempts):
            related.append({
                "organization_id": item.get("domain"), "organization_name": item.get("company"),
                "relationship": "UNRESOLVED_REDIRECT_TO_CURRENT_WEBSITE",
                "reason": "A separate discovery record redirects to this website; no parent/branch reassignment is inferred.",
            })

    support_ids = [preplanning[0]["id"], form_ref["evidence_id"]]
    organization_name = "Foothills Memorial Chapel"
    drafts = [
        {
            "variant": "DIRECT_BUSINESSLIKE", "recommended": True,
            "subject": "A short review of your pre-arrangement pathway",
            "body": (
                "Hello Foothills Memorial Chapel team,\n\n"
                "I reviewed your public website and noticed that it provides pre-planning information and a linked pre-arrangements form. "
                "I put together a short, cited review of that visitor pathway with a few practical checks for clarity and completion. "
                "Would it be useful if I sent the findings over?\n\n"
                "Best,\n[FULL NAME]\n[BUSINESS NAME]\n[MAILING ADDRESS]\n[PHONE / EMAIL]\n\n"
                "If you would prefer not to receive messages from me, reply unsubscribe."
            ),
            "supporting_evidence_ids": support_ids, "sendable": False, "outreach_sent": False,
        },
        {
            "variant": "CONSULTATIVE_HELPFUL", "recommended": False,
            "subject": "A practical website observation for Foothills",
            "body": (
                "Hello Foothills Memorial Chapel team,\n\n"
                "While reviewing your public site, I saw the pre-planning resources and pre-arrangements form you make available to families. "
                "I prepared a concise outside review of that pathway—what is already working and a few practical points worth checking. "
                "I would be glad to share it if that would be useful.\n\n"
                "Best,\n[FULL NAME] | [BUSINESS NAME]\n[MAILING ADDRESS] | [PHONE / EMAIL]\n"
                "Reply unsubscribe if you do not want further messages."
            ),
            "supporting_evidence_ids": support_ids, "sendable": False, "outreach_sent": False,
        },
        {
            "variant": "VERY_SHORT", "recommended": False,
            "subject": "Foothills website review",
            "body": (
                "Hello Foothills Memorial Chapel team— I reviewed the public pre-planning and pre-arrangements pathway on your website and made a short list of practical observations. "
                "May I send it over?\n\n[FULL NAME], [BUSINESS NAME], [MAILING ADDRESS], [PHONE / EMAIL]\n"
                "Reply unsubscribe to opt out."
            ),
            "supporting_evidence_ids": support_ids, "sendable": False, "outreach_sent": False,
        },
    ]
    checklist = {name: False for name in sorted(PRESEND_CHECKS)}
    result = {
        "schema_version": 1, "generator": "first_prospect_package", "generator_version": "1.0.0",
        "pilot_id": prospect["pilot_id"], "audit_id": prospect["selected_audit_id"],
        "organization": {
            "organization_id": organization_id, "canonical_name": (record.get("business_profile") or {}).get("company"),
            "customer_name": organization_name, "website": websites[0].get("value"),
            "city": (record.get("business_profile") or {}).get("city"),
            "province": (record.get("business_profile") or {}).get("province"),
            "crm_safe": bool((record.get("quality_control") or {}).get("crm_sync_safe")),
            "outreach_ready": bool((record.get("quality_control") or {}).get("outreach_ready")),
            "related_records": related,
        },
        "selected_contact": {
            **selected, "publication_association": "FIRST_PARTY_ORGANIZATION_PAGE",
            "consent_or_approval_inference": "NONE",
        },
        "presend_review": {**store.presend_review(identifier), "operator_checklist": checklist},
        "customer_safe_mini_audit": {
            "title": "Foothills Memorial Chapel — Digital Presence Snapshot",
            "what_we_reviewed": page_urls,
            "positive_observations": [
                {"classification": "OBSERVED", "statement": "We observed public information about pre-planning, obituaries, and cremation services.", "evidence_ids": [preplanning[0]["id"], obituaries[0]["id"], cremation[0]["id"]]},
                {"classification": "OBSERVED", "statement": "We observed a clearly linked pre-arrangements form in the retained first-party website navigation.", "evidence_ids": [form_ref["evidence_id"]]},
            ],
            "primary_opportunity": {
                "classification": "INTERPRETATION",
                "statement": "Because an online pre-arrangements entry point is already present, a focused human review could assess whether that pathway is clear, reassuring, and easy to complete across common devices.",
                "evidence_ids": support_ids,
                "limitation": "No usability defect is asserted until a human tests the linked pathway.",
            },
            "recommended_action": {
                "classification": "RECOMMENDED_ACTION",
                "statement": "Review the existing pre-arrangement pathway, then scope only evidence-supported navigation, call-to-action, form, or content changes.",
                "evidence_ids": support_ids,
            },
            "unsafe_or_internal": [
                "Do not say online arrangements are absent; a pre-arrangements form link was observed.",
                "Do not expose scores, revenue estimates, lost-family claims, ranking claims, mailbox activity, or inferred consent.",
            ],
        },
        "internal_evidence_appendix": evidence_by_id,
        "commercial_angle": {
            "primary": "Human review and improvement of the existing pre-arrangement visitor pathway.",
            "bounded_wording": "We observed pre-planning information and a linked pre-arrangements form; we have not yet tested the form or concluded that the pathway has a defect.",
            "human_validation_before_use": ["Open and complete a non-submitting walkthrough of the current form on desktop and mobile.", "Confirm the link, labels, and current organization identity remain unchanged."],
        },
        "offer": {
            "entry": "Free mini audit / findings conversation.",
            "primary_variant": "AUDIT_PLUS_FIX", "pilot_range_cad": [750, 1500],
            "smallest_viable_scope": ["Human pathway review", "prioritized findings", "one defined navigation or call-to-action improvement after access and approval"],
            "expanded_scope": ["Mobile/desktop path review", "form and content clarity recommendations", "implementation of a defined set of approved website changes", "post-change verification"],
            "dependencies": ["Website/CMS access or cooperation from the current site provider", "Approval of copy and form changes", "A confirmed test process that does not create live arrangements"],
            "risks": ["The hosted funeral-home platform may limit template/form changes", "The existing form may already meet business needs", "Scope must be confirmed after human testing"],
            "exclude": ["Guaranteed revenue or conversion outcomes", "Unverified SEO/accessibility/compliance remediation", "Full redesign without separate discovery", "Changes to live forms without authorization and testing"],
            "secondary_variant": "MANAGED", "managed_range_cad_monthly": [750, 1250],
            "managed_scope_after_project_only": ["Periodic site monitoring", "Evidence-backed digital-presence reviews", "Approved content/technical maintenance", "Monthly prioritized recommendations"],
        },
        "drafts": drafts,
        "response_paths": {
            "sure_send_it": "Thanks—I’ll send the one-page snapshot with the cited observations. If any point is useful, would a 15-minute call be worthwhile to discuss the existing pre-arrangement pathway?",
            "what_do_you_charge": "The initial snapshot is free. If the review identifies changes you want implemented, the pilot Fix Sprint is typically CAD $750–$1,500, with a final quote only after we agree on scope and access.",
            "already_have_someone": "Understood. I’m happy to send the short review as a second opinion for your existing provider—no pressure and no assumption that a change is needed.",
            "not_interested": "Thanks for letting me know. I won’t follow up further.",
        },
        "discovery_questions": [
            "Who currently manages the website and approves changes?",
            "What do you want a family to do after reading the pre-planning pages?",
            "How is the pre-arrangements form used by your team today?",
            "Where, if anywhere, do families encounter confusion or abandon the online process?",
            "Are mobile inquiries handled differently from desktop inquiries?",
            "Which website changes are currently easiest or hardest to make?",
            "Is improving online inquiry or pre-arrangement flow a current priority?",
            "If a small improvement were worthwhile, who would own budget and approval?",
        ],
        "safety": {"operator_approval_recorded": False, "contacted_recorded": False, "outreach_sent": False, "crm_write_performed": False},
    }
    stable = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    result["package_id"] = hashlib.sha256(stable.encode()).hexdigest()[:24]
    return result


def write_package(path: Path, package: Dict[str, Any]) -> bool:
    path = Path(path)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if existing == package:
        return False
    AgentOrchestrator._atomic_json(path, package)
    return True
