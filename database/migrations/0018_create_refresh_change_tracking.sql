CREATE TABLE refresh_runs (
    id INTEGER PRIMARY KEY,
    run_type TEXT NOT NULL CHECK (run_type IN ('website_page', 'person_observation', 'business_fact')),
    scope_type TEXT NOT NULL CHECK (length(trim(scope_type)) > 0),
    scope_value TEXT,
    reference_time TEXT NOT NULL CHECK (length(trim(reference_time)) > 0),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    extractor_version TEXT,
    config_fingerprint TEXT,
    error_summary TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (run_type, scope_type, scope_value, reference_time)
);

CREATE TABLE refresh_run_items (
    id INTEGER PRIMARY KEY,
    refresh_run_id INTEGER NOT NULL,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('website_page', 'person_observation', 'business_fact')),
    subject_key TEXT NOT NULL CHECK (length(trim(subject_key)) > 0),
    semantic_fingerprint TEXT NOT NULL CHECK (length(trim(semantic_fingerprint)) = 64),
    reference_id INTEGER,
    present INTEGER NOT NULL CHECK (present IN (0, 1)),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (refresh_run_id, subject_type, subject_key),
    FOREIGN KEY (refresh_run_id) REFERENCES refresh_runs(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE change_events (
    id INTEGER PRIMARY KEY,
    refresh_run_id INTEGER NOT NULL,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('website_page', 'person_observation', 'business_fact')),
    subject_key TEXT NOT NULL CHECK (length(trim(subject_key)) > 0),
    change_type TEXT NOT NULL CHECK (change_type IN ('added', 'changed', 'missing', 'reappeared')),
    previous_fingerprint TEXT CHECK (previous_fingerprint IS NULL OR length(trim(previous_fingerprint)) = 64),
    current_fingerprint TEXT CHECK (current_fingerprint IS NULL OR length(trim(current_fingerprint)) = 64),
    previous_reference_id INTEGER,
    current_reference_id INTEGER,
    reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) > 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    detected_at TEXT NOT NULL,
    FOREIGN KEY (refresh_run_id) REFERENCES refresh_runs(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE UNIQUE INDEX idx_change_events_run_subject_type
    ON change_events(refresh_run_id, subject_type, subject_key, change_type);
CREATE INDEX idx_refresh_runs_scope_status
    ON refresh_runs(run_type, scope_type, scope_value, status, id);
CREATE INDEX idx_refresh_items_run_subject
    ON refresh_run_items(refresh_run_id, subject_type, subject_key);
CREATE INDEX idx_refresh_items_subject_fingerprint
    ON refresh_run_items(subject_type, subject_key, semantic_fingerprint);
CREATE INDEX idx_change_events_subject
    ON change_events(subject_type, subject_key, id);
CREATE INDEX idx_change_events_type_detected
    ON change_events(change_type, detected_at, id);

CREATE TRIGGER change_events_no_update
BEFORE UPDATE ON change_events
BEGIN
    SELECT RAISE(ABORT, 'change events are immutable');
END;

CREATE TRIGGER change_events_no_delete
BEFORE DELETE ON change_events
BEGIN
    SELECT RAISE(ABORT, 'change events are immutable');
END;

CREATE TRIGGER completed_refresh_run_no_update
BEFORE UPDATE OF run_type, scope_type, scope_value, reference_time, status, extractor_version, config_fingerprint, started_at, completed_at, created_at
ON refresh_runs
WHEN OLD.status = 'completed'
BEGIN
    SELECT RAISE(ABORT, 'completed refresh runs are immutable');
END;

CREATE TRIGGER completed_refresh_items_no_update
BEFORE UPDATE ON refresh_run_items
WHEN (SELECT status FROM refresh_runs WHERE id = OLD.refresh_run_id) = 'completed'
BEGIN
    SELECT RAISE(ABORT, 'completed refresh items are immutable');
END;

CREATE TRIGGER completed_refresh_items_no_delete
BEFORE DELETE ON refresh_run_items
WHEN (SELECT status FROM refresh_runs WHERE id = OLD.refresh_run_id) = 'completed'
BEGIN
    SELECT RAISE(ABORT, 'completed refresh items are immutable');
END;
