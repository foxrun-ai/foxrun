CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  title TEXT,
  started_at REAL,
  last_activity_at REAL,
  cwd TEXT,
  source TEXT,
  ended_at REAL
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY,
  session_id TEXT,
  content TEXT
);
CREATE VIRTUAL TABLE messages_fts_trigram USING fts5(content, tokenize='trigram');
INSERT INTO sessions VALUES ('hermes-session-1', 'Pricing launch notes', 1787400000, 1787400060, '/home/example/projects/demo', 'cli', 1787400120);
INSERT INTO messages VALUES (1, 'hermes-session-1', 'Pricing launch notes are ready.');
INSERT INTO messages_fts_trigram(rowid, content) VALUES (1, 'Pricing launch notes are ready.');
