-- Additive product schema for Jev run evidence.
-- Raw state and questions are not stored. Review this file before live use.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS jev_runs (
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

CREATE TABLE IF NOT EXISTS jev_feedback (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES jev_runs(request_id),
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('review', 'correction', 'outcome')),
  assessment TEXT NOT NULL CHECK (assessment IN ('accepted', 'rejected', 'mixed', 'informational')),
  fit TEXT CHECK (fit IS NULL OR fit IN ('fit', 'uncertain', 'not_fit')),
  rationale TEXT,
  evidence_ref TEXT NOT NULL CHECK (length(trim(evidence_ref)) > 0),
  note TEXT
);

CREATE INDEX IF NOT EXISTS jev_feedback_request_created
  ON jev_feedback(request_id, created_at);

CREATE TRIGGER IF NOT EXISTS jev_feedback_no_update
BEFORE UPDATE ON jev_feedback
BEGIN
  SELECT RAISE(ABORT, 'jev_feedback is append-only');
END;

CREATE TRIGGER IF NOT EXISTS jev_feedback_no_delete
BEFORE DELETE ON jev_feedback
BEGIN
  SELECT RAISE(ABORT, 'jev_feedback is append-only');
END;

CREATE VIEW IF NOT EXISTS jev_run_review_status AS
SELECT
  r.request_id,
  CASE WHEN EXISTS (
    SELECT 1 FROM jev_feedback f
    WHERE f.request_id = r.request_id
      AND f.kind = 'review'
      AND length(trim(f.evidence_ref)) > 0
  ) THEN 'reviewed' ELSE 'unchecked' END AS quality_status,
  (SELECT count(*) FROM jev_feedback f WHERE f.request_id = r.request_id) AS evidence_count
FROM jev_runs r;

COMMIT;
