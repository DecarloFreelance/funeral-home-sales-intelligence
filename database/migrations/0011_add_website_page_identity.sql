ALTER TABLE website_pages
    ADD COLUMN identity_score REAL
        CHECK (
            identity_score IS NULL
            OR (
                identity_score >= 0.0
                AND identity_score <= 1.0
            )
        );

ALTER TABLE website_pages
    ADD COLUMN identity_observable INTEGER NOT NULL DEFAULT 0
        CHECK (identity_observable IN (0, 1));

CREATE INDEX idx_website_pages_identity
    ON website_pages(
        website_id,
        identity_observable,
        identity_score DESC,
        id
    );
