CREATE TABLE website_pages (
    id INTEGER PRIMARY KEY,
    website_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    path TEXT NOT NULL,
    page_kind TEXT NOT NULL DEFAULT 'other'
        CHECK (page_kind IN (
            'root',
            'about',
            'team',
            'staff',
            'people',
            'directors',
            'professionals',
            'locations',
            'contact',
            'history',
            'management',
            'personnel',
            'other'
        )),
    priority_score INTEGER NOT NULL DEFAULT 0,
    depth INTEGER NOT NULL DEFAULT 0
        CHECK (depth >= 0),
    discovered_from_url TEXT,
    link_text TEXT,
    status_code INTEGER
        CHECK (
            status_code IS NULL
            OR (
                status_code >= 100
                AND status_code <= 599
            )
        ),
    content_type TEXT,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (website_id, normalized_url),
    FOREIGN KEY (website_id)
        REFERENCES websites(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX idx_website_pages_website_priority
ON website_pages(website_id, priority_score DESC, id);

CREATE INDEX idx_website_pages_kind
ON website_pages(page_kind);

CREATE INDEX idx_website_pages_path
ON website_pages(path);
