CREATE TABLE people (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL
        CHECK (length(trim(canonical_name)) > 0),
    normalized_name TEXT NOT NULL
        CHECK (length(trim(normalized_name)) > 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'merged', 'inactive')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE person_observation_review_queue (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected', 'deferred')),
    reviewer_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_at TEXT,
    FOREIGN KEY (observation_id)
        REFERENCES website_page_person_observations(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE person_affiliations (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    observed_role TEXT NOT NULL
        CHECK (length(trim(observed_role)) > 0),
    normalized_role TEXT NOT NULL
        CHECK (length(trim(normalized_role)) > 0),
    branch_context TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    source_observation_id INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (person_id, entity_id, normalized_role, branch_context),
    FOREIGN KEY (person_id) REFERENCES people(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (source_observation_id)
        REFERENCES website_page_person_observations(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE person_contact_points (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    contact_type TEXT NOT NULL CHECK (contact_type IN ('email', 'phone')),
    observed_value TEXT NOT NULL CHECK (length(trim(observed_value)) > 0),
    normalized_value TEXT NOT NULL CHECK (length(trim(normalized_value)) > 0),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    source_observation_id INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (person_id, contact_type, normalized_value),
    FOREIGN KEY (person_id) REFERENCES people(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (source_observation_id)
        REFERENCES website_page_person_observations(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE person_evidence (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    resolution_candidate_id INTEGER,
    review_decision TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (person_id, observation_id),
    FOREIGN KEY (person_id) REFERENCES people(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (observation_id)
        REFERENCES website_page_person_observations(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (resolution_candidate_id)
        REFERENCES person_resolution_candidates(id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE person_resolution_candidates (
    id INTEGER PRIMARY KEY,
    left_observation_id INTEGER NOT NULL,
    right_observation_id INTEGER NOT NULL,
    score REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    reason_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected', 'deferred')),
    priority INTEGER NOT NULL DEFAULT 100,
    reviewer_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (left_observation_id < right_observation_id),
    UNIQUE (left_observation_id, right_observation_id),
    FOREIGN KEY (left_observation_id)
        REFERENCES website_page_person_observations(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (right_observation_id)
        REFERENCES website_page_person_observations(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE person_review_queue (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL UNIQUE,
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected', 'deferred')),
    reviewer_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_at TEXT,
    FOREIGN KEY (candidate_id)
        REFERENCES person_resolution_candidates(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE person_merge_history (
    id INTEGER PRIMARY KEY,
    survivor_person_id INTEGER NOT NULL,
    merged_person_id INTEGER NOT NULL,
    decision_source TEXT NOT NULL,
    reason TEXT NOT NULL,
    rolled_back_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (survivor_person_id <> merged_person_id),
    FOREIGN KEY (survivor_person_id) REFERENCES people(id) ON DELETE RESTRICT,
    FOREIGN KEY (merged_person_id) REFERENCES people(id) ON DELETE RESTRICT
);

CREATE TABLE person_merge_affiliation_history (
    merge_history_id INTEGER NOT NULL,
    affiliation_id INTEGER NOT NULL,
    previous_person_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    observed_role TEXT NOT NULL,
    normalized_role TEXT NOT NULL,
    branch_context TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_observation_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('moved', 'deduplicated')),
    PRIMARY KEY (merge_history_id, affiliation_id),
    FOREIGN KEY (merge_history_id) REFERENCES person_merge_history(id) ON DELETE CASCADE
);

CREATE TABLE person_merge_contact_history (
    merge_history_id INTEGER NOT NULL,
    contact_id INTEGER NOT NULL,
    previous_person_id INTEGER NOT NULL,
    contact_type TEXT NOT NULL,
    observed_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_observation_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('moved', 'deduplicated')),
    PRIMARY KEY (merge_history_id, contact_id),
    FOREIGN KEY (merge_history_id) REFERENCES person_merge_history(id) ON DELETE CASCADE
);

CREATE TABLE person_merge_evidence_history (
    merge_history_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL,
    previous_person_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    resolution_candidate_id INTEGER,
    review_decision TEXT,
    PRIMARY KEY (merge_history_id, evidence_id),
    FOREIGN KEY (merge_history_id) REFERENCES person_merge_history(id) ON DELETE CASCADE
);

CREATE INDEX idx_people_normalized_name ON people(normalized_name);
CREATE INDEX idx_people_status ON people(status);
CREATE INDEX idx_person_observation_review_status
    ON person_observation_review_queue(status, id);
CREATE INDEX idx_person_affiliations_person ON person_affiliations(person_id);
CREATE INDEX idx_person_affiliations_entity ON person_affiliations(entity_id);
CREATE INDEX idx_person_affiliations_role ON person_affiliations(normalized_role);
CREATE INDEX idx_person_contacts_person ON person_contact_points(person_id);
CREATE INDEX idx_person_contacts_type_value ON person_contact_points(contact_type, normalized_value);
CREATE INDEX idx_person_evidence_person ON person_evidence(person_id);
CREATE INDEX idx_person_evidence_observation ON person_evidence(observation_id);
CREATE INDEX idx_person_candidates_status_priority
    ON person_resolution_candidates(status, priority, score DESC, id);
CREATE INDEX idx_person_candidates_observations
    ON person_resolution_candidates(left_observation_id, right_observation_id);
CREATE INDEX idx_person_review_status_priority
    ON person_review_queue(status, priority, candidate_id);
CREATE INDEX idx_person_merge_survivor ON person_merge_history(survivor_person_id);
CREATE INDEX idx_person_merge_merged ON person_merge_history(merged_person_id);
