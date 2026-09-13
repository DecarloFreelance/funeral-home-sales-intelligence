#!/usr/bin/env python3
"""V26-native crawl-evidence extractor and per-record QC classifier.

Reads the crawl-queue, crawled-pages, and crawl-report artifacts already
produced by build_v26_crawl_queue.py / run_v26_crawl_pilot.py and turns them
into field-level facts with full provenance, plus a per-record VERIFIED /
REVIEW / UNRESOLVED classification. This is deliberately a NEW, V26-native
schema -- it does not adapt V26 records into the retired lineage's
business_profile/contact_intelligence shape.

Reuses existing repository conventions rather than inventing new ones:
- enrichment.evidence.fact()/CONFIDENCE_STATES for the fact schema and
  provenance fields (id, source_url, observed_at, stale_after, detector,
  detector_version, confidence, verification_state, evidence, derived).
- extraction.contact_extractor's existing JSON-LD traversal
  (_json_ld_nodes/_values/_format_address), conservative role/name
  extraction (_people_from_text, ROLE_PATTERN), and conservative
  EMAIL_PATTERN/PHONE_PATTERN text matching -- the same logic already used
  for the retired pipeline's contact extraction, applied here to V26
  evidence instead.

Does not modify data/portal_findings.json, operator_ui/repository.py,
export_portal_findings.py, the V26 queue builder, or discovery/crawler.py.
Writes only a new, separate artifact; never merges anything back into V26.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from enrichment.evidence import fact, iso, utc_now
from extraction.contact_extractor import (
    BUSINESS_TYPES,
    _format_address,
    _json_ld_nodes,
    _values,
    extract_contact_intelligence,
)

EXTRACTOR_VERSION = "1.0.0"
ARTIFACT_VERSION = "v26-extraction-v1"

DEFAULT_PAGES = Path("data/generated/enrichment/v26_crawl_batch50_pages.json")
DEFAULT_REPORT = Path("data/generated/enrichment/v26_crawl_batch50_pages_report.json")
DEFAULT_QUEUE = Path("data/generated/enrichment/v26_crawl_batch50_queue.json")
DEFAULT_OUTPUT = Path("data/generated/enrichment/v26_extraction_results.json")

DETECTOR_JSONLD = "jsonld_localbusiness"
DETECTOR_STATIC_TEXT = "static_text_pattern"
DETECTOR_ROLE_CONTEXT = "page_role_context"


class ExtractionError(ValueError):
    """The input artifacts do not have the expected shape."""


def _normalize_location_value(value: Any) -> str:
    """Deterministic, non-fuzzy normalization for city/province comparison:
    collapse whitespace and case-fold. No abbreviation/alias mapping -- an
    exact normalized match is required, by design, to avoid silently
    inferring branch attribution."""
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _page_observed_at(page: Dict[str, Any], default: datetime) -> datetime:
    value = (page.get("crawl") or {}).get("observedAt")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return default


def _sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _with_direct_or_derived(built_fact: Dict[str, Any], directory_record_id: str) -> Dict[str, Any]:
    return {
        **built_fact,
        "directory_record_id": directory_record_id,
        "direct_or_derived": "derived" if built_fact["derived"] else "direct",
    }


def extract_jsonld_business_facts(
    directory_record_id: str, domain: str, pages: List[Dict[str, Any]], observed_at: datetime,
) -> List[Dict[str, Any]]:
    """Detector 1: structured LocalBusiness/Organization JSON-LD.

    Highest confidence -- structured, schema.org-typed, authored by the
    site itself. Extracts email, telephone, address, and geo where present.
    """
    facts: List[Dict[str, Any]] = []
    for page in pages:
        page_url = str(page.get("url") or "")
        page_observed_at = _page_observed_at(page, observed_at)
        json_ld_values = (page.get("metadata") or {}).get("jsonLd") or []
        for node in _json_ld_nodes(json_ld_values):
            node_types = node.get("@type", [])
            if isinstance(node_types, str):
                node_types = [node_types]
            if not {str(item).lower() for item in node_types} & BUSINESS_TYPES:
                continue

            for value in _values(node.get("email")):
                value = value.lower()
                facts.append(_with_direct_or_derived(fact(
                    domain, "email", value, source="schema.org", source_url=page_url,
                    source_type="structured_data", observed_at=page_observed_at,
                    detector=DETECTOR_JSONLD, version=EXTRACTOR_VERSION, confidence=0.9,
                    verification_state="STRUCTURED_DIRECT",
                    evidence=f"JSON-LD {node.get('@type')} email: {value}", freshness_days=60,
                ), directory_record_id))

            for value in _values(node.get("telephone")):
                facts.append(_with_direct_or_derived(fact(
                    domain, "phone", value, source="schema.org", source_url=page_url,
                    source_type="structured_data", observed_at=page_observed_at,
                    detector=DETECTOR_JSONLD, version=EXTRACTOR_VERSION, confidence=0.9,
                    verification_state="STRUCTURED_DIRECT",
                    evidence=f"JSON-LD {node.get('@type')} telephone: {value}", freshness_days=60,
                ), directory_record_id))

            # Organization/LocalBusiness contact details are commonly nested
            # one level down in a ContactPoint (or list of them) rather than
            # on the parent node directly.
            contact_points = node.get("contactPoint")
            contact_points = contact_points if isinstance(contact_points, list) else [contact_points]
            for contact_point in contact_points:
                if not isinstance(contact_point, dict):
                    continue
                for value in _values(contact_point.get("email")):
                    value = value.lower()
                    facts.append(_with_direct_or_derived(fact(
                        domain, "email", value, source="schema.org", source_url=page_url,
                        source_type="structured_data", observed_at=page_observed_at,
                        detector=DETECTOR_JSONLD, version=EXTRACTOR_VERSION, confidence=0.9,
                        verification_state="STRUCTURED_DIRECT",
                        evidence=f"JSON-LD {node.get('@type')} contactPoint email: {value}", freshness_days=60,
                    ), directory_record_id))
                for value in _values(contact_point.get("telephone")):
                    facts.append(_with_direct_or_derived(fact(
                        domain, "phone", value, source="schema.org", source_url=page_url,
                        source_type="structured_data", observed_at=page_observed_at,
                        detector=DETECTOR_JSONLD, version=EXTRACTOR_VERSION, confidence=0.9,
                        verification_state="STRUCTURED_DIRECT",
                        evidence=f"JSON-LD {node.get('@type')} contactPoint telephone: {value}", freshness_days=60,
                    ), directory_record_id))

            address = _format_address(node.get("address"))
            if address:
                facts.append(_with_direct_or_derived(fact(
                    domain, "address", address, source="schema.org", source_url=page_url,
                    source_type="structured_data", observed_at=page_observed_at,
                    detector=DETECTOR_JSONLD, version=EXTRACTOR_VERSION, confidence=0.9,
                    verification_state="STRUCTURED_DIRECT",
                    evidence=f"JSON-LD {node.get('@type')} address: {address.get('formatted', '')}",
                    freshness_days=120,
                ), directory_record_id))

            geo = node.get("geo")
            if isinstance(geo, dict) and geo.get("latitude") and geo.get("longitude"):
                value = {"latitude": geo["latitude"], "longitude": geo["longitude"]}
                facts.append(_with_direct_or_derived(fact(
                    domain, "geo", value, source="schema.org", source_url=page_url,
                    source_type="structured_data", observed_at=page_observed_at,
                    detector=DETECTOR_JSONLD, version=EXTRACTOR_VERSION, confidence=0.85,
                    verification_state="STRUCTURED_DIRECT",
                    evidence=f"JSON-LD {node.get('@type')} geo: {value}", freshness_days=120,
                ), directory_record_id))
    return facts


def extract_breadcrumb_navigation(
    directory_record_id: str, pages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detector 2: BreadcrumbList JSON-LD as navigation evidence only.

    Never produces a business fact -- a breadcrumb entry proves that a URL
    exists in the site's declared navigation, not any fact about the
    business. Kept in a separate `navigation` list, not `facts`.
    """
    navigation: List[Dict[str, Any]] = []
    for page in pages:
        page_url = str(page.get("url") or "")
        json_ld_values = (page.get("metadata") or {}).get("jsonLd") or []
        for node in _json_ld_nodes(json_ld_values):
            node_types = node.get("@type", [])
            if isinstance(node_types, str):
                node_types = [node_types]
            if "breadcrumblist" not in {str(item).lower() for item in node_types}:
                continue
            for item in node.get("itemListElement") or []:
                if not isinstance(item, dict):
                    continue
                navigation.append({
                    "directory_record_id": directory_record_id,
                    "source_page": page_url,
                    "breadcrumb_url": item.get("item"),
                    "breadcrumb_label": item.get("name"),
                })
    return navigation


def extract_text_and_role_facts(
    directory_record_id: str, domain: str, pages: List[Dict[str, Any]], observed_at: datetime,
) -> List[Dict[str, Any]]:
    """Detectors 3 and 4: conservative static-text email/phone matching and
    same/adjacent-line role/name attribution. Reuses
    extraction.contact_extractor.extract_contact_intelligence's existing
    cleaning/validation pipeline (contact_cleaner, email/phone intelligence)
    rather than re-matching raw regex hits directly."""
    intelligence = extract_contact_intelligence(pages, domain=domain)
    facts: List[Dict[str, Any]] = []
    observed_by_url = {str(p.get("url") or ""): _page_observed_at(p, observed_at) for p in pages}

    for item in intelligence.get("email_sources") or []:
        if item.get("source_type") != "page_text":
            continue  # structured_data emails are handled by extract_jsonld_business_facts
        value = item["value"]
        source_url = item.get("source_url", "")
        facts.append(_with_direct_or_derived(fact(
            domain, "email", value, source="page_text", source_url=source_url,
            source_type="page_text", observed_at=observed_by_url.get(source_url, observed_at),
            detector=DETECTOR_STATIC_TEXT, version=EXTRACTOR_VERSION, confidence=0.6,
            verification_state="DISCOVERED",
            evidence=f"Email pattern matched in page text: {value}", freshness_days=60,
        ), directory_record_id))

    for item in intelligence.get("phone_sources") or []:
        if item.get("source_type") != "page_text":
            continue
        value = item["value"]
        source_url = item.get("source_url", "")
        facts.append(_with_direct_or_derived(fact(
            domain, "phone", value, source="page_text", source_url=source_url,
            source_type="page_text", observed_at=observed_by_url.get(source_url, observed_at),
            detector=DETECTOR_STATIC_TEXT, version=EXTRACTOR_VERSION, confidence=0.6,
            verification_state="DISCOVERED",
            evidence=f"Phone pattern matched in page text: {value}", freshness_days=60,
        ), directory_record_id))

    for person in intelligence.get("people") or []:
        source_url = person.get("source_url", "")
        value = {"name": person["name"], "title": person.get("title", "")}
        facts.append(_with_direct_or_derived(fact(
            domain, "person", value, source=person.get("source", "page_text"),
            source_url=source_url, source_type="website",
            observed_at=observed_by_url.get(source_url, observed_at),
            detector=DETECTOR_ROLE_CONTEXT, version=EXTRACTOR_VERSION, confidence=0.6,
            verification_state="DISCOVERED",
            evidence=f"{person['name']} — {person.get('title', '')} "
                     f"(same/adjacent-line role match)", freshness_days=60,
        ), directory_record_id))

    return facts


def classify_record(
    facts: List[Dict[str, Any]], crawl_status: str, shared_domain: bool,
    record_city: str, record_province: str,
) -> Dict[str, Any]:
    """Per-record QC. See module docstring for the rules; the short version:
    VERIFIED requires a structured JSON-LD fact, and -- only when the domain
    is shared by more than one V26 record -- an address fact whose city and
    province match this specific record. A shared domain with no address
    fact to check against can never reach VERIFIED, precisely to prevent
    generic corporate contact details from being silently propagated to
    every branch that happens to share a crawl."""
    if crawl_status != "SUCCESS":
        return {"status": "UNRESOLVED", "reasons": ["crawl_failed"]}
    if not facts:
        return {"status": "UNRESOLVED", "reasons": ["crawl_succeeded_zero_facts"]}

    structured = [f for f in facts if f["detector"] == DETECTOR_JSONLD]
    if not structured:
        only_detectors = sorted({f["detector"] for f in facts})
        return {"status": "REVIEW", "reasons": [f"no_structured_facts:{','.join(only_detectors)}"]}

    address_facts = [f for f in structured if f["field"] == "address"]
    if not shared_domain:
        if address_facts:
            match = any(
                _normalize_location_value(a["value"].get("city")) == _normalize_location_value(record_city)
                and _normalize_location_value(a["value"].get("province")) == _normalize_location_value(record_province)
                for a in address_facts
            )
            if not match:
                return {"status": "REVIEW", "reasons": ["address_city_province_mismatch"]}
        return {"status": "VERIFIED", "reasons": ["structured_fact_unique_domain"]}

    # Shared/corporate domain: address match is mandatory, not optional.
    if not address_facts:
        return {"status": "REVIEW", "reasons": ["shared_domain_no_address_to_attribute"]}
    match = any(
        _normalize_location_value(a["value"].get("city")) == _normalize_location_value(record_city)
        and _normalize_location_value(a["value"].get("province")) == _normalize_location_value(record_province)
        for a in address_facts
    )
    if not match:
        return {"status": "REVIEW", "reasons": ["shared_domain_address_mismatch"]}
    return {"status": "VERIFIED", "reasons": ["structured_fact_matches_branch_address"]}


def build_enrichment(
    pages_path: Path, report_path: Path, queue_path: Path, observed_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    observed_at = observed_at or utc_now()

    if not pages_path.is_file():
        raise ExtractionError(f"Pages artifact not found: {pages_path}")
    if not report_path.is_file():
        raise ExtractionError(f"Report artifact not found: {report_path}")
    if not queue_path.is_file():
        raise ExtractionError(f"Queue artifact not found: {queue_path}")

    try:
        pages = json.loads(pages_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Input artifact is not valid JSON: {exc}") from exc

    if not isinstance(pages, list) or not isinstance(queue, list) or not isinstance(report, dict):
        raise ExtractionError("Unexpected shape: pages/queue must be lists, report must be an object")

    pages_by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for page in pages:
        pages_by_domain.setdefault(page.get("domain", ""), []).append(page)

    domain_counts = Counter(row.get("domain", "") for row in queue)
    queue_by_id = {row["directory_record_id"]: row for row in queue if row.get("directory_record_id")}

    records_out = []
    for lead_report in report.get("leads") or []:
        queue_entry = lead_report.get("queue_entry") or {}
        directory_record_id = queue_entry.get("directory_record_id")
        if not directory_record_id:
            continue  # not a V26-shaped queue entry; nothing to attribute facts to
        domain = lead_report.get("domain", "")
        domain_pages = pages_by_domain.get(domain, [])
        source_row = queue_by_id.get(directory_record_id, queue_entry)
        record_city = source_row.get("city", "")
        record_province = source_row.get("province", "")
        shared_domain = domain_counts.get(domain, 0) > 1

        jsonld_facts = extract_jsonld_business_facts(directory_record_id, domain, domain_pages, observed_at)
        text_role_facts = extract_text_and_role_facts(directory_record_id, domain, domain_pages, observed_at)
        navigation = extract_breadcrumb_navigation(directory_record_id, domain_pages)
        record_facts = jsonld_facts + text_role_facts

        qc = classify_record(record_facts, lead_report.get("status", "FAILED"), shared_domain, record_city, record_province)

        records_out.append({
            "directory_record_id": directory_record_id,
            "domain": domain,
            "city": record_city,
            "province": record_province,
            "qc_status": qc["status"],
            "qc_reasons": qc["reasons"],
            "crawl_linkage": {
                "crawl_status": lead_report.get("status", "FAILED"),
                "reused_crawl": bool(lead_report.get("reused_crawl", False)),
                "shared_domain": shared_domain,
                "pages_available": len(domain_pages),
            },
            "facts": record_facts,
            "navigation": navigation,
        })

    records_out.sort(key=lambda r: r["directory_record_id"])

    status_counts = Counter(r["qc_status"] for r in records_out)
    detector_counts = Counter(f["detector"] for r in records_out for f in r["facts"])

    return {
        "version": ARTIFACT_VERSION,
        "generated_at": iso(observed_at),
        "extractor_version": EXTRACTOR_VERSION,
        "input": {
            "pages_artifact": str(pages_path),
            "pages_sha256": _sha256(pages_path),
            "report_artifact": str(report_path),
            "report_sha256": _sha256(report_path),
            "queue_artifact": str(queue_path),
            "queue_sha256": _sha256(queue_path),
        },
        "records": records_out,
        "summary": {
            "records_total": len(records_out),
            "verified": status_counts.get("VERIFIED", 0),
            "review": status_counts.get("REVIEW", 0),
            "unresolved": status_counts.get("UNRESOLVED", 0),
            "facts_total": sum(len(r["facts"]) for r in records_out),
            "facts_by_detector": dict(sorted(detector_counts.items())),
            "navigation_total": sum(len(r["navigation"]) for r in records_out),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        result = build_enrichment(args.pages, args.report, args.queue)
    except ExtractionError as exc:
        print(f"REFUSED: {exc}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
