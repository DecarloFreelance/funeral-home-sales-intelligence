ALTER TABLE website_pages
    ADD COLUMN last_fetched_at TEXT;

ALTER TABLE website_pages
    ADD COLUMN last_success_at TEXT;

ALTER TABLE website_pages
    ADD COLUMN last_failure_at TEXT;

ALTER TABLE website_pages
    ADD COLUMN last_status_code INTEGER
        CHECK (
            last_status_code IS NULL
            OR (
                last_status_code >= 100
                AND last_status_code <= 599
            )
        );

ALTER TABLE website_pages
    ADD COLUMN last_content_type TEXT;

ALTER TABLE website_pages
    ADD COLUMN last_error TEXT;

ALTER TABLE website_pages
    ADD COLUMN last_content_hash TEXT
        CHECK (
            last_content_hash IS NULL
            OR length(trim(last_content_hash)) = 64
        );
