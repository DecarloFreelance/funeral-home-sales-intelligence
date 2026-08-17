ALTER TABLE website_discovery_runs
ADD COLUMN host_delay_seconds REAL NOT NULL DEFAULT 0.0
CHECK (host_delay_seconds >= 0.0 AND host_delay_seconds <= 60.0);

ALTER TABLE website_discovery_runs
ADD COLUMN max_concurrency INTEGER NOT NULL DEFAULT 1
CHECK (max_concurrency BETWEEN 1 AND 10);
