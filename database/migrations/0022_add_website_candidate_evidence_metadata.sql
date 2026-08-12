ALTER TABLE website_evidence ADD COLUMN normalized_value_id INTEGER;
ALTER TABLE website_evidence ADD COLUMN evidence_class TEXT;
ALTER TABLE website_evidence ADD COLUMN derivation_method TEXT;
ALTER TABLE website_evidence ADD COLUMN derivation_version TEXT;
ALTER TABLE website_evidence ADD COLUMN raw_value TEXT;

UPDATE website_evidence
SET evidence_class = CASE evidence_type
    WHEN 'normalized_url' THEN 'explicit_source_url'
    WHEN 'domain' THEN 'source_domain'
    WHEN 'manual' THEN 'manual'
    ELSE 'explicit_source_url'
END,
    derivation_method = COALESCE(derivation_method, 'legacy_website_evidence'),
    derivation_version = COALESCE(derivation_version, 'website-candidate-evidence-v1'),
    raw_value = COALESCE(raw_value, evidence_value)
WHERE evidence_class IS NULL;

CREATE INDEX idx_website_evidence_class
    ON website_evidence(website_id, evidence_class);

CREATE INDEX idx_website_evidence_normalized_value
    ON website_evidence(normalized_value_id);

CREATE UNIQUE INDEX idx_website_evidence_logical
    ON website_evidence(
        website_id,
        evidence_class,
        COALESCE(source_record_id, 0),
        COALESCE(normalized_value_id, 0),
        COALESCE(evidence_value, '')
    );
