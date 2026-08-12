CREATE TABLE pipeline_runs (
    id INTEGER PRIMARY KEY,
    pipeline_version TEXT NOT NULL,
    source_dataset_id INTEGER NOT NULL,
    input_path TEXT NOT NULL,
    input_format TEXT NOT NULL CHECK (input_format IN ('csv', 'json')),
    external_id_field TEXT,
    input_fingerprint TEXT NOT NULL CHECK (length(input_fingerprint) = 64),
    through_stage TEXT NOT NULL CHECK (through_stage IN ('import', 'normalize', 'deterministic_match', 'fuzzy_match', 'review_queue', 'materialize')),
    skip_fuzzy INTEGER NOT NULL DEFAULT 0 CHECK (skip_fuzzy IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    resumed_from_run_id INTEGER,
    started_at TEXT,
    completed_at TEXT,
    failed_at TEXT,
    error_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (source_dataset_id) REFERENCES source_datasets(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (resumed_from_run_id) REFERENCES pipeline_runs(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE pipeline_run_stages (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER NOT NULL,
    stage_name TEXT NOT NULL CHECK (stage_name IN ('import', 'normalize', 'deterministic_match', 'fuzzy_match', 'review_queue', 'materialize')),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    started_at TEXT,
    completed_at TEXT,
    input_count INTEGER NOT NULL DEFAULT 0 CHECK (input_count >= 0),
    processed_count INTEGER NOT NULL DEFAULT 0 CHECK (processed_count >= 0),
    inserted_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    updated_count INTEGER NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
    unchanged_count INTEGER NOT NULL DEFAULT 0 CHECK (unchanged_count >= 0),
    skipped_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    review_count INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id) ON UPDATE CASCADE ON DELETE CASCADE,
    UNIQUE (pipeline_run_id, stage_name),
    UNIQUE (pipeline_run_id, ordinal)
);

CREATE TABLE pipeline_run_errors (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER NOT NULL,
    pipeline_run_stage_id INTEGER,
    record_reference TEXT,
    error_message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (pipeline_run_stage_id) REFERENCES pipeline_run_stages(id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE INDEX idx_pipeline_runs_status_created
    ON pipeline_runs(status, created_at DESC, id DESC);
CREATE INDEX idx_pipeline_runs_source_fingerprint
    ON pipeline_runs(source_dataset_id, input_fingerprint);
CREATE INDEX idx_pipeline_run_stages_run_ordinal
    ON pipeline_run_stages(pipeline_run_id, ordinal);
CREATE INDEX idx_pipeline_run_stages_status
    ON pipeline_run_stages(status, pipeline_run_id);
CREATE INDEX idx_pipeline_run_errors_run
    ON pipeline_run_errors(pipeline_run_id, id);

CREATE TRIGGER prevent_pipeline_run_error_update
BEFORE UPDATE ON pipeline_run_errors
BEGIN
    SELECT RAISE(ABORT, 'pipeline run errors are immutable');
END;

CREATE TRIGGER prevent_pipeline_run_error_delete
BEFORE DELETE ON pipeline_run_errors
BEGIN
    SELECT RAISE(ABORT, 'pipeline run errors are immutable');
END;
