from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

from automation.orchestrator import AgentOrchestrator
from pilot.workflow import PRESEND_CHECKS, PilotStore


PATHWAY_REVIEW_SENDER_NAME = "Alex De Carlo"
PATHWAY_REVIEW_SENDER_BUSINESS = "Digital Pathway"


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


def _fact_is_current(fact: Dict[str, Any]) -> bool:
    try:
        return datetime.fromisoformat(str(fact.get("stale_after")).replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


def _current_positive_facts(record: Dict[str, Any], field: str, organization_id: str) -> List[Dict[str, Any]]:
    return sorted((
        fact for fact in _facts(record, field)
        if fact.get("value") is True
        and _host(fact.get("source_url")) == organization_id
        and fact.get("verification_state") in {"EXTRACTED", "DIRECTLY_OBSERVED", "CORROBORATED"}
        and _fact_is_current(fact)
    ), key=lambda fact: str(fact.get("id") or ""))


def _current_website_facts(record: Dict[str, Any], organization_id: str) -> List[Dict[str, Any]]:
    return sorted((
        fact for fact in _facts(record, "organization.website")
        if _host(fact.get("value")) == organization_id
        and _host(fact.get("source_url")) == organization_id
        and fact.get("verification_state") in {"LOCALLY_VALIDATED", "DIRECTLY_OBSERVED", "CORROBORATED"}
        and _fact_is_current(fact)
    ), key=lambda fact: str(fact.get("id") or ""))


def _fact_refs(facts: Iterable[Dict[str, Any]], organization_id: str) -> List[Dict[str, Any]]:
    return [{
        "evidence_id": fact["id"], "organization_id": organization_id,
        "source_url": fact.get("source_url"), "detector": fact.get("detector"),
        "detector_version": fact.get("detector_version"), "confidence": fact.get("confidence"),
        "verification_state": fact.get("verification_state"), "observed_at": fact.get("observed_at"),
        "semantic_value": fact.get("value"), "evidence": fact.get("evidence"),
    } for fact in facts]


def _owner_salutation(record: Dict[str, Any], organization_id: str, fallback: str) -> str:
    names = []
    for fact in _facts(record, "contact.person"):
        value = fact.get("value") or {}
        name = str(value.get("name") or "").strip()
        title = str(value.get("title") or "").strip()
        if title.casefold() != "owner" or _host(fact.get("source_url")) != organization_id or not name:
            continue
        first_name = name.split()[0]
        if first_name not in names:
            names.append(first_name)
    return " and ".join(names) if names else f"{fallback} team"


def build_first_prospect_package(store: PilotStore, identifier: str,
                                 records: Iterable[Dict[str, Any]], pages: Iterable[Dict[str, Any]],
                                 research: Iterable[Dict[str, Any]] = (), forms: Dict[str, Any] | None = None) -> Dict[str, Any]:
    prospect = store._prospect(identifier)
    contact_history = store.contact_history(prospect["pilot_id"])
    if not contact_history["eligible_as_unsent"]:
        reason = "prior external contact" if contact_history["ever_contacted"] else "ambiguous contact history"
        raise ValueError(f"Fresh initial outreach package blocked by {reason}")
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

    preplanning = _current_positive_facts(record, "services.preplanning", organization_id)
    online_arrangements = _current_positive_facts(record, "digital.online_arrangements", organization_id)
    obituaries = _facts(record, "services.obituaries")
    cremation = _facts(record, "services.cremation")
    websites = _current_website_facts(record, organization_id)
    contacts = _facts(record, "contact.public_email")
    pathway_page = next((page for page in owned_pages if re.search(
        r"\b(?:online\s+arrangements?|pre[ -]?arrangements?)(?:\s+form)?\b",
        str(page.get("text") or page.get("markdown") or ""), re.I,
    )), None)
    if not all((websites, preplanning, contacts)):
        raise ValueError("Current evidence does not support a pre-planning pathway package")
    stronger_pathway = bool(online_arrangements)
    form_ref = {
        "evidence_id": _page_id(organization_id, pathway_page["url"]),
        "organization_id": organization_id, "source_url": pathway_page["url"],
        "page_title": (pathway_page.get("metadata") or {}).get("title"),
        "detector": "first_prospect_page_review", "detector_version": "1.0.0",
        "confidence": 0.95, "verification_state": "DIRECTLY_OBSERVED",
        "observed_at": preplanning[0].get("observed_at"),
        "semantic_value": "A first-party online-arrangements pathway was retained in the bounded scan.",
        "limitation": "The pathway was not submitted and its completion experience was not tested.",
    } if pathway_page else None
    evidence = [
        *_fact_refs(websites, organization_id), *_fact_refs(preplanning, organization_id),
        *_fact_refs(online_arrangements, organization_id),
        *_fact_refs(obituaries, organization_id), *_fact_refs(cremation, organization_id),
        *_fact_refs(contacts, organization_id), *([form_ref] if form_ref else []),
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
    organization_forms = [item for item in (forms or {}).get("forms", []) if item.get("organization_id") == organization_id]
    detailed_form = next((item for item in organization_forms if item.get("form_type") == "DETAILED_INTAKE_FORM"), None)
    human_observations = [item for item in store.history(identifier) if item.get("event_type") == "HUMAN_OBSERVATION"]

    support_ids = [preplanning[0]["id"]]
    if stronger_pathway:
        support_ids.append(online_arrangements[0]["id"])
    organization_name = str((record.get("business_profile") or {}).get("company") or organization_id)
    short_name = re.sub(
        r"\s+(?:Funeral Home(?: Inc\.)?|Funeral Service(?: Ltd\.)?|Memorial Chapel)\.?$",
        "", organization_name, flags=re.I,
    )
    possessive_name = short_name if short_name.casefold().endswith("'s") else f"{short_name}'s"
    salutation = _owner_salutation(record, organization_id, short_name)
    # Match the established manually reviewed pilot-message convention. The
    # repository intentionally does not persist a mailing address or sender
    # phone/email; those remain mandatory human presend checks rather than
    # values the generation layer can invent.
    sender_signature = f"{PATHWAY_REVIEW_SENDER_NAME}\n{PATHWAY_REVIEW_SENDER_BUSINESS}"
    angle_type = "PREARRANGEMENT_PATHWAY_REVIEW" if stronger_pathway else "PREPLANNING_INFORMATION_PATHWAY_REVIEW"
    angle_slug = "prearrangement-pathway-review" if stronger_pathway else "preplanning-information-pathway-review"
    pathway_label = "pre-arrangement" if stronger_pathway else "pre-planning"
    observed_services = (
        "both pre-planning information and an online-arrangements pathway"
        if stronger_pathway else "pre-planning information"
    )
    customer_safe_observation = (
        f"{possessive_name} public website provides pre-planning information and an online-arrangements pathway."
        if stronger_pathway else f"{possessive_name} public website provides pre-planning information."
    )
    proposed_improvement = (
        "Perform a non-submitting desktop/mobile review of the existing pathway and scope only evidence-supported navigation, call-to-action, content, or completion-clarity improvements."
        if stronger_pathway else "Review the existing pre-planning information pathway on desktop and mobile and scope only evidence-supported navigation, call-to-action, content, or completion-clarity improvements."
    )
    drafts = [
        {
            "variant": "DIRECT_BUSINESSLIKE", "recommended": True,
            "subject": f"A small review of {possessive_name} {pathway_label} pathway",
            "body": (
                f"Hello {salutation},\n\n"
                f"I was reviewing {possessive_name} public website and noticed that you already provide {observed_services}.\n\n"
                "I put together a short review of that existing pathway, focusing on a few practical things that can be "
                "checked on desktop and mobile without submitting anything or changing the current process.\n\n"
                "Would it be useful if I sent the one-page summary?\n\n"
                f"{sender_signature}\n\n"
                "If you would rather not receive messages from me, reply ‘unsubscribe’ and I will stop."
            ),
            "supporting_evidence_ids": support_ids, "sendable": False, "outreach_sent": False,
        },
        {
            "variant": "CONSULTATIVE_HELPFUL", "recommended": False,
            "subject": f"A practical website observation for {short_name}",
            "body": (
                f"Hello {organization_name} team,\n\n"
                f"While reviewing your public site, I saw the {observed_services} you make available to families. "
                "I prepared a concise outside review of that pathway—what is already working and a few practical points worth checking. "
                "I would be glad to share it if that would be useful.\n\n"
                f"{sender_signature}\n"
                "Reply unsubscribe if you do not want further messages."
            ),
            "supporting_evidence_ids": support_ids, "sendable": False, "outreach_sent": False,
        },
        {
            "variant": "VERY_SHORT", "recommended": False,
            "subject": f"{short_name} website review",
            "body": (
                f"Hello {organization_name} team— I reviewed the public {pathway_label} pathway on your website and made a short list of practical observations. "
                f"May I send it over?\n\n{sender_signature}\n"
                "Reply unsubscribe to opt out."
            ),
            "supporting_evidence_ids": support_ids, "sendable": False, "outreach_sent": False,
        },
    ]
    checklist = {name: False for name in sorted(PRESEND_CHECKS)}
    angle_id = f"{organization_id}-{angle_slug}-v1"
    supersedes_angle_id = None
    current_angle = store.selected_angle(identifier)
    if current_angle and all((
        current_angle.get("angle_type") == angle_type,
        current_angle.get("customer_safe_observation") == customer_safe_observation,
        current_angle.get("proposed_improvement") == proposed_improvement,
        sorted(current_angle.get("evidence_ids") or []) == sorted(support_ids),
    )):
        if current_angle.get("angle_id") == angle_id:
            angle_id = f"{organization_id}-{angle_slug}-v2"
            supersedes_angle_id = current_angle["angle_id"]
        else:
            angle_id = current_angle["angle_id"]
            supersedes_angle_id = current_angle.get("supersedes_angle_id")
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
        "human_observations": human_observations,
        "form_intelligence": {
            "forms": organization_forms,
            "detailed_intake_form": detailed_form,
            "interpretation_status": "REVIEW_REQUIRED",
            "automatic_defect_created": False,
        },
        "customer_safe_mini_audit": {
            "title": f"{organization_name} — Digital Presence Snapshot",
            "what_we_reviewed": page_urls,
            "positive_observations": ([
                {"classification": "OBSERVED", "statement": "We observed public information about pre-planning.", "evidence_ids": [preplanning[0]["id"]]},
                {"classification": "OBSERVED", "statement": "We observed an online-arrangements pathway on the retained first-party website.", "evidence_ids": [online_arrangements[0]["id"]]},
            ] if stronger_pathway else [
                {"classification": "OBSERVED", "statement": "We observed public information about pre-planning on the retained first-party website.", "evidence_ids": [preplanning[0]["id"]]},
            ]),
            "primary_opportunity": {
                "classification": "INTERPRETATION",
                "statement": ("Because an online pre-arrangements entry point is already present, a focused human review could assess whether that pathway is clear, reassuring, and easy to complete across common devices." if stronger_pathway else "A focused human review could assess the existing pre-planning information pathway across desktop and mobile without asserting that a defect exists."),
                "evidence_ids": support_ids,
                "limitation": "No usability defect is asserted until a human tests the linked pathway.",
            },
            "recommended_action": {
                "classification": "RECOMMENDED_ACTION",
                "statement": proposed_improvement,
                "evidence_ids": support_ids,
            },
            "unsafe_or_internal": [
                ("Do not say online arrangements are absent; a pre-arrangements form link was observed." if stronger_pathway else "Do not characterize bounded-scan non-detection as proof that online arrangements are absent."),
                "Do not expose scores, revenue estimates, lost-family claims, ranking claims, mailbox activity, or inferred consent.",
            ],
        },
        "internal_evidence_appendix": evidence_by_id,
        "commercial_angle": {
            "primary": ("Human review of the existing online pre-arrangement pathway." if stronger_pathway else "Human review of the existing pre-planning information pathway."),
            "bounded_wording": ("We observed pre-planning information and an online-arrangements pathway. A non-submitting human review may be worthwhile to assess navigation, call-to-action, content, and completion clarity across desktop and mobile. No form, usability, accessibility, privacy, legal, security, or conversion defect has been established." if stronger_pathway else "We observed pre-planning information. A desktop/mobile review may be worthwhile to assess the existing information pathway and scope only evidence-supported improvements. No usability, accessibility, privacy, legal, security, or conversion defect has been established."),
            "human_validation_before_use": ["Complete a non-submitting desktop/mobile walkthrough.", "Scope only observations supported by the current rendered experience.", "Confirm the link, labels, and organization identity remain unchanged."],
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
        "selected_angles": [{
            "angle_id": angle_id,
            "supersedes_angle_id": supersedes_angle_id,
            "organization_id": organization_id,
            "angle_type": angle_type,
            "evidence_ids": support_ids,
            "customer_safe_observation": customer_safe_observation,
            "proposed_improvement": proposed_improvement,
            "safety_classification": "CUSTOMER_SAFE_WITH_WORDING",
            "source_identity": {"generator": "first_prospect_package", "pilot_cohort": "FIRST_REVENUE_PILOT_2026_08"},
            "draft_preview": {
                "subject": drafts[0]["subject"], "body": drafts[0]["body"],
                "sendable": False, "outreach_sent": False,
            },
        }],
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
