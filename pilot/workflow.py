from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

from automation.orchestrator import AgentOrchestrator
from enrichment.quality import approved_for_commercial_use


VERSION = "1.0.0"
COHORT = "FIRST_REVENUE_PILOT_2026_08"
OFFER = {
    "name": "Funeral Home Digital Presence & Growth Audit",
    "purpose": [
        "Identify evidence-backed digital presence observations.",
        "Highlight cautiously worded improvement opportunities.",
        "Create a reason for a human business conversation.",
        "Optionally lead to separately agreed implementation work.",
    ],
    "variants": {
        "AUDIT": "Paid stand-alone digital presence and growth audit.",
        "AUDIT_PLUS_FIX": "Audit credited toward a one-time implementation project.",
        "MANAGED": "Audit followed by an ongoing managed improvement service.",
    },
    "pricing_policy": "Amounts are manually configured and never inferred from intelligence scores.",
    "content_classes": {
        "OBSERVED": "Direct positive evidence from a cited public source.",
        "NOT_DETECTED_IN_SCAN": "Not observed in the bounded crawl; never an absolute absence claim.",
        "INTERPRETATION": "A cautious opportunity interpretation supported by cited scan evidence.",
        "RECOMMENDED_ACTION": "A practical recommendation without guaranteed impact.",
        "INTERNAL_ONLY": "Ranking, uncertainty, and workflow metadata excluded from customer output.",
    },
}
STATES = {
    "CANDIDATE", "MANUAL_REVIEW", "APPROVED_FOR_CONTACT", "CONTACT_PREPARED",
    "CONTACTED", "REPLIED", "MEETING", "PROPOSAL", "WON", "LOST",
    "DEFERRED", "DISQUALIFIED",
}
TRANSITIONS = {
    "CANDIDATE": {"MANUAL_REVIEW", "DEFERRED", "DISQUALIFIED"},
    "MANUAL_REVIEW": {"APPROVED_FOR_CONTACT", "DEFERRED", "DISQUALIFIED"},
    "APPROVED_FOR_CONTACT": {"CONTACT_PREPARED", "DEFERRED", "DISQUALIFIED"},
    "CONTACT_PREPARED": {"CONTACTED", "DEFERRED", "DISQUALIFIED"},
    "CONTACTED": {"REPLIED", "LOST", "DEFERRED", "DISQUALIFIED"},
    "REPLIED": {"MEETING", "LOST", "DEFERRED", "DISQUALIFIED"},
    "MEETING": {"PROPOSAL", "LOST", "DEFERRED", "DISQUALIFIED"},
    "PROPOSAL": {"WON", "LOST", "DEFERRED", "DISQUALIFIED"},
    "DEFERRED": {"MANUAL_REVIEW", "DISQUALIFIED"},
    "WON": set(), "LOST": set(), "DISQUALIFIED": set(),
}
POSITIVE_FIELDS = {
    "organization.social_profile": ("public_social_link", "Our scan observed a public social profile linked from the website."),
    "business.careers_page": ("careers_page", "Our scan observed a publicly linked careers page."),
    "digital.online_arrangements": ("online_arrangements", "Our scan observed language indicating an online arrangement capability."),
    "digital.livestream": ("livestream", "Our scan observed language indicating livestream or webcast capability."),
    "services.preplanning": ("preplanning", "Our scan observed public information about pre-planning services."),
    "services.obituaries": ("obituaries", "Our scan observed public obituary information."),
    "services.cremation": ("cremation", "Our scan observed public information about cremation services."),
    "services.burial": ("burial", "Our scan observed public information about burial services."),
}
NEGATIVE_ACTIONS = {
    "digital.online_arrangements": "Review whether a clearly linked online-arrangement path would help visitors begin the process.",
    "digital.livestream": "Review whether livestream or webcast information should be easier to find for remote attendees.",
    "business.careers_page": "Review whether a clearly linked careers page would support future recruiting.",
    "organization.social_profile": "Review whether linking official social profiles would make the public presence easier to verify.",
}


def _stable(*values: Any, length=24) -> str:
    material = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _host(value: Any) -> str:
    return (urlsplit(str(value or "")).hostname or "").lower().removeprefix("www.")


def _facts(record: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    return [fact for fact in (record.get("enrichment") or {}).get("facts") or [] if fact.get("field") == field]


def _evidence(fact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "evidence_id": fact["id"],
        "source_url": fact.get("source_url", ""),
        "observed_at": fact.get("observed_at"),
        "verification_state": fact.get("verification_state"),
        "confidence": fact.get("confidence"),
    }


def _best_contact(record: Dict[str, Any]) -> Dict[str, Any] | None:
    domain = str(record.get("domain") or "")
    emails = _facts(record, "contact.public_email")
    phones = _facts(record, "contact.public_phone")
    people = _facts(record, "contact.person")
    if emails:
        ranked = sorted(emails, key=lambda fact: (
            _host(fact.get("source_url")) == domain,
            fact.get("verification_state") == "DNS_VALID",
            fact.get("confidence", 0),
            str(fact.get("value")),
        ), reverse=True)
        fact = ranked[0]
        return {
            "contact_id": _stable(domain, "email", fact["id"]),
            "channel": "EMAIL", "value": fact.get("value"),
            "qualification": "Publicly listed business email; local/DNS validation does not prove mailbox activity.",
            "evidence": _evidence(fact),
            "named_contact_candidates": [value.get("value") for value in people],
        }
    if phones:
        fact = sorted(phones, key=lambda value: (value.get("confidence", 0), str(value.get("value"))), reverse=True)[0]
        return {
            "contact_id": _stable(domain, "phone", fact["id"]),
            "channel": "PHONE", "value": fact.get("value"),
            "qualification": "Publicly listed business phone; metadata validation does not prove reachability.",
            "evidence": _evidence(fact),
            "named_contact_candidates": [value.get("value") for value in people],
        }
    return None


def _customer_audit(record: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    domain = str(record.get("domain") or "")
    website_facts = _facts(record, "organization.website")
    if not website_facts:
        raise ValueError(f"Pilot record lacks verified website evidence: {domain}")
    pages = sorted(set(candidate.get("pages_checked") or []))
    ownership = candidate.get("page_evidence") or []
    owned_urls = sorted({item.get("url") for item in ownership if item.get("organization_id") == domain and item.get("url")})
    if not pages or owned_urls != pages:
        raise ValueError(f"Pilot page evidence does not belong to organization: {domain}")
    scan_scope_id = _stable(domain, "bounded-scan", pages)
    observations = [{
        "observation_type": "OBSERVED",
        "category": "verified_website",
        "statement": "Our scan successfully accessed the public website shown below.",
        "evidence_ids": [website_facts[0]["id"]],
        "source_urls": [website_facts[0].get("source_url")],
        "confidence": website_facts[0].get("verification_state"),
    }]
    evidence = {website_facts[0]["id"]: _evidence(website_facts[0])}
    for field, (category, statement) in POSITIVE_FIELDS.items():
        facts = _facts(record, field)
        if not facts:
            continue
        observations.append({
            "observation_type": "OBSERVED", "category": category,
            "statement": statement,
            "evidence_ids": [fact["id"] for fact in facts],
            "source_urls": sorted({fact.get("source_url") for fact in facts if fact.get("source_url")}),
            "confidence": max((fact.get("confidence", 0) for fact in facts), default=0),
        })
        evidence.update({fact["id"]: _evidence(fact) for fact in facts})
    technologies = _facts(record, "technology.platform")
    technology_groups: Dict[str, List[Dict[str, Any]]] = {}
    for fact in technologies:
        technology_groups.setdefault(str(fact.get("value")), []).append(fact)
    for technology, facts in sorted(technology_groups.items()):
        observations.append({
            "observation_type": "OBSERVED", "category": "technology_indicator",
            "statement": f"Our scan detected public-page indicators consistent with {technology}.",
            "evidence_ids": [fact["id"] for fact in facts],
            "source_urls": sorted({fact.get("source_url") for fact in facts if fact.get("source_url")}),
            "confidence": max((fact.get("confidence", 0) for fact in facts), default=0),
        })
        evidence.update({fact["id"]: _evidence(fact) for fact in facts})
    opportunities = []
    actions = []
    for item in candidate.get("observed_opportunities") or []:
        field = item.get("field")
        if field not in NEGATIVE_ACTIONS:
            continue
        label = field.rsplit(".", 1)[-1].replace("_", " ")
        observations.append({
            "observation_type": "NOT_DETECTED_IN_SCAN", "category": field,
            "statement": f"During our bounded website scan, we did not detect clearly linked {label} information.",
            "evidence_ids": [scan_scope_id], "source_urls": pages,
            "confidence": "LIMITED_BY_SCAN_SCOPE",
        })
        opportunities.append({
            "observation_type": "INTERPRETATION", "category": field,
            "statement": f"This may represent an opportunity to make {label} information easier for visitors to find.",
            "evidence_ids": [scan_scope_id],
        })
        actions.append({
            "observation_type": "RECOMMENDED_ACTION", "category": field,
            "statement": NEGATIVE_ACTIONS[field], "evidence_ids": [scan_scope_id],
        })
    evidence[scan_scope_id] = {
        "evidence_id": scan_scope_id, "source_urls": pages,
        "qualification": "Bounded scan scope; non-detection is not proof of absence.",
    }
    profile = record.get("business_profile") or {}
    locations = [value for value in profile.get("locations") or [] if isinstance(value, dict)]
    location = locations[0] if locations else {}
    contact = _best_contact(record)
    if contact:
        evidence[contact["evidence"]["evidence_id"]] = contact["evidence"]
    customer_view = {
        "offer": OFFER["name"],
        "organization": {
            "name": profile.get("company") or domain,
            "website": website_facts[0].get("value"),
            "city": location.get("city") or profile.get("city") or "",
            "province": location.get("province") or profile.get("province") or "",
        },
        "contact": contact,
        "observations": observations,
        "opportunities": opportunities,
        "recommended_actions": actions,
        "limitations": [
            "Observations reflect the cited public pages at the recorded scan time.",
            "A bounded-scan non-detection is not a claim that a capability is absent.",
            "No revenue, ranking, compliance, mailbox-activity, reachability, or causal-impact claim is made.",
        ],
    }
    audit_id = _stable("pilot-audit", VERSION, domain, customer_view, evidence)
    return {
        "audit_id": audit_id, "audit_version": VERSION,
        "customer_safe_audit": customer_view,
        "evidence_appendix": evidence,
        "internal_metadata": {
            "rank_score": candidate.get("rank_score"),
            "selection_reasons": candidate.get("selection_reasons") or [],
            "uncertainty": ["Ownership/independence is not asserted unless directly evidenced."],
            "blocking_flags": [],
            "customer_visible": False,
        },
    }


def _draft_preview(name: str, audit: Dict[str, Any], contact_id: str) -> Dict[str, Any]:
    opportunity = next(iter(audit["customer_safe_audit"].get("opportunities") or []), None)
    if not opportunity:
        raise ValueError("No customer-safe opportunity supports a pilot draft preview")
    return {
        "status": "PREVIEW_ONLY_PENDING_MANUAL_REVIEW_AND_APPROVAL",
        "sendable": False,
        "recommended_contact_id": contact_id,
        "subject": f"A short digital presence audit for {name}",
        "body": (
            f"Hello {name} team,\n\n"
            "I reviewed your public website and prepared a short digital presence audit. "
            f"{opportunity['statement']} "
            "If useful, I would be happy to share the cited observations and practical recommendations for your review.\n\n"
            "Would you be open to taking a look?\n\nBest,\nAlex"
        ),
        "supporting_evidence_ids": opportunity["evidence_ids"],
        "audit_id": audit["audit_id"],
        "outreach_sent": False,
    }


def build_pilot_cohort(records: Iterable[Dict[str, Any]], commercial_package: Dict[str, Any], *, limit=10) -> Dict[str, Any]:
    records_by_domain = {str(record.get("domain") or ""): record for record in records}
    eligible = []
    for candidate in commercial_package.get("shortlist") or []:
        domain = str(candidate.get("organization_id") or "")
        record = records_by_domain.get(domain)
        if not record or not approved_for_commercial_use(record, outreach=True):
            continue
        contact = _best_contact(record)
        if not contact:
            continue
        parent_evidence = _facts(record, "organization.parent_organization")
        email_penalty = 0 if contact["channel"] == "EMAIL" else 15
        parent_penalty = 20 if parent_evidence else 0
        selection_score = int(candidate.get("rank_score") or 0) - email_penalty - parent_penalty
        audit = _customer_audit(record, candidate)
        warnings = []
        if parent_evidence:
            warnings.append("A parent-organization fact exists; confirm local decision authority before contact.")
        if contact["channel"] != "EMAIL":
            warnings.append("No approved public email was selected; phone contact would require separate human judgment.")
        name = audit["customer_safe_audit"]["organization"]["name"]
        eligible.append({
            "pilot_id": _stable(COHORT, domain), "organization_id": domain,
            "organization_name": name,
            "pilot_cohort": COHORT, "initial_state": "CANDIDATE",
            "selected_contact": contact, "selected_audit_id": audit["audit_id"],
            "selected_audit_version": audit["audit_version"],
            "selection_score_internal": selection_score,
            "selection_rationale": candidate.get("selection_reasons") or [],
            "warnings": warnings, "audit_package": audit,
            "guarded_draft_preview": _draft_preview(name, audit, contact["contact_id"]),
            "draft_status": "BLOCKED_PENDING_MANUAL_REVIEW_AND_APPROVAL",
        })
    selected = sorted(eligible, key=lambda value: (-value["selection_score_internal"], value["organization_id"]))[:limit]
    payload = {
        "schema_version": 1, "generator": "controlled_pilot", "generator_version": VERSION,
        "pilot_cohort": COHORT, "offer_definition": OFFER, "prospects": selected,
        "safety": {"crm_write_performed": False, "network_request_performed": False, "outreach_sent": False},
    }
    payload["cohort_id"] = _stable(payload)
    return payload


def _rates(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def build_stats(cohort: Dict[str, Any], events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    events = list(events)
    states = {item["pilot_id"]: item.get("initial_state", "CANDIDATE") for item in cohort.get("prospects") or []}
    reached = {state: set() for state in STATES}
    for identifier, state in states.items():
        reached[state].add(identifier)
    offers: Dict[str, Dict[str, Any]] = {}
    reply_sentiments: Dict[str, str] = {}
    observation_by_pilot = {
        item["pilot_id"]: {
            observation["category"]
            for observation in item["audit_package"]["customer_safe_audit"]["observations"]
        }
        for item in cohort.get("prospects") or []
    }
    for event in events:
        identifier = event.get("pilot_id")
        if identifier not in states:
            continue
        if event.get("event_type") == "STATE_TRANSITION":
            state = event.get("to_state")
            states[identifier] = state
            reached.setdefault(state, set()).add(identifier)
            if state == "REPLIED" and event.get("reply_sentiment"):
                reply_sentiments[identifier] = event["reply_sentiment"]
        elif event.get("event_type") == "OFFER_ASSIGNED":
            offers[identifier] = event
    contacted = reached["CONTACTED"]
    replied = reached["REPLIED"]
    positive = {value for value, sentiment in reply_sentiments.items() if sentiment == "POSITIVE"}
    meetings, proposals, wins = reached["MEETING"], reached["PROPOSAL"], reached["WON"]
    revenue = sum(float(value.get("accepted_amount") or 0) for value in offers.values())
    recurring = sum(float(value.get("recurring_amount") or 0) for value in offers.values())
    contacted_categories = Counter(category for identifier in contacted for category in observation_by_pilot.get(identifier, set()))
    winning_categories = Counter(category for identifier in wins for category in observation_by_pilot.get(identifier, set()))
    return {
        "cohort_size": len(states), "current_states": dict(sorted(Counter(states.values()).items())),
        "manual_review": len(reached["MANUAL_REVIEW"]),
        "approved": len(reached["APPROVED_FOR_CONTACT"]), "drafted": len(reached["CONTACT_PREPARED"]),
        "contacted": len(contacted), "replies": len(replied), "positive_replies": len(positive),
        "negative_replies": sum(value == "NEGATIVE" for value in reply_sentiments.values()),
        "meetings": len(meetings), "proposals": len(proposals), "wins": len(wins),
        "losses": len(reached["LOST"]), "disqualified": len(reached["DISQUALIFIED"]),
        "deferred": len(reached["DEFERRED"]), "manual_revenue": round(revenue, 2),
        "manually_recorded_recurring_amount": round(recurring, 2),
        "offer_variants": dict(sorted(Counter(value.get("offer_variant") for value in offers.values()).items())),
        "rates_percent": {
            "contact_to_reply": _rates(len(replied), len(contacted)),
            "contact_to_positive_reply": _rates(len(positive), len(contacted)),
            "contact_to_meeting": _rates(len(meetings), len(contacted)),
            "meeting_to_proposal": _rates(len(proposals), len(meetings)),
            "proposal_to_win": _rates(len(wins), len(proposals)),
        },
        "revenue_per_contacted": round(revenue / len(contacted), 2) if contacted else None,
        "revenue_per_won": round(revenue / len(wins), 2) if wins else None,
        "observation_categories_contacted": dict(sorted(contacted_categories.items())),
        "observation_categories_won": dict(sorted(winning_categories.items())),
        "sample_warning": "Pilot rates are descriptive only and are not statistically predictive.",
    }


class PilotStore:
    def __init__(self, cohort_path: Path, events_path: Path):
        self.cohort_path = Path(cohort_path)
        self.events_path = Path(events_path)

    @staticmethod
    def _load(path: Path, default):
        if not path.is_file():
            return default
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, type(default)):
            raise ValueError(f"Malformed pilot data: {path}")
        return value

    def cohort(self) -> Dict[str, Any]:
        return self._load(self.cohort_path, {})

    def events(self) -> List[Dict[str, Any]]:
        return self._load(self.events_path, [])

    def save_cohort(self, cohort: Dict[str, Any]) -> bool:
        existing = self.cohort()
        if existing == cohort:
            return False
        AgentOrchestrator._atomic_json(self.cohort_path, cohort)
        return True

    def _prospect(self, identifier: str) -> Dict[str, Any]:
        match = next((item for item in self.cohort().get("prospects", []) if identifier in {item.get("pilot_id"), item.get("organization_id")}), None)
        if not match:
            raise ValueError("Unknown pilot prospect")
        return match

    def history(self, identifier: str) -> List[Dict[str, Any]]:
        prospect = self._prospect(identifier)
        return [event for event in self.events() if event.get("pilot_id") == prospect["pilot_id"]]

    def state(self, identifier: str) -> str:
        prospect = self._prospect(identifier)
        state = prospect.get("initial_state", "CANDIDATE")
        for event in self.history(prospect["pilot_id"]):
            if event.get("event_type") == "STATE_TRANSITION":
                state = event["to_state"]
        return state

    def effective(self) -> List[Dict[str, Any]]:
        return [{**item, "current_state": self.state(item["pilot_id"])} for item in self.cohort().get("prospects", [])]

    def _append(self, event: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        lock_path = self.events_path.with_suffix(self.events_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            events = self.events()
            existing = next((value for value in events if value.get("event_id") == event["event_id"]), None)
            if existing:
                return existing, False
            AgentOrchestrator._atomic_json(self.events_path, [*events, event])
            return event, True

    def transition(self, identifier: str, to_state: str, actor: str, *, note="", reply_sentiment=None,
                   activity_references=(), _approval_checked=False) -> tuple[Dict[str, Any], bool]:
        prospect = self._prospect(identifier)
        actor = actor.strip()
        to_state = to_state.upper()
        if not actor:
            raise ValueError("Actor is required")
        if to_state not in STATES:
            raise ValueError("Unsupported pilot state")
        if to_state == "APPROVED_FOR_CONTACT" and not _approval_checked:
            raise ValueError("Use the current-evidence approval workflow")
        current = self.state(prospect["pilot_id"])
        if to_state not in TRANSITIONS[current]:
            raise ValueError(f"Pilot transition is not allowed: {current} -> {to_state}")
        sentiment = str(reply_sentiment or "").upper() or None
        if to_state == "REPLIED" and sentiment not in {"POSITIVE", "NEGATIVE", "NEUTRAL"}:
            raise ValueError("REPLIED requires POSITIVE, NEGATIVE, or NEUTRAL sentiment")
        if to_state != "REPLIED" and sentiment:
            raise ValueError("Reply sentiment is valid only for REPLIED")
        event = {
            "schema_version": 1, "event_type": "STATE_TRANSITION",
            "pilot_id": prospect["pilot_id"], "organization_id": prospect["organization_id"],
            "from_state": current, "to_state": to_state, "actor": actor,
            "timestamp": _now(), "note": note, "reply_sentiment": sentiment,
            "selected_contact_id": prospect["selected_contact"]["contact_id"],
            "selected_audit_id": prospect["selected_audit_id"],
            "selected_audit_version": prospect["selected_audit_version"],
            "activity_references": sorted({str(value) for value in activity_references if str(value).strip()}),
        }
        event["event_id"] = _stable({key: value for key, value in event.items() if key != "timestamp"})
        return self._append(event)

    def approve(self, identifier: str, actor: str, records: Iterable[Dict[str, Any]], *, note=""):
        prospect = self._prospect(identifier)
        record = next((value for value in records if value.get("domain") == prospect["organization_id"]), None)
        if not record or not approved_for_commercial_use(record, outreach=True):
            raise ValueError("Current CRM/outreach readiness does not permit approval")
        current_fact_ids = {fact.get("id") for fact in (record.get("enrichment") or {}).get("facts") or []}
        appendix = prospect["audit_package"]["evidence_appendix"]
        required_fact_ids = {
            evidence_id for evidence_id, evidence in appendix.items()
            if "source_url" in evidence
        }
        if not required_fact_ids.issubset(current_fact_ids):
            raise ValueError("Current evidence no longer supports the selected audit package")
        return self.transition(
            prospect["pilot_id"], "APPROVED_FOR_CONTACT", actor,
            note=note, _approval_checked=True,
        )

    def prepare_draft(self, identifier: str, actor: str) -> tuple[Dict[str, Any], bool]:
        prospect = self._prospect(identifier)
        if self.state(prospect["pilot_id"]) == "CONTACT_PREPARED":
            existing = next((event for event in reversed(self.history(prospect["pilot_id"])) if event.get("draft")), None)
            return existing, False
        if self.state(prospect["pilot_id"]) != "APPROVED_FOR_CONTACT":
            raise ValueError("Draft requires explicit APPROVED_FOR_CONTACT state")
        contact = prospect["selected_contact"]
        if contact["channel"] != "EMAIL":
            raise ValueError("Guarded email draft requires a selected public email")
        preview = prospect["guarded_draft_preview"]
        draft = {**preview, "status": "PREPARED_UNSENT", "sendable": False, "to": contact["value"]}
        event = {
            "schema_version": 1, "event_type": "STATE_TRANSITION",
            "pilot_id": prospect["pilot_id"], "organization_id": prospect["organization_id"],
            "from_state": "APPROVED_FOR_CONTACT", "to_state": "CONTACT_PREPARED",
            "actor": actor.strip(), "timestamp": _now(), "note": "Guarded unsent draft prepared.",
            "reply_sentiment": None, "selected_contact_id": contact["contact_id"],
            "selected_audit_id": prospect["selected_audit_id"],
            "selected_audit_version": prospect["selected_audit_version"],
            "activity_references": [], "draft": draft,
        }
        if not event["actor"]:
            raise ValueError("Actor is required")
        event["event_id"] = _stable({key: value for key, value in event.items() if key != "timestamp"})
        return self._append(event)

    def assign_offer(self, identifier: str, variant: str, actor: str, *, quoted_amount=0, accepted_amount=0, recurring_amount=0, note=""):
        prospect = self._prospect(identifier)
        variant = variant.upper()
        if variant not in OFFER["variants"]:
            raise ValueError("Unsupported offer variant")
        amounts = [float(quoted_amount), float(accepted_amount), float(recurring_amount)]
        if any(value < 0 for value in amounts):
            raise ValueError("Offer amounts cannot be negative")
        if not actor.strip():
            raise ValueError("Actor is required")
        event = {
            "schema_version": 1, "event_type": "OFFER_ASSIGNED",
            "pilot_id": prospect["pilot_id"], "organization_id": prospect["organization_id"],
            "offer_variant": variant, "quoted_amount": amounts[0],
            "accepted_amount": amounts[1], "recurring_amount": amounts[2],
            "actor": actor.strip(), "timestamp": _now(), "note": note,
            "selected_audit_id": prospect["selected_audit_id"],
            "selected_audit_version": prospect["selected_audit_version"],
            "activity_references": [],
        }
        event["event_id"] = _stable({key: value for key, value in event.items() if key != "timestamp"})
        return self._append(event)

    def stats(self) -> Dict[str, Any]:
        return build_stats(self.cohort(), self.events())
