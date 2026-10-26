-- People 0.1.0: draft, base, ours. Install into the workspace database.
-- Enable foreign_keys on each connection before using these tables.
-- Messages are a one-way small-talk mirror; never edit them locally.

CREATE TABLE IF NOT EXISTS persons (
  id TEXT PRIMARY KEY NOT NULL,
  display_name TEXT NOT NULL,
  portfolio_person_id TEXT,
  aliases TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(aliases) AND json_type(aliases) = 'array'),
  primary_comms_channel TEXT,
  note_path TEXT,
  function TEXT,
  source_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(source_refs) AND json_type(source_refs) = 'array'),
  evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organizations (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  domain TEXT,
  note_path TEXT,
  function TEXT,
  evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organization_memberships (
  id TEXT PRIMARY KEY NOT NULL,
  person TEXT NOT NULL REFERENCES persons(id),
  organization TEXT NOT NULL REFERENCES organizations(id),
  role TEXT,
  starts_on TEXT,
  ends_on TEXT,
  evidence_ref TEXT,
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on)
);

CREATE TABLE IF NOT EXISTS handles (
  id TEXT PRIMARY KEY NOT NULL,
  person_id TEXT REFERENCES persons(id),
  channel TEXT NOT NULL,
  account TEXT NOT NULL,
  address TEXT NOT NULL,
  source_contact_id TEXT,
  verified_at TEXT,
  evidence_ref TEXT,
  function TEXT,
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (channel, account, address)
);

CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY NOT NULL,
  channel TEXT NOT NULL,
  source_account_id TEXT NOT NULL,
  source_thread_id TEXT NOT NULL,
  title TEXT,
  workspace_tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(workspace_tags) AND json_type(workspace_tags) = 'array'),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  function TEXT,
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (channel, source_account_id, source_thread_id)
);

CREATE TABLE IF NOT EXISTS participants (
  id TEXT PRIMARY KEY NOT NULL,
  thread_id TEXT NOT NULL REFERENCES threads(id),
  person_id TEXT REFERENCES persons(id),
  handle_id TEXT REFERENCES handles(id),
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (person_id IS NOT NULL OR handle_id IS NOT NULL),
  UNIQUE (thread_id, person_id),
  UNIQUE (thread_id, handle_id)
);

CREATE TABLE IF NOT EXISTS pipelines (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  function TEXT,
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_stages (
  pipeline TEXT NOT NULL REFERENCES pipelines(id),
  stage TEXT NOT NULL,
  ord INTEGER NOT NULL CHECK (typeof(ord) = 'integer' AND ord >= 0),
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  PRIMARY KEY (pipeline, stage),
  UNIQUE (pipeline, ord)
);

CREATE TABLE IF NOT EXISTS opportunities (
  id TEXT PRIMARY KEY NOT NULL,
  title TEXT NOT NULL,
  person_id TEXT REFERENCES persons(id),
  organization_id TEXT REFERENCES organizations(id),
  primary_handle_id TEXT REFERENCES handles(id),
  pipeline TEXT NOT NULL REFERENCES pipelines(id),
  stage TEXT NOT NULL,
  outcome TEXT NOT NULL DEFAULT 'open' CHECK (outcome IN ('open', 'won', 'lost', 'abandoned')),
  value REAL,
  currency TEXT,
  offer_summary TEXT,
  owner TEXT,
  function TEXT,
  external_opportunity_ref TEXT,
  source_checked_at TEXT,
  evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (pipeline, stage) REFERENCES pipeline_stages(pipeline, stage)
);

CREATE TABLE IF NOT EXISTS messages (
  channel TEXT NOT NULL,
  source_account_id TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  source_thread_id TEXT NOT NULL,
  sender_handle_id TEXT,
  recipient_handle_ids TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(recipient_handle_ids) AND json_type(recipient_handle_ids) = 'array'),
  workspace_tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(workspace_tags) AND json_type(workspace_tags) = 'array'),
  sent_at TEXT,
  direction TEXT CHECK (direction IN ('inbound', 'outbound', 'unknown')),
  source_url TEXT,
  body_ref TEXT,
  delivery_state TEXT,
  content_hash TEXT,
  source_system TEXT NOT NULL,
  source_record_key TEXT,
  source_updated_at TEXT,
  observed_at TEXT,
  pulled_at TEXT NOT NULL,
  refresh_run_id TEXT,
  source_hash TEXT,
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  PRIMARY KEY (channel, source_account_id, source_message_id),
  FOREIGN KEY (channel, source_account_id, source_thread_id)
    REFERENCES threads(channel, source_account_id, source_thread_id)
);

CREATE TABLE IF NOT EXISTS interactions (
  id TEXT PRIMARY KEY NOT NULL,
  person_id TEXT REFERENCES persons(id),
  handle_id TEXT REFERENCES handles(id),
  thread_id TEXT REFERENCES threads(id),
  opportunity_id TEXT REFERENCES opportunities(id),
  author_person_id TEXT REFERENCES persons(id),
  summary_author TEXT NOT NULL,
  happened_at TEXT NOT NULL,
  summary TEXT NOT NULL,
  source_link TEXT,
  source_channel TEXT,
  source_account_id TEXT,
  source_message_id TEXT,
  function TEXT,
  evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (source_channel, source_account_id, source_message_id)
    REFERENCES messages(channel, source_account_id, source_message_id),
  CHECK ((source_channel IS NULL AND source_account_id IS NULL AND source_message_id IS NULL)
      OR (source_channel IS NOT NULL AND source_account_id IS NOT NULL AND source_message_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS meetings (
  id TEXT PRIMARY KEY NOT NULL,
  title TEXT NOT NULL,
  happened_at TEXT NOT NULL,
  ended_at TEXT,
  thread_id TEXT REFERENCES threads(id),
  person_id TEXT REFERENCES persons(id),
  organization_id TEXT REFERENCES organizations(id),
  opportunity_id TEXT REFERENCES opportunities(id),
  summary TEXT,
  transcript_path TEXT,
  source_url TEXT,
  function TEXT,
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (ended_at IS NULL OR ended_at >= happened_at)
);

CREATE TABLE IF NOT EXISTS agreements (
  id TEXT PRIMARY KEY NOT NULL,
  agreement_family_id TEXT NOT NULL,
  version TEXT NOT NULL,
  opportunity_id TEXT REFERENCES opportunities(id),
  counterparty_person_id TEXT REFERENCES persons(id),
  counterparty_organization_id TEXT REFERENCES organizations(id),
  type TEXT NOT NULL CHECK (type IN ('client', 'creator', 'ambassador', 'vendor')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'signed', 'expired')),
  start TEXT,
  end TEXT,
  value REAL,
  currency TEXT,
  file_path TEXT,
  file_hash TEXT,
  signed_at TEXT,
  supersedes_id TEXT REFERENCES agreements(id),
  rights_summary TEXT,
  function TEXT,
  evidence_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'),
  tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (agreement_family_id, version),
  CHECK ((counterparty_person_id IS NOT NULL AND counterparty_organization_id IS NULL)
      OR (counterparty_person_id IS NULL AND counterparty_organization_id IS NOT NULL)),
  CHECK (start IS NULL OR end IS NULL OR end >= start)
);

CREATE VIEW IF NOT EXISTS v_open_threads AS
SELECT t.id, t.title, t.channel, t.source_account_id, t.source_thread_id,
       t.workspace_tags, t.status, t.function,
       (SELECT count(*) FROM participants p WHERE p.thread_id = t.id) AS participant_count,
       (SELECT max(m.sent_at) FROM messages m
        WHERE m.channel = t.channel AND m.source_account_id = t.source_account_id
          AND m.source_thread_id = t.source_thread_id) AS last_message_at,
       (SELECT max(m.pulled_at) FROM messages m
        WHERE m.channel = t.channel AND m.source_account_id = t.source_account_id
          AND m.source_thread_id = t.source_thread_id) AS last_pulled_at
FROM threads t
WHERE t.status = 'open';

CREATE VIEW IF NOT EXISTS v_pipeline_board AS
SELECT p.id AS pipeline, p.name AS pipeline_name, s.stage, s.ord,
       o.id AS opportunity_id, o.title, o.outcome, o.person_id,
       pe.display_name AS person_name, o.organization_id, org.name AS organization_name,
       o.value, o.currency, o.owner, o.function
FROM pipelines p
JOIN pipeline_stages s ON s.pipeline = p.id
LEFT JOIN opportunities o ON o.pipeline = s.pipeline AND o.stage = s.stage AND o.outcome = 'open'
LEFT JOIN persons pe ON pe.id = o.person_id
LEFT JOIN organizations org ON org.id = o.organization_id;

CREATE VIEW IF NOT EXISTS v_people_without_handles AS
SELECT p.id, p.display_name, p.portfolio_person_id, p.note_path, p.function, p.tags
FROM persons p
WHERE NOT EXISTS (SELECT 1 FROM handles h WHERE h.person_id = p.id);
