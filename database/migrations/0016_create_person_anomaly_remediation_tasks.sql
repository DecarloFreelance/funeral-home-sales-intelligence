CREATE TABLE person_anomaly_remediation_tasks (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    anomaly_code TEXT NOT NULL CHECK (length(trim(anomaly_code)) > 0),
    anomaly_fingerprint TEXT NOT NULL CHECK (length(trim(anomaly_fingerprint)) > 0),
    task_type TEXT NOT NULL CHECK (task_type IN ('verify_contact', 'verify_affiliation', 'verify_identity', 'inspect_source', 'inspect_page', 'confirm_branch', 'resolve_conflict', 'other')),
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'blocked', 'completed', 'cancelled', 'stale')),
    owner TEXT,
    due_at TEXT,
    created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
    created_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT,
    cancelled_at TEXT,
    stale_at TEXT,
    FOREIGN KEY (person_id) REFERENCES people(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE person_anomaly_remediation_task_history (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    anomaly_code TEXT NOT NULL CHECK (length(trim(anomaly_code)) > 0),
    anomaly_fingerprint TEXT NOT NULL CHECK (length(trim(anomaly_fingerprint)) > 0),
    previous_status TEXT CHECK (previous_status IS NULL OR previous_status IN ('open', 'in_progress', 'blocked', 'completed', 'cancelled', 'stale')),
    new_status TEXT NOT NULL CHECK (new_status IN ('open', 'in_progress', 'blocked', 'completed', 'cancelled', 'stale')),
    actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    note TEXT,
    previous_owner TEXT,
    new_owner TEXT,
    previous_due_at TEXT,
    new_due_at TEXT,
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (task_id) REFERENCES person_anomaly_remediation_tasks(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (person_id) REFERENCES people(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX idx_person_anomaly_remediation_tasks_person ON person_anomaly_remediation_tasks(person_id);
CREATE INDEX idx_person_anomaly_remediation_tasks_fingerprint ON person_anomaly_remediation_tasks(anomaly_fingerprint);
CREATE INDEX idx_person_anomaly_remediation_tasks_code ON person_anomaly_remediation_tasks(anomaly_code);
CREATE INDEX idx_person_anomaly_remediation_tasks_status ON person_anomaly_remediation_tasks(status);
CREATE INDEX idx_person_anomaly_remediation_tasks_owner ON person_anomaly_remediation_tasks(owner);
CREATE INDEX idx_person_anomaly_remediation_tasks_due_at ON person_anomaly_remediation_tasks(due_at);
CREATE INDEX idx_person_anomaly_remediation_tasks_person_status ON person_anomaly_remediation_tasks(person_id, status);
CREATE INDEX idx_person_anomaly_remediation_tasks_code_status ON person_anomaly_remediation_tasks(anomaly_code, status);
CREATE INDEX idx_person_anomaly_remediation_tasks_fingerprint_status ON person_anomaly_remediation_tasks(anomaly_fingerprint, status);
CREATE INDEX idx_person_anomaly_remediation_task_history_task ON person_anomaly_remediation_task_history(task_id, id);

CREATE TRIGGER person_anomaly_remediation_task_history_no_update
BEFORE UPDATE ON person_anomaly_remediation_task_history
BEGIN
    SELECT RAISE(ABORT, 'person anomaly remediation task history is immutable');
END;

CREATE TRIGGER person_anomaly_remediation_task_history_no_delete
BEFORE DELETE ON person_anomaly_remediation_task_history
BEGIN
    SELECT RAISE(ABORT, 'person anomaly remediation task history is immutable');
END;
