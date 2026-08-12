CREATE TABLE merge_membership_history (
    merge_history_id INTEGER NOT NULL,
    source_record_id INTEGER NOT NULL,
    membership_role TEXT NOT NULL
        CHECK (membership_role IN ('organization', 'location', 'branch')),
    action TEXT NOT NULL
        CHECK (action IN ('moved', 'duplicate')),
    PRIMARY KEY (merge_history_id, source_record_id),
    FOREIGN KEY (merge_history_id)
        REFERENCES merge_history(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (source_record_id)
        REFERENCES source_records(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE merge_parent_history (
    merge_history_id INTEGER NOT NULL,
    child_entity_id INTEGER NOT NULL,
    previous_parent_entity_id INTEGER,
    PRIMARY KEY (merge_history_id, child_entity_id),
    FOREIGN KEY (merge_history_id)
        REFERENCES merge_history(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (child_entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (previous_parent_entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX idx_merge_membership_history_source
    ON merge_membership_history(source_record_id);

CREATE INDEX idx_merge_parent_history_child
    ON merge_parent_history(child_entity_id);
