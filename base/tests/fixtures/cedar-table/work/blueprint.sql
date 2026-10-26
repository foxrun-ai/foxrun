-- Work module blueprint v3 (2026-09-21). Adds additive program control.
-- Status lists follow Linear's five categories; tasks add blocked. Links are rows (task_links), never columns.
-- activity is append-only. Undo: swap back the backup database kept in the run folder.
CREATE TABLE IF NOT EXISTS functions (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, organization TEXT, parent TEXT REFERENCES functions(id), owner TEXT, page TEXT, tags TEXT, created_on TEXT);
CREATE TABLE IF NOT EXISTS goals (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  horizon TEXT NOT NULL CHECK (horizon IN ('north-star','3-year','1-year','quarter')), period TEXT,
  function TEXT REFERENCES functions(id), owner TEXT,
  status TEXT NOT NULL DEFAULT 'on-track' CHECK (status IN ('on-track','at-risk','off-track','done','dropped','superseded')),
  tags TEXT, created_on TEXT, replaced_by TEXT);
CREATE TABLE IF NOT EXISTS measures (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, function TEXT REFERENCES functions(id), goal TEXT REFERENCES goals(id), owner TEXT,
  target REAL, unit TEXT, source TEXT, created_on TEXT);
CREATE TABLE IF NOT EXISTS measure_history (
  measure TEXT NOT NULL REFERENCES measures(id), as_of TEXT NOT NULL, value REAL, note TEXT, PRIMARY KEY (measure, as_of));
CREATE TABLE IF NOT EXISTS programs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, objective TEXT, created_on TEXT,
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('backlog','todo','in-progress','blocked','in-review','done','canceled','superseded')),
  canceled_reason TEXT);
CREATE TABLE IF NOT EXISTS themes (
  id TEXT PRIMARY KEY, program TEXT NOT NULL REFERENCES programs(id), name TEXT NOT NULL, tagline TEXT, ord INTEGER);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, result TEXT, goal TEXT REFERENCES goals(id),
  status TEXT NOT NULL DEFAULT 'backlog' CHECK (status IN ('backlog','todo','in-progress','blocked','in-review','done','canceled','superseded')),
  function TEXT REFERENCES functions(id), owner TEXT, due TEXT, page TEXT, tags TEXT, created_on TEXT, extra TEXT,
  description TEXT, problem TEXT, job_when TEXT, job_want TEXT, job_so TEXT, done_when TEXT, context TEXT, ord INTEGER,
  program TEXT REFERENCES programs(id), theme TEXT REFERENCES themes(id), needs TEXT,
  order_column INTEGER, span INTEGER DEFAULT 1, alongside INTEGER DEFAULT 0, replaces TEXT, canceled_reason TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT,
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('backlog','todo','in-progress','blocked','in-review','done','canceled','superseded')),
  project TEXT REFERENCES projects(id), function TEXT REFERENCES functions(id), tags TEXT,
  owner TEXT, created_by TEXT, claimed_by TEXT, claimed_at TEXT, blocked_by TEXT REFERENCES tasks(id), done_check TEXT,
  parent TEXT REFERENCES tasks(id), ord INTEGER,
  planned TEXT, deadline TEXT, important INTEGER DEFAULT 0, urgent INTEGER DEFAULT 0, flag INTEGER DEFAULT 0,
  idempotency_key TEXT UNIQUE, created_on TEXT, source TEXT, extra TEXT, goal TEXT REFERENCES goals(id),
  note TEXT, acceptance TEXT, context TEXT, prior_project TEXT,
  check_by TEXT NOT NULL DEFAULT 'lead' CHECK (check_by IN ('lead','@person@')),
  canceled_reason TEXT, folded_into TEXT REFERENCES tasks(id));
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  "by" TEXT NOT NULL, model TEXT NOT NULL, runtime TEXT NOT NULL, session TEXT, started_at TEXT NOT NULL,
  ended_at TEXT, result TEXT, fix_rounds INTEGER DEFAULT 0, evidence TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS task_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL REFERENCES tasks(id),
  system TEXT NOT NULL, scope TEXT, external_id TEXT, path TEXT, relation TEXT NOT NULL,
  active INTEGER DEFAULT 1, created_on TEXT, UNIQUE (task, system, external_id));
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  field TEXT, old_value TEXT, new_value TEXT, actor TEXT NOT NULL, source TEXT, at TEXT NOT NULL, note TEXT, verb TEXT);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  author TEXT NOT NULL, at TEXT NOT NULL, body TEXT NOT NULL, reply_to INTEGER REFERENCES comments(id),
  field TEXT);
CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  path TEXT NOT NULL, role TEXT, author TEXT, at TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, statement TEXT, person_words TEXT,
  status TEXT NOT NULL CHECK (status IN ('open','soft','ruled','deferred','withdrawn','superseded')),
  replaces TEXT, path TEXT, project TEXT, function TEXT, tags TEXT,
  decided_on TEXT, in_artifact INTEGER DEFAULT 0, artifact_version INTEGER, source TEXT, extra TEXT);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, version TEXT,
  call TEXT NOT NULL CHECK (call IN ('approve','discuss','wrong','edit')), person_words TEXT, given_at TEXT NOT NULL, source TEXT);
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
CREATE VIEW IF NOT EXISTS open_decisions AS SELECT id,name,status,decided_on FROM decisions WHERE status IN ('open','soft') ORDER BY decided_on;
CREATE VIEW IF NOT EXISTS open_tasks AS SELECT id,title,status,project,owner,planned,deadline,important,urgent,flag FROM tasks
  WHERE status NOT IN ('done','canceled','superseded') AND parent IS NULL ORDER BY urgent DESC, important DESC, deadline, id;
CREATE VIEW IF NOT EXISTS needs_me AS
  SELECT t.id,t.title,t.status,t.project,t.planned,t.deadline FROM tasks t
  WHERE t.status NOT IN ('done','canceled','superseded') AND (
    lower(coalesce(t.owner,''))='@person@'
    OR (t.status='in-review' AND t.check_by='@person@')
    OR (t.status='blocked' AND EXISTS
      (SELECT 1 FROM tasks blocker WHERE
       (blocker.id=t.blocked_by OR blocker.id IN
        (SELECT link.task FROM task_links link WHERE link.system='task'
         AND link.relation='blocks' AND link.external_id=t.id AND link.active=1))
       AND lower(coalesce(blocker.owner,''))='@person@'
       AND blocker.status NOT IN ('done','canceled','superseded')))
  ) ORDER BY t.deadline,t.id;
CREATE VIEW IF NOT EXISTS close_now AS
  SELECT t.id,t.title,t.status,t.project,t.planned,t.deadline,
    (SELECT a.new_value FROM activity a
      WHERE a.subject_type='task' AND a.subject_id=t.id AND a.field='receipt'
      ORDER BY a.id DESC LIMIT 1) AS evidence_path
  FROM tasks t
  WHERE t.status='in-review'
  ORDER BY t.deadline,t.id;
CREATE VIEW IF NOT EXISTS needs_business_input AS
  SELECT id,title,status,project,planned,deadline FROM needs_me WHERE status='blocked';
CREATE VIEW IF NOT EXISTS this_week AS SELECT id,title,status,project,planned,deadline FROM tasks
  WHERE status NOT IN ('done','canceled','superseded') AND (planned <= date('now','+7 days') OR deadline <= date('now','+7 days')) ORDER BY planned, deadline;
CREATE VIEW IF NOT EXISTS next_step AS SELECT id,title,status,parent,ord FROM tasks WHERE parent IS NOT NULL AND status IN ('todo','in-progress') ORDER BY parent, ord LIMIT 1;
CREATE VIEW IF NOT EXISTS eisenhower AS SELECT id,title,project,
  CASE WHEN important=1 AND urgent=1 THEN 1 WHEN important=1 THEN 2 WHEN urgent=1 THEN 3 ELSE 4 END AS box
  FROM tasks WHERE status NOT IN ('done','canceled','superseded') ORDER BY box, deadline;
CREATE VIEW IF NOT EXISTS program_plan AS
  WITH counts AS (
    SELECT p.id,
      sum(CASE WHEN t.id IS NOT NULL AND t.status<>'canceled' THEN 1 ELSE 0 END) AS live_tasks,
      sum(CASE WHEN t.status='done' THEN 1 ELSE 0 END) AS done_tasks,
      sum(CASE WHEN t.status='backlog' THEN 1 ELSE 0 END) AS backlog_tasks,
      sum(CASE WHEN t.status='blocked' THEN 1 ELSE 0 END) AS blocked_tasks,
      sum(CASE WHEN t.status IN ('in-progress','in-review') THEN 1 ELSE 0 END) AS in_progress_tasks
    FROM projects p LEFT JOIN tasks t ON t.project=p.id
    WHERE p.program IS NOT NULL AND p.status<>'superseded'
    GROUP BY p.id),
  rollup AS (
    SELECT *, CASE
      WHEN live_tasks=0 THEN 'todo'
      WHEN done_tasks>0 AND live_tasks-backlog_tasks=done_tasks THEN 'done'
      WHEN blocked_tasks>0 AND in_progress_tasks=0 THEN 'blocked'
      WHEN in_progress_tasks>0 OR done_tasks>0 THEN 'in-progress'
      ELSE 'todo' END AS stream_status
    FROM counts)
  SELECT p.program AS program_id, pg.name AS program, p.theme AS theme_id, th.name AS theme,
    th.ord AS theme_ord, p.id AS stream_id, p.title AS stream, p.result,
    p.needs, p.order_column, p.span, p.alongside, p.ord AS stream_ord,
    r.stream_status, r.live_tasks, r.done_tasks, r.backlog_tasks,
    t.id AS task_id, t.title AS task, t.ord AS task_ord, t.status, t.owner, t.claimed_by
  FROM projects p
  JOIN programs pg ON pg.id=p.program
  JOIN themes th ON th.id=p.theme
  JOIN rollup r ON r.id=p.id
  JOIN tasks t ON t.project=p.id
  WHERE p.status<>'superseded'
  ORDER BY th.ord,p.ord,t.ord,t.id;
CREATE VIEW IF NOT EXISTS stream_brief AS
  WITH counts AS (
    SELECT p.id,
      sum(CASE WHEN t.id IS NOT NULL AND t.status<>'canceled' THEN 1 ELSE 0 END) AS live_tasks,
      sum(CASE WHEN t.status='done' THEN 1 ELSE 0 END) AS done_tasks,
      sum(CASE WHEN t.status='backlog' THEN 1 ELSE 0 END) AS backlog_tasks,
      sum(CASE WHEN t.status='blocked' THEN 1 ELSE 0 END) AS blocked_tasks,
      sum(CASE WHEN t.status IN ('in-progress','in-review') THEN 1 ELSE 0 END) AS in_progress_tasks,
      sum(CASE WHEN t.id IS NOT NULL AND t.status NOT IN ('done','canceled','superseded') THEN 1 ELSE 0 END) AS open_tasks
    FROM projects p LEFT JOIN tasks t ON t.project=p.id
    WHERE p.program IS NOT NULL AND p.status<>'superseded'
    GROUP BY p.id),
  rollup AS (
    SELECT *, CASE
      WHEN live_tasks=0 THEN 'todo'
      WHEN done_tasks>0 AND live_tasks-backlog_tasks=done_tasks THEN 'done'
      WHEN blocked_tasks>0 AND in_progress_tasks=0 THEN 'blocked'
      WHEN in_progress_tasks>0 OR done_tasks>0 THEN 'in-progress'
      ELSE 'todo' END AS stream_status
    FROM counts)
  SELECT p.program AS program_id, pg.name AS program, p.theme AS theme_id, th.name AS theme,
    p.id AS stream_id, p.title AS stream, p.result, p.needs, r.stream_status AS status, p.owner,
    p.ord, p.order_column, p.span, p.alongside,
    r.open_tasks, r.live_tasks, r.done_tasks, r.backlog_tasks,
    (SELECT group_concat(summary,' | ') FROM (
      SELECT r.id || ': ' || coalesce(r.result,'running') AS summary
      FROM runs r WHERE r.subject_type='stream' AND r.subject_id=p.id
      ORDER BY r.started_at DESC LIMIT 3)) AS last_runs
  FROM projects p
  JOIN programs pg ON pg.id=p.program
  JOIN themes th ON th.id=p.theme
  JOIN rollup r ON r.id=p.id
  WHERE p.status<>'superseded'
  ORDER BY th.ord,p.ord,p.id;
