CREATE TABLE websites (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    source_record_id INTEGER,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    domain TEXT NOT NULL,
    website_kind TEXT NOT NULL DEFAULT 'candidate'
        CHECK (website_kind IN (
            'candidate',
            'official',
            'branch',
            'shared',
            'alternate',
            'social'
        )),
    discovery_method TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'review', 'selected', 'rejected')),
    is_primary INTEGER NOT NULL DEFAULT 0
        CHECK (is_primary IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (entity_id, normalized_url),
    FOREIGN KEY (entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (source_record_id)
        REFERENCES source_records(id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

CREATE TABLE website_evidence (
    id INTEGER PRIMARY KEY,
    website_id INTEGER NOT NULL,
    source_record_id INTEGER,
    evidence_type TEXT NOT NULL
        CHECK (evidence_type IN (
            'source_url',
            'normalized_url',
            'domain',
            'business_name',
            'location',
            'parent_organization',
            'manual'
        )),
    evidence_value TEXT,
    contribution REAL NOT NULL DEFAULT 0.0
        CHECK (contribution >= -1.0 AND contribution <= 1.0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (website_id)
        REFERENCES websites(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (source_record_id)
        REFERENCES source_records(id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

CREATE TABLE website_review_queue (
    id INTEGER PRIMARY KEY,
    website_id INTEGER NOT NULL UNIQUE,
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'deferred')),
    reviewer_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_at TEXT,
    FOREIGN KEY (website_id)
        REFERENCES websites(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX idx_websites_entity
    ON websites(entity_id);

CREATE INDEX idx_websites_domain
    ON websites(domain);

CREATE INDEX idx_websites_status_confidence
    ON websites(status, confidence DESC);

CREATE INDEX idx_websites_kind
    ON websites(website_kind);

CREATE UNIQUE INDEX idx_websites_one_primary_per_entity
    ON websites(entity_id)
    WHERE is_primary = 1;

CREATE INDEX idx_website_evidence_website
    ON website_evidence(website_id);

CREATE INDEX idx_website_review_queue_status_priority
    ON website_review_queue(status, priority);
