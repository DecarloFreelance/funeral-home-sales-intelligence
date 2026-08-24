from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from automation.orchestrator import AgentOrchestrator
from enrichment.quality import CRM_BLOCKING_CODES, readiness_from_findings


VERSION = 1
DECISION_TYPES = {
    "CONFIRM_CURRENT_RELATIONSHIP",
    "REJECT_CANDIDATE",
    "MARK_DISTINCT",
    "CONFIRM_DUPLICATE",
    "CONFIRM_ALTERNATE_EMAIL",
    "REJECT_EMAIL_ASSOCIATION",
    "CONFIRM_BRANCH_RELATIONSHIP",
    "DEFER",
    "SUPPRESS_FALSE_POSITIVE",
}
RESOLVING_DECISIONS = {
    "CONFIRM_CURRENT_RELATIONSHIP",
    "MARK_DISTINCT",
    "CONFIRM_ALTERNATE_EMAIL",
    "CONFIRM_BRANCH_RELATIONSHIP",
    "SUPPRESS_FALSE_POSITIVE",
}
DEFERRED_DECISIONS = {"DEFER", "REJECT_CANDIDATE", "REJECT_EMAIL_ASSOCIATION"}
ALLOWED_BY_CODE = {
    "NO_USABLE_WEBSITE_EVIDENCE": {"CONFIRM_CURRENT_RELATIONSHIP", "REJECT_CANDIDATE", "DEFER", "SUPPRESS_FALSE_POSITIVE"},
    "ORGANIZATION_WEBSITE_MISMATCH": {"CONFIRM_CURRENT_RELATIONSHIP", "REJECT_CANDIDATE", "DEFER", "SUPPRESS_FALSE_POSITIVE"},
    "POSSIBLE_DUPLICATE_ORGANIZATION": {"MARK_DISTINCT", "CONFIRM_DUPLICATE", "DEFER", "SUPPRESS_FALSE_POSITIVE"},
    "SHARED_ADDRESS_REVIEW": {"MARK_DISTINCT", "CONFIRM_DUPLICATE", "CONFIRM_BRANCH_RELATIONSHIP", "DEFER", "SUPPRESS_FALSE_POSITIVE"},
    "EMAIL_DOMAIN_MISMATCH": {"CONFIRM_ALTERNATE_EMAIL", "REJECT_EMAIL_ASSOCIATION", "DEFER", "SUPPRESS_FALSE_POSITIVE"},
    "MULTI_LOCATION_ACCOUNT_REVIEW": {"CONFIRM_BRANCH_RELATIONSHIP", "DEFER", "SUPPRESS_FALSE_POSITIVE"},
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(*values: Any, length=24) -> str:
    material = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]


def _question_for(research: Dict[str, Any], finding_id: str, code: str) -> Dict[str, Any]:
    for question in (research or {}).get("questions") or []:
        if question.get("finding_id") == finding_id or question.get("finding_code") == code:
            return question
    return {}


def _related_entities(evidence: Any) -> List[str]:
    if not isinstance(evidence, dict):
        return []
    values = evidence.get("domains") or evidence.get("related_domains") or []
    return sorted({str(value) for value in values if value})


def _evidence_references(finding: Dict[str, Any], outcome: Dict[str, Any]) -> List[str]:
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
    outcome_evidence = outcome.get("evidence") if isinstance(outcome.get("evidence"), dict) else {}
    return sorted({str(value) for value in [
        evidence.get("source_url"),
        *(evidence.get("source_urls") or []),
        outcome.get("official_website"),
        outcome_evidence.get("redirect_from"),
        outcome_evidence.get("redirect_to"),
        *(outcome_evidence.get("association_sources") or []),
    ] if value})


def build_review_items(review: Iterable[Dict[str, Any]], research: Iterable[Dict[str, Any]],
                       records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    research_by_domain = {
        str(item.get("domain") or ""): item.get("research_resolution") or {}
        for item in research if isinstance(item, dict)
    }
    records_by_domain = {str(item.get("domain") or ""): item for item in records if isinstance(item, dict)}
    items = []
    for group in review:
        domain = str(group.get("domain") or "")
        record = records_by_domain.get(domain, {})
        profile = record.get("business_profile") or {}
        locations = [value for value in profile.get("locations") or [] if isinstance(value, dict)]
        location = locations[0] if locations else {}
        for finding in group.get("findings") or []:
            if not finding.get("requires_review", finding.get("severity") in {"HIGH", "MEDIUM"}):
                continue
            finding_id = str(finding.get("id") or "")
            code = str(finding.get("code") or "")
            question = _question_for(research_by_domain.get(domain, {}), finding_id, code)
            outcome = question.get("outcome") or {}
            evidence = finding.get("evidence")
            items.append({
                "schema_version": VERSION,
                "review_id": _stable_id("manual-review", domain, finding_id, code),
                "organization_id": domain,
                "organization_name": profile.get("company") or domain,
                "finding_id": finding_id,
                "finding_type": code,
                "finding_reference": {"domain": domain, "finding_id": finding_id},
                "finding_snapshot": finding,
                "research_question": question.get("question") or finding.get("recommended_action"),
                "current_website": profile.get("website") or record.get("website") or domain,
                "candidate": {
                    "website": outcome.get("official_website") or (
                        evidence.get("source_url") if isinstance(evidence, dict) else None
                    ),
                    "email": evidence.get("email") if isinstance(evidence, dict) else None,
                    "organization_ids": _related_entities(evidence),
                },
                "evidence_references": _evidence_references(finding, outcome),
                "checked_sources": question.get("candidate_sources") or [],
                "automated_confidence": outcome.get("confidence", 0.0),
                "unresolved_reason": outcome.get("reason") or "No deterministic research conclusion is available.",
                "province": location.get("province") or profile.get("province") or "",
                "location_context": {
                    "address": location.get("address") or profile.get("address") or "",
                    "city": location.get("city") or profile.get("city") or "",
                    "province": location.get("province") or profile.get("province") or "",
                },
                "related_organization_ids": _related_entities(evidence),
                "original_crm_sync_safe": bool(group.get("crm_sync_safe")),
                "original_outreach_ready": bool(group.get("outreach_ready")),
            })
    return sorted(items, key=lambda item: (item["organization_id"], item["finding_type"], item["review_id"]))


def _latest(decisions: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for decision in decisions:
        result[decision.get("review_id")] = decision
    return result


def _disposition(item: Dict[str, Any], decision_type: str | None) -> str:
    if decision_type == "CONFIRM_DUPLICATE":
        return "CONFIRMED_DUPLICATE"
    if (
        decision_type == "CONFIRM_CURRENT_RELATIONSHIP"
        and item.get("finding_type") == "NO_USABLE_WEBSITE_EVIDENCE"
    ):
        return "CONFIRMED_RELATIONSHIP_PENDING_RECRAWL"
    if decision_type == "CONFIRM_BRANCH_RELATIONSHIP":
        return "CONFIRMED_RELATIONSHIP_PENDING_MAPPING"
    if decision_type in RESOLVING_DECISIONS:
        return "RESOLVED"
    if decision_type in DEFERRED_DECISIONS:
        return "DEFERRED"
    return "UNRESOLVED"


def effective_items(items: Iterable[Dict[str, Any]], decisions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest = _latest(decisions)
    output = []
    for item in items:
        decision = latest.get(item["review_id"])
        decision_type = decision.get("decision_type") if decision else None
        disposition = _disposition(item, decision_type)
        output.append({**item, "decision": decision, "disposition": disposition})
    return output


def review_metrics(items: Iterable[Dict[str, Any]], decisions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    effective = effective_items(items, decisions)
    unresolved = [item for item in effective if item["disposition"] not in {"RESOLVED", "DEFERRED"}]
    deferred = [item for item in effective if item["disposition"] == "DEFERRED"]
    blocking = [item for item in effective if item["disposition"] not in {"RESOLVED"}]
    crm_blocking = [item for item in blocking if (
        item["finding_snapshot"].get("severity") == "HIGH"
        or item["finding_type"] in CRM_BLOCKING_CODES
    )]
    outreach_blocking = [item for item in blocking if item["finding_snapshot"].get("requires_review", True)]
    return {
        "total_review_items": len(effective),
        "unresolved": len(unresolved),
        "resolved": sum(item["disposition"] == "RESOLVED" for item in effective),
        "deferred": len(deferred),
        "confirmed_false_positives": sum((item.get("decision") or {}).get("decision_type") == "SUPPRESS_FALSE_POSITIVE" for item in effective),
        "confirmed_relationships": sum((item.get("decision") or {}).get("decision_type") in {"CONFIRM_CURRENT_RELATIONSHIP", "CONFIRM_ALTERNATE_EMAIL", "CONFIRM_BRANCH_RELATIONSHIP"} for item in effective),
        "confirmed_duplicates": sum(item["disposition"] == "CONFIRMED_DUPLICATE" for item in effective),
        "crm_blocking_items": len(crm_blocking),
        "outreach_blocking_items": len(outreach_blocking),
        "by_finding_type": dict(sorted(Counter(item["finding_type"] for item in effective).items())),
        "by_province": dict(sorted(Counter(item["province"] or "UNKNOWN" for item in effective).items())),
    }


def organization_readiness(items: Iterable[Dict[str, Any]], decisions: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    effective = effective_items(items, decisions)
    grouped: Dict[str, List[Dict[str, Any]]] = {
        item["organization_id"]: [] for item in effective
    }
    for item in effective:
        if item["disposition"] == "RESOLVED":
            continue
        grouped.setdefault(item["organization_id"], []).append(item["finding_snapshot"])
    return {domain: readiness_from_findings(findings) for domain, findings in grouped.items()}


def effective_review_queue(items: Iterable[Dict[str, Any]], decisions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    effective = effective_items(items, decisions)
    readiness = organization_readiness(effective, decisions)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in effective:
        grouped.setdefault(item["organization_id"], []).append(item)
    output = []
    for domain, organization_items in sorted(grouped.items()):
        remaining = [item for item in organization_items if item["disposition"] != "RESOLVED"]
        state = readiness[domain]
        output.append({
            "organization_id": domain,
            "status": "NEEDS_REVIEW" if remaining else "MANUALLY_RESOLVED",
            "items": organization_items,
            "remaining_review_ids": [item["review_id"] for item in remaining],
            **state,
        })
    return output


class ManualReviewStore:
    def __init__(self, queue_path: Path, decisions_path: Path):
        self.queue_path = Path(queue_path)
        self.decisions_path = Path(decisions_path)

    @staticmethod
    def _load(path: Path) -> List[Dict[str, Any]]:
        if not path.is_file():
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"Expected JSON list: {path}")
        return value

    def items(self) -> List[Dict[str, Any]]:
        return self._load(self.queue_path)

    def decisions(self) -> List[Dict[str, Any]]:
        return self._load(self.decisions_path)

    def refresh(self, review, research, records) -> List[Dict[str, Any]]:
        items = build_review_items(review, research, records)
        AgentOrchestrator._atomic_json(self.queue_path, items)
        return items

    def decide(self, review_id: str, decision_type: str, actor: str, *, note="",
               evidence_references=()) -> tuple[Dict[str, Any], bool]:
        decision_type = decision_type.upper()
        if decision_type not in DECISION_TYPES:
            raise ValueError("Unsupported decision type")
        actor = actor.strip()
        if not actor:
            raise ValueError("Actor is required")
        item = next((value for value in self.items() if value.get("review_id") == review_id), None)
        if item is None:
            raise ValueError("Unknown review item")
        allowed = ALLOWED_BY_CODE.get(item["finding_type"], {"DEFER", "SUPPRESS_FALSE_POSITIVE"})
        if decision_type not in allowed:
            raise ValueError(f"Decision {decision_type} is not valid for {item['finding_type']}")
        evidence = sorted({str(value) for value in evidence_references if str(value).strip()})
        if decision_type in RESOLVING_DECISIONS | {"CONFIRM_DUPLICATE"} and not evidence:
            raise ValueError("Evidence reference is required for this decision")
        identifier = _stable_id(review_id, decision_type, actor, note, evidence)
        lock_path = self.decisions_path.with_suffix(self.decisions_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            decisions = self.decisions()
            existing = next((value for value in decisions if value.get("decision_id") == identifier), None)
            if existing:
                return existing, False
            prior = [value for value in decisions if value.get("review_id") == review_id]
            decision = {
                "schema_version": VERSION,
                "decision_id": identifier,
                "review_id": review_id,
                "decision_type": decision_type,
                "actor": actor,
                "timestamp": _iso_now(),
                "note": note,
                "evidence_references": evidence,
                # Snapshot the complete review context so later source changes do
                # not erase what the operator actually saw and decided.
                "previous_unresolved_state": item,
                "previous_decision_id": prior[-1]["decision_id"] if prior else None,
                "resulting_disposition": _disposition(item, decision_type),
                "safety": {
                    "entity_merge_performed": False,
                    "page_or_contact_reassignment_performed": False,
                    "automatic_threshold_changed": False,
                },
            }
            AgentOrchestrator._atomic_json(self.decisions_path, [*decisions, decision])
            return decision, True
