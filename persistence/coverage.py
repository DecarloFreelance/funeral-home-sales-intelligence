from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from persistence.importer import NULL, SOURCE_SYSTEM, _json, _literal, _stable_id, _write_csv
from persistence.postgres import PsqlRunner


DEFAULT_MAPPINGS = Path("data/generated/directory_955/verified_crawlset/business_website_mappings.json")
DEFAULT_REPORT = Path("data/generated/batches/4a7aa3af0c4f8a44/crawl_report.json")
DEFAULT_PAGES = Path("data/generated/batches/4a7aa3af0c4f8a44/pages.json")
CRAWL_RUN_ID = "4a7aa3af0c4f8a44"


@dataclass
class CoverageBundle:
    websites: list[list[object]]
    crawl_run: list[list[object]]
    targets: list[list[object]]
    pages: list[list[object]]

    def counts(self) -> dict[str, int]:
        return {
            "canonical_website_mappings": len(self.websites),
            "crawl_runs": len(self.crawl_run),
            "crawl_targets": len(self.targets),
            "crawl_pages": len(self.pages),
            "successful_targets": sum(row[3] == "SUCCESS" for row in self.targets),
            "zero_page_targets": sum(int(row[4]) == 0 for row in self.targets),
        }


def build_coverage_bundle(
    mappings_path: Path = DEFAULT_MAPPINGS,
    report_path: Path = DEFAULT_REPORT,
    pages_path: Path = DEFAULT_PAGES,
) -> CoverageBundle:
    mappings = json.loads(mappings_path.read_text(encoding="utf-8"))
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    page_records = json.loads(pages_path.read_text(encoding="utf-8"))
    if len(mappings) != 530 or len({row["directory_record_id"] for row in mappings}) != 530:
        raise ValueError("Expected 530 unique reviewed business website mappings")
    if report.get("queued_domains") != 352 or len(report.get("leads") or []) != 352:
        raise ValueError("Expected a complete 352-domain crawl report")
    websites = []
    for row in sorted(mappings, key=lambda item: item["directory_record_id"]):
        website = row["website"]
        domain = row.get("domain") or (
            urlsplit(website if "://" in website else f"https://{website}").hostname or ""
        )
        websites.append([
            _stable_id("web", row["directory_record_id"], website), row["directory_record_id"],
            website, domain.lower().removeprefix("www."), "VERIFIED", "true", SOURCE_SYSTEM,
            row.get("verification_class") or "", row.get("source") or "",
            row.get("verification_score") if row.get("verification_score") is not None else NULL,
        ])
    targets = []
    for lead in sorted(report["leads"], key=lambda item: item["domain"]):
        status = "SUCCESS" if int(lead.get("pages") or 0) > 0 else "ZERO_PAGE"
        targets.append([
            _stable_id("target", CRAWL_RUN_ID, lead["domain"]), CRAWL_RUN_ID, lead["domain"],
            status, int(lead.get("pages") or 0),
            lead.get("duration_ms") if lead.get("duration_ms") is not None else NULL,
            _json(lead.get("attempts") or []),
        ])
    if sum(row[3] == "SUCCESS" for row in targets) != 314:
        raise ValueError("Expected 314 successful crawl targets")
    if sum(row[3] == "ZERO_PAGE" for row in targets) != 38:
        raise ValueError("Expected 38 zero-page crawl targets")

    pages_by_id = {}
    for page in page_records:
        url = str(page.get("url") or "")
        crawl = page.get("crawl") or {}
        metadata = page.get("metadata") or {}
        discovery = page.get("discovery") or {}
        text = str(page.get("text") or page.get("markdown") or "")
        html = str(page.get("html") or "")
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        html_hash = hashlib.sha256(html.encode()).hexdigest()
        page_id = _stable_id("page", CRAWL_RUN_ID, url, text_hash, html_hash)
        domain = str(discovery.get("queue_domain") or "").lower().removeprefix("www.")
        if not domain:
            domain = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        pages_by_id[page_id] = [
            page_id, CRAWL_RUN_ID, domain, url, crawl.get("loadedUrl") or "",
            crawl.get("httpStatusCode") if crawl.get("httpStatusCode") is not None else NULL,
            crawl.get("contentType") or "", crawl.get("observedAt") or NULL,
            metadata.get("title") or "", metadata.get("canonicalUrl") or "",
            metadata.get("description") or "", text, text_hash, html_hash, str(pages_path),
            _json(metadata), _json(discovery),
        ]
    pages = [pages_by_id[key] for key in sorted(pages_by_id)]
    if len(page_records) != 1373 or len(pages) != 1372:
        raise ValueError("Expected 1,373 persisted rows and 1,372 unique page observations")
    run = [[
        CRAWL_RUN_ID, str(report_path), hashlib.sha256(report_text.encode()).hexdigest(),
        352, 314, 38, int(report.get("pages") or 0), len(pages),
        report.get("duration_ms") if report.get("duration_ms") is not None else NULL,
        _json(report),
    ]]
    return CoverageBundle(websites, run, targets, pages)


def import_coverage(runner: PsqlRunner, bundle: CoverageBundle) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix="fhsi-coverage-import-") as temp:
        root = Path(temp)
        files = {
            "coverage_websites": (bundle.websites, 10), "crawl_runs": (bundle.crawl_run, 10),
            "crawl_targets": (bundle.targets, 7), "crawl_pages": (bundle.pages, 17),
        }
        paths = {}
        for name, (rows, width) in files.items():
            paths[name] = root / f"{name}.csv"
            _write_csv(paths[name], rows, width)
        runner.run(_coverage_sql(paths))
    return bundle.counts()


def _coverage_sql(paths: dict[str, Path]) -> str:
    copies = "\n".join(
        f"\\copy stage_{name} FROM '{_literal(path)}' WITH (FORMAT csv, NULL '{NULL}')"
        for name, path in paths.items()
    )
    return f"""BEGIN;
CREATE TEMP TABLE stage_coverage_websites (website_id text, organization_id text, url text, domain text, status text, is_canonical text, source_system text, verification_class text, verification_source text, verification_score text) ON COMMIT DROP;
CREATE TEMP TABLE stage_crawl_runs (crawl_run_id text, source_file text, source_sha256 text, queued_domains text, successful_domains text, zero_page_domains text, reported_page_responses text, persisted_unique_pages text, duration_ms text, report text) ON COMMIT DROP;
CREATE TEMP TABLE stage_crawl_targets (crawl_target_id text, crawl_run_id text, domain text, status text, page_count text, duration_ms text, attempts text) ON COMMIT DROP;
CREATE TEMP TABLE stage_crawl_pages (crawl_page_id text, crawl_run_id text, domain text, url text, loaded_url text, http_status text, content_type text, observed_at text, title text, canonical_url text, description text, extracted_text text, text_sha256 text, html_sha256 text, source_file text, metadata text, discovery text) ON COMMIT DROP;
{copies}
DO $$ BEGIN IF EXISTS (SELECT 1 FROM stage_coverage_websites s LEFT JOIN fhsi.organizations o USING (organization_id) WHERE o.organization_id IS NULL) THEN RAISE EXCEPTION 'coverage mapping references an unknown organization'; END IF; END $$;
UPDATE fhsi.organization_websites SET is_canonical=false, updated_at=now() WHERE source_system='{SOURCE_SYSTEM}';
INSERT INTO fhsi.organization_websites (website_id, organization_id, url, domain, status, is_canonical, source_system, verification_class, verification_source, verification_score)
SELECT website_id, organization_id, url, domain, status, is_canonical::boolean, source_system, verification_class, verification_source, verification_score::double precision FROM stage_coverage_websites
ON CONFLICT (website_id) DO UPDATE SET organization_id=EXCLUDED.organization_id, url=EXCLUDED.url, domain=EXCLUDED.domain, status=EXCLUDED.status, is_canonical=EXCLUDED.is_canonical, source_system=EXCLUDED.source_system, verification_class=EXCLUDED.verification_class, verification_source=EXCLUDED.verification_source, verification_score=EXCLUDED.verification_score, updated_at=now();
INSERT INTO fhsi.crawl_runs (crawl_run_id, source_file, source_sha256, queued_domains, successful_domains, zero_page_domains, reported_page_responses, persisted_unique_pages, duration_ms, report)
SELECT crawl_run_id, source_file, source_sha256, queued_domains::integer, successful_domains::integer, zero_page_domains::integer, reported_page_responses::integer, persisted_unique_pages::integer, duration_ms::bigint, report::jsonb FROM stage_crawl_runs
ON CONFLICT (crawl_run_id) DO UPDATE SET source_file=EXCLUDED.source_file, source_sha256=EXCLUDED.source_sha256, queued_domains=EXCLUDED.queued_domains, successful_domains=EXCLUDED.successful_domains, zero_page_domains=EXCLUDED.zero_page_domains, reported_page_responses=EXCLUDED.reported_page_responses, persisted_unique_pages=EXCLUDED.persisted_unique_pages, duration_ms=EXCLUDED.duration_ms, report=EXCLUDED.report, imported_at=now();
INSERT INTO fhsi.crawl_targets (crawl_target_id, crawl_run_id, domain, status, page_count, duration_ms, attempts)
SELECT crawl_target_id, crawl_run_id, domain, status, page_count::integer, duration_ms::bigint, attempts::jsonb FROM stage_crawl_targets
ON CONFLICT (crawl_target_id) DO UPDATE SET crawl_run_id=EXCLUDED.crawl_run_id, domain=EXCLUDED.domain, status=EXCLUDED.status, page_count=EXCLUDED.page_count, duration_ms=EXCLUDED.duration_ms, attempts=EXCLUDED.attempts, imported_at=now();
INSERT INTO fhsi.crawl_pages (crawl_page_id, crawl_run_id, domain, url, loaded_url, http_status, content_type, observed_at, title, canonical_url, description, extracted_text, text_sha256, html_sha256, source_file, metadata, discovery)
SELECT crawl_page_id, crawl_run_id, domain, url, loaded_url, http_status::integer, content_type, observed_at::timestamptz, title, canonical_url, description, extracted_text, text_sha256, html_sha256, source_file, metadata::jsonb, discovery::jsonb FROM stage_crawl_pages
ON CONFLICT (crawl_page_id) DO UPDATE SET crawl_run_id=EXCLUDED.crawl_run_id, domain=EXCLUDED.domain, url=EXCLUDED.url, loaded_url=EXCLUDED.loaded_url, http_status=EXCLUDED.http_status, content_type=EXCLUDED.content_type, observed_at=EXCLUDED.observed_at, title=EXCLUDED.title, canonical_url=EXCLUDED.canonical_url, description=EXCLUDED.description, extracted_text=EXCLUDED.extracted_text, text_sha256=EXCLUDED.text_sha256, html_sha256=EXCLUDED.html_sha256, source_file=EXCLUDED.source_file, metadata=EXCLUDED.metadata, discovery=EXCLUDED.discovery, imported_at=now();
COMMIT;
"""


def coverage_counts(runner: PsqlRunner) -> dict[str, int]:
    output = runner.run("""
SELECT key || '=' || value FROM (
 SELECT 'canonical_website_mappings' key, count(*) value FROM fhsi.organization_websites WHERE is_canonical
 UNION ALL SELECT 'all_website_signals', count(*) FROM fhsi.organization_websites
 UNION ALL SELECT 'crawl_runs', count(*) FROM fhsi.crawl_runs
 UNION ALL SELECT 'crawl_targets', count(*) FROM fhsi.crawl_targets
 UNION ALL SELECT 'crawl_pages', count(*) FROM fhsi.crawl_pages
 UNION ALL SELECT 'successful_targets', count(*) FROM fhsi.crawl_targets WHERE status='SUCCESS'
 UNION ALL SELECT 'zero_page_targets', count(*) FROM fhsi.crawl_targets WHERE status='ZERO_PAGE'
) counts ORDER BY key;
""", tuples_only=True)
    return {key: int(value) for key, value in (line.split("=", 1) for line in output.splitlines() if line)}
