-- Amazon add-on, version 0.1.0. Draft package; requires commerce.
-- Apply to the target workspace database only during authorized installation.
-- Enable SQLite foreign keys in the caller before using these tables.
-- Local operators own accounts and compliance_cases.

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT NOT NULL PRIMARY KEY,
    source_account_id TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    legal_entity TEXT,
    owner TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'closed')),
    function TEXT NOT NULL DEFAULT 'amazon' CHECK (function = 'amazon'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Outside key: seller account + marketplace + seller SKU.
-- Only the listing feeder writes this mirror. Source status is free text.
CREATE TABLE IF NOT EXISTS listings (
    source_account_id TEXT NOT NULL,
    marketplace_id TEXT NOT NULL,
    seller_sku TEXT NOT NULL,
    asin TEXT,
    country TEXT,
    title TEXT,
    source_status TEXT,
    is_suppressed INTEGER CHECK (is_suppressed IN (0, 1)),
    suppression_reason TEXT,
    price REAL CHECK (price >= 0),
    currency TEXT,
    source_updated_at TEXT,
    observed_at TEXT,
    pulled_at TEXT NOT NULL,
    source_url TEXT,
    refresh_run_id TEXT,
    PRIMARY KEY (source_account_id, marketplace_id, seller_sku),
    FOREIGN KEY (source_account_id) REFERENCES accounts (source_account_id)
);

-- Outside key: seller account + advertising profile + campaign ID.
-- Only the advertising feeder writes this mirror. Do not store performance
-- totals without their reporting windows; performance is outside T9.
CREATE TABLE IF NOT EXISTS ads_campaigns (
    source_account_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    marketplace_id TEXT,
    name TEXT,
    source_status TEXT,
    source_campaign_type TEXT,
    budget_amount REAL CHECK (budget_amount >= 0),
    source_budget_period TEXT,
    currency TEXT,
    starts_on TEXT,
    ends_on TEXT,
    source_updated_at TEXT,
    observed_at TEXT,
    pulled_at TEXT NOT NULL,
    source_url TEXT,
    refresh_run_id TEXT,
    PRIMARY KEY (source_account_id, profile_id, campaign_id),
    FOREIGN KEY (source_account_id) REFERENCES accounts (source_account_id)
);

-- Local status tracks our work; source_status preserves Amazon's words.
-- A case may concern the account or a specific marketplace and seller SKU.
CREATE TABLE IF NOT EXISTS compliance_cases (
    id TEXT NOT NULL PRIMARY KEY,
    account_id TEXT NOT NULL,
    marketplace_id TEXT,
    seller_sku TEXT,
    source_case_id TEXT,
    source_status TEXT,
    requirement TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'awaiting_external', 'resolved', 'closed')),
    assigned_to TEXT,
    deadline TEXT,
    report_number TEXT,
    evidence_refs TEXT CHECK (evidence_refs IS NULL OR
        (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array')),
    source_url TEXT,
    function TEXT NOT NULL DEFAULT 'amazon' CHECK (function = 'amazon'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (seller_sku IS NULL OR marketplace_id IS NOT NULL),
    FOREIGN KEY (account_id) REFERENCES accounts (id)
);

-- Append-only writer contract: one metric and source window per as_of.
-- source_window preserves the source's window identifier or dated interval.
-- Writers retain original units, thresholds, source timestamps and missing data.
CREATE TABLE IF NOT EXISTS account_health_history (
    source_account_id TEXT NOT NULL,
    marketplace_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    source_window TEXT NOT NULL,
    as_of TEXT NOT NULL,
    value REAL,
    unit TEXT,
    threshold REAL,
    threshold_operator TEXT
        CHECK (threshold_operator IN ('lt', 'lte', 'eq', 'gte', 'gt')),
    source_status TEXT,
    warning_count INTEGER CHECK (warning_count >= 0),
    violation_count INTEGER CHECK (violation_count >= 0),
    observed_at TEXT NOT NULL,
    source_pulled_at TEXT NOT NULL,
    source_through TEXT,
    source_url TEXT,
    refresh_run_id TEXT,
    definition_version TEXT NOT NULL,
    PRIMARY KEY (source_account_id, marketplace_id, metric, source_window, as_of),
    FOREIGN KEY (source_account_id) REFERENCES accounts (source_account_id)
);

CREATE VIEW IF NOT EXISTS v_suppressed_listings AS
SELECT source_account_id, marketplace_id, seller_sku, asin, country,
       title, source_status, is_suppressed, suppression_reason,
       price, currency, source_updated_at, observed_at, pulled_at,
       source_url, refresh_run_id
FROM listings
WHERE is_suppressed = 1;

CREATE VIEW IF NOT EXISTS v_open_compliance_cases AS
SELECT id, account_id, marketplace_id, seller_sku, source_case_id,
       source_status, requirement, status, assigned_to, deadline,
       report_number, evidence_refs, source_url, function,
       created_at, updated_at
FROM compliance_cases
WHERE status IN ('open', 'in_progress', 'awaiting_external');
