-- Lessons: the corrections and lessons that every agent reads (T260). The Keeper owns this table.
--
-- This is the live tracker shape in the system data.db, beside tasks and decisions.
-- memory/blueprint.sql holds the reviewed future shape, memory_lessons; T497 moves the names.
-- Writers: work.py lesson-add and lesson-update. Reader: the active_lessons view and memory/lessons.py.
-- Apply: python3 memory/lessons.py apply --db <data.db>. Additive only; a second run changes nothing.

CREATE TABLE IF NOT EXISTS lessons (
  id TEXT PRIMARY KEY CHECK (id GLOB 'L[1-9]*' AND id NOT GLOB 'L*[^0-9]*'),
  text TEXT NOT NULL CHECK (length(trim(text)) > 0 AND instr(text, char(10)) = 0),
  person_words TEXT,
  source TEXT NOT NULL CHECK (length(trim(source)) > 0),
  workspace TEXT NOT NULL DEFAULT 'all',
  applies_to TEXT NOT NULL DEFAULT 'all',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','replaced')),
  replaces TEXT REFERENCES lessons(id),
  created_on TEXT NOT NULL CHECK (date(created_on) = created_on),
  UNIQUE (source, text)
);

CREATE VIEW IF NOT EXISTS active_lessons AS
  SELECT id, text, workspace, applies_to, source, created_on FROM lessons
  WHERE status = 'active'
  ORDER BY created_on DESC, CAST(substr(id, 2) AS INTEGER) DESC;
