CREATE TABLE business_fact_agent_reviews (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    fact_id INTEGER NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('keep', 'flag', 'reject')),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    evidence_reference TEXT NOT NULL CHECK (length(trim(evidence_reference)) > 0),
    provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
    model TEXT NOT NULL CHECK (length(trim(model)) > 0),
    prompt_version TEXT NOT NULL CHECK (length(trim(prompt_version)) > 0),
    artifact_sha256 TEXT NOT NULL CHECK (length(trim(artifact_sha256)) = 64),
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (run_id, fact_id),
    FOREIGN KEY (fact_id) REFERENCES business_fact_observations(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX idx_business_fact_agent_review_run ON business_fact_agent_reviews(run_id);
CREATE INDEX idx_business_fact_agent_review_fact ON business_fact_agent_reviews(fact_id);
CREATE INDEX idx_business_fact_agent_review_disposition ON business_fact_agent_reviews(disposition);
