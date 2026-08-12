CREATE TABLE business_fact_observations (
    id INTEGER PRIMARY KEY,
    website_page_id INTEGER NOT NULL,
    website_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    source_url TEXT NOT NULL CHECK (length(trim(source_url)) > 0),
    page_kind TEXT NOT NULL CHECK (length(trim(page_kind)) > 0),
    fact_key TEXT NOT NULL CHECK (fact_key IN ('ownership_type', 'parent_organization', 'founded_year', 'languages_offered', 'service_offering', 'service_area', 'technology_signal')),
    value_kind TEXT NOT NULL CHECK (value_kind IN ('enum', 'text', 'integer', 'multi_text')),
    raw_value TEXT NOT NULL CHECK (length(trim(raw_value)) > 0),
    normalized_value TEXT NOT NULL CHECK (length(trim(normalized_value)) > 0),
    scope TEXT NOT NULL CHECK (scope IN ('explicit', 'inherited_from_website', 'ambiguous')),
    scope_entity_id INTEGER,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extraction_method TEXT NOT NULL CHECK (length(trim(extraction_method)) > 0),
    extractor_version TEXT NOT NULL CHECK (length(trim(extractor_version)) > 0),
    evidence_snippet TEXT NOT NULL CHECK (length(trim(evidence_snippet)) > 0),
    content_hash TEXT NOT NULL CHECK (length(trim(content_hash)) = 64),
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (website_page_id, content_hash, fact_key, normalized_value, raw_value, scope_entity_id),
    CHECK ((scope = 'explicit' AND scope_entity_id IS NOT NULL) OR (scope <> 'explicit' AND scope_entity_id IS NULL)),
    FOREIGN KEY (website_page_id) REFERENCES website_pages(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (website_id) REFERENCES websites(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (scope_entity_id) REFERENCES entities(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX idx_business_fact_page ON business_fact_observations(website_page_id);
CREATE INDEX idx_business_fact_website ON business_fact_observations(website_id);
CREATE INDEX idx_business_fact_entity ON business_fact_observations(entity_id);
CREATE INDEX idx_business_fact_key ON business_fact_observations(fact_key);
CREATE INDEX idx_business_fact_value ON business_fact_observations(normalized_value);
CREATE INDEX idx_business_fact_hash ON business_fact_observations(content_hash);
CREATE INDEX idx_business_fact_scope ON business_fact_observations(scope, scope_entity_id);
