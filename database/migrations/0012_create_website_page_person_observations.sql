CREATE TABLE website_page_person_observations (
    id INTEGER PRIMARY KEY,
    website_page_id INTEGER NOT NULL,
    website_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    observed_name TEXT NOT NULL
        CHECK (length(trim(observed_name)) > 0),
    normalized_name TEXT NOT NULL
        CHECK (length(trim(normalized_name)) > 0),
    role_title TEXT NOT NULL
        CHECK (length(trim(role_title)) > 0),
    normalized_role TEXT NOT NULL
        CHECK (length(trim(normalized_role)) > 0),
    email TEXT,
    normalized_email TEXT NOT NULL DEFAULT '',
    phone TEXT,
    normalized_phone TEXT NOT NULL DEFAULT '',
    branch_context TEXT,
    confidence REAL NOT NULL
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extraction_method TEXT NOT NULL
        CHECK (extraction_method IN (
            'structured_role_block',
            'role_adjacent_name'
        )),
    extractor_version TEXT NOT NULL
        CHECK (length(trim(extractor_version)) > 0),
    evidence_snippet TEXT NOT NULL
        CHECK (length(trim(evidence_snippet)) > 0),
    source_url TEXT NOT NULL
        CHECK (length(trim(source_url)) > 0),
    content_hash TEXT NOT NULL
        CHECK (length(trim(content_hash)) = 64),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (
        website_page_id,
        content_hash,
        normalized_name,
        normalized_role,
        normalized_email,
        normalized_phone
    ),
    FOREIGN KEY (website_page_id)
        REFERENCES website_pages(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (website_id)
        REFERENCES websites(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (entity_id)
        REFERENCES entities(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX idx_page_person_observations_page
    ON website_page_person_observations(website_page_id);

CREATE INDEX idx_page_person_observations_website
    ON website_page_person_observations(website_id);

CREATE INDEX idx_page_person_observations_entity
    ON website_page_person_observations(entity_id);

CREATE INDEX idx_page_person_observations_email
    ON website_page_person_observations(normalized_email);

CREATE INDEX idx_page_person_observations_phone
    ON website_page_person_observations(normalized_phone);

CREATE INDEX idx_page_person_observations_name
    ON website_page_person_observations(normalized_name);

CREATE INDEX idx_page_person_observations_content_hash
    ON website_page_person_observations(content_hash);
