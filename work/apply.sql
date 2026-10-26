-- Safe, repeatable upgrade for an existing work-module database.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS bugs (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT, capability TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','fixed','wont-fix')),
  reports INTEGER NOT NULL DEFAULT 1 CHECK (reports >= 0), created_on TEXT);
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, started_at TEXT, ended_at TEXT, impact TEXT, restored_by TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','restored','closed')),
  rca_cause TEXT, bug TEXT REFERENCES bugs(id), created_on TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS record_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subject_type TEXT NOT NULL CHECK (subject_type IN ('incident','bug')),
  subject_id TEXT NOT NULL,
  target_type TEXT NOT NULL CHECK (target_type IN ('task','project','function','theme','run','decision','incident','bug')),
  target_id TEXT NOT NULL,
  relation TEXT NOT NULL CHECK (relation IN ('fix','caused-by','found-in','updated','about')),
  UNIQUE (subject_type, subject_id, target_type, target_id, relation));
CREATE INDEX IF NOT EXISTS record_links_target ON record_links(target_type,target_id,relation);
DROP VIEW IF EXISTS close_now;
CREATE VIEW close_now AS
  SELECT t.id,t.title,t.status,t.project,t.planned,t.deadline,
    (SELECT a.new_value FROM activity a
      WHERE a.subject_type='task' AND a.subject_id=t.id AND a.field='receipt'
      ORDER BY a.id DESC LIMIT 1) AS evidence_path
  FROM tasks t
  WHERE t.status='in-review'
  ORDER BY t.deadline,t.id;
DROP VIEW IF EXISTS needs_business_input;
CREATE VIEW needs_business_input AS
  SELECT id,title,status,project,planned,deadline FROM tasks
  WHERE status='blocked'
    AND instr(',' || replace(lower(coalesce(tags,'')),' ','') || ',', ',business-input,') > 0
  ORDER BY deadline,id;
COMMIT;
