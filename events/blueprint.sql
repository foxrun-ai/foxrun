-- Events blueprint. It defines the tables for what happened. Each table name starts with the word events.
--
-- Five tables come from base/schema.sql, blueprint 13, each under its events name:
--   work_changes -> events_changes        work_comments -> events_comments
--   work_attachments -> events_attachments  base_receipts -> events_receipts
--   work_runs -> events_runs
-- Only the table name changes. Every column and every check is the product's.
-- The Jev skill owns events_jev_runs and events_jev_feedback.
-- Their source is skills/jev/references/agent-os-migration.sql.
--
-- Load this file with connect() of base/person.py. Plain sqlite3 lacks foxrun_workspace_allowed.
-- The commands of today (events/log.py, work/work.py) read the old tables: activity, comments, attachments, runs.
-- The write guards and the seq counter are in base/guards.sql, for the old names. They are not in this file.
-- The old database builder (base/build_database.py) does not build this file. events/tests/test_blueprint.py checks it.

CREATE TABLE IF NOT EXISTS "events_changes" (
  "action" TEXT NOT NULL CHECK ("action" IN ('created','updated','moved','archived','deleted','captured','imported','claimed','started','finished','failed','verified','accepted','decided','replaced','corrected','merged','released','published','sent','fixed','restored','closed','rolled-back')),
  "actor" TEXT NOT NULL,
  "detail_id" INTEGER,
  "detail_type" TEXT CHECK ("detail_type" IN ('comment','attachment','run','approval','receipt','proposal')),
  "field" TEXT,
  "new_value" TEXT,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "old_value" TEXT,
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file','snapshot','account-market','approval','attachment','change','comment','deliverable-content','draft-fact','field','handle-snapshot','link','measure-observation','module','object-type','page','receipt','restock-recommendation','value','capability')),
  "subject_version" TEXT,
  "summary" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace",1)),
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (workspace <> 'foxrun' OR subject_type='function'),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE TABLE IF NOT EXISTS "events_comments" (
  "action" TEXT NOT NULL CHECK ("action" IN ('commented')),
  "actor" TEXT NOT NULL,
  "body" TEXT NOT NULL,
  "field" TEXT,
  "flag" INTEGER CHECK ("flag" IN (0,1)),
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "reply_to" INTEGER,
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file')),
  "summary" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  FOREIGN KEY ("reply_to") REFERENCES "events_comments"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE INDEX IF NOT EXISTS "events_comments_link_0" ON "events_comments"("reply_to");

CREATE TABLE IF NOT EXISTS "events_attachments" (
  "action" TEXT NOT NULL CHECK ("action" IN ('attached','published')),
  "actor" TEXT NOT NULL,
  "bytes" INTEGER,
  "hash" TEXT,
  "kind" TEXT,
  "mime_type" TEXT,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "path" TEXT,
  "payload" TEXT,
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "role" TEXT NOT NULL CHECK ("role" IN ('produced','evidence')),
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file','page')),
  "summary" TEXT,
  "url" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (coalesce(length(trim(path)),0)>0 OR coalesce(length(trim(url)),0)>0 OR coalesce(length(payload),0)>0),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE TABLE IF NOT EXISTS "events_receipts" (
  "action" TEXT NOT NULL CHECK ("action" IN ('handed-off','compacted','forked','closed')),
  "actor" TEXT NOT NULL,
  "handoff_path" TEXT,
  "last_seq" INTEGER,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "parent_session" TEXT,
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "runtime" TEXT,
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('session')),
  "summary" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (action NOT IN ('handed-off','compacted','closed') OR last_seq IS NOT NULL),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE TABLE IF NOT EXISTS "events_runs" (
  "actor" TEXT NOT NULL,
  "cost_micro" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "currency" TEXT,
  "ended_at" TEXT CHECK ("ended_at" IS NULL OR julianday("ended_at") IS NOT NULL),
  "fix_rounds" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "log_path" TEXT,
  "model" TEXT,
  "note" TEXT,
  "number" TEXT NOT NULL,
  "proof" TEXT,
  "result" TEXT,
  "runtime" TEXT,
  "session" TEXT,
  "started_at" TEXT CHECK ("started_at" IS NULL OR julianday("started_at") IS NOT NULL),
  "status" TEXT NOT NULL CHECK ("status" IN ('running','succeeded','failed','partial','canceled','unknown')),
  "subject_id" INTEGER,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','workflow','feeder')),
  "tokens" INTEGER,
  "tool" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  CHECK (("cost_micro" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

-- The Jev skill owns the next two tables. Index, trigger, and view names are the skill's.
CREATE TABLE IF NOT EXISTS events_jev_runs (
  request_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
  use_case TEXT NOT NULL,
  model_requested TEXT NOT NULL,
  model_returned TEXT,
  model_version TEXT,
  provider_generation_id TEXT,
  sdk_version TEXT NOT NULL,
  request_schema_version TEXT NOT NULL,
  question_set_version TEXT NOT NULL,
  state_schema_version TEXT NOT NULL,
  input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
  question_types_json TEXT NOT NULL,
  result_json TEXT,
  output_ref TEXT,
  elapsed_ms INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER,
  total_tokens INTEGER,
  provider_cost_amount REAL,
  provider_cost_currency TEXT,
  provider_cost_source TEXT,
  error_code TEXT
);

CREATE TABLE IF NOT EXISTS events_jev_feedback (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES events_jev_runs(request_id),
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('review', 'correction', 'outcome')),
  assessment TEXT NOT NULL CHECK (assessment IN ('accepted', 'rejected', 'mixed', 'informational')),
  fit TEXT CHECK (fit IS NULL OR fit IN ('fit', 'uncertain', 'not_fit')),
  rationale TEXT,
  evidence_ref TEXT NOT NULL CHECK (length(trim(evidence_ref)) > 0),
  note TEXT
);

CREATE INDEX IF NOT EXISTS jev_feedback_request_created
  ON events_jev_feedback(request_id, created_at);

CREATE TRIGGER IF NOT EXISTS jev_feedback_no_update
BEFORE UPDATE ON events_jev_feedback
BEGIN
  SELECT RAISE(ABORT, 'events_jev_feedback is append-only');
END;

CREATE TRIGGER IF NOT EXISTS jev_feedback_no_delete
BEFORE DELETE ON events_jev_feedback
BEGIN
  SELECT RAISE(ABORT, 'events_jev_feedback is append-only');
END;

CREATE VIEW IF NOT EXISTS jev_run_review_status AS
SELECT
  r.request_id,
  CASE WHEN EXISTS (
    SELECT 1 FROM events_jev_feedback f
    WHERE f.request_id = r.request_id
      AND f.kind = 'review'
      AND length(trim(f.evidence_ref)) > 0
  ) THEN 'reviewed' ELSE 'unchecked' END AS quality_status,
  (SELECT count(*) FROM events_jev_feedback f WHERE f.request_id = r.request_id) AS evidence_count
FROM events_jev_runs r;
