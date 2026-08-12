CREATE TABLE website_checks (
    id INTEGER PRIMARY KEY,
    website_id INTEGER NOT NULL,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    dns_status TEXT NOT NULL DEFAULT 'not_checked'
        CHECK (dns_status IN (
            'not_checked',
            'ok',
            'failed'
        )),
    dns_addresses TEXT NOT NULL DEFAULT '[]',
    tls_status TEXT NOT NULL DEFAULT 'not_checked'
        CHECK (tls_status IN (
            'not_checked',
            'ok',
            'failed',
            'not_applicable'
        )),
    tls_expires_at TEXT,
    https_status_code INTEGER
        CHECK (
            https_status_code IS NULL
            OR (
                https_status_code >= 100
                AND https_status_code <= 599
            )
        ),
    http_status_code INTEGER
        CHECK (
            http_status_code IS NULL
            OR (
                http_status_code >= 100
                AND http_status_code <= 599
            )
        ),
    redirect_count INTEGER NOT NULL DEFAULT 0
        CHECK (redirect_count >= 0),
    response_time_ms INTEGER
        CHECK (
            response_time_ms IS NULL
            OR response_time_ms >= 0
        ),
    content_type TEXT,
    canonical_url TEXT,
    soft_404 INTEGER NOT NULL DEFAULT 0
        CHECK (soft_404 IN (0, 1)),
    parked_or_for_sale INTEGER NOT NULL DEFAULT 0
        CHECK (parked_or_for_sale IN (0, 1)),
    identity_score REAL
        CHECK (
            identity_score IS NULL
            OR (
                identity_score >= 0.0
                AND identity_score <= 1.0
            )
        ),
    outcome TEXT NOT NULL DEFAULT 'unknown'
        CHECK (outcome IN (
            'unknown',
            'reachable',
            'unreachable',
            'mismatch',
            'parked'
        )),
    error_message TEXT,
    checked_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (website_id)
        REFERENCES websites(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX idx_website_checks_website_checked_at
    ON website_checks(website_id, checked_at DESC, id DESC);

CREATE INDEX idx_website_checks_outcome_checked_at
    ON website_checks(outcome, checked_at DESC);
