CREATE SCHEMA IF NOT EXISTS fhsi;

CREATE TABLE IF NOT EXISTS fhsi.schema_migrations (
    version text PRIMARY KEY,
    name text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fhsi.organizations (
    organization_id text PRIMARY KEY,
    canonical_name text NOT NULL,
    city text NOT NULL DEFAULT '',
    province text NOT NULL DEFAULT '',
    country text NOT NULL DEFAULT 'Canada',
    record_type text NOT NULL DEFAULT '',
    directory_index integer,
    website_status text NOT NULL DEFAULT '',
    founded_year text NOT NULL DEFAULT '',
    ownership_type text NOT NULL DEFAULT '',
    parent_organization text NOT NULL DEFAULT '',
    service_area text NOT NULL DEFAULT '',
    service_offering text NOT NULL DEFAULT '',
    languages_offered text NOT NULL DEFAULT '',
    source_system text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_system, directory_index)
);

CREATE INDEX IF NOT EXISTS organizations_name_city_idx
    ON fhsi.organizations (lower(canonical_name), lower(city), province);

CREATE TABLE IF NOT EXISTS fhsi.source_records (
    source_system text NOT NULL,
    source_record_id text NOT NULL,
    organization_id text NOT NULL REFERENCES fhsi.organizations(organization_id),
    source_name text NOT NULL DEFAULT '',
    payload jsonb NOT NULL,
    payload_sha256 text NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_record_id)
);

CREATE INDEX IF NOT EXISTS source_records_organization_idx
    ON fhsi.source_records (organization_id);

CREATE TABLE IF NOT EXISTS fhsi.organization_websites (
    website_id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES fhsi.organizations(organization_id),
    url text NOT NULL,
    domain text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT '',
    is_canonical boolean NOT NULL DEFAULT true,
    source_system text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, url)
);

CREATE INDEX IF NOT EXISTS organization_websites_domain_idx
    ON fhsi.organization_websites (lower(domain));

CREATE TABLE IF NOT EXISTS fhsi.evidence_sources (
    evidence_id text PRIMARY KEY,
    source_url text NOT NULL DEFAULT '',
    source_file text NOT NULL DEFAULT '',
    source_text_sha256 text NOT NULL DEFAULT '',
    source_html_sha256 text NOT NULL DEFAULT '',
    evidence_class text NOT NULL DEFAULT '',
    evidence_excerpt text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS evidence_sources_url_idx
    ON fhsi.evidence_sources (source_url);

CREATE TABLE IF NOT EXISTS fhsi.contacts (
    contact_id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES fhsi.organizations(organization_id),
    contact_type text NOT NULL CHECK (contact_type IN ('email', 'phone')),
    normalized_value text NOT NULL,
    classification text NOT NULL DEFAULT 'BRANCH_SAFE',
    evidence_id text REFERENCES fhsi.evidence_sources(evidence_id),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, contact_type, normalized_value, evidence_id)
);

CREATE INDEX IF NOT EXISTS contacts_value_idx
    ON fhsi.contacts (contact_type, normalized_value);
CREATE INDEX IF NOT EXISTS contacts_organization_idx
    ON fhsi.contacts (organization_id);

CREATE TABLE IF NOT EXISTS fhsi.people (
    person_id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES fhsi.organizations(organization_id),
    full_name text NOT NULL,
    title text NOT NULL DEFAULT '',
    is_decision_maker boolean NOT NULL DEFAULT false,
    evidence_id text REFERENCES fhsi.evidence_sources(evidence_id),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, full_name, title, evidence_id)
);

CREATE INDEX IF NOT EXISTS people_organization_idx ON fhsi.people (organization_id);
CREATE INDEX IF NOT EXISTS people_decision_maker_idx
    ON fhsi.people (organization_id) WHERE is_decision_maker;

CREATE TABLE IF NOT EXISTS fhsi.research_facts (
    fact_id text PRIMARY KEY,
    organization_id text REFERENCES fhsi.organizations(organization_id),
    field_name text NOT NULL,
    value jsonb NOT NULL,
    confidence double precision,
    verification_state text NOT NULL DEFAULT '',
    evidence_id text REFERENCES fhsi.evidence_sources(evidence_id),
    detector text NOT NULL DEFAULT '',
    detector_version text NOT NULL DEFAULT '',
    observed_at timestamptz,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS research_facts_org_field_idx
    ON fhsi.research_facts (organization_id, field_name);

CREATE TABLE IF NOT EXISTS fhsi.manual_review_findings (
    finding_id text PRIMARY KEY,
    organization_id text REFERENCES fhsi.organizations(organization_id),
    finding_type text NOT NULL,
    status text NOT NULL,
    severity text NOT NULL DEFAULT '',
    evidence_id text REFERENCES fhsi.evidence_sources(evidence_id),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_system text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS manual_review_status_idx
    ON fhsi.manual_review_findings (status, severity);

CREATE TABLE IF NOT EXISTS fhsi.organization_resolutions (
    resolution_id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES fhsi.organizations(organization_id),
    related_organization_id text REFERENCES fhsi.organizations(organization_id),
    resolution_type text NOT NULL,
    status text NOT NULL,
    evidence_id text REFERENCES fhsi.evidence_sources(evidence_id),
    rationale text NOT NULL DEFAULT '',
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS organization_resolutions_org_idx
    ON fhsi.organization_resolutions (organization_id, status);

CREATE TABLE IF NOT EXISTS fhsi.crm_lead_snapshots (
    domain text PRIMARY KEY,
    organization_id text REFERENCES fhsi.organizations(organization_id),
    company_name text NOT NULL DEFAULT '',
    pipeline_stage text NOT NULL DEFAULT '',
    crm_status text NOT NULL DEFAULT '',
    priority_score double precision,
    priority_level text NOT NULL DEFAULT '',
    contact_method text NOT NULL DEFAULT '',
    primary_email text NOT NULL DEFAULT '',
    primary_phone text NOT NULL DEFAULT '',
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_action text NOT NULL DEFAULT '',
    follow_up_date text NOT NULL DEFAULT '',
    crm_sync_safe boolean NOT NULL DEFAULT false,
    outreach_ready boolean NOT NULL DEFAULT false,
    source_updated_at text NOT NULL DEFAULT '',
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS crm_lead_readiness_idx
    ON fhsi.crm_lead_snapshots (crm_sync_safe, outreach_ready);

COMMENT ON TABLE fhsi.crm_lead_snapshots IS
    'Read-only migration snapshot. SQLite remains authoritative for workflow and outreach state.';
