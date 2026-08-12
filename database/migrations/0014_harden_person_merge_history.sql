ALTER TABLE person_merge_history ADD COLUMN rollback_actor TEXT;
ALTER TABLE person_merge_history ADD COLUMN rollback_reason TEXT;
ALTER TABLE person_merge_affiliation_history ADD COLUMN resulting_affiliation_id INTEGER;
ALTER TABLE person_merge_contact_history ADD COLUMN resulting_contact_id INTEGER;
ALTER TABLE person_merge_affiliation_history ADD COLUMN previous_active INTEGER NOT NULL DEFAULT 1
    CHECK (previous_active IN (0, 1));
ALTER TABLE person_merge_contact_history ADD COLUMN previous_active INTEGER NOT NULL DEFAULT 1
    CHECK (previous_active IN (0, 1));
ALTER TABLE person_merge_evidence_history ADD COLUMN action TEXT NOT NULL DEFAULT 'moved'
    CHECK (action IN ('moved', 'deduplicated'));

CREATE INDEX idx_person_merge_history_active
    ON person_merge_history(rolled_back_at, id);

CREATE TRIGGER person_merge_history_no_delete
BEFORE DELETE ON person_merge_history
BEGIN
    SELECT RAISE(ABORT, 'person merge history is immutable');
END;

CREATE TRIGGER person_merge_history_no_core_update
BEFORE UPDATE OF survivor_person_id, merged_person_id, decision_source, reason, created_at
ON person_merge_history
BEGIN
    SELECT RAISE(ABORT, 'person merge history core fields are immutable');
END;

CREATE TRIGGER person_merge_history_rollback_once
BEFORE UPDATE OF rolled_back_at, rollback_actor, rollback_reason
ON person_merge_history
WHEN OLD.rolled_back_at IS NOT NULL
  OR NEW.rolled_back_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'person merge rollback is single-use');
END;

CREATE TRIGGER person_merge_affiliation_history_no_update
BEFORE UPDATE ON person_merge_affiliation_history
BEGIN
    SELECT RAISE(ABORT, 'person merge child history is immutable');
END;

CREATE TRIGGER person_merge_affiliation_history_no_delete
BEFORE DELETE ON person_merge_affiliation_history
BEGIN
    SELECT RAISE(ABORT, 'person merge child history is immutable');
END;

CREATE TRIGGER person_merge_contact_history_no_update
BEFORE UPDATE ON person_merge_contact_history
BEGIN
    SELECT RAISE(ABORT, 'person merge child history is immutable');
END;

CREATE TRIGGER person_merge_contact_history_no_delete
BEFORE DELETE ON person_merge_contact_history
BEGIN
    SELECT RAISE(ABORT, 'person merge child history is immutable');
END;

CREATE TRIGGER person_merge_evidence_history_no_update
BEFORE UPDATE ON person_merge_evidence_history
BEGIN
    SELECT RAISE(ABORT, 'person merge child history is immutable');
END;

CREATE TRIGGER person_merge_evidence_history_no_delete
BEFORE DELETE ON person_merge_evidence_history
BEGIN
    SELECT RAISE(ABORT, 'person merge child history is immutable');
END;
