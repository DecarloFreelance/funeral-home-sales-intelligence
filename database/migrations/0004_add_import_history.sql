CREATE TABLE import_runs (
    id INTEGER PRIMARY KEY,
    source_dataset_id INTEGER NOT NULL,
    input_path TEXT NOT NULL,
    input_format TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    records_unchanged INTEGER NOT NULL DEFAULT 0,
    records_failed INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_dataset_id)
        REFERENCES source_datasets(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE import_run_errors (
    id INTEGER PRIMARY KEY,
    import_run_id INTEGER NOT NULL,
    row_number INTEGER,
    external_record_id TEXT,
    error_message TEXT NOT NULL,
    raw_payload TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (import_run_id)
        REFERENCES import_runs(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

ALTER TABLE source_records
ADD COLUMN import_run_id INTEGER
REFERENCES import_runs(id)
ON UPDATE CASCADE
ON DELETE SET NULL;

CREATE INDEX idx_import_runs_dataset
ON import_runs(source_dataset_id);

CREATE INDEX idx_import_runs_status
ON import_runs(status);

CREATE INDEX idx_import_run_errors_run
ON import_run_errors(import_run_id);

CREATE INDEX idx_source_records_import_run
ON source_records(import_run_id);
