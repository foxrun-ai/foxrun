CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, flag INTEGER DEFAULT 0, deadline TEXT);
CREATE VIEW needs_me AS SELECT id, title, status FROM tasks WHERE flag=1 AND status NOT IN ('done','accepted','canceled');
CREATE TABLE comments (id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT, author TEXT, at TEXT, body TEXT);
CREATE TABLE decisions (id TEXT PRIMARY KEY, name TEXT, statement TEXT, person_words TEXT, status TEXT, decided_on TEXT, source TEXT);
CREATE TABLE approvals (id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT, call TEXT, person_words TEXT, given_at TEXT);
INSERT INTO tasks VALUES ('T286', 'Hook: PreCompact handoff and coverage check', 'in-progress', 1, NULL);
INSERT INTO tasks VALUES ('T301', 'Context meter skill', 'todo', 0, NULL);
INSERT INTO tasks VALUES ('T302', 'Archiving and memory decay', 'backlog', 0, NULL);
INSERT INTO tasks VALUES ('T303', 'Presentation patterns in the base soul', 'blocked', 0, NULL);
INSERT INTO tasks VALUES ('T304', 'Finished item', 'done', 0, NULL);
INSERT INTO tasks VALUES ('T305', 'Accepted item', 'accepted', 0, NULL);
INSERT INTO tasks VALUES ('T306', 'Canceled item', 'canceled', 0, NULL);
INSERT INTO decisions VALUES ('g-handoff-one-shape', 'Handoff, pre-compaction note, and close are one shape', NULL,
  'handoff, pre-compaction note, and close are one shape with three triggers (hand it, continue, stop)', 'ruled', '2026-09-27', 'comment:1');
-- @Person@'s ruling turn (U002, 23:02Z in both transcripts), recorded on T286 three minutes later.
INSERT INTO comments VALUES (1, 'task', 'T286', 'architect', '2026-09-27T19:05:00-04:00',
  '@Person@: Ruled: handoff, pre-compaction note, and close are one shape with three triggers.');
