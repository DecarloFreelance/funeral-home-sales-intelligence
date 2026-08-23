from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, Iterable, List


def _iso(now):
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _percent(count, total):
    return round(count / total * 100, 1) if total else 0.0


def _stale(fact, now):
    try:
        return datetime.fromisoformat(str(fact.get("stale_after")).replace("Z", "+00:00")) <= now
    except (TypeError, ValueError):
        return False


def build_metrics(results, review, state, audit, *, now=None, baseline=None):
    now = now or datetime.now(timezone.utc)
    results = list(results)
    review = list(review)
    audit = list(audit)
    organizations = len(results)
    field_entities = defaultdict(set)
    states = Counter()
    facts = []
    contact_fields = {
        "email": "contact.public_email",
        "phone": "contact.public_phone",
        "named_contact": "contact.person",
        "decision_maker_candidate": "contact.role_category",
    }
    for record in results:
        domain = str(record.get("domain") or "")
        for item in (record.get("enrichment") or {}).get("facts") or []:
            facts.append(item)
            field_entities[item.get("field")].add(domain)
            states[item.get("verification_state")] += 1

    fields = {
        field: {"organizations": len(domains), "percent": _percent(len(domains), organizations)}
        for field, domains in sorted(field_entities.items())
    }
    contact_coverage = {
        label: fields.get(field, {"organizations": 0, "percent": 0.0})
        for label, field in contact_fields.items()
    }
    finding_counts = Counter(
        finding.get("code") for item in review for finding in item.get("findings", [])
    )
    latest_run_id = audit[-1].get("run_id") if audit else None
    latest_events = [item for item in audit if item.get("run_id") == latest_run_id]
    latest_outcomes = Counter(item.get("outcome") for item in latest_events)
    tasks = state.get("tasks", {}) if isinstance(state, dict) else {}
    task_statuses = Counter(item.get("status") for item in tasks.values())
    crm_ready = sum((record.get("quality_control") or {}).get("crm_sync_safe") is True for record in results)
    outreach_ready = sum((record.get("quality_control") or {}).get("outreach_ready") is True for record in results)
    metrics = {
        "schema_version": 1,
        "generated_at": _iso(now),
        "organizations": organizations,
        "facts": len(facts),
        "facts_per_organization": round(len(facts) / organizations, 1) if organizations else 0.0,
        "field_count": len(fields),
        "field_coverage": fields,
        "contact_coverage": contact_coverage,
        "verification_states": dict(sorted(states.items())),
        "conflicted_facts": states.get("CONFLICTED", 0),
        "conflict_rate_percent": _percent(
            sum(bool((record.get("enrichment") or {}).get("conflicted_fields")) for record in results),
            organizations,
        ),
        "review_required": len(review),
        "review_rate_percent": _percent(len(review), organizations),
        "stale_facts": sum(_stale(item, now) for item in facts),
        "quality_findings": dict(sorted(finding_counts.items())),
        "unresolved_identity": sum(
            bool({"ORGANIZATION_WEBSITE_MISMATCH", "CONFLICTING_FACTS", "POSSIBLE_DUPLICATE_ORGANIZATION"}
                 & {finding.get("code") for finding in item.get("findings", [])})
            for item in review
        ),
        "crm_ready": crm_ready,
        "outreach_ready": outreach_ready,
        "agent_tasks": dict(sorted(task_statuses.items())),
        "latest_agent_run": {
            "run_id": latest_run_id,
            "outcomes": dict(sorted(latest_outcomes.items())),
            "events": len(latest_events),
        },
    }
    metrics["regressions"] = compare_metrics(baseline, metrics) if baseline else []
    fingerprint_value = {
        key: value for key, value in metrics.items()
        if key not in {"generated_at", "regressions", "snapshot_id", "latest_agent_run"}
    }
    fingerprint_value["latest_agent_outcomes"] = metrics["latest_agent_run"]["outcomes"]
    metrics["snapshot_id"] = hashlib.sha256(
        json.dumps(fingerprint_value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return metrics


def compare_metrics(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    if after["organizations"] < before.get("organizations", 0):
        findings.append({"code": "ORGANIZATION_COUNT_DROP", "before": before["organizations"], "after": after["organizations"]})
    old_facts = before.get("facts", 0)
    if old_facts and after["facts"] < old_facts * 0.9:
        findings.append({"code": "FACT_COUNT_DROP_GT_10_PERCENT", "before": old_facts, "after": after["facts"]})
    for field in ("email", "phone", "named_contact", "decision_maker_candidate"):
        old = (before.get("contact_coverage", {}).get(field) or {}).get("percent", 0)
        new = (after.get("contact_coverage", {}).get(field) or {}).get("percent", 0)
        if new < old - 10:
            findings.append({"code": "CONTACT_COVERAGE_DROP", "field": field, "before": old, "after": new})
    for field in ("conflict_rate_percent", "review_rate_percent"):
        old = before.get(field, 0)
        new = after.get(field, 0)
        if new > old + 10:
            findings.append({"code": "RATE_INCREASE_GT_10_POINTS", "field": field, "before": old, "after": new})
    failures = after.get("latest_agent_run", {}).get("outcomes", {}).get("FAILED", 0)
    if failures:
        findings.append({"code": "AGENT_FAILURES", "after": failures})
    return findings
