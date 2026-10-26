-- Run through tools/apply_program_schema.py so missing columns are added first.
CREATE TABLE IF NOT EXISTS programs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, objective TEXT, created_on TEXT);
CREATE TABLE IF NOT EXISTS themes (
  id TEXT PRIMARY KEY, program TEXT NOT NULL REFERENCES programs(id), name TEXT NOT NULL, tagline TEXT, ord INTEGER);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  "by" TEXT NOT NULL, model TEXT NOT NULL, runtime TEXT NOT NULL, session TEXT, started_at TEXT NOT NULL,
  ended_at TEXT, result TEXT, fix_rounds INTEGER DEFAULT 0, evidence TEXT, note TEXT);

DROP VIEW IF EXISTS program_plan;
CREATE VIEW program_plan AS
  WITH counts AS (
    SELECT p.id,
      sum(CASE WHEN t.id IS NOT NULL AND t.status NOT IN ('canceled','superseded') THEN 1 ELSE 0 END) AS live_tasks,
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

DROP VIEW IF EXISTS stream_brief;
CREATE VIEW stream_brief AS
  WITH counts AS (
    SELECT p.id,
      sum(CASE WHEN t.id IS NOT NULL AND t.status NOT IN ('canceled','superseded') THEN 1 ELSE 0 END) AS live_tasks,
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
