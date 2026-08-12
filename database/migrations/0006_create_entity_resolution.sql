CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('organization', 'branch')),
    canonical_name TEXT,
    parent_entity_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'merged', 'inactive')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (parent_entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

CREATE TABLE entity_source_records (
    entity_id INTEGER NOT NULL,
    source_record_id INTEGER NOT NULL,
    membership_role TEXT NOT NULL DEFAULT 'location'
        CHECK (membership_role IN ('organization', 'location', 'branch')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (entity_id, source_record_id),
    FOREIGN KEY (entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (source_record_id)
        REFERENCES source_records(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE match_candidates (
    id INTEGER PRIMARY KEY,
    left_source_record_id INTEGER NOT NULL,
    right_source_record_id INTEGER NOT NULL,
    candidate_method TEXT NOT NULL,
    score REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    decision TEXT NOT NULL DEFAULT 'pending'
        CHECK (decision IN ('pending', 'match', 'no_match', 'review')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (left_source_record_id < right_source_record_id),
    UNIQUE (left_source_record_id, right_source_record_id, candidate_method),
    FOREIGN KEY (left_source_record_id)
        REFERENCES source_records(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (right_source_record_id)
        REFERENCES source_records(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE match_evidence (
    id INTEGER PRIMARY KEY,
    match_candidate_id INTEGER NOT NULL,
    signal_name TEXT NOT NULL,
    left_value TEXT,
    right_value TEXT,
    contribution REAL NOT NULL,
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('deterministic', 'fuzzy', 'context')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (match_candidate_id)
        REFERENCES match_candidates(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE entity_review_queue (
    id INTEGER PRIMARY KEY,
    match_candidate_id INTEGER NOT NULL UNIQUE,
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'deferred')),
    reviewer_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_at TEXT,
    FOREIGN KEY (match_candidate_id)
        REFERENCES match_candidates(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE merge_history (
    id INTEGER PRIMARY KEY,
    survivor_entity_id INTEGER NOT NULL,
    merged_entity_id INTEGER NOT NULL,
    decision_source TEXT NOT NULL,
    reason TEXT NOT NULL,
    rolled_back_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (survivor_entity_id <> merged_entity_id),
    FOREIGN KEY (survivor_entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (merged_entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX idx_entities_type
ON entities(entity_type);

CREATE INDEX idx_entities_parent
ON entities(parent_entity_id);

CREATE INDEX idx_entities_status
ON entities(status);

CREATE INDEX idx_entity_source_records_source
ON entity_source_records(source_record_id);

CREATE INDEX idx_match_candidates_left
ON match_candidates(left_source_record_id);

CREATE INDEX idx_match_candidates_right
ON match_candidates(right_source_record_id);

CREATE INDEX idx_match_candidates_decision
ON match_candidates(decision);

CREATE INDEX idx_match_candidates_score
ON match_candidates(score);

CREATE INDEX idx_match_evidence_candidate
ON match_evidence(match_candidate_id);

CREATE INDEX idx_match_evidence_signal
ON match_evidence(signal_name);

CREATE INDEX idx_entity_review_queue_status_priority
ON entity_review_queue(status, priority);

CREATE INDEX idx_merge_history_survivor
ON merge_history(survivor_entity_id);

CREATE INDEX idx_merge_history_merged
ON merge_history(merged_entity_id);
