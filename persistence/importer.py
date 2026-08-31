from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from persistence.postgres import PsqlRunner


DEFAULT_DIRECTORY = Path(
    "data/generated/directory_955/full_955_enrichment_v13/full_955_enrichment.json"
)
DEFAULT_CRM = Path("data/crm.sqlite")
SOURCE_SYSTEM = "canada_funeral_directory_955"
NULL = "__FHSI_NULL__"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, *parts: Any) -> str:
    material = "\x1f".join(_json(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(material.encode()).hexdigest()}"


def _evidence(item: dict[str, Any]) -> tuple[str, list[str]]:
    values = [
        str(item.get("source_url") or ""), str(item.get("source_file") or ""),
        str(item.get("source_text_sha256") or ""), str(item.get("source_html_sha256") or ""),
        str(item.get("evidence_class") or ""),
        str(item.get("evidence_line") or item.get("evidence_marker") or ""),
    ]
    evidence_id = _stable_id("ev", *values)
    known = {
        "source_url", "source_file", "source_text_sha256", "source_html_sha256",
        "evidence_class", "evidence_line", "evidence_marker",
    }
    metadata = {key: value for key, value in item.items() if key not in known}
    return evidence_id, [evidence_id, *values, _json(metadata)]


@dataclass
class ImportBundle:
    organizations: list[list[Any]]
    source_records: list[list[Any]]
    websites: list[list[Any]]
    evidence: list[list[Any]]
    contacts: list[list[Any]]
    people: list[list[Any]]
    crm_leads: list[list[Any]]

    def counts(self) -> dict[str, int]:
        return {
            "organizations": len(self.organizations),
            "source_records": len(self.source_records),
            "evidence_sources": len(self.evidence),
            "contacts": len(self.contacts),
            "people": len(self.people),
            "crm_lead_snapshots": len(self.crm_leads),
        }


def build_bundle(directory_path: Path = DEFAULT_DIRECTORY, crm_path: Path = DEFAULT_CRM) -> ImportBundle:
    records = json.loads(directory_path.read_text(encoding="utf-8"))
    if len(records) != 955:
        raise ValueError(f"Expected 955 canonical directory records, found {len(records)}")
    ids = [str(row.get("directory_record_id") or "") for row in records]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("Canonical directory IDs must be non-empty and unique")

    organizations, source_records, websites, contacts, people = [], [], [], [], []
    evidence_by_id: dict[str, list[str]] = {}
    domains: dict[str, set[str]] = {}
    for row in records:
        organization_id = row["directory_record_id"]
        organizations.append([
            organization_id, row.get("company") or "", row.get("city") or "",
            row.get("province") or "", "Canada", row.get("record_type") or "",
            row.get("directory_index") if row.get("directory_index") is not None else NULL,
            row.get("website_status") or "", row.get("founded_year") or "",
            row.get("ownership_type") or "", row.get("parent_organization") or "",
            row.get("service_area") or "", row.get("service_offering") or "",
            row.get("languages_offered") or "", SOURCE_SYSTEM,
        ])
        payload = _json(row)
        source_records.append([
            SOURCE_SYSTEM, organization_id, organization_id, row.get("source") or "",
            payload, hashlib.sha256(payload.encode()).hexdigest(),
        ])
        website = str(row.get("website") or "").strip()
        if website:
            domain = (urlsplit(website if "://" in website else f"https://{website}").hostname or "").lower()
            website_id = _stable_id("web", organization_id, website)
            websites.append([
                website_id, organization_id, website, domain, row.get("website_status") or "",
                "false", SOURCE_SYSTEM,
            ])
            if domain:
                domains.setdefault(domain.removeprefix("www."), set()).add(organization_id)

        enrichment = row.get("branch_safe_enrichment") or {}
        for kind in ("email", "phone"):
            for item in enrichment.get(f"{kind}s") or []:
                evidence_id, evidence_row = _evidence(item)
                evidence_by_id[evidence_id] = evidence_row
                value = str(item.get("value") or "").strip()
                contact_id = _stable_id("contact", organization_id, kind, value, evidence_id)
                contacts.append([
                    contact_id, organization_id, kind, value, "BRANCH_SAFE", evidence_id, _json(item),
                ])
        decision_keys = {
            (str(item.get("name") or "").strip(), str(item.get("title") or "").strip(),
             str(item.get("source_url") or "").strip())
            for item in enrichment.get("decision_makers") or []
        }
        for item in enrichment.get("staff") or []:
            evidence_id, evidence_row = _evidence(item)
            evidence_by_id[evidence_id] = evidence_row
            name, title = str(item.get("name") or "").strip(), str(item.get("title") or "").strip()
            if not name:
                raise ValueError(f"Staff record without a name for {organization_id}")
            is_dm = bool(item.get("decision_maker")) or (
                name, title, str(item.get("source_url") or "").strip()
            ) in decision_keys
            person_id = _stable_id("person", organization_id, name, title, evidence_id)
            people.append([
                person_id, organization_id, name, title, str(is_dm).lower(), evidence_id, _json(item),
            ])

    if len({row[0] for row in contacts}) != len(contacts):
        raise ValueError("Deterministic contact IDs collided")
    if len({row[0] for row in people}) != len(people):
        raise ValueError("Deterministic person IDs collided")

    crm_leads = []
    connection = sqlite3.connect(f"file:{crm_path.resolve()}?mode=ro", uri=True)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(leads)")]
        expected = [
            "domain", "company_name", "pipeline_stage", "crm_status", "priority_score",
            "priority_level", "contact_method", "primary_email", "primary_phone", "attempts",
            "next_action", "follow_up_date", "crm_sync_safe", "outreach_ready", "updated_at",
        ]
        missing = [column for column in expected if column not in columns]
        if missing:
            raise ValueError("SQLite leads schema is missing: " + ", ".join(missing))
        query = "SELECT " + ", ".join(expected) + " FROM leads ORDER BY domain"
        for values in connection.execute(query):
            item = dict(zip(expected, values))
            domain = str(item["domain"] or "").lower().removeprefix("www.")
            matches = domains.get(domain, set())
            organization_id = next(iter(matches)) if len(matches) == 1 else NULL
            crm_leads.append([
                domain, organization_id, item["company_name"] or "", item["pipeline_stage"] or "",
                item["crm_status"] or "", item["priority_score"] if item["priority_score"] is not None else NULL,
                item["priority_level"] or "", item["contact_method"] or "",
                item["primary_email"] or "", item["primary_phone"] or "", item["attempts"] or 0,
                item["next_action"] or "", item["follow_up_date"] or "",
                str(bool(item["crm_sync_safe"])).lower(), str(bool(item["outreach_ready"])).lower(),
                item["updated_at"] or "",
            ])
    finally:
        connection.close()
    if len({row[0] for row in crm_leads}) != len(crm_leads):
        raise ValueError("SQLite CRM contains duplicate domains")
    return ImportBundle(
        organizations, source_records, websites, list(evidence_by_id.values()), contacts, people, crm_leads
    )


FILES = {
    "organizations": 15, "source_records": 6, "websites": 7, "evidence": 8,
    "contacts": 7, "people": 7, "crm_leads": 16,
}


def _write_csv(path: Path, rows: Iterable[list[Any]], width: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for row in rows:
            if len(row) != width:
                raise ValueError(f"Invalid staging width for {path.name}")
            writer.writerow(row)


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def import_bundle(runner: PsqlRunner, bundle: ImportBundle) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix="fhsi-postgres-import-") as temp:
        root = Path(temp)
        mappings = {
            "organizations": bundle.organizations, "source_records": bundle.source_records,
            "websites": bundle.websites, "evidence": bundle.evidence,
            "contacts": bundle.contacts, "people": bundle.people, "crm_leads": bundle.crm_leads,
        }
        paths = {}
        for name, rows in mappings.items():
            paths[name] = root / f"{name}.csv"
            _write_csv(paths[name], rows, FILES[name])
        sql = _import_sql(paths)
        runner.run(sql)
    return bundle.counts()


def _import_sql(paths: dict[str, Path]) -> str:
    copies = "\n".join(
        f"\\copy stage_{name} FROM '{_literal(path)}' WITH (FORMAT csv, NULL '{NULL}')"
        for name, path in paths.items()
    )
    return f"""BEGIN;
CREATE TEMP TABLE stage_organizations (organization_id text, canonical_name text, city text, province text, country text, record_type text, directory_index text, website_status text, founded_year text, ownership_type text, parent_organization text, service_area text, service_offering text, languages_offered text, source_system text) ON COMMIT DROP;
CREATE TEMP TABLE stage_source_records (source_system text, source_record_id text, organization_id text, source_name text, payload text, payload_sha256 text) ON COMMIT DROP;
CREATE TEMP TABLE stage_websites (website_id text, organization_id text, url text, domain text, status text, is_canonical text, source_system text) ON COMMIT DROP;
CREATE TEMP TABLE stage_evidence (evidence_id text, source_url text, source_file text, source_text_sha256 text, source_html_sha256 text, evidence_class text, evidence_excerpt text, metadata text) ON COMMIT DROP;
CREATE TEMP TABLE stage_contacts (contact_id text, organization_id text, contact_type text, normalized_value text, classification text, evidence_id text, attributes text) ON COMMIT DROP;
CREATE TEMP TABLE stage_people (person_id text, organization_id text, full_name text, title text, is_decision_maker text, evidence_id text, attributes text) ON COMMIT DROP;
CREATE TEMP TABLE stage_crm_leads (domain text, organization_id text, company_name text, pipeline_stage text, crm_status text, priority_score text, priority_level text, contact_method text, primary_email text, primary_phone text, attempts text, next_action text, follow_up_date text, crm_sync_safe text, outreach_ready text, source_updated_at text) ON COMMIT DROP;
{copies}
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM stage_organizations incoming
    JOIN fhsi.organizations existing USING (organization_id)
    WHERE existing.source_system <> incoming.source_system
  ) THEN
    RAISE EXCEPTION 'organization ID belongs to a different source system';
  END IF;
END $$;
INSERT INTO fhsi.organizations (organization_id, canonical_name, city, province, country, record_type, directory_index, website_status, founded_year, ownership_type, parent_organization, service_area, service_offering, languages_offered, source_system)
SELECT organization_id, canonical_name, city, province, country, record_type, directory_index::integer, website_status, founded_year, ownership_type, parent_organization, service_area, service_offering, languages_offered, source_system FROM stage_organizations
ON CONFLICT (organization_id) DO UPDATE SET canonical_name=EXCLUDED.canonical_name, city=EXCLUDED.city, province=EXCLUDED.province, country=EXCLUDED.country, record_type=EXCLUDED.record_type, directory_index=EXCLUDED.directory_index, website_status=EXCLUDED.website_status, founded_year=EXCLUDED.founded_year, ownership_type=EXCLUDED.ownership_type, parent_organization=EXCLUDED.parent_organization, service_area=EXCLUDED.service_area, service_offering=EXCLUDED.service_offering, languages_offered=EXCLUDED.languages_offered, source_system=EXCLUDED.source_system, updated_at=now();
INSERT INTO fhsi.source_records (source_system, source_record_id, organization_id, source_name, payload, payload_sha256)
SELECT source_system, source_record_id, organization_id, source_name, payload::jsonb, payload_sha256 FROM stage_source_records
ON CONFLICT (source_system, source_record_id) DO UPDATE SET organization_id=EXCLUDED.organization_id, source_name=EXCLUDED.source_name, payload=EXCLUDED.payload, payload_sha256=EXCLUDED.payload_sha256, imported_at=now();
INSERT INTO fhsi.organization_websites (website_id, organization_id, url, domain, status, is_canonical, source_system)
SELECT website_id, organization_id, url, domain, status, is_canonical::boolean, source_system FROM stage_websites
ON CONFLICT (website_id) DO UPDATE SET organization_id=EXCLUDED.organization_id, url=EXCLUDED.url, domain=EXCLUDED.domain, status=EXCLUDED.status, is_canonical=CASE WHEN fhsi.organization_websites.verification_class <> '' THEN fhsi.organization_websites.is_canonical ELSE EXCLUDED.is_canonical END, source_system=EXCLUDED.source_system, updated_at=now();
INSERT INTO fhsi.evidence_sources (evidence_id, source_url, source_file, source_text_sha256, source_html_sha256, evidence_class, evidence_excerpt, metadata)
SELECT evidence_id, source_url, source_file, source_text_sha256, source_html_sha256, evidence_class, evidence_excerpt, metadata::jsonb FROM stage_evidence
ON CONFLICT (evidence_id) DO UPDATE SET source_url=EXCLUDED.source_url, source_file=EXCLUDED.source_file, source_text_sha256=EXCLUDED.source_text_sha256, source_html_sha256=EXCLUDED.source_html_sha256, evidence_class=EXCLUDED.evidence_class, evidence_excerpt=EXCLUDED.evidence_excerpt, metadata=EXCLUDED.metadata;
INSERT INTO fhsi.contacts (contact_id, organization_id, contact_type, normalized_value, classification, evidence_id, attributes)
SELECT contact_id, organization_id, contact_type, normalized_value, classification, evidence_id, attributes::jsonb FROM stage_contacts
ON CONFLICT (contact_id) DO UPDATE SET organization_id=EXCLUDED.organization_id, contact_type=EXCLUDED.contact_type, normalized_value=EXCLUDED.normalized_value, classification=EXCLUDED.classification, evidence_id=EXCLUDED.evidence_id, attributes=EXCLUDED.attributes, updated_at=now();
INSERT INTO fhsi.people (person_id, organization_id, full_name, title, is_decision_maker, evidence_id, attributes)
SELECT person_id, organization_id, full_name, title, is_decision_maker::boolean, evidence_id, attributes::jsonb FROM stage_people
ON CONFLICT (person_id) DO UPDATE SET organization_id=EXCLUDED.organization_id, full_name=EXCLUDED.full_name, title=EXCLUDED.title, is_decision_maker=EXCLUDED.is_decision_maker, evidence_id=EXCLUDED.evidence_id, attributes=EXCLUDED.attributes, updated_at=now();
INSERT INTO fhsi.crm_lead_snapshots (domain, organization_id, company_name, pipeline_stage, crm_status, priority_score, priority_level, contact_method, primary_email, primary_phone, attempts, next_action, follow_up_date, crm_sync_safe, outreach_ready, source_updated_at)
SELECT domain, organization_id, company_name, pipeline_stage, crm_status, priority_score::double precision, priority_level, contact_method, primary_email, primary_phone, attempts::integer, next_action, follow_up_date, crm_sync_safe::boolean, outreach_ready::boolean, source_updated_at FROM stage_crm_leads
ON CONFLICT (domain) DO UPDATE SET organization_id=EXCLUDED.organization_id, company_name=EXCLUDED.company_name, pipeline_stage=EXCLUDED.pipeline_stage, crm_status=EXCLUDED.crm_status, priority_score=EXCLUDED.priority_score, priority_level=EXCLUDED.priority_level, contact_method=EXCLUDED.contact_method, primary_email=EXCLUDED.primary_email, primary_phone=EXCLUDED.primary_phone, attempts=EXCLUDED.attempts, next_action=EXCLUDED.next_action, follow_up_date=EXCLUDED.follow_up_date, crm_sync_safe=EXCLUDED.crm_sync_safe, outreach_ready=EXCLUDED.outreach_ready, source_updated_at=EXCLUDED.source_updated_at, imported_at=now();
COMMIT;
"""


def database_counts(runner: PsqlRunner) -> dict[str, int]:
    output = runner.run("""
SELECT key || '=' || value FROM (
  SELECT 'organizations' key, count(*) value FROM fhsi.organizations
  UNION ALL SELECT 'source_records', count(*) FROM fhsi.source_records
  UNION ALL SELECT 'evidence_sources', count(*) FROM fhsi.evidence_sources
  UNION ALL SELECT 'contacts', count(*) FROM fhsi.contacts
  UNION ALL SELECT 'people', count(*) FROM fhsi.people
  UNION ALL SELECT 'crm_lead_snapshots', count(*) FROM fhsi.crm_lead_snapshots
) counts ORDER BY key;
""", tuples_only=True)
    return {key: int(value) for key, value in (line.split("=", 1) for line in output.splitlines() if line)}


def integrity_report(runner: PsqlRunner) -> dict[str, int]:
    output = runner.run("""
SELECT key || '=' || value FROM (
  SELECT 'orphan_source_records' key, count(*) value FROM fhsi.source_records s LEFT JOIN fhsi.organizations o USING (organization_id) WHERE o.organization_id IS NULL
  UNION ALL SELECT 'orphan_websites', count(*) FROM fhsi.organization_websites w LEFT JOIN fhsi.organizations o USING (organization_id) WHERE o.organization_id IS NULL
  UNION ALL SELECT 'orphan_contacts', count(*) FROM fhsi.contacts c LEFT JOIN fhsi.organizations o USING (organization_id) WHERE o.organization_id IS NULL
  UNION ALL SELECT 'orphan_people', count(*) FROM fhsi.people p LEFT JOIN fhsi.organizations o USING (organization_id) WHERE o.organization_id IS NULL
  UNION ALL SELECT 'contacts_without_evidence', count(*) FROM fhsi.contacts WHERE evidence_id IS NULL
  UNION ALL SELECT 'people_without_evidence', count(*) FROM fhsi.people WHERE evidence_id IS NULL
  UNION ALL SELECT 'duplicate_source_ids', count(*) FROM (SELECT source_system, source_record_id FROM fhsi.source_records GROUP BY 1,2 HAVING count(*) > 1) d
  UNION ALL SELECT 'duplicate_contact_ids', count(*) FROM (SELECT contact_id FROM fhsi.contacts GROUP BY 1 HAVING count(*) > 1) d
  UNION ALL SELECT 'duplicate_person_ids', count(*) FROM (SELECT person_id FROM fhsi.people GROUP BY 1 HAVING count(*) > 1) d
) checks ORDER BY key;
""", tuples_only=True)
    return {key: int(value) for key, value in (line.split("=", 1) for line in output.splitlines() if line)}
