ALTER TABLE fhsi.organization_websites
    ADD COLUMN IF NOT EXISTS verification_class text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS verification_source text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS verification_score double precision;

CREATE INDEX IF NOT EXISTS organization_websites_canonical_idx
    ON fhsi.organization_websites (organization_id) WHERE is_canonical;

CREATE TABLE IF NOT EXISTS fhsi.crawl_runs (
    crawl_run_id text PRIMARY KEY,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    queued_domains integer NOT NULL CHECK (queued_domains >= 0),
    successful_domains integer NOT NULL CHECK (successful_domains >= 0),
    zero_page_domains integer NOT NULL CHECK (zero_page_domains >= 0),
    reported_page_responses integer NOT NULL CHECK (reported_page_responses >= 0),
    persisted_unique_pages integer NOT NULL CHECK (persisted_unique_pages >= 0),
    duration_ms bigint,
    report jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fhsi.crawl_targets (
    crawl_target_id text PRIMARY KEY,
    crawl_run_id text NOT NULL REFERENCES fhsi.crawl_runs(crawl_run_id),
    domain text NOT NULL,
    status text NOT NULL,
    page_count integer NOT NULL CHECK (page_count >= 0),
    duration_ms bigint,
    attempts jsonb NOT NULL DEFAULT '[]'::jsonb,
    imported_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (crawl_run_id, domain)
);

CREATE INDEX IF NOT EXISTS crawl_targets_status_idx
    ON fhsi.crawl_targets (status, page_count);

CREATE TABLE IF NOT EXISTS fhsi.crawl_pages (
    crawl_page_id text PRIMARY KEY,
    crawl_run_id text NOT NULL REFERENCES fhsi.crawl_runs(crawl_run_id),
    domain text NOT NULL,
    url text NOT NULL,
    loaded_url text NOT NULL DEFAULT '',
    http_status integer,
    content_type text NOT NULL DEFAULT '',
    observed_at timestamptz,
    title text NOT NULL DEFAULT '',
    canonical_url text NOT NULL DEFAULT '',
    description text NOT NULL DEFAULT '',
    extracted_text text NOT NULL DEFAULT '',
    text_sha256 text NOT NULL,
    html_sha256 text NOT NULL,
    source_file text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    discovery jsonb NOT NULL DEFAULT '{}'::jsonb,
    imported_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (crawl_run_id, url, text_sha256, html_sha256)
);

CREATE INDEX IF NOT EXISTS crawl_pages_domain_idx ON fhsi.crawl_pages (domain);
CREATE INDEX IF NOT EXISTS crawl_pages_url_idx ON fhsi.crawl_pages (url);
CREATE INDEX IF NOT EXISTS crawl_pages_observed_idx ON fhsi.crawl_pages (observed_at);
CREATE INDEX IF NOT EXISTS crawl_pages_text_search_idx
    ON fhsi.crawl_pages USING gin (to_tsvector('english', extracted_text));
