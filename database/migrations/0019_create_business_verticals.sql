CREATE TABLE business_verticals (
    id INTEGER PRIMARY KEY,
    vertical_key TEXT NOT NULL UNIQUE CHECK (length(trim(vertical_key)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    profile_version TEXT NOT NULL CHECK (length(trim(profile_version)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE entity_vertical_memberships (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    vertical_id INTEGER NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    classification_method TEXT NOT NULL CHECK (length(trim(classification_method)) > 0),
    classification_version TEXT NOT NULL CHECK (length(trim(classification_version)) > 0),
    source_record_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (entity_id, vertical_id),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (vertical_id) REFERENCES business_verticals(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (source_record_id) REFERENCES source_records(id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE INDEX idx_business_verticals_key ON business_verticals(vertical_key);
CREATE INDEX idx_entity_vertical_memberships_entity ON entity_vertical_memberships(entity_id);
CREATE INDEX idx_entity_vertical_memberships_vertical ON entity_vertical_memberships(vertical_id);

CREATE TRIGGER entity_vertical_memberships_no_update
BEFORE UPDATE ON entity_vertical_memberships
BEGIN
    SELECT RAISE(ABORT, 'vertical memberships are immutable');
END;

CREATE TRIGGER entity_vertical_memberships_no_delete
BEFORE DELETE ON entity_vertical_memberships
BEGIN
    SELECT RAISE(ABORT, 'vertical memberships are immutable');
END;
