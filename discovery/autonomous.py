"""Bounded, evidence-preserving autonomous discovery primitives.

Search results are candidates, never canonical facts.  This module deliberately
contains no outreach/CRM imports and publishes only through ``DiscoveryStore``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Protocol
from urllib.parse import urlsplit

from automation.orchestrator import AgentOrchestrator
from discovery.ingestion import domain_from_website, normalize_website


VERSION = "national_discovery/1.0.0"
TERMINAL_QUERY = {"COMPLETED", "EXHAUSTED"}
LIFECYCLE = {
    "DISCOVERED", "IDENTITY_PENDING", "VERIFIED", "CANONICALIZED",
    "ENRICHMENT_READY", "PUBLISHED", "QUARANTINED", "REJECTED",
    "DUPLICATE", "STALE", "RETRYABLE_FAILURE",
}
REVIEW_REASONS = {
    "SHARED_DOMAIN_AMBIGUITY", "PARENT_LOCATION_AMBIGUITY",
    "CONFLICTING_ADDRESS", "CONFLICTING_ORGANIZATION_NAME",
    "REDIRECT_IDENTITY_AMBIGUITY", "SOURCE_FIRST_PARTY_CONFLICT",
    "POSSIBLE_DUPLICATE", "WEAK_FUNERAL_RELEVANCE",
    "CANADIAN_LOCATION_MISMATCH",
}
PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut",
    "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}
TERMS = ("funeral home", "funeral service", "funeral chapel", "cremation services")
FRENCH_TERMS = ("salon funéraire", "services funéraires", "maison funéraire", "services de crémation")
FUNERAL_RE = re.compile(r"\b(funeral|mortuary|cremation|funéraire|funeraire|crémation|cremation)\b", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_id(*values: Any) -> str:
    raw = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def normalized_query(value: str) -> str:
    return " ".join(str(value).casefold().split())


def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-zà-ÿ0-9]+", str(value).casefold()) if len(x) > 2 and x not in {"the", "and", "home", "funeral", "services", "service"}}


@dataclass
class DiscoveryCandidate:
    discovered_name: str
    discovered_url: str = ""
    discovered_phone: str = ""
    discovered_email: str = ""
    address: str = ""
    municipality: str = ""
    province: str = ""
    postal_code: str = ""
    source_type: str = "search"
    source_url: str = ""
    source_identity: str = ""
    search_query: str = ""
    search_provider: str = ""
    raw_source_value: Any = None
    discovered_at: str = field(default_factory=utc_now)
    detector_version: str = VERSION
    stale_after: str = ""
    candidate_id: str = field(init=False)
    normalized_url_candidate: str = field(init=False)
    status: str = "DISCOVERED"
    first_party_verification_status: str = "NOT_CHECKED"
    organization_name_match_evidence: List[Dict[str, Any]] = field(default_factory=list)
    geographic_match_evidence: List[Dict[str, Any]] = field(default_factory=list)
    funeral_service_relevance_evidence: List[Dict[str, Any]] = field(default_factory=list)
    redirect_chain: List[str] = field(default_factory=list)
    canonical_organization_candidate: str = ""
    canonical_domain_candidate: str = ""
    confidence: float = 0.0
    rejection_reasons: List[str] = field(default_factory=list)
    quarantine_reasons: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.province = self.province.strip().upper()
        self.normalized_url_candidate = normalize_website(self.discovered_url)
        raw_identity = self.normalized_url_candidate or "|".join([
            self.discovered_name.casefold().strip(), self.address.casefold().strip(),
            self.municipality.casefold().strip(), self.province,
        ])
        self.candidate_id = stable_id("candidate", self.source_type, self.source_identity or self.source_url, raw_identity)
        if not self.stale_after:
            self.stale_after = (datetime.now(timezone.utc) + timedelta(days=90)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if self.discovered_url and not self.normalized_url_candidate:
            self.status = "REJECTED"
            self.first_party_verification_status = "INVALID_URL"
            self.rejection_reasons = ["MALFORMED_WEBSITE"]

    @classmethod
    def from_mapping(cls, value: Dict[str, Any], **context: Any) -> "DiscoveryCandidate":
        return cls(
            discovered_name=str(value.get("company") or value.get("name") or value.get("title") or ""),
            discovered_url=str(value.get("website") or value.get("business_website") or ""),
            discovered_phone=str(value.get("phone") or ""), discovered_email=str(value.get("email") or ""),
            address=str(value.get("address") or ""), municipality=str(value.get("city") or value.get("municipality") or ""),
            province=str(value.get("province") or value.get("region") or ""), postal_code=str(value.get("postal_code") or ""),
            source_type=str(context.get("source_type") or value.get("source") or "search"),
            source_url=str(value.get("source_url") or context.get("source_url") or ""),
            source_identity=str(value.get("source_identity") or context.get("source_identity") or ""),
            search_query=str(context.get("query") or value.get("search_query") or ""),
            search_provider=str(context.get("provider") or value.get("search_provider") or ""),
            raw_source_value=value,
        )


@dataclass(frozen=True)
class PlannedQuery:
    query: str
    strategy: str
    geography: str
    provider: str
    fingerprint: str


class SearchProvider(Protocol):
    name: str
    def search(self, query: str, *, cursor: str = "", limit: int = 20) -> Dict[str, Any]: ...


class QueryPlanner:
    """Deterministic bounded planner based on observed coverage gaps."""
    def __init__(self, provider: str, *, terms: Iterable[str] = TERMS):
        self.provider = provider
        self.terms = tuple(terms)

    def plan(self, organizations: Iterable[Dict[str, Any]], ledger: Dict[str, Any], *, limit: int = 100, now: str | None = None) -> List[PlannedQuery]:
        coverage = {code: 0 for code in PROVINCES}
        municipalities: Dict[str, set[str]] = {code: set() for code in PROVINCES}
        for org in organizations:
            for loc in org.get("locations") or [{}]:
                province = str(loc.get("province") or org.get("province") or "").upper()
                city = str(loc.get("city") or loc.get("municipality") or org.get("city") or "").strip()
                if province in coverage:
                    coverage[province] += 1
                    if city:
                        municipalities[province].add(city)
        candidates = []
        # Known municipalities first within the weakest regions. Territory-wide
        # queries cover absent regions without inventing a municipality dataset.
        for code in sorted(PROVINCES, key=lambda x: (coverage[x], x)):
            places = sorted(municipalities[code]) or [""]
            language_terms = (*self.terms, *(FRENCH_TERMS if code == "QC" else ()))
            for place in places:
                for term in language_terms:
                    query = " ".join(x for x in (f'"{term}"', place, PROVINCES[code], "Canada") if x)
                    fingerprint = stable_id("query", normalized_query(query), "GEOGRAPHIC", code, self.provider)
                    candidates.append(PlannedQuery(query, "SEARCH_GAP" if coverage[code] else "GEOGRAPHIC", code, self.provider, fingerprint))
        eligible = []
        current = datetime.fromisoformat((now or utc_now()).replace("Z", "+00:00"))
        for query in candidates:
            previous = ledger.get(query.fingerprint)
            if previous and previous.get("status") in TERMINAL_QUERY:
                expiry = previous.get("stale_after")
                try:
                    if datetime.fromisoformat(str(expiry).replace("Z", "+00:00")) > current:
                        continue
                except (TypeError, ValueError):
                    continue
            eligible.append(query)
            if len(eligible) >= limit:
                break
        return eligible


class DiscoveryStore:
    schema_version = 1
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self):
        if not self.path.is_file():
            return {"schema_version": 1, "candidates": {}, "query_ledger": {}, "organizations": {}, "runs": [], "review_queue": {}, "enrichment_queue": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1:
            raise ValueError("Unsupported discovery store schema")
        value.setdefault("enrichment_queue", {})
        return value

    def save(self):
        AgentOrchestrator._atomic_json(self.path, self.data)

    def seed(self, organizations: Iterable[Dict[str, Any]]):
        for item in organizations:
            domain = str(item.get("domain") or "").lower()
            if domain:
                self.data["organizations"].setdefault(domain, {**item, "organization_id": domain, "discovery_status": "PUBLISHED", "seeded": True})

    def upsert_candidate(self, candidate: DiscoveryCandidate) -> bool:
        existing = self.data["candidates"].get(candidate.candidate_id)
        if existing:
            # Preserve earliest raw evidence; append independent observations.
            observations = existing.setdefault("observations", [])
            observation = {"source_type": candidate.source_type, "source_url": candidate.source_url, "search_query": candidate.search_query, "provider": candidate.search_provider, "observed_at": candidate.discovered_at}
            if observation not in observations:
                observations.append(observation)
            return False
        value = asdict(candidate)
        value["observations"] = [{"source_type": candidate.source_type, "source_url": candidate.source_url, "search_query": candidate.search_query, "provider": candidate.search_provider, "observed_at": candidate.discovered_at}]
        self.data["candidates"][candidate.candidate_id] = value
        return True

    def publish(self, candidate: Dict[str, Any]) -> str:
        if candidate.get("status") != "ENRICHMENT_READY" or candidate.get("confidence", 0) < .85:
            raise ValueError("Candidate is not eligible for publication")
        domain = candidate["canonical_domain_candidate"]
        if domain in self.data["organizations"]:
            candidate["status"] = "DUPLICATE"
            return "DUPLICATE"
        organization_id = stable_id("organization", domain, candidate.get("discovered_name"))
        self.data["organizations"][domain] = {
            "organization_id": organization_id, "domain": domain,
            "company": candidate.get("discovered_name"),
            "website": candidate.get("normalized_url_candidate"),
            "locations": [{"address": candidate.get("address"), "city": candidate.get("municipality"), "province": candidate.get("province"), "postal_code": candidate.get("postal_code")}],
            "discovery_status": "PUBLISHED", "confidence": candidate.get("confidence"),
            "candidate_id": candidate.get("candidate_id"), "provenance": candidate.get("observations", []),
            "canonicalized_at": utc_now(), "detector_version": VERSION,
        }
        self.data["enrichment_queue"][organization_id] = {
            "organization_id": organization_id, "domain": domain,
            "status": "PENDING", "candidate_id": candidate.get("candidate_id"),
            "enqueued_at": utc_now(),
        }
        candidate["canonical_organization_candidate"] = organization_id
        candidate["status"] = "PUBLISHED"
        return "PUBLISHED"


def verify_candidate(candidate: Dict[str, Any], evidence: Dict[str, Any], known: Dict[str, Any]) -> Dict[str, Any]:
    """Apply deterministic identity evidence from a safe bounded fetch."""
    if candidate.get("status") == "REJECTED":
        return candidate
    final_url = normalize_website(str(evidence.get("final_url") or ""))
    if not final_url or not evidence.get("reachable"):
        candidate.update(status="RETRYABLE_FAILURE" if evidence.get("retryable") else "REJECTED", first_party_verification_status="UNREACHABLE")
        candidate.setdefault("rejection_reasons", []).append("WEBSITE_UNREACHABLE")
        return candidate
    domain = domain_from_website(final_url)
    original = domain_from_website(candidate.get("normalized_url_candidate", ""))
    candidate["redirect_chain"] = list(evidence.get("redirect_chain") or [candidate.get("normalized_url_candidate"), final_url])
    candidate["canonical_domain_candidate"] = domain
    text = " ".join(str(evidence.get(x) or "") for x in ("title", "text", "structured_data"))
    name_score = len(_tokens(candidate.get("discovered_name", "")) & _tokens(text)) / max(1, len(_tokens(candidate.get("discovered_name", ""))))
    geography_values = [candidate.get("municipality", ""), candidate.get("province", ""), candidate.get("address", ""), candidate.get("postal_code", "")]
    geo_matches = [x for x in geography_values if x and str(x).casefold() in text.casefold()]
    funeral = bool(FUNERAL_RE.search(text))
    candidate["organization_name_match_evidence"] = [{"source_url": final_url, "score": round(name_score, 3), "direct": True}]
    candidate["geographic_match_evidence"] = [{"source_url": final_url, "matched": geo_matches, "direct": True}] if geo_matches else []
    candidate["funeral_service_relevance_evidence"] = [{"source_url": final_url, "matched": True, "direct": True}] if funeral else []
    reasons = []
    if original != domain:
        reasons.append("REDIRECT_IDENTITY_AMBIGUITY")
    if evidence.get("country_mismatch"):
        reasons.append("CANADIAN_LOCATION_MISMATCH")
    if evidence.get("parent_location_ambiguous"):
        reasons.append("PARENT_LOCATION_AMBIGUITY")
    if domain in known and known[domain].get("company", "").casefold() != candidate.get("discovered_name", "").casefold():
        # Same domains can legitimately contain locations; preserve and review
        # rather than creating a second organization or silently merging.
        reasons.append("SHARED_DOMAIN_AMBIGUITY")
    confidence = .35 * min(1, name_score) + .25 * bool(geo_matches) + .25 * funeral + .15 * bool(evidence.get("identity_marker"))
    candidate["confidence"] = round(confidence, 3)
    if reasons:
        candidate.update(status="QUARANTINED", quarantine_reasons=sorted(set(reasons)), first_party_verification_status="AMBIGUOUS")
    elif name_score >= .6 and geo_matches and funeral and evidence.get("identity_marker"):
        candidate.update(status="ENRICHMENT_READY", first_party_verification_status="VERIFIED_FIRST_PARTY")
    elif not funeral:
        candidate.update(status="REJECTED", rejection_reasons=["GENERIC_OR_NON_FUNERAL_SITE"], first_party_verification_status="NOT_FIRST_PARTY")
    else:
        candidate.update(status="QUARANTINED", quarantine_reasons=["CONFLICTING_ORGANIZATION_NAME" if name_score < .6 else "SOURCE_FIRST_PARTY_CONFLICT"], first_party_verification_status="AMBIGUOUS")
    return candidate


@dataclass
class DiscoveryBudget:
    max_queries: int = 100
    max_candidates: int = 500
    max_verification_fetches: int = 100
    max_pages_per_candidate: int = 4
    concurrency: int = 1
    per_host_delay: float = .25
    retry_limit: int = 2
    timeout: float = 15
    max_runtime_seconds: int = 1800
    checkpoint_interval: int = 1
    saturation_batches: int = 3
    saturation_min_queries: int = 5
    saturation_max_novel_per_query: float = .02


class NationalDiscoveryCoordinator:
    def __init__(self, store: DiscoveryStore, provider: SearchProvider, verifier: Callable[[Dict[str, Any]], Dict[str, Any]], budget: DiscoveryBudget):
        self.store, self.provider, self.verifier, self.budget = store, provider, verifier, budget

    def run(self, plan: Iterable[PlannedQuery], *, dry_run=False) -> Dict[str, Any]:
        started = datetime.now(timezone.utc); metrics = {"queries_attempted": 0, "search_results": 0, "candidates_discovered": 0, "known_duplicates": 0, "candidate_websites_verified": 0, "organizations_newly_published": 0, "records_enriched": 0, "quarantined": 0, "rejected": 0, "retryable_failures": 0, "providers_used": [], "budget_consumed": 0}
        for planned in list(plan)[:self.budget.max_queries]:
            if (datetime.now(timezone.utc)-started).total_seconds() >= self.budget.max_runtime_seconds or metrics["candidates_discovered"] >= self.budget.max_candidates:
                break
            try:
                result = self.provider.search(planned.query, limit=min(20, self.budget.max_candidates-metrics["candidates_discovered"]))
            except Exception as error:
                self.store.data["query_ledger"][planned.fingerprint] = {"query": planned.query, "normalized_query": normalized_query(planned.query), "strategy": planned.strategy, "geography": planned.geography, "provider": planned.provider, "executed_at": utc_now(), "status": "RETRYABLE_FAILURE", "retry_state": {"error_class": type(error).__name__, "attempts": 1}, "query_fingerprint": planned.fingerprint}
                if not dry_run: self.store.save()
                continue
            metrics["queries_attempted"] += 1; metrics["budget_consumed"] += int(result.get("cost", 1)); metrics["providers_used"] = sorted(set([*metrics["providers_used"], planned.provider]))
            rows = list(result.get("results") or []); metrics["search_results"] += len(rows); novel = dup = rejected = verified = published = 0
            for row in rows:
                candidate = DiscoveryCandidate.from_mapping(row, query=planned.query, provider=planned.provider, source_type="search", source_identity=str(row.get("source_identity") or row.get("source_url") or ""))
                if candidate.canonical_domain_candidate in self.store.data["organizations"]: dup += 1
                is_novel = candidate.candidate_id not in self.store.data["candidates"]
                if not dry_run: self.store.upsert_candidate(candidate)
                novel += int(is_novel); metrics["candidates_discovered"] += int(is_novel)
                current = asdict(candidate) if dry_run else self.store.data["candidates"][candidate.candidate_id]
                domain = domain_from_website(current.get("normalized_url_candidate", ""))
                if domain in self.store.data["organizations"]:
                    current["status"] = "DUPLICATE"; dup += 1; continue
                if current.get("status") == "REJECTED": rejected += 1; continue
                if verified >= self.budget.max_verification_fetches: break
                verified += 1
                verify_candidate(current, self.verifier(current), self.store.data["organizations"])
                if current["status"] == "ENRICHMENT_READY":
                    if not dry_run and self.store.publish(current) == "PUBLISHED": published += 1
                elif current["status"] == "QUARANTINED":
                    self.store.data["review_queue"][current["candidate_id"]] = {"candidate_id": current["candidate_id"], "reasons": current["quarantine_reasons"], "evidence": {k: current.get(k) for k in ("organization_name_match_evidence", "geographic_match_evidence", "funeral_service_relevance_evidence", "redirect_chain", "observations")}}
                elif current["status"] == "REJECTED": rejected += 1
                if current["status"] == "QUARANTINED": metrics["quarantined"] += 1
                elif current["status"] == "RETRYABLE_FAILURE": metrics["retryable_failures"] += 1
            ledger = {"query": planned.query, "normalized_query": normalized_query(planned.query), "strategy": planned.strategy, "geography": planned.geography, "provider": planned.provider, "executed_at": utc_now(), "result_count": len(rows), "candidate_count": len(rows), "novel_candidate_count": novel, "novel_verified_organization_count": published, "duplicate_count": dup, "rejected_count": rejected, "next_cursor": result.get("next_cursor", ""), "provider_status": result.get("status", "OK"), "retry_state": {}, "query_fingerprint": planned.fingerprint, "status": "COMPLETED", "stale_after": (datetime.now(timezone.utc)+timedelta(days=30)).replace(microsecond=0).isoformat().replace("+00:00", "Z")}
            if not dry_run:
                self.store.data["query_ledger"][planned.fingerprint] = ledger; self.store.save()
            metrics["known_duplicates"] += dup; metrics["candidate_websites_verified"] += verified; metrics["organizations_newly_published"] += published; metrics["rejected"] += rejected
        metrics["elapsed_seconds"] = round((datetime.now(timezone.utc)-started).total_seconds(), 3)
        metrics["new_organizations_per_query"] = round(metrics["organizations_newly_published"]/max(1,metrics["queries_attempted"]), 4)
        metrics["duplicate_rate"] = round(metrics["known_duplicates"]/max(1,metrics["search_results"]), 4)
        metrics["dry_run"] = dry_run; metrics["run_status"] = "PLANNED_ONLY" if dry_run else "CHECKPOINTED"
        if not dry_run:
            self.store.data["runs"].append({"run_id": stable_id("run", utc_now(), metrics), "completed_at": utc_now(), **metrics}); self.store.save()
        return metrics


def saturation_status(ledger: Dict[str, Any], budget: DiscoveryBudget) -> Dict[str, Any]:
    completed = sorted((x for x in ledger.values() if x.get("status") == "COMPLETED"), key=lambda x: x.get("executed_at", ""))
    recent = completed[-budget.saturation_batches * budget.saturation_min_queries:]
    by_segment: Dict[str, list] = {}
    for item in recent: by_segment.setdefault(f"{item.get('strategy')}:{item.get('geography')}", []).append(item)
    segments = {}
    for key, rows in by_segment.items():
        q = len(rows); novel = sum(x.get("novel_verified_organization_count", 0) for x in rows)
        rate = novel/max(1,q); segments[key] = {"queries":q,"novel_verified_organizations":novel,"novel_per_query":round(rate,4),"status":"DISCOVERY_SATURATED_UNDER_CURRENT_STRATEGIES" if q >= budget.saturation_min_queries and rate <= budget.saturation_max_novel_per_query else "ACTIVE"}
    return {"national_completeness_claimed": False, "segments": segments}


def coverage_report(organizations: Iterable[Dict[str, Any]], candidates: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    organizations = list(organizations); locations=[]
    for org in organizations:
        locations.extend(org.get("locations") or [{"city":org.get("city", ""),"province":org.get("province","")}])
    by_province={code:{"organizations":0,"locations":0,"municipalities":set()} for code in PROVINCES}
    for org in organizations:
        provinces={str(x.get("province") or org.get("province") or "").upper() for x in (org.get("locations") or [{}])}
        for p in provinces:
            if p in by_province: by_province[p]["organizations"] += 1
    for loc in locations:
        p=str(loc.get("province") or "").upper(); city=str(loc.get("city") or loc.get("municipality") or "").strip()
        if p in by_province: by_province[p]["locations"] += 1; city and by_province[p]["municipalities"].add(city)
    for value in by_province.values(): value["municipalities"] = len(value["municipalities"])
    candidates=list(candidates)
    return {"canonical_organizations":len(organizations),"canonical_domains":len({x.get('domain') for x in organizations if x.get('domain')}),"locations":len(locations),"provinces_territories_represented":sum(v['locations']>0 for v in by_province.values()),"by_province_territory":by_province,"backlog":{"candidates_pending_verification":sum(x.get('status') in {'DISCOVERED','IDENTITY_PENDING','RETRYABLE_FAILURE','STALE'} for x in candidates),"quarantine_count":sum(x.get('status')=='QUARANTINED' for x in candidates),"retry_count":sum(x.get('status')=='RETRYABLE_FAILURE' for x in candidates),"stale_revalidation_count":sum(x.get('status')=='STALE' for x in candidates)}}
