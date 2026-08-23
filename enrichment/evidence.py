from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Dict, Iterable, List


CONFIDENCE_STATES = {
    "DISCOVERED",
    "EXTRACTED",
    "INFERRED",
    "CORROBORATED",
    "LOCALLY_VALIDATED",
    "LOCAL_VALID",
    "DNS_VALID",
    "METADATA_VALIDATED",
    "EXTERNALLY_VERIFIED",
    "CONFLICTED",
    "NOT_CHECKED",
}
SINGLE_VALUE_FIELDS = {
    "organization.canonical_domain",
    "organization.canonical_name",
    "organization.legal_name",
    "organization.founding_year",
    "organization.parent_organization",
    "organization.website",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_fact_id(entity_id: str, field: str, value: Any, source_url: str, detector: str, version: str) -> str:
    material = json.dumps(
        [entity_id, field, value, source_url, detector, version],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def fact(
    entity_id: str,
    field: str,
    value: Any,
    *,
    source: str,
    source_url: str,
    source_type: str,
    observed_at: datetime,
    detector: str,
    version: str,
    confidence: float,
    verification_state: str,
    evidence: str,
    derived: bool = False,
    freshness_days: int = 180,
) -> Dict[str, Any]:
    if verification_state not in CONFIDENCE_STATES:
        raise ValueError(f"Unsupported verification state: {verification_state}")
    confidence = round(max(0.0, min(float(confidence), 1.0)), 2)
    return {
        "id": stable_fact_id(entity_id, field, value, source_url, detector, version),
        "field": field,
        "value": value,
        "source": source,
        "source_url": source_url,
        "source_type": source_type,
        "observed_at": iso(observed_at),
        "stale_after": iso(observed_at + timedelta(days=freshness_days)),
        "detector": detector,
        "detector_version": version,
        "confidence": confidence,
        "verification_state": verification_state,
        "evidence": evidence[:500],
        "derived": bool(derived),
    }


def reconcile_facts(facts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate observations, mark corroboration, and preserve conflicts."""
    unique = {item["id"]: dict(item) for item in facts}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in unique.values():
        grouped.setdefault(item["field"], []).append(item)

    for items in grouped.values():
        values: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            key = json.dumps(item["value"], sort_keys=True, ensure_ascii=False)
            values.setdefault(key, []).append(item)
        if len(values) > 1 and items[0]["field"] in SINGLE_VALUE_FIELDS:
            for item in items:
                item["verification_state"] = "CONFLICTED"
            continue
        sources = {item["source_url"] for item in items if item["source_url"]}
        if len(sources) >= 2:
            for item in items:
                if not item["derived"] and item["verification_state"] in {"DISCOVERED", "EXTRACTED"}:
                    item["verification_state"] = "CORROBORATED"
                    item["confidence"] = max(item["confidence"], 0.85)
    return sorted(unique.values(), key=lambda item: (item["field"], item["id"]))
