#!/usr/bin/env python3
"""Temporary-tracker tests for session_run.py."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

import program
import work
# Recheck 2 (T742): load the fixture from this folder by path. With base/ first on the path,
# 'tests' meant base/tests when the suite runs as discover -s work/tests from the home.
import importlib.util as _fixture_util
_fixture_spec = _fixture_util.spec_from_file_location('work_tests_fixtures', Path(__file__).with_name('__init__.py'))
_fixtures = _fixture_util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixtures)
native_hooks = _fixtures.native_hooks


TOOL = (Path(__file__).resolve().parent / '../../events/session_run.py')
# Exact runs DDL from the read-only system-workspace tracker schema on 2026-09-25.
RUNS_SCHEMA = '''CREATE TABLE runs (
  id TEXT PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  "by" TEXT NOT NULL, model TEXT NOT NULL, runtime TEXT NOT NULL, started_at TEXT NOT NULL,
  ended_at TEXT, result TEXT, fix_rounds INTEGER DEFAULT 0, evidence TEXT, note TEXT, "session" TEXT);'''
SETUP_SCHEMA = '''CREATE TABLE projects (id TEXT PRIMARY KEY, "function" TEXT, status TEXT NOT NULL DEFAULT 'todo');
CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, project TEXT REFERENCES projects(id),
  "function" TEXT, tags TEXT, created_by TEXT, created_on TEXT, source TEXT, note TEXT, idempotency_key TEXT UNIQUE);
CREATE TABLE activity (id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT, field TEXT,
  old_value TEXT, new_value TEXT, actor TEXT, source TEXT, at TEXT);'''


class SessionRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.hooks = native_hooks(self.root)
        self.workspace = self.root / "system-workspace"
        self.workspace.mkdir()
        self.nested = self.workspace / "inside"
        self.nested.mkdir()
        self.database = self.workspace / "system-workspace.sqlite"
        with sqlite3.connect(self.database) as db:
            db.executescript(RUNS_SCHEMA + SETUP_SCHEMA)
            db.execute("INSERT INTO projects(id) VALUES ('WS01')")

    def call(self, *args: str, input_data: dict | None = None, raw_input: str | None = None,
             env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            input=raw_input if raw_input is not None else json.dumps(input_data) if input_data is not None else None,
            text=True, capture_output=True, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "FOX_SESSION_TRACKED_ROOT": str(self.root),
                 **(env_extra or {})},
        )

    def rows(self) -> list[sqlite3.Row]:
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            return db.execute("SELECT * FROM runs").fetchall()

    def hook(self, script: str, payload: dict, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.hooks / ('codex' if script.startswith('codex') else 'claude') / script)], input=json.dumps(payload), text=True,
            capture_output=True, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "FOX_SESSION_TRACKED_ROOT": str(self.root),
                 **(env_extra or {})},
        )

    def setup_task(self, database: Path | None = None) -> str:
        result = self.call("setup", "--db", str(database or self.database), "--create")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result.stdout.strip()

    def test_start_writes_once_on_standing_task(self) -> None:
        task = self.setup_task()
        self.assertEqual(self.setup_task(), task)
        command = ("start", "--runtime", "claude", "--session", "session-a", "--cwd", str(self.nested),
                   "--desktop-session", "local_abc")
        self.assertEqual(self.call(*command).returncode, 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.call(*command).returncode, 0)
        row = self.rows()[0]
        self.assertEqual((row["subject_type"], row["subject_id"], row["by"], row["runtime"], row["session"]),
                         ("task", task, "claude", "claude", "session-a"))
        self.assertIn("cwd=" + str(self.nested.resolve()), row["note"])
        self.assertEqual(len(self.rows()), 1)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1)

    def test_setup_and_logging_ignore_cleared_stream(self) -> None:
        task = self.setup_task()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE tasks SET project=NULL WHERE id=?", (task,))
        result = self.call("setup", "--db", str(self.database))
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, task, ""))
        result = self.call("start", "--runtime", "codex", "--session", "no-stream", "--cwd", str(self.workspace))
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows()[0]["subject_id"], task)

    def test_setup_on_fresh_tracker_without_projects_makes_unfiled_holder(self) -> None:
        # T595: a fresh install has no project; setup still makes the holder, so sessions log as runs.
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("DELETE FROM projects")
        task = self.setup_task()
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT project,idempotency_key FROM tasks WHERE id=?", (task,)).fetchone(),
                             (None, "session-holding-task"))
        result = self.call("start", "--runtime", "claude", "--session", "fresh", "--cwd", str(self.workspace))
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows()[0]["subject_id"], task)
        missing = self.call("setup", "--db", str(self.database), "--create", "--project", "WS99")
        self.assertEqual(missing.returncode, 0)  # the holder exists already, so setup only reports it
        self.assertEqual(missing.stdout.strip(), task)

    def test_display_variants_and_blob_fields_do_not_select_identity(self) -> None:
        # Put every unrelated row before the actual holder, with older timestamps.
        variants = (("done", "recurring", "Session work to place"),
                    ("canceled", "recurring", "Session work to place"),
                    ("superseded", "recurring", "Session work to place"),
                    ("todo", None, "  SESSION work TO place  "),
                    ("todo", "ops", "Session work to place"),
                    ("todo", "recurring,", "Session work to place"),
                    ("todo", b"recurring,", "Session work to place"),
                    ("todo", "recurring", b"Session work to place"),
                    ("todo", "recurring", "Session work to place"))
        with closing(sqlite3.connect(self.database)) as db, db:
            for index, (status, tags, title) in enumerate(variants):
                db.execute("INSERT INTO tasks(id,title,status,project,tags,created_on) VALUES (?,?,?,'WS01',?,'1900-01-01')",
                           ("T" + str(index), title, status, tags))
            db.execute("INSERT INTO tasks(id,title,status,tags,idempotency_key) VALUES "
                       "('T9','Any display title','todo','recurring','session-holding-task')")
            before = db.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        result = self.call("setup", "--db", str(self.database))
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, "T9", ""))
        for runtime in ("claude", "codex"):
            result = self.call("start", "--runtime", runtime, "--session", runtime, "--cwd", str(self.workspace))
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            self.call("end", "--session", runtime, "--cwd", str(self.workspace))
        self.assertEqual([row["subject_id"] for row in self.rows()], ["T9", "T9"])
        self.assertTrue(all(row["ended_at"] for row in self.rows()))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(before, db.execute("SELECT * FROM tasks ORDER BY id").fetchall())

    def test_vault_root_and_other_folders_route_to_system_workspace(self) -> None:
        self.setup_task()
        for name, directory in (("vault-root", self.root), ("shared", self.root / "atlas"),
                                ("other", self.root / "career-workspace")):
            directory.mkdir(exist_ok=True)
            result = self.call("start", "--runtime", "codex", "--session", name, "--cwd", str(directory))
            self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual({row["session"] for row in self.rows()}, {"vault-root", "shared", "other"})

    def test_setup_and_start_choose_key_among_duplicate_titles(self) -> None:
        task = self.setup_task()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE tasks SET title='  SESSION work TO place  ',tags='RECURRING',created_on='2026-10-02' WHERE id=?", (task,))
            db.executemany("INSERT INTO tasks (id,title,status,project,tags,created_on) VALUES (?,?,?,?,?,?)", (
                ("T7", "Session work to place", "todo", "WS01", "recurring", "2026-10-04"),
                ("T6", "Session work to place", "todo", "WS01", None, "2020-01-01"),
                ("T4", "Session work to place", "done", "WS01", "recurring", "2019-01-01"),
            ))
            before = db.execute("SELECT * FROM tasks ORDER BY id").fetchall()
            activity = db.execute("SELECT * FROM activity").fetchall()
        expected_warning = ""
        result = self.call("setup", "--db", str(self.database))
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, task, expected_warning))
        for runtime in ("claude", "codex"):
            name = "duplicates-" + runtime
            result = self.call("start", "--runtime", runtime, "--session", name, "--cwd", str(self.workspace))
            self.assertEqual((result.returncode, result.stderr), (0, expected_warning))
            self.call("end", "--session", name, "--cwd", str(self.workspace))
        self.assertEqual([row["subject_id"] for row in self.rows()], [task, task])
        self.assertTrue(all(row["ended_at"] for row in self.rows()))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(before, db.execute("SELECT * FROM tasks ORDER BY id").fetchall())
            self.assertEqual(activity, db.execute("SELECT * FROM activity").fetchall())

    def test_logging_uses_key_with_offset_and_equal_timestamps(self) -> None:
        task = self.setup_task()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO tasks(id,title,status,project,tags) VALUES ('T7','Session work to place','todo','WS01','recurring')")
        for index, (primary_time, duplicate_time) in enumerate((
            ("2026-10-01T15:56:39-04:00", "2026-10-01T15:00:00-05:00"),
            ("2026-10-04", "2026-10-02"), ("2026-10-04", "2026-10-04"),
        )):
            with self.subTest(primary_time=primary_time, duplicate_time=duplicate_time):
                with closing(sqlite3.connect(self.database)) as db, db:
                    db.execute("UPDATE tasks SET created_on=? WHERE id=?", (primary_time, task))
                    db.execute("UPDATE tasks SET created_on=? WHERE id='T7'", (duplicate_time,))
                warning = ""
                result = self.call("setup", "--db", str(self.database))
                self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, task, warning))
                name = "rowid-" + str(index)
                result = self.call("start", "--runtime", "codex", "--session", name, "--cwd", str(self.workspace))
                self.assertEqual((result.returncode, result.stderr), (0, warning))
                result = self.call("end", "--session", name, "--cwd", str(self.workspace))
                self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual([row["subject_id"] for row in self.rows()], [task] * 3)
        self.assertTrue(all(row["ended_at"] for row in self.rows()))

    def test_setup_start_and_resume_ignore_canceled_and_superseded_streams(self) -> None:
        task = self.setup_task()
        for status in ("canceled", "superseded"):
            with self.subTest(status=status):
                with closing(sqlite3.connect(self.database)) as db, db:
                    db.execute("UPDATE projects SET status=? WHERE id='WS01'", (status,))
                result = self.call("setup", "--db", str(self.database))
                self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, task, ""))
                for runtime in ("claude", "codex"):
                    name = status + "-" + runtime
                    result = self.call("start", "--runtime", runtime, "--session", name, "--cwd", str(self.workspace))
                    self.assertEqual((result.returncode, result.stderr), (0, ""))
                    self.call("end", "--session", name, "--cwd", str(self.workspace))
                    result = self.hook(runtime + "_session_start.sh", {
                        "hook_event_name": "SessionStart", "session_id": name,
                        "cwd": str(self.workspace), "source": "resume",
                    })
                    self.assertEqual((result.returncode, result.stderr), (0, ""))
                    self.assertIsNone(next(row for row in self.rows() if row["session"] == name)["ended_at"])
                    self.hook(runtime + "_session_end.sh", {
                        "hook_event_name": "SessionEnd", "session_id": name, "cwd": str(self.workspace),
                    })
        self.assertEqual([row["subject_id"] for row in self.rows()], [task] * 4)
        self.assertTrue(all(row["ended_at"] for row in self.rows()))

    def test_initial_setup_rejects_canceled_and_superseded_ws01(self) -> None:
        for status in ("canceled", "superseded"):
            with self.subTest(status=status):
                with closing(sqlite3.connect(self.database)) as db, db:
                    db.execute("UPDATE projects SET status=? WHERE id='WS01'", (status,))
                result = self.call("setup", "--db", str(self.database), "--create")
                self.assertEqual(result.returncode, 2)
                self.assertIn("project is " + status + ": WS01", result.stderr)
                with closing(sqlite3.connect(self.database)) as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
                    self.assertEqual(db.execute("SELECT count(*) FROM activity").fetchone()[0], 0)

    def test_cedar_shop_routes_separately_and_excluded_workspace_and_outside_skip(self) -> None:
        self.setup_task()
        cedar = self.root / "cedar-shop"
        nested = cedar / "inside"
        nested.mkdir(parents=True)
        paul_db = cedar / "cedar-shop.sqlite"
        with sqlite3.connect(paul_db) as db:
            db.executescript(RUNS_SCHEMA + SETUP_SCHEMA)
            db.execute("INSERT INTO projects(id) VALUES ('WS01')")
        self.setup_task(paul_db)
        for name, directory in (("cedar", cedar), ("cedar-nested", nested)):
            self.assertEqual(0, self.call("start", "--runtime", "codex", "--session", name,
                                          "--cwd", str(directory)).returncode)
        excluded_workspace = self.root / "excluded_workspace" / "inside"
        excluded_workspace.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as outside:
            for name, directory in (("excluded_workspace", excluded_workspace), ("outside", Path(outside))):
                result = self.call("start", "--runtime", "codex", "--session", name,
                                   "--cwd", str(directory))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.rows(), [])
        with sqlite3.connect(paul_db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM runs").fetchone()[0], 2)

    def test_end_closes_and_fills_pending_model_from_transcript(self) -> None:
        self.setup_task()
        self.call("start", "--runtime", "claude", "--session", "session-b", "--cwd", str(self.nested))
        transcript = self.root / "session-b.jsonl"
        transcript.write_text(
            json.dumps({"type": "user", "message": "hello"}) + "\n" +
            json.dumps({"type": "assistant", "message": {"model": "fixture-model"}}) + "\n",
            encoding="utf-8",
        )
        result = self.call("end", "--session", "session-b", "--cwd", str(self.nested),
                           "--transcript", str(transcript))
        self.assertEqual(result.returncode, 0)
        row = self.rows()[0]
        self.assertEqual((row["model"], row["result"]), ("fixture-model", None))
        self.assertIsNotNone(row["ended_at"])
        self.assertEqual(self.call("end", "--session", "session-b", "--cwd", str(self.nested)).returncode, 0)
        self.assertEqual(self.rows()[0]["ended_at"], row["ended_at"])

    def test_bad_input_exits_zero_with_stderr(self) -> None:
        result = self.call("start", "--runtime", "claude", "--session", "", "--cwd", str(self.workspace))
        self.assertEqual(result.returncode, 0)
        self.assertIn("--session", result.stderr)
        self.assertEqual(self.rows(), [])

    def test_hook_json_starts_and_ends_codex(self) -> None:
        task = self.setup_task()
        start = {"hook_event_name": "SessionStart", "session_id": "codex-a", "cwd": str(self.workspace),
                 "model": "inherit", "source": "startup"}
        self.assertEqual(self.hook("codex_session_start.sh", start).returncode, 0)
        self.assertEqual((self.rows()[0]["subject_id"], self.rows()[0]["model"]), (task, "inherit"))
        end = {"hook_event_name": "SessionEnd", "session_id": "codex-a", "cwd": str(self.workspace)}
        self.assertEqual(self.hook("codex_session_end.sh", end).returncode, 0)
        self.assertIsNone(self.rows()[0]["result"])

    def test_claude_shell_hooks_use_transcript_model(self) -> None:
        self.setup_task()
        start = {"hook_event_name": "SessionStart", "session_id": "claude-a", "cwd": str(self.workspace),
                 "source": "startup"}
        self.assertEqual(self.hook("claude_session_start.sh", start).returncode, 0)
        self.assertEqual(len(self.rows()), 1)
        transcript = self.root / "claude-a.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {"model": "fixture-model"}}) + "\n")
        end = {"hook_event_name": "SessionEnd", "session_id": "claude-a", "cwd": str(self.workspace),
               "transcript_path": str(transcript)}
        self.assertEqual(self.hook("claude_session_end.sh", end).returncode, 0)
        self.assertEqual((self.rows()[0]["model"], self.rows()[0]["result"]), ("fixture-model", None))

    def test_resume_reopens_ended_run_once_and_records_one_activity(self) -> None:
        self.setup_task()
        payload = {"hook_event_name": "SessionStart", "session_id": "resume-a", "cwd": str(self.workspace),
                   "source": "startup"}
        self.hook("claude_session_start.sh", payload)
        original_id = self.rows()[0]["id"]
        self.hook("claude_session_end.sh", {**payload, "hook_event_name": "SessionEnd"})
        ended_at = self.rows()[0]["ended_at"]
        self.assertIsNotNone(ended_at)
        self.hook("claude_session_start.sh", {**payload, "source": "resume"})
        self.hook("claude_session_start.sh", {**payload, "source": "resume"})
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual((self.rows()[0]["id"], self.rows()[0]["ended_at"]), (original_id, None))
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT subject_type,subject_id,field,old_value,new_value FROM activity "
                                        "WHERE subject_type='run'").fetchall(),
                             [("run", original_id, "ended_at", ended_at, None)])

    def test_resume_starts_new_run_when_ended_run_has_result(self) -> None:
        self.setup_task()
        self.call("start", "--runtime", "codex", "--session", "graded", "--cwd", str(self.workspace))
        self.call("end", "--session", "graded", "--cwd", str(self.workspace))
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE runs SET result='pass' WHERE session='graded'")
        self.call("start", "--runtime", "codex", "--session", "graded", "--cwd", str(self.workspace),
                  "--source", "resume")
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(sum(row["ended_at"] is None for row in self.rows()), 1)

    def test_resume_without_prior_run_starts_one(self) -> None:
        self.setup_task()
        payload = {"hook_event_name": "SessionStart", "session_id": "new-resume",
                   "cwd": str(self.workspace), "source": "resume"}
        self.assertEqual(0, self.hook("codex_session_start.sh", payload).returncode)
        self.assertEqual([row["session"] for row in self.rows()], ["new-resume"])

    def test_workspace_without_tracker_logs_to_system_data_db(self) -> None:
        # Since the 10.15 move one system tracker (<home>/data.db) holds every workspace.
        home, portfolio = self.root / "home", self.root / "portfolio"
        (home / "config").mkdir(parents=True)
        (home / "config/person.json").write_text(
            (Path(os.environ["FOXRUN_HOME"]) / "config/person.json").read_text())
        (portfolio / "cedar-shop/inside").mkdir(parents=True)
        system = home / "data.db"
        with sqlite3.connect(system) as db:
            db.executescript(RUNS_SCHEMA + SETUP_SCHEMA)
            db.execute("INSERT INTO projects(id) VALUES ('WS01')")
        self.setup_task(system)
        env = {k: v for k, v in os.environ.items() if k != "FOX_SESSION_TRACKED_ROOT"}
        env.update(PYTHONDONTWRITEBYTECODE="1", FOXRUN_HOME=str(home), FOXRUN_PORTFOLIO=str(portfolio))
        for event in ("SessionStart", "SessionEnd"):
            payload = {"hook_event_name": event, "session_id": "system-db", "source": "startup",
                       "cwd": str(portfolio / "cedar-shop/inside")}
            result = subprocess.run([sys.executable, str(TOOL), "hook-start" if event == "SessionStart" else "hook-end",
                                     "--runtime", "codex"], input=json.dumps(payload), text=True,
                                    capture_output=True, check=False, env=env)
            self.assertEqual((result.returncode, result.stderr), (0, ""))
        with closing(sqlite3.connect(system)) as db:
            rows = db.execute('SELECT "session", ended_at FROM runs').fetchall()
        self.assertEqual([row[0] for row in rows], ["system-db"])
        self.assertIsNotNone(rows[0][1])
        self.assertEqual(self.rows(), [])

    def test_worker_entrypoints_and_explicit_flag_skip(self) -> None:
        self.setup_task()
        for entrypoint in ("sdk-python", "sdk-tool", "sdk-"):
            payload = {"hook_event_name": "SessionStart", "session_id": entrypoint, "cwd": str(self.workspace),
                       "source": "startup"}
            self.assertEqual(0, self.hook("claude_session_start.sh", payload,
                                          {"CLAUDE_CODE_ENTRYPOINT": entrypoint}).returncode)
        self.assertEqual(self.rows(), [])
        for entrypoint in ("claude-desktop", "cli"):
            payload = {"hook_event_name": "SessionStart", "session_id": entrypoint, "cwd": str(self.workspace),
                       "source": "startup"}
            self.assertEqual(0, self.hook("claude_session_start.sh", payload,
                                          {"CLAUDE_CODE_ENTRYPOINT": entrypoint}).returncode)
        self.assertEqual({row["session"] for row in self.rows()}, {"claude-desktop", "cli"})
        for script, runtime in (("claude_session_start.sh", "claude"), ("codex_session_start.sh", "codex")):
            payload = {"hook_event_name": "SessionStart", "session_id": runtime + "-flagged",
                       "cwd": str(self.workspace), "source": "startup"}
            self.assertEqual(0, self.hook(script, payload, {"FOXRUN_NO_SESSION_LOG": "1"}).returncode)
        self.assertEqual(0, self.hook("codex_session_end.sh",
                                      {"hook_event_name": "SessionEnd", "session_id": "cli",
                                       "cwd": str(self.workspace)},
                                      {"FOXRUN_NO_SESSION_LOG": "1"}).returncode)
        self.assertEqual(len(self.rows()), 2)
        self.assertIsNone(next(row for row in self.rows() if row["session"] == "cli")["ended_at"])

    def test_bad_hook_stdin_and_no_setup_are_safe(self) -> None:
        result = self.call("hook-start", "--runtime", "codex", raw_input="not json")
        self.assertEqual(result.returncode, 0)
        self.assertIn("session_run:", result.stderr)
        payload = {"hook_event_name": "SessionStart", "session_id": "without-setup",
                   "cwd": str(self.workspace), "source": "startup"}
        result = self.hook("codex_session_start.sh", payload)
        self.assertEqual(result.returncode, 0)
        self.assertIn("backfill required", result.stderr)
        self.assertEqual(self.rows(), [])

    def test_locked_database_waits_about_two_seconds_and_exits_zero(self) -> None:
        self.setup_task()
        with sqlite3.connect(self.database) as lock:
            lock.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            result = self.call("start", "--runtime", "codex", "--session", "locked",
                               "--cwd", str(self.workspace))
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 0)
            self.assertIn("database is locked", result.stderr)
            self.assertGreaterEqual(elapsed, 1.8)
            self.assertLess(elapsed, 3.5)
        self.assertEqual(self.rows(), [])
        self.call("start", "--runtime", "codex", "--session", "locked-end", "--cwd", str(self.workspace))
        with sqlite3.connect(self.database) as lock:
            lock.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            result = self.call("end", "--session", "locked-end", "--cwd", str(self.workspace))
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 0)
            self.assertIn("database is locked", result.stderr)
            self.assertGreaterEqual(elapsed, 1.8)
            self.assertLess(elapsed, 3.5)
        self.assertIsNone(self.rows()[0]["ended_at"])

class MovedStandingTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.hooks = native_hooks(self.root)
        self.databases = {}
        schema = ((Path(__file__).resolve().parent / '../blueprint.sql')).read_text(encoding="utf-8")
        for workspace, task in (("system-workspace", "T9"), ("cedar-shop", "T5")):
            directory = self.root / workspace
            directory.mkdir()
            seed = self.root / (workspace + "-seed.sqlite")
            database = directory / (workspace + ".sqlite")
            with closing(sqlite3.connect(seed)) as db:
                db.executescript(schema)
                db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Foundation'),('PG2','Agent Team')")
                db.execute("INSERT INTO themes (id,program,name) VALUES ('TH1','PG1','First'),('TH2','PG2','Second')")
                db.executemany("INSERT INTO projects (id,title,status,program,theme) VALUES (?,?,?,?,?)", (
                    ("WS01", "Original", "todo", "PG1", "TH1"),
                    ("WS02", "Same program", "todo", "PG1", "TH1"),
                    ("WS03", "Another program", "todo", "PG2", "TH2"),
                ))
                db.execute("INSERT INTO tasks (id,title,status,project,tags,owner,idempotency_key) "
                           "VALUES (?,'Session work to place','todo','WS01','recurring','person','session-holding-task')", (task,))
                db.execute("INSERT INTO approvals (id,subject_type,subject_id,call,given_at) "
                           "VALUES (1,'task',?,'approve','2026-10-04')", (task,))
                db.commit()
                with closing(sqlite3.connect(database)) as copy:
                    db.backup(copy)
            self.databases[workspace] = database

    def rows(self, database: Path, sql: str, values=()) -> list[dict]:
        with closing(sqlite3.connect(database)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, values)]

    def call(self, *args: str, hook: str | None = None, payload: dict | None = None, expected_stderr: str = "") -> None:
        command = [str(self.hooks / ('codex' if hook.startswith('codex') else 'claude') / hook)] if hook else [sys.executable, str(TOOL), *args]
        result = subprocess.run(
            command, input=json.dumps(payload) if payload else None,
            text=True, capture_output=True, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "FOX_SESSION_TRACKED_ROOT": str(self.root)},
        )
        self.assertEqual((result.returncode, result.stderr), (0, expected_stderr))

    def check_moved_sessions(self, hooks: bool) -> None:
        for workspace, task in (("system-workspace", "T9"), ("cedar-shop", "T5")):
            database = self.databases[workspace]
            other = self.databases["cedar-shop" if workspace == "system-workspace" else "system-workspace"]
            other_task = self.rows(other, "SELECT * FROM tasks")
            for target in ("WS02", "WS03"):
                with self.subTest(workspace=workspace, target=target, hooks=hooks):
                    out, err = io.StringIO(), io.StringIO()
                    code = work.run([
                        "--db", str(database), "--receipt-root", str(database.parent),
                        "task-move", task, "--project", target, "--by", "builder",
                        "--approval", "1",
                    ], stdout=out, stderr=err)
                    self.assertEqual((code, err.getvalue()), (0, ""))
                    [move] = self.rows(database, "SELECT note FROM activity WHERE subject_id=? AND field='project' "
                                                 "ORDER BY id DESC LIMIT 1", (task,))
                    self.assertIn("approval 1;", move["note"])
                    before = self.rows(database, "SELECT * FROM activity")
                    self.call("setup", "--db", str(database))
                    self.assertEqual(before, self.rows(database, "SELECT * FROM activity"))
                    self.assertEqual([task], [row["id"] for row in self.rows(database, "SELECT id FROM tasks")])
                    self.assertEqual([{"id": task, "project": target}],
                                     self.rows(database, "SELECT id,project FROM needs_me"))
                    for runtime in ("claude", "codex"):
                        session = f"{workspace}-{target}-{runtime}"
                        if hooks:
                            payload = {"hook_event_name": "SessionStart", "session_id": session,
                                       "cwd": str(database.parent), "model": "test-model", "source": "startup"}
                            self.call(hook=runtime + "_session_start.sh", payload=payload)
                        else:
                            self.call("start", "--runtime", runtime, "--session", session,
                                      "--cwd", str(database.parent), "--model", "test-model")
                        [opened] = self.rows(database, "SELECT * FROM runs WHERE session=?", (session,))
                        self.assertEqual((opened["subject_type"], opened["subject_id"], opened["runtime"]),
                                         ("task", task, runtime))
                        self.assertIsNone(opened["ended_at"])
                        with closing(program.connect(database)) as db:
                            self.assertIn(opened["id"], [row["id"] for row in program.open_runs(db, target)])
                            self.assertEqual([], program.open_runs(db, "WS01"))
                        if hooks:
                            self.call(hook=runtime + "_session_end.sh",
                                      payload={**payload, "hook_event_name": "SessionEnd"})
                        else:
                            self.call("end", "--session", session, "--cwd", str(database.parent))
                        [ended] = self.rows(database, "SELECT * FROM runs WHERE session=?", (session,))
                        self.assertEqual(ended["id"], opened["id"])
                        self.assertIsNotNone(ended["ended_at"])
                        self.assertIsNone(ended["result"])
                    self.assertEqual(other_task, self.rows(other, "SELECT * FROM tasks"))

    def test_setup_start_end_after_stream_and_program_moves_on_tracker_copies(self) -> None:
        self.check_moved_sessions(hooks=False)

    def test_all_session_hooks_after_stream_and_program_moves_on_tracker_copies(self) -> None:
        self.check_moved_sessions(hooks=True)

    def test_duplicate_repair_preserves_standing_task_and_session_logging_in_both_trackers(self) -> None:
        for workspace, task in (("system-workspace", "T9"), ("cedar-shop", "T5")):
            with self.subTest(workspace=workspace):
                database = self.databases[workspace]
                with closing(sqlite3.connect(database)) as db:
                    db.execute("INSERT INTO tasks (id,title,status,project,tags) "
                               "VALUES ('T7','  SESSION work TO place  ','todo','WS03','recurring')")
                    db.execute("INSERT INTO tasks (id,title,status,project,tags) "
                               "VALUES ('T8','Session work to place','todo','WS03','recurring')")
                    db.commit()
                original = self.rows(database, "SELECT * FROM tasks WHERE id=?", (task,))
                for stage in ("before-repair", "after-repair"):
                    if stage == "after-repair":
                        out, err = io.StringIO(), io.StringIO()
                        code = work.run([
                            "--db", str(database), "--receipt-root", str(database.parent),
                            "task-update", "T7", "--title", "Repaired duplicate", "--by", "builder",
                        ], stdout=out, stderr=err)
                        self.assertEqual((code, err.getvalue()), (0, ""))
                        out, err = io.StringIO(), io.StringIO()
                        code = work.run([
                            "--db", str(database), "--receipt-root", str(database.parent),
                            "cancel", "T8", "--reason", "Repair duplicate", "--by", "anyone",
                        ], stdout=out, stderr=err)
                        self.assertEqual((code, err.getvalue()), (0, ""))
                    warning = ""
                    self.call("setup", "--db", str(database), expected_stderr=warning)
                    name = workspace + "-" + stage
                    self.call("start", "--runtime", "codex", "--session", name, "--cwd", str(database.parent), expected_stderr=warning)
                    self.call("end", "--session", name, "--cwd", str(database.parent))
                    [run] = self.rows(database, "SELECT * FROM runs WHERE session=?", (name,))
                    self.assertEqual(run["subject_id"], task)
                    self.assertIsNotNone(run["ended_at"])
                    self.assertEqual(original, self.rows(database, "SELECT * FROM tasks WHERE id=?", (task,)))


if __name__ == "__main__":
    unittest.main()
