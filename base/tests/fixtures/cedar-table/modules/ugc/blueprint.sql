-- UGC 0.1.0; T9. Draft schema only; no source calls or business seeds.
-- Requires people. The installer enables foreign_keys before transactions.
-- External module IDs remain references; people owns their table definitions.
-- Writers validate approved tags, ISO times, exact decimals, and evidence scope.
-- The trend writer is append-only; this CREATE-only package installs no triggers.

CREATE TABLE IF NOT EXISTS creator_cycles (
    id TEXT PRIMARY KEY NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    cycle_key TEXT NOT NULL,
    name TEXT NOT NULL,
    cycle_type TEXT NOT NULL CHECK (cycle_type IN ('recurring', 'one_off')),
    period_start TEXT,
    period_end TEXT,
    agreement_id TEXT REFERENCES agreements(id),
    agreed_amount TEXT,
    currency TEXT,
    amount_unknown_reason TEXT,
    legacy_phase TEXT,
    next_task_id TEXT,
    shipment_ids TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(shipment_ids) AND json_type(shipment_ids) = 'array'),
    closed_at TEXT,
    closure_evidence_ref TEXT,
    closed_with_exceptions TEXT,
    function TEXT NOT NULL DEFAULT 'ugc' CHECK (function = 'ugc'),
    tags TEXT NOT NULL DEFAULT '["ugc"]' CHECK (json_valid(tags) AND json_type(tags) = 'array' AND json_array_length(tags) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
    import_key TEXT UNIQUE,
    conflict_status TEXT NOT NULL DEFAULT 'clear' CHECK (conflict_status IN ('clear', 'unresolved', 'resolved')),
    UNIQUE (opportunity_id, cycle_key),
    CHECK (period_start IS NULL OR period_end IS NULL OR period_end >= period_start),
    CHECK (agreed_amount IS NOT NULL OR amount_unknown_reason IS NOT NULL),
    CHECK (agreed_amount IS NULL OR currency IS NOT NULL),
    CHECK (closed_at IS NULL OR closure_evidence_ref IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY NOT NULL,
    creator_cycle_id TEXT NOT NULL REFERENCES creator_cycles(id),
    agreement_id TEXT REFERENCES agreements(id),
    promise_key TEXT NOT NULL,
    format TEXT NOT NULL,
    platform TEXT,
    quantity INTEGER CHECK (quantity IS NULL OR (typeof(quantity) = 'integer' AND quantity > 0)),
    quantity_unknown_reason TEXT,
    due_date TEXT,
    required_shots TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(required_shots) AND json_type(required_shots) = 'array'),
    acceptance_criteria TEXT,
    published_required INTEGER CHECK (published_required IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'agreed', 'waived')),
    task_id TEXT,
    waiver_ref TEXT,
    function TEXT NOT NULL DEFAULT 'ugc' CHECK (function = 'ugc'),
    tags TEXT NOT NULL DEFAULT '["ugc"]' CHECK (json_valid(tags) AND json_type(tags) = 'array' AND json_array_length(tags) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
    import_key TEXT UNIQUE,
    conflict_status TEXT NOT NULL DEFAULT 'clear' CHECK (conflict_status IN ('clear', 'unresolved', 'resolved')),
    UNIQUE (creator_cycle_id, promise_key),
    CHECK (quantity IS NOT NULL OR quantity_unknown_reason IS NOT NULL),
    CHECK (status <> 'waived' OR waiver_ref IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS content_permissions (
    id TEXT PRIMARY KEY NOT NULL,
    permission_key TEXT NOT NULL UNIQUE,
    agreement_id TEXT REFERENCES agreements(id),
    content_id TEXT,
    creator_id TEXT REFERENCES persons(id),
    platform TEXT,
    usage TEXT NOT NULL CHECK (usage IN ('organic', 'paid', 'editing', 'creator_handle')),
    territory TEXT,
    valid_from TEXT,
    valid_until TEXT,
    source_interaction_id TEXT REFERENCES interactions(id),
    evidence_ref TEXT,
    status TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('proposed', 'granted', 'revoked', 'unknown')),
    function TEXT NOT NULL DEFAULT 'ugc' CHECK (function = 'ugc'),
    tags TEXT NOT NULL DEFAULT '["ugc"]' CHECK (json_valid(tags) AND json_type(tags) = 'array' AND json_array_length(tags) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
    import_key TEXT UNIQUE,
    conflict_status TEXT NOT NULL DEFAULT 'clear' CHECK (conflict_status IN ('clear', 'unresolved', 'resolved')),
    CHECK (agreement_id IS NOT NULL OR content_id IS NOT NULL OR creator_id IS NOT NULL),
    CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from),
    CHECK (status <> 'granted' OR (evidence_ref IS NOT NULL AND length(trim(evidence_ref)) > 0))
);

CREATE TABLE IF NOT EXISTS file_reqs (
    id TEXT PRIMARY KEY NOT NULL,
    creator_cycle_id TEXT NOT NULL REFERENCES creator_cycles(id),
    provider TEXT NOT NULL,
    source_id TEXT,
    title TEXT NOT NULL,
    folder_path TEXT,
    url TEXT,
    expires_at TEXT,
    link_state TEXT NOT NULL DEFAULT 'unchecked' CHECK (link_state IN ('unchecked', 'available', 'expired', 'unavailable')),
    checked_at TEXT,
    sent_interaction_id TEXT REFERENCES interactions(id),
    received_at TEXT,
    status TEXT NOT NULL DEFAULT 'prepared' CHECK (status IN ('prepared', 'created', 'sent', 'received', 'closed')),
    approval_ref TEXT,
    receipt_ref TEXT,
    function TEXT NOT NULL DEFAULT 'ugc' CHECK (function = 'ugc'),
    tags TEXT NOT NULL DEFAULT '["ugc"]' CHECK (json_valid(tags) AND json_type(tags) = 'array' AND json_array_length(tags) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
    import_key TEXT UNIQUE,
    conflict_status TEXT NOT NULL DEFAULT 'clear' CHECK (conflict_status IN ('clear', 'unresolved', 'resolved')),
    UNIQUE (provider, source_id),
    CHECK (status = 'prepared' OR (source_id IS NOT NULL AND approval_ref IS NOT NULL AND receipt_ref IS NOT NULL)),
    CHECK (status NOT IN ('sent', 'received') OR sent_interaction_id IS NOT NULL),
    CHECK (status <> 'received' OR received_at IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS payments_owed_daily (
    obligation_id TEXT NOT NULL,
    request_version INTEGER NOT NULL CHECK (request_version > 0),
    person_id TEXT NOT NULL REFERENCES persons(id),
    creator_cycle_id TEXT REFERENCES creator_cycles(id),
    currency TEXT NOT NULL,
    as_of TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    agreed_amount TEXT,
    requested_amount TEXT,
    reported_paid_amount TEXT,
    confirmed_amount TEXT,
    disputed_amount TEXT,
    owed_amount TEXT,
    amount_unknown_reason TEXT,
    due_at TEXT,
    days_overdue INTEGER CHECK (days_overdue IS NULL OR (typeof(days_overdue) = 'integer' AND days_overdue >= 0)),
    evidence_state TEXT NOT NULL CHECK (evidence_state IN ('unknown', 'unverified', 'reported', 'verified_receipt', 'person_confirmation', 'disputed')),
    confirmation_basis TEXT NOT NULL DEFAULT 'none' CHECK (confirmation_basis IN ('none', 'verified_receipt', 'person_confirmation')),
    proof_ref TEXT,
    confirmed_by TEXT,
    confirmed_at TEXT,
    has_dispute INTEGER NOT NULL DEFAULT 0 CHECK (has_dispute IN (0, 1)),
    observed_at TEXT NOT NULL,
    source_through TEXT,
    source_pulled_at TEXT,
    refresh_run_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    coverage_status TEXT NOT NULL DEFAULT 'unknown' CHECK (coverage_status IN ('complete', 'partial', 'unknown')),
    source_hash TEXT NOT NULL,
    function TEXT NOT NULL DEFAULT 'ugc' CHECK (function = 'ugc'),
    tags TEXT NOT NULL DEFAULT '["ugc"]' CHECK (json_valid(tags) AND json_type(tags) = 'array' AND json_array_length(tags) > 0),
    evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
    conflict_status TEXT NOT NULL DEFAULT 'clear' CHECK (conflict_status IN ('clear', 'unresolved', 'resolved')),
    PRIMARY KEY (obligation_id, request_version, person_id, currency, as_of),
    UNIQUE (obligation_id, request_version, person_id, currency, scheduled_for),
    CHECK (agreed_amount IS NOT NULL AND owed_amount IS NOT NULL OR amount_unknown_reason IS NOT NULL),
    CHECK (confirmation_basis = 'none' OR (
        proof_ref IS NOT NULL AND length(trim(proof_ref)) > 0
        AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)),
    CHECK (confirmed_amount IS NULL OR (
        confirmed_amount GLOB '[0-9]*' AND confirmed_amount NOT GLOB '*[^0-9.]*'
        AND confirmed_amount NOT LIKE '%.%.%' AND confirmed_amount NOT LIKE '%.'
        AND (length(ltrim(replace(confirmed_amount, '.', ''), '0')) = 0 OR confirmation_basis <> 'none'))),
    CHECK (evidence_state NOT IN ('verified_receipt', 'person_confirmation') OR evidence_state = confirmation_basis),
    CHECK (evidence_state <> 'disputed' OR has_dispute = 1)
);

CREATE TABLE IF NOT EXISTS media_files (
    source_record_key TEXT PRIMARY KEY NOT NULL,
    source_system TEXT NOT NULL,
    source_account_id TEXT NOT NULL,
    source_instance_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    source_updated_at TEXT,
    observed_at TEXT NOT NULL,
    pulled_at TEXT NOT NULL,
    source_window_start TEXT,
    source_window_end TEXT,
    refresh_run_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_url TEXT,
    identity_status TEXT NOT NULL DEFAULT 'unknown' CHECK (identity_status IN ('verified', 'ambiguous', 'unknown')),
    coverage_status TEXT NOT NULL DEFAULT 'unknown' CHECK (coverage_status IN ('complete', 'partial', 'unknown')),
    creator_cycle_id TEXT,
    deliverable_id TEXT,
    content_id TEXT,
    path TEXT,
    file_hash TEXT,
    bytes INTEGER CHECK (bytes IS NULL OR (typeof(bytes) = 'integer' AND bytes >= 0)),
    mime_type TEXT,
    parent_folder_id TEXT,
    expires_at TEXT,
    availability TEXT NOT NULL DEFAULT 'unknown' CHECK (availability IN ('available', 'expired', 'missing', 'unknown')),
    checked_at TEXT,
    function TEXT NOT NULL DEFAULT 'ugc' CHECK (function = 'ugc'),
    tags TEXT NOT NULL DEFAULT '["ugc"]' CHECK (json_valid(tags) AND json_type(tags) = 'array' AND json_array_length(tags) > 0),
    UNIQUE (source_system, source_account_id, source_instance_id, source_id, version_id)
);

-- People supplies the source-qualified open thread rows and coverage fields.
-- This view intentionally stays dependent on people; no placeholder table ships.
CREATE VIEW IF NOT EXISTS v_reply_queue AS
SELECT t.* FROM v_open_threads AS t WHERE t.function = 'ugc';

-- Keep the latest known observation for each obligation, person, and currency.
-- All same-time conflicting request versions remain visible.
CREATE VIEW IF NOT EXISTS v_payments_owed AS
SELECT p.*,
       CASE WHEN p.confirmation_basis = 'none' OR p.has_dispute = 1
                 OR p.conflict_status = 'unresolved' THEN 1 ELSE 0 END AS ask_person,
       CASE WHEN p.source_through IS NULL THEN NULL
            ELSE CAST(julianday('now') - julianday(p.source_through) AS INTEGER) END AS source_age_days,
       (SELECT COUNT(*) FROM payments_owed_daily AS peer
        WHERE peer.obligation_id = p.obligation_id AND peer.person_id = p.person_id
          AND peer.currency = p.currency AND peer.as_of = p.as_of) > 1 AS version_conflict
FROM payments_owed_daily AS p
WHERE NOT EXISTS (
    SELECT 1 FROM payments_owed_daily AS newer
    WHERE newer.obligation_id = p.obligation_id AND newer.person_id = p.person_id
      AND newer.currency = p.currency AND newer.as_of > p.as_of
);

-- Every unwaived promise stays visible. Files never become acceptance evidence.
CREATE VIEW IF NOT EXISTS v_missing_content AS
SELECT d.id AS deliverable_id, d.creator_cycle_id, c.opportunity_id,
       d.promise_key, d.format, d.platform, d.quantity AS promised_quantity,
       d.quantity_unknown_reason, d.due_date, d.status, d.task_id,
       (SELECT COUNT(DISTINCT m.file_hash) FROM media_files AS m
        WHERE m.deliverable_id = d.id AND m.creator_cycle_id = c.id
          AND m.identity_status = 'verified') AS observed_file_count,
       (SELECT COUNT(DISTINCT m.file_hash) FROM media_files AS m
        WHERE m.deliverable_id = d.id AND m.creator_cycle_id = c.id
          AND m.identity_status = 'verified' AND m.availability = 'available'
          AND (m.expires_at IS NULL OR julianday(m.expires_at) > julianday('now'))) AS available_file_count,
       NULL AS accepted_quantity, NULL AS missing_quantity,
       'unknown: exact acceptance evidence is not loaded' AS acceptance_status,
       (SELECT COUNT(*) FROM file_reqs AS r
        WHERE r.creator_cycle_id = c.id AND r.status <> 'closed') AS open_file_request_count,
       c.closed_at AS cycle_closed_at, d.function, d.tags, d.evidence_refs,
       NULL AS source_through, 'unknown' AS coverage_status,
       CASE WHEN d.conflict_status = 'unresolved' OR c.conflict_status = 'unresolved'
            THEN 'unresolved' ELSE d.conflict_status END AS conflict_status
FROM deliverables AS d JOIN creator_cycles AS c ON c.id = d.creator_cycle_id
WHERE d.status <> 'waived';

CREATE VIEW IF NOT EXISTS v_rights_expiring AS
SELECT p.*,
       CASE WHEN p.status <> 'granted' THEN p.status
            WHEN p.conflict_status = 'unresolved' THEN 'conflicted'
            WHEN p.valid_from IS NULL OR p.valid_until IS NULL
                 OR p.platform IS NULL OR p.territory IS NULL THEN 'unknown_scope'
            WHEN date(p.valid_until) < date('now') THEN 'expired'
            WHEN date(p.valid_until) <= date('now', '+30 days') THEN 'expiring'
            ELSE 'check_required' END AS rights_status,
       CAST(julianday(date(p.valid_until)) - julianday(date('now')) AS INTEGER) AS days_remaining,
       NULL AS source_through, 'unknown' AS coverage_status
FROM content_permissions AS p
WHERE p.status <> 'granted' OR p.conflict_status = 'unresolved'
   OR p.valid_from IS NULL OR p.valid_until IS NULL
   OR p.platform IS NULL OR p.territory IS NULL
   OR date(p.valid_until) <= date('now', '+30 days');
