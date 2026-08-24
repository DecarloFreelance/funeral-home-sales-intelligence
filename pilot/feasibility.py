from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

from automation.agents import RecordAgent
from automation.orchestrator import AgentOrchestrator
from pilot.workflow import _angle_evidence, _record_identity, _stable


SCHEMA_VERSION = 1
VERSION = "1.0.0"
AGENT_NAME = "implementation_feasibility"

IMPLEMENTATION_PATHS = {"DIRECT_EDIT_LIKELY", "PROVIDER_CONTROL_LIKELY", "UNKNOWN_ACCESS"}
SCOPES = {"NARROW", "MODERATE", "UNSCOPED"}
OUTCOMES = {"READY_FOR_DISCOVERY", "PROVIDER_CONFIRMATION_REQUIRED", "INSUFFICIENT_EVIDENCE"}
IDENTITY_BLOCKERS = {
    "NO_USABLE_WEBSITE_EVIDENCE",
    "POSSIBLE_DUPLICATE_ORGANIZATION",
    "MULTI_LOCATION_ACCOUNT_REVIEW",
    "SHARED_ADDRESS_REVIEW",
    "ORGANIZATION_WEBSITE_MISMATCH",
}
HOSTED_PROVIDER_PATTERNS = {
    "CFS Funeral Home Websites": (
        r"(?:consolidatedfuneralservices\.com|/framework/(?:css|js)/cfs[-./])",
        0.98,
    ),
    "Tribute Archive infrastructure": (r"tributearchive\.com", 0.95),
    "FuneralTech": (r"(?:client-data\.funeraltechweb\.com|website powered by\s+FuneralTech)", 0.98),
}
HOST_CONTROL_PROVIDERS = {"CFS Funeral Home Websites", "FuneralTech"}
DIRECT_MANAGEMENT_VALUES = {
    "organization-managed cms",
    "organization managed cms",
    "direct cms access confirmed",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _host(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _owned_pages(organization_id: str, pages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    owned = []
    for page in pages:
        queue_domain = _host((page.get("discovery") or {}).get("queue_domain"))
        page_host = _host(page.get("url"))
        owner = queue_domain or page_host
        if owner == organization_id:
            owned.append(page)
    return sorted(owned, key=lambda value: str(value.get("url") or ""))


def _technology_signals(record: Dict[str, Any], organization_id: str) -> List[Dict[str, Any]]:
    signals = []
    for fact in (record.get("enrichment") or {}).get("facts") or []:
        if fact.get("field") not in {"technology.platform", "technology.management"}:
            continue
        source_url = str(fact.get("source_url") or "")
        if source_url and _host(source_url) != organization_id:
            continue
        signals.append({
            "evidence_id": fact.get("id"),
            "field": fact.get("field"),
            "value": fact.get("value"),
            "source_url": source_url,
            "observed_at": fact.get("observed_at"),
            "stale_after": fact.get("stale_after"),
            "confidence": fact.get("confidence"),
            "verification_state": fact.get("verification_state"),
        })
    return sorted(signals, key=lambda value: (str(value.get("field")), str(value.get("value")), str(value.get("evidence_id"))))


def _provider_signals(organization_id: str, pages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    signals = []
    for page in _owned_pages(organization_id, pages):
        html = str(page.get("html") or "")
        for provider, (pattern, confidence) in HOSTED_PROVIDER_PATTERNS.items():
            match = re.search(pattern, html, re.I)
            if not match:
                continue
            signals.append({
                "provider": provider,
                "source_url": str(page.get("url") or ""),
                "page_fingerprint": _sha256(html),
                "observed_at": (page.get("crawl") or {}).get("observedAt"),
                "marker": match.group(0)[:120],
                "confidence": confidence,
                "verification_state": "DIRECTLY_OBSERVED",
            })
    unique = {(value["provider"], value["source_url"], value["marker"]): value for value in signals}
    return [unique[key] for key in sorted(unique)]


def _identity_blockers(record: Dict[str, Any]) -> List[str]:
    quality = record.get("quality_control") or {}
    codes = {
        str(value.get("code") or "")
        for value in quality.get("findings") or []
        if value.get("code") in IDENTITY_BLOCKERS
    }
    return sorted(codes)


def _expired_evidence_ids(resolved: Dict[str, Any]) -> List[str]:
    now = datetime.now(timezone.utc)
    expired = []
    for evidence_id, value in resolved.items():
        stale_after = value.get("stale_after")
        if not stale_after:
            continue
        try:
            horizon = datetime.fromisoformat(str(stale_after).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            expired.append(evidence_id)
            continue
        if horizon <= now:
            expired.append(evidence_id)
    return sorted(expired)


def _resolved_evidence(record: Dict[str, Any], forms: Dict[str, Any], angle: Dict[str, Any]):
    try:
        return _angle_evidence(record, forms, angle.get("evidence_ids") or []), None
    except ValueError as error:
        return {}, str(error)


def _input_material(context: Dict[str, Any]) -> Dict[str, Any]:
    organization_id = str(context.get("domain") or "").lower().removeprefix("www.")
    record = context.get("record") or {}
    angle = context.get("selected_angle") or {}
    forms = context.get("forms") or {"forms": []}
    pages = context.get("pages") or []
    resolved, evidence_error = _resolved_evidence(record, forms, angle) if angle else ({}, "Missing COMMERCIAL_ANGLE_SELECTED")
    return {
        "organization_id": organization_id,
        "pilot_id": angle.get("pilot_id"),
        "angle_id": angle.get("angle_id"),
        "selected_angle": angle,
        "current_organization_fingerprint": _record_identity(record) if record else None,
        "resolved_evidence": resolved,
        "evidence_error": evidence_error,
        "technology_signals": _technology_signals(record, organization_id),
        "provider_signals": _provider_signals(organization_id, pages),
        "identity_blockers": _identity_blockers(record),
        "expired_evidence_ids": _expired_evidence_ids(resolved),
    }


def _bounded_scope(angle: Dict[str, Any], resolved: Dict[str, Any]) -> bool:
    angle_type = str(angle.get("angle_type") or "").upper()
    observation = str(angle.get("customer_safe_observation") or "")
    improvement = str(angle.get("proposed_improvement") or "")
    if not observation or not improvement:
        return False
    if angle_type.startswith("FORM_") or "_FORM_" in angle_type:
        form_count = sum(bool(value.get("form_id") or value.get("observation_id")) for value in resolved.values())
        return form_count >= 1
    return any(token in angle_type for token in ("LINK", "NAVIGATION", "CONTENT", "PATHWAY")) and bool(resolved)


def _form_advisory(angle: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        "scope_assumptions": [
            "The selected observation remains current at implementation time.",
            "The existing form and enquiry destination remain in scope; no platform replacement is implied.",
        ],
        "required_access": [
            "Confirm who controls the page or form template.",
            "Confirm appropriate CMS, form-builder, provider, or staging access before implementation.",
        ],
        "discovery_questions": [
            "Who currently manages the website and this form?",
            "Can the form labels or prompt associations be edited directly, or must the website provider make the change?",
            "Is a staging or preview workflow available?",
            "Which fields should the organization treat as required or optional?",
        ],
        "proposed_work_units": [
            "Review the selected form configuration and confirm the bounded change.",
            "Implement the approved prompt or label association without changing the enquiry destination.",
            "Verify the affected form in the agreed desktop, mobile, and keyboard checks.",
            "Provide concise before-and-after evidence and a handoff note.",
        ],
        "verification_plan": [
            "Capture the current prompts and control relationships before modification.",
            "Confirm persistent or explicit field identification after modification.",
            "Perform non-destructive checks of the existing form path on desktop, mobile, and by keyboard.",
            "Confirm the existing submission destination and unrelated pages remain unchanged.",
        ],
        "acceptance_criteria": [
            "The selected fields have the approved visible or programmatic prompt association.",
            "The existing enquiry destination remains unchanged.",
            "The agreed non-destructive desktop, mobile, and keyboard checks pass.",
            "Before-and-after evidence is delivered.",
        ],
        "rescope_triggers": [
            "The provider must perform or separately approve implementation.",
            "The form technology or website platform must be replaced.",
            "Shared-template changes affect sibling organizations or unrelated pages.",
            "Existing submission behaviour is already broken or requires repair.",
            "Additional pages, forms, redesign, or content strategy enter scope.",
        ],
    }


def _pathway_advisory() -> Dict[str, List[str]]:
    return {
        "scope_assumptions": [
            "The selected first-party pathway evidence remains current at review time.",
            "The work is a bounded desktop/mobile review; no defect, redesign, or platform replacement is implied.",
        ],
        "required_access": [
            "No edit access is required for the review.",
            "Confirm website ownership and appropriate CMS or provider access before any separately approved implementation.",
        ],
        "discovery_questions": [
            "Who currently manages the website and approves pathway changes?",
            "What should a visitor do after reading the pre-planning information?",
            "Can navigation, calls to action, or content be edited directly, or must the provider make changes?",
        ],
        "proposed_work_units": [
            "Review the existing pre-planning information pathway on desktop and mobile without submitting anything.",
            "Document only evidence-supported navigation, call-to-action, content, or completion-clarity observations.",
            "Scope any proposed change separately after ownership, access, and approval are confirmed.",
        ],
        "verification_plan": [
            "Retain current page and pathway evidence before review.",
            "Check the existing navigation and information path on desktop and mobile.",
            "Confirm every recommendation maps to a current observed page element.",
        ],
        "acceptance_criteria": [
            "The review distinguishes observations from recommendations and asserts no unsupported defect.",
            "Every scoped recommendation cites current organization-bound evidence.",
            "No form is submitted and no customer-site change is performed.",
        ],
        "rescope_triggers": [
            "The provider must perform or separately approve implementation.",
            "The requested work expands to forms, platform replacement, redesign, compliance, or conversion claims.",
            "Current evidence or organization identity changes.",
        ],
    }


def _unscoped_advisory() -> Dict[str, List[str]]:
    return {
        "scope_assumptions": [],
        "required_access": ["Current implementation ownership and access must be established before scoping."],
        "discovery_questions": [
            "Who controls the affected website component?",
            "Can the selected change be isolated without redesign or platform replacement?",
            "What non-destructive acceptance check would establish completion?",
        ],
        "proposed_work_units": [],
        "verification_plan": [],
        "acceptance_criteria": [],
        "rescope_triggers": ["Any implementation should be re-scoped after sufficient current evidence and access details are available."],
    }


class ImplementationFeasibilityAgent(RecordAgent):
    """Produce an internal-only implementation advisory for one selected angle."""

    name = AGENT_NAME
    version = VERSION
    max_attempts = 2

    def fingerprint_payload(self, context: Dict[str, Any]) -> Any:
        return _input_material(context)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        material = _input_material(context)
        angle = material["selected_angle"]
        if not angle:
            raise ValueError("Implementation feasibility requires COMMERCIAL_ANGLE_SELECTED")

        organization_id = material["organization_id"]
        evidence_error = material["evidence_error"]
        blockers = material["identity_blockers"]
        expired_evidence_ids = material["expired_evidence_ids"]
        identity_changed = material["current_organization_fingerprint"] != angle.get("organization_fingerprint")
        current_evidence_fingerprint = _stable(material["resolved_evidence"]) if not evidence_error else None
        evidence_changed = current_evidence_fingerprint != angle.get("evidence_fingerprint")
        invalid_reasons = []
        if evidence_error:
            invalid_reasons.append(evidence_error)
        if identity_changed:
            invalid_reasons.append("Selected commercial-angle organization identity changed")
        if evidence_changed and not evidence_error:
            invalid_reasons.append("Selected commercial-angle evidence is stale or materially changed")
        if blockers:
            invalid_reasons.append("Identity-critical findings remain unresolved: " + ", ".join(blockers))
        if expired_evidence_ids:
            invalid_reasons.append("Selected commercial-angle evidence is stale: " + ", ".join(expired_evidence_ids))

        provider_signals = material["provider_signals"]
        technology_signals = material["technology_signals"]
        hosted_providers = {
            value["provider"] for value in provider_signals
            if value["provider"] in HOST_CONTROL_PROVIDERS
        }
        management_values = {
            str(value.get("value") or "").strip().casefold()
            for value in technology_signals
            if value.get("field") == "technology.management"
            and float(value.get("confidence") or 0) >= 0.9
            and value.get("verification_state") in {"DIRECTLY_OBSERVED", "CORROBORATED"}
        }
        direct_management = bool(management_values & DIRECT_MANAGEMENT_VALUES)
        conflicting_provider_signals = bool(hosted_providers and direct_management)
        bounded = _bounded_scope(angle, material["resolved_evidence"])

        if invalid_reasons:
            implementation_path, scope, outcome, confidence = (
                "UNKNOWN_ACCESS", "UNSCOPED", "INSUFFICIENT_EVIDENCE", 0.0,
            )
            guidance = _unscoped_advisory()
        else:
            scope = "NARROW" if bounded else "UNSCOPED"
            normalized_angle_type = str(angle.get("angle_type") or "").upper()
            if bounded and (normalized_angle_type.startswith("FORM_") or "_FORM_" in normalized_angle_type):
                guidance = _form_advisory(angle)
            elif bounded:
                guidance = _pathway_advisory()
            else:
                guidance = _unscoped_advisory()
            if conflicting_provider_signals or hosted_providers:
                implementation_path = "PROVIDER_CONTROL_LIKELY"
                outcome = "PROVIDER_CONFIRMATION_REQUIRED"
                confidence = 0.9 if hosted_providers else 0.7
            elif direct_management:
                implementation_path = "DIRECT_EDIT_LIKELY"
                outcome = "READY_FOR_DISCOVERY" if bounded else "INSUFFICIENT_EVIDENCE"
                confidence = 0.85 if bounded else 0.4
            else:
                implementation_path = "UNKNOWN_ACCESS"
                outcome = "READY_FOR_DISCOVERY" if bounded else "INSUFFICIENT_EVIDENCE"
                confidence = 0.7 if bounded else 0.2

        input_fingerprint = _sha256({"agent_version": self.version, **material})
        source_urls = sorted({
            str(value.get("source_url") or value.get("page_url") or "")
            for value in material["resolved_evidence"].values()
            if value.get("source_url") or value.get("page_url")
        } | {
            str(value.get("source_url") or "")
            for value in [*provider_signals, *technology_signals]
            if value.get("source_url")
        })
        advisory = {
            "schema_version": SCHEMA_VERSION,
            "agent_name": self.name,
            "agent_version": self.version,
            "feasibility_id": _stable("implementation-feasibility", organization_id, angle.get("angle_id")),
            "organization_id": organization_id,
            "pilot_id": angle.get("pilot_id"),
            "angle_id": angle.get("angle_id"),
            "organization_fingerprint": material["current_organization_fingerprint"],
            "angle_evidence_fingerprint": current_evidence_fingerprint,
            "input_fingerprint": input_fingerprint,
            "implementation_path": implementation_path,
            "scope": scope,
            "advisory_outcome": outcome,
            "confidence": confidence,
            "evidence_ids": sorted(material["resolved_evidence"]),
            "source_urls": source_urls,
            "provider_signals": provider_signals,
            "technology_signals": technology_signals,
            **guidance,
            "limitations": [
                *invalid_reasons,
                "This advisory does not establish website ownership, edit authority, price, effort, or guaranteed feasibility.",
                "It is internal guidance and is not approval to contact, quote, access, or modify a customer system.",
            ],
            "internal_only": True,
            "forbidden_authority": [
                "approval", "outreach", "CRM", "lifecycle mutation", "site modification", "pricing",
            ],
            "evaluated_at": _now(),
        }
        if implementation_path not in IMPLEMENTATION_PATHS or scope not in SCOPES or outcome not in OUTCOMES:
            raise AssertionError("Implementation feasibility produced an unsupported classification")
        return {"implementation_feasibility": advisory}


def evaluate_with_orchestrator(
    store,
    identifier: str,
    records: Iterable[Dict[str, Any]],
    forms: Dict[str, Any],
    pages: Iterable[Dict[str, Any]],
    state_path: Path,
    audit_path: Path,
) -> Dict[str, Any] | None:
    """Evaluate one selected angle without appending pilot events or changing lifecycle state."""
    angle = store.selected_angle(identifier)
    if angle is None:
        return None
    prospect = store._prospect(identifier)
    record = next((value for value in records if value.get("domain") == prospect["organization_id"]), None)
    if record is None:
        raise ValueError("Current organization evidence is missing")
    state_path = Path(state_path)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        orchestrator = AgentOrchestrator(state_path, audit_path, [ImplementationFeasibilityAgent()])
        result = orchestrator.process({
            "domain": prospect["organization_id"],
            "record": record,
            "selected_angle": angle,
            "forms": forms,
            "pages": list(pages),
        })
        orchestrator.flush_audit()
    return result["implementation_feasibility"]
