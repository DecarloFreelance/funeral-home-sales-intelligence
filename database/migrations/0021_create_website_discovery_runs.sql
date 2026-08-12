CREATE TABLE website_discovery_runs (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('offline_candidates', 'network_verify')),
    entity_id INTEGER,
    source_dataset_id INTEGER,
    entity_limit INTEGER NOT NULL CHECK (entity_limit BETWEEN 1 AND 25),
    candidate_limit INTEGER NOT NULL CHECK (candidate_limit BETWEEN 1 AND 2),
    timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds BETWEEN 1 AND 10),
    max_redirects INTEGER NOT NULL CHECK (max_redirects BETWEEN 0 AND 5),
    max_retries INTEGER NOT NULL CHECK (max_retries BETWEEN 0 AND 1),
    network_used INTEGER NOT NULL CHECK (network_used IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    entities_examined INTEGER NOT NULL DEFAULT 0 CHECK (entities_examined >= 0),
    candidates_considered INTEGER NOT NULL DEFAULT 0 CHECK (candidates_considered >= 0),
    candidates_inserted INTEGER NOT NULL DEFAULT 0 CHECK (candidates_inserted >= 0),
    candidates_unchanged INTEGER NOT NULL DEFAULT 0 CHECK (candidates_unchanged >= 0),
    review_required INTEGER NOT NULL DEFAULT 0 CHECK (review_required >= 0),
    succeeded INTEGER NOT NULL DEFAULT 0 CHECK (succeeded >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    skipped_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    checkpoint_entity_id INTEGER,
    error_summary TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (source_dataset_id) REFERENCES source_datasets(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE website_discovery_run_items (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    website_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error_class TEXT,
    error_message TEXT,
    check_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (run_id) REFERENCES website_discovery_runs(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (website_id) REFERENCES websites(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (check_id) REFERENCES website_checks(id) ON UPDATE CASCADE ON DELETE SET NULL,
    UNIQUE (run_id, website_id)
);

CREATE INDEX idx_website_discovery_runs_status
    ON website_discovery_runs(status, started_at DESC, id DESC);
CREATE INDEX idx_website_discovery_runs_scope
    ON website_discovery_runs(entity_id, source_dataset_id);
CREATE INDEX idx_website_discovery_items_run_status
    ON website_discovery_run_items(run_id, status, id);
CREATE INDEX idx_website_discovery_items_website
    ON website_discovery_run_items(website_id, status);

CREATE TRIGGER prevent_website_discovery_item_update_after_completion
BEFORE UPDATE OF check_id ON website_discovery_run_items
WHEN OLD.status = 'completed'
BEGIN
    SELECT RAISE(ABORT, 'completed website discovery items are immutable');
END;
