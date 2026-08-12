CREATE TABLE normalized_values (
    id INTEGER PRIMARY KEY,
    source_record_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    original_value TEXT,
    normalized_value TEXT,
    normalizer_name TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    normalized_at TEXT NOT NULL,
    warnings TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (source_record_id)
        REFERENCES source_records(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX idx_normalized_values_source_record
ON normalized_values(source_record_id);

CREATE INDEX idx_normalized_values_field
ON normalized_values(field_name);

CREATE INDEX idx_normalized_values_normalizer
ON normalized_values(normalizer_name, normalizer_version);

CREATE INDEX idx_normalized_values_source_field
ON normalized_values(source_record_id, field_name);
