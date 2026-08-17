CREATE TABLE website_quality_agent_reviews (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    website_id INTEGER NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('usable', 'limited', 'blocked', 'retry', 'manual_lookup')),
    next_method TEXT NOT NULL CHECK (next_method IN ('http', 'playwright', 'targeted_page', 'manual_lookup', 'none')),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    evidence_reference TEXT NOT NULL CHECK (length(trim(evidence_reference)) > 0),
    provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
    model TEXT NOT NULL CHECK (length(trim(model)) > 0),
    prompt_version TEXT NOT NULL CHECK (length(trim(prompt_version)) > 0),
    artifact_sha256 TEXT NOT NULL CHECK (length(trim(artifact_sha256)) = 64),
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (run_id, website_id),
    FOREIGN KEY (website_id) REFERENCES websites(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX idx_website_quality_review_run ON website_quality_agent_reviews(run_id);
CREATE INDEX idx_website_quality_review_website ON website_quality_agent_reviews(website_id);
CREATE INDEX idx_website_quality_review_classification ON website_quality_agent_reviews(classification);
