CREATE TABLE source_datasets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    source_url TEXT,
    publisher TEXT,
    jurisdiction TEXT,
    license_name TEXT,
    license_url TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE source_records (
    id INTEGER PRIMARY KEY,
    source_dataset_id INTEGER NOT NULL,
    external_record_id TEXT,
    raw_payload TEXT NOT NULL,
    payload_format TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (source_dataset_id)
        REFERENCES source_datasets(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX idx_source_records_dataset
    ON source_records(source_dataset_id);

CREATE INDEX idx_source_records_external_id
    ON source_records(source_dataset_id, external_record_id);

CREATE INDEX idx_source_records_checksum
    ON source_records(checksum);

CREATE INDEX idx_source_records_retrieved_at
    ON source_records(retrieved_at);
