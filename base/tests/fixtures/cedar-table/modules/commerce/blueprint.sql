-- Commerce 0.1.0: definitions only. No feeders, seed data, or live installation.
-- All mirror primary keys retain outside identity and account scope.
-- Timestamp keys and pulled_at use UTC YYYY-MM-DDTHH:MM:SSZ.
CREATE TABLE IF NOT EXISTS products (
    source_system TEXT NOT NULL CHECK (source_system IN ('shopify')),
    source_account_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT,
    handle TEXT,
    source_status TEXT,
    vendor TEXT,
    product_type TEXT,
    source_url TEXT,
    source_updated_at TEXT,
    pulled_at TEXT NOT NULL CHECK (pulled_at GLOB '????-??-??T??:??:??Z' AND datetime(pulled_at) IS NOT NULL),
    PRIMARY KEY (source_system, source_account_id, source_id)
);

CREATE TABLE IF NOT EXISTS orders (
    source_system TEXT NOT NULL CHECK (source_system IN ('shopify', 'shipbob')),
    source_account_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reference_id TEXT,
    source_channel_id TEXT,
    originating_order_ref TEXT,
    ordered_at TEXT,
    source_status TEXT,
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    total_minor INTEGER,
    source_url TEXT,
    source_updated_at TEXT,
    pulled_at TEXT NOT NULL CHECK (pulled_at GLOB '????-??-??T??:??:??Z' AND datetime(pulled_at) IS NOT NULL),
    PRIMARY KEY (source_system, source_account_id, source_id),
    CHECK (total_minor IS NULL OR currency IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS order_lines (
    source_system TEXT NOT NULL CHECK (source_system IN ('shopify', 'shipbob')),
    source_account_id TEXT NOT NULL,
    order_source_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    product_source_id TEXT,
    variant_source_id TEXT,
    source_sku TEXT,
    quantity INTEGER CHECK (quantity IS NULL OR quantity >= 0),
    unit_price_minor INTEGER,
    line_total_minor INTEGER,
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    source_status TEXT,
    source_updated_at TEXT,
    pulled_at TEXT NOT NULL CHECK (pulled_at GLOB '????-??-??T??:??:??Z' AND datetime(pulled_at) IS NOT NULL),
    PRIMARY KEY (source_system, source_account_id, order_source_id, source_id),
    FOREIGN KEY (source_system, source_account_id, order_source_id)
        REFERENCES orders (source_system, source_account_id, source_id),
    CHECK ((unit_price_minor IS NULL AND line_total_minor IS NULL) OR currency IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS shipments (
    source_system TEXT NOT NULL CHECK (source_system IN ('shipbob')),
    source_account_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    order_source_id TEXT NOT NULL,
    source_status TEXT,
    origin_location_id TEXT,
    carrier TEXT,
    tracking_number TEXT,
    tracking_url TEXT,
    shipped_at TEXT,
    delivered_at TEXT,
    delivery_evidence_ref TEXT,
    source_url TEXT,
    source_updated_at TEXT,
    pulled_at TEXT NOT NULL CHECK (pulled_at GLOB '????-??-??T??:??:??Z' AND datetime(pulled_at) IS NOT NULL),
    PRIMARY KEY (source_system, source_account_id, source_id),
    FOREIGN KEY (source_system, source_account_id, order_source_id)
        REFERENCES orders (source_system, source_account_id, source_id),
    CHECK (delivered_at IS NULL OR (delivery_evidence_ref IS NOT NULL AND length(trim(delivery_evidence_ref)) > 0))
);

-- source_id is the native inventory item ID, scoped by its native location ID.
CREATE TABLE IF NOT EXISTS stock_levels (
    source_system TEXT NOT NULL CHECK (source_system IN ('shopify', 'shipbob')),
    source_account_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    source_sku TEXT,
    on_hand INTEGER,
    available INTEGER,
    reserved INTEGER,
    inbound INTEGER,
    observed_at TEXT,
    source_url TEXT,
    source_updated_at TEXT,
    pulled_at TEXT NOT NULL CHECK (pulled_at GLOB '????-??-??T??:??:??Z' AND datetime(pulled_at) IS NOT NULL),
    PRIMARY KEY (source_system, source_account_id, source_id, location_id)
);

-- No provider is assumed. The future feeder must bind real native review IDs.
CREATE TABLE IF NOT EXISTS customer_reviews (
    source_system TEXT NOT NULL CHECK (length(trim(source_system)) > 0),
    source_account_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    product_source_id TEXT,
    title TEXT,
    body_ref TEXT,
    rating REAL,
    rating_scale_max REAL CHECK (rating_scale_max IS NULL OR rating_scale_max > 0),
    source_status TEXT,
    reviewed_at TEXT,
    source_url TEXT,
    source_updated_at TEXT,
    pulled_at TEXT NOT NULL CHECK (pulled_at GLOB '????-??-??T??:??:??Z' AND datetime(pulled_at) IS NOT NULL),
    PRIMARY KEY (source_system, source_account_id, source_id),
    CHECK (rating IS NULL OR (rating_scale_max IS NOT NULL AND rating >= 0 AND rating <= rating_scale_max))
);

-- Retained observations: no FK to mutable mirrors; future writer appends only.
CREATE TABLE IF NOT EXISTS stock_history (
    source_system TEXT NOT NULL CHECK (source_system IN ('shopify', 'shipbob')),
    source_account_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    as_of TEXT NOT NULL CHECK (as_of GLOB '????-??-??T??:??:??Z' AND datetime(as_of) IS NOT NULL),
    source_sku TEXT,
    on_hand INTEGER,
    available INTEGER,
    reserved INTEGER,
    inbound INTEGER,
    observed_at TEXT,
    source_pulled_at TEXT NOT NULL CHECK (source_pulled_at GLOB '????-??-??T??:??:??Z' AND datetime(source_pulled_at) IS NOT NULL),
    refresh_run_id TEXT NOT NULL,
    PRIMARY KEY (source_system, source_account_id, source_id, location_id, as_of),
    CHECK (source_pulled_at <= as_of)
);

CREATE TABLE IF NOT EXISTS restocks (
    id TEXT NOT NULL PRIMARY KEY,
    source_system TEXT NOT NULL CHECK (source_system IN ('shopify', 'shipbob')),
    source_account_id TEXT NOT NULL,
    inventory_source_id TEXT NOT NULL,
    source_sku TEXT,
    origin_location_id TEXT,
    destination_location_id TEXT NOT NULL,
    requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
    approved_quantity INTEGER CHECK (approved_quantity IS NULL OR approved_quantity >= 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'planned', 'approved', 'ordered', 'in_transit', 'received', 'cancelled')),
    due_on TEXT CHECK (due_on IS NULL OR (date(due_on) IS NOT NULL AND due_on = date(due_on))),
    owner TEXT,
    function TEXT,
    evidence_ref TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS receivings (
    id TEXT NOT NULL PRIMARY KEY,
    restock_id TEXT NOT NULL REFERENCES restocks (id),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    counted_at TEXT NOT NULL,
    counted_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed', 'disputed', 'superseded')),
    supersedes_id TEXT REFERENCES receivings (id),
    evidence_ref TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (supersedes_id IS NULL OR supersedes_id <> id),
    CHECK (status <> 'confirmed' OR (evidence_ref IS NOT NULL AND length(trim(evidence_ref)) > 0))
);

CREATE TABLE IF NOT EXISTS support_cases (
    id TEXT NOT NULL PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('shopify', 'shipbob', 'amazon', 'tiktok_shop', 'other')),
    source_account_id TEXT,
    source_case_id TEXT,
    source_status TEXT,
    subject TEXT NOT NULL,
    owner TEXT,
    function TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'waiting', 'escalated', 'resolved', 'closed')),
    opened_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    next_action TEXT,
    next_action_due_on TEXT CHECK (next_action_due_on IS NULL OR (date(next_action_due_on) IS NOT NULL AND next_action_due_on = date(next_action_due_on))),
    source_url TEXT,
    evidence_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (source_case_id IS NULL OR source_account_id IS NOT NULL)
);

CREATE VIEW IF NOT EXISTS v_low_stock AS
SELECT source_system, source_account_id, source_id, location_id,
       source_sku, on_hand, available, reserved, inbound, observed_at, pulled_at
FROM stock_levels
WHERE available IS NOT NULL AND available <= 0;

CREATE VIEW IF NOT EXISTS v_restock_due AS
SELECT id, source_system, source_account_id, inventory_source_id, source_sku,
       origin_location_id, destination_location_id, requested_quantity,
       approved_quantity, status, due_on, owner, function,
       CAST(julianday(date('now')) - julianday(due_on) AS INTEGER) AS days_overdue
FROM restocks
WHERE status IN ('planned', 'approved', 'ordered', 'in_transit')
  AND due_on IS NOT NULL AND due_on <= date('now');

CREATE VIEW IF NOT EXISTS v_open_support_cases AS
SELECT id, source, source_account_id, source_case_id, source_status,
       subject, owner, function, status, opened_at, next_action,
       next_action_due_on, source_url, evidence_ref, updated_at
FROM support_cases
WHERE status IN ('open', 'waiting', 'escalated');

CREATE VIEW IF NOT EXISTS v_mirror_age AS
SELECT mirror_name, row_count, newest_pulled_at, oldest_pulled_at,
       CAST(strftime('%s', 'now') AS INTEGER)
         - CAST(strftime('%s', newest_pulled_at) AS INTEGER) AS newest_age_seconds
FROM (
    SELECT 'products' AS mirror_name, COUNT(*) AS row_count,
           MAX(pulled_at) AS newest_pulled_at, MIN(pulled_at) AS oldest_pulled_at FROM products
    UNION ALL
    SELECT 'orders', COUNT(*), MAX(pulled_at), MIN(pulled_at) FROM orders
    UNION ALL
    SELECT 'order_lines', COUNT(*), MAX(pulled_at), MIN(pulled_at) FROM order_lines
    UNION ALL
    SELECT 'shipments', COUNT(*), MAX(pulled_at), MIN(pulled_at) FROM shipments
    UNION ALL
    SELECT 'stock_levels', COUNT(*), MAX(pulled_at), MIN(pulled_at) FROM stock_levels
    UNION ALL
    SELECT 'customer_reviews', COUNT(*), MAX(pulled_at), MIN(pulled_at) FROM customer_reviews
);
