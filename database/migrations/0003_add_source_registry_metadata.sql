ALTER TABLE source_datasets ADD COLUMN source_format TEXT;
ALTER TABLE source_datasets ADD COLUMN trust_level TEXT;
ALTER TABLE source_datasets ADD COLUMN refresh_interval_days INTEGER;
ALTER TABLE source_datasets ADD COLUMN coverage TEXT;
ALTER TABLE source_datasets ADD COLUMN licensing_notes TEXT;

CREATE INDEX idx_source_datasets_type
ON source_datasets(source_type);

CREATE INDEX idx_source_datasets_jurisdiction
ON source_datasets(jurisdiction);

CREATE INDEX idx_source_datasets_active
ON source_datasets(is_active);
