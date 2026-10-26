-- Memory blueprint. It defines the four memory tables. Each table name starts with the word memory.
--
-- memory_lessons comes from base/schema.sql, blueprint 13: work_lessons under its memory name. Only the table name changes.
-- memory_sources, memory_evidence, and memory_rollups are new. No older definition exists.
--
-- Load this file with connect() of base/person.py. Plain sqlite3 lacks foxrun_workspace_allowed.
-- No command writes the three new tables yet. The old database builder (base/build_database.py) does not build this file.
-- memory/tests/test_blueprint.py checks this file.

CREATE TABLE IF NOT EXISTS "memory_lessons" (
  "codified_in" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "replay_case" TEXT,
  "skill" TEXT,
  "source" TEXT NOT NULL CHECK ("source" IN ('feedback','lesson','failure')),
  "source_ref" TEXT NOT NULL,
  "status" TEXT NOT NULL CHECK ("status" IN ('open','codified','replaced','canceled')),
  "subject" TEXT NOT NULL,
  "text" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number")
) STRICT;

-- memory_sources: one row for each raw file or heavy raw item. Code writes the row at capture. A model never writes it.
-- Every row has its hash. Files: SHA-256 of bytes. Folders: memory/source_digest.py digest_tree; all files, directories, and link text, with no exclusions or link traversal.
CREATE TABLE IF NOT EXISTS "memory_sources" (
  "id" INTEGER PRIMARY KEY,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  "number" TEXT NOT NULL,
  "weight" TEXT NOT NULL CHECK ("weight" IN ('light','heavy')),
  "path" TEXT NOT NULL CHECK (length(trim("path")) > 0),
  "family" TEXT,
  "sha256" TEXT NOT NULL CHECK (length("sha256")=64 AND "sha256" NOT GLOB '*[^0-9a-f]*'),
  "url" TEXT,
  "canonical_url" TEXT,
  "title" TEXT,
  "made_by" TEXT,
  "made_at" TEXT CHECK ("made_at" IS NULL OR julianday("made_at") IS NOT NULL),
  "captured_by" TEXT NOT NULL CHECK (length(trim("captured_by")) > 0),
  "captured_at" TEXT NOT NULL CHECK (julianday("captured_at") IS NOT NULL),
  "trusted" INTEGER NOT NULL CHECK ("trusted" IN (0,1)),
  "status" TEXT NOT NULL CHECK ("status" IN ('ok','changed','missing')),
  "checked_at" TEXT CHECK ("checked_at" IS NULL OR julianday("checked_at") IS NOT NULL),
  "tags" TEXT CHECK ("tags" IS NULL OR json_valid("tags")) CHECK ("tags" IS NULL OR json_type("tags")='array'),
  "note" TEXT,
  "details" TEXT CHECK ("details" IS NULL OR json_valid("details")),
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  UNIQUE ("workspace","number"),
  UNIQUE ("workspace","weight","path"),
  UNIQUE ("workspace","canonical_url")
) STRICT;

-- memory_evidence: one row links a decision or a lesson to one source. The writer command adds the link when it writes the claim.
CREATE TABLE IF NOT EXISTS "memory_evidence" (
  "id" INTEGER PRIMARY KEY,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('decision','lesson')),
  "subject_id" INTEGER NOT NULL,
  "source" INTEGER NOT NULL,
  "locator" TEXT,
  "actor" TEXT NOT NULL CHECK (length(trim("actor")) > 0),
  "session" TEXT,
  "created_at" TEXT NOT NULL CHECK (julianday("created_at") IS NOT NULL),
  UNIQUE ("subject_type","subject_id","source"),
  FOREIGN KEY ("source") REFERENCES "memory_sources"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX IF NOT EXISTS "memory_evidence_link_0" ON "memory_evidence"("source");

-- memory_rollups: counts of event rows for one day, week, or month. Code builds each row from the event rows. No row reads another rollup row.
CREATE TABLE IF NOT EXISTS "memory_rollups" (
  "id" INTEGER PRIMARY KEY,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  "period" TEXT NOT NULL CHECK ("period" IN ('day','week','month')),
  "starts_on" TEXT NOT NULL CHECK (julianday("starts_on") IS NOT NULL AND date("starts_on")="starts_on"),
  "event_table" TEXT NOT NULL CHECK ("event_table" IN ('events_changes','events_comments','events_attachments','events_receipts','decisions_approvals')),
  "subject_type" TEXT NOT NULL,
  "action" TEXT,
  "event_count" INTEGER NOT NULL CHECK ("event_count" >= 0),
  "last_seq" INTEGER,
  "built_at" TEXT NOT NULL CHECK (julianday("built_at") IS NOT NULL)
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS "memory_rollups_key" ON "memory_rollups"("workspace","period","starts_on","event_table","subject_type",coalesce("action",''));
