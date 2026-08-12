CREATE TABLE person_anomaly_dispositions (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    anomaly_code TEXT NOT NULL CHECK (length(trim(anomaly_code)) > 0),
    anomaly_fingerprint TEXT NOT NULL CHECK (length(trim(anomaly_fingerprint)) > 0),
    status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'dismissed', 'reopened', 'stale')),
    reviewer_actor TEXT NOT NULL CHECK (length(trim(reviewer_actor)) > 0),
    reviewer_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    acknowledged_at TEXT,
    dismissed_at TEXT,
    reopened_at TEXT,
    stale_at TEXT,
    UNIQUE (person_id, anomaly_code, anomaly_fingerprint),
    FOREIGN KEY (person_id) REFERENCES people(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE person_anomaly_disposition_history (
    id INTEGER PRIMARY KEY,
    disposition_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    anomaly_code TEXT NOT NULL CHECK (length(trim(anomaly_code)) > 0),
    anomaly_fingerprint TEXT NOT NULL CHECK (length(trim(anomaly_fingerprint)) > 0),
    previous_status TEXT CHECK (previous_status IS NULL OR previous_status IN ('open', 'acknowledged', 'dismissed', 'reopened', 'stale')),
    new_status TEXT NOT NULL CHECK (new_status IN ('open', 'acknowledged', 'dismissed', 'reopened', 'stale')),
    actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    note TEXT,
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (disposition_id) REFERENCES person_anomaly_dispositions(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (person_id) REFERENCES people(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX idx_person_anomaly_dispositions_person
    ON person_anomaly_dispositions(person_id);
CREATE INDEX idx_person_anomaly_dispositions_status
    ON person_anomaly_dispositions(status);
CREATE INDEX idx_person_anomaly_dispositions_code
    ON person_anomaly_dispositions(anomaly_code);
CREATE INDEX idx_person_anomaly_dispositions_fingerprint
    ON person_anomaly_dispositions(anomaly_fingerprint);
CREATE INDEX idx_person_anomaly_dispositions_person_status
    ON person_anomaly_dispositions(person_id, status);
CREATE INDEX idx_person_anomaly_dispositions_code_status
    ON person_anomaly_dispositions(anomaly_code, status);
CREATE INDEX idx_person_anomaly_disposition_history_disposition
    ON person_anomaly_disposition_history(disposition_id, id);

CREATE TRIGGER person_anomaly_disposition_history_no_update
BEFORE UPDATE ON person_anomaly_disposition_history
BEGIN
    SELECT RAISE(ABORT, 'person anomaly disposition history is immutable');
END;

CREATE TRIGGER person_anomaly_disposition_history_no_delete
BEFORE DELETE ON person_anomaly_disposition_history
BEGIN
    SELECT RAISE(ABORT, 'person anomaly disposition history is immutable');
END;
