#!/usr/bin/env python3
"""Synthetic regressions for the portable work writer."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import closing, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import work
import lint_replaces

MODULES_ROOT = Path(__file__).resolve().parent.parent.parent


def blueprint_sql() -> str:
    return ((Path(__file__).resolve().parent / '../fixtures/pre_t309.sql')).read_text(encoding="utf-8")


def apply_sql() -> str:
    return ((Path(__file__).resolve().parent / '../fixtures/pre_t309_apply.sql')).read_text(encoding="utf-8")


def pre_t264(sql: str) -> str:
    """Return the schema as it was before T264: no accepted status, no comments.field."""
    sql = sql.replace("'done','accepted','canceled'", "'done','canceled'")
    sql = sql.replace("status IN ('done','accepted')", "status='done'")
    return sql.replace("reply_to INTEGER REFERENCES comments(id),\n  field TEXT);", "reply_to INTEGER REFERENCES comments(id));")


def legacy_blueprint() -> str:
    sql = pre_t264(blueprint_sql())
    sql = sql.replace(",'superseded')) ,", ")),")
    sql = sql.replace(",'superseded')),\n  tags TEXT, created_on TEXT, replaced_by TEXT);", ")), tags TEXT, created_on TEXT);")
    sql = sql.replace(",'superseded')),\n  function TEXT", ")),\n  function TEXT")
    sql = sql.replace(", alongside INTEGER DEFAULT 0, replaces TEXT);", ", alongside INTEGER DEFAULT 0);")
    start = sql.index("CREATE TABLE IF NOT EXISTS programs")
    end = sql.index("CREATE TABLE IF NOT EXISTS projects", start)
    sql = sql[:start] + sql[end:]
    sql = sql.replace(
        ",\n  program TEXT REFERENCES programs(id), theme TEXT REFERENCES themes(id), needs TEXT,\n"
        "  order_column INTEGER, span INTEGER DEFAULT 1, alongside INTEGER DEFAULT 0);",
        ");",
    )
    sql = sql.replace(", prior_project TEXT);", ");")
    start = sql.index("CREATE TABLE IF NOT EXISTS runs")
    end = sql.index("CREATE TABLE IF NOT EXISTS task_links", start)
    sql = sql[:start] + sql[end:]
    return sql[:sql.index("CREATE VIEW IF NOT EXISTS program_plan")]


def current_blueprint() -> str:
    sql = blueprint_sql()
    sql = sql.replace(",'superseded')),\n  tags TEXT, created_on TEXT, replaced_by TEXT);", ")),\n  tags TEXT, created_on TEXT);")
    sql = sql.replace(",'superseded')),\n  function TEXT", ")),\n  function TEXT")
    sql = sql.replace(", alongside INTEGER DEFAULT 0, replaces TEXT);", ", alongside INTEGER DEFAULT 0);")
    return sql


class WorkWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="work-writer-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.receipts = self.root / "receipts"
        self.receipts.mkdir()
        self.db = self.make_db("one.sqlite")
        self.add_task(self.db, "T1")

    def make_db(self, name: str, schema: str | None = None) -> Path:
        path = self.root / name
        with closing(sqlite3.connect(path)) as db:
            db.executescript(blueprint_sql() if schema is None else schema)
            db.commit()
        return path

    def add_task(self, database: Path, task: str, **values) -> None:
        row = {
            "title": "Synthetic " + task,
            "status": "todo",
            "owner": None,
            "claimed_by": None,
            "flag": 0,
            "acceptance": "reviewed evidence required",
        }
        row.update(values)
        with closing(sqlite3.connect(database)) as db:
            db.execute(
                "INSERT INTO tasks (id,title,status,owner,claimed_by,flag,acceptance) VALUES (?,?,?,?,?,?,?)",
                (task, row["title"], row["status"], row["owner"], row["claimed_by"], row["flag"], row["acceptance"]),
            )
            db.commit()

    def call(self, database: Path, *arguments: str, hook=None, receipt_root: Path | None = None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--db", str(database), "--receipt-root", str(receipt_root or self.receipts), *arguments]
        code = work.run(argv, before_final_receipt_check=hook, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def six(self, database: Path | None = None, *, acceptance: bool = True) -> list[str]:
        """Give an old fixture the T718 columns; return the six fields for create."""
        database = database or self.db
        if "problem" not in {row["name"] for row in self.rows(database, "PRAGMA table_info(tasks)")}:
            add_six_field_columns(database)
        where = self.root / "where.md"
        where.write_text("spec\n", encoding="utf-8")
        return six_field_arguments(str(where), acceptance=acceptance)

    def rows(self, database: Path, sql: str, values=()):
        with closing(sqlite3.connect(database)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, values)]

    def counts(self, database: Path):
        with closing(sqlite3.connect(database)) as db:
            return {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("task_links", "attachments", "comments", "activity", "approvals")
            }

    def receipt(self, relative: str, body: bytes = b"evidence") -> Path:
        path = self.receipts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def test_explicit_paths_and_two_independent_databases(self):
        missing = self.root / "missing.sqlite"
        code, _, error = self.call(missing, "show", "T1")
        self.assertEqual(2, code)
        self.assertIn("must already exist", error)
        self.assertFalse(missing.exists())

        second = self.make_db("two.sqlite")
        self.add_task(second, "T1", title="Other workspace")
        self.assertEqual(0, self.call(self.db, "claim", "T1", "--by", "alice")[0])
        first_task = self.rows(self.db, "SELECT status,claimed_by FROM tasks WHERE id='T1'")[0]
        second_task = self.rows(second, "SELECT title,status,claimed_by FROM tasks WHERE id='T1'")[0]
        self.assertEqual({"status": "in-progress", "claimed_by": "alice"}, first_task)
        self.assertEqual({"title": "Other workspace", "status": "todo", "claimed_by": None}, second_task)

    def test_parser_requires_database_and_receipt_root(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                work.build_parser().parse_args(["show", "T1"])
        code = work.run(
            ["--receipt-root", str(self.receipts), "show", "T1"],
            stdout=io.StringIO(), stderr=io.StringIO(),
        )
        self.assertEqual(2, code)

    def test_empty_or_different_schema_is_refused_without_migration(self):
        empty = self.root / "empty.sqlite"
        sqlite3.connect(empty).close()
        code, _, error = self.call(empty, "show", "T1")
        self.assertEqual(2, code)
        self.assertIn("unsupported work schema", error)
        with closing(sqlite3.connect(empty)) as db:
            self.assertEqual([], db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

        missing_hash = self.make_db("missing-hash.sqlite", blueprint_sql().replace(", hash TEXT);", ");"))
        self.add_task(missing_hash, "T1")
        self.assertEqual(2, self.call(missing_hash, "show", "T1")[0])

    def test_writer_accepts_legacy_and_upgraded_schemas(self):
        legacy = self.make_db("legacy.sqlite", legacy_blueprint())
        current = self.make_db("current.sqlite", current_blueprint())
        self.add_task(legacy, "T1")
        self.add_task(current, "T1")
        for database in (legacy, current, self.db):
            with self.subTest(database=database.name):
                self.assertEqual(0, self.call(database, "show", "T1")[0])
                self.assertEqual(0, self.call(database, "claim", "T1", "--by", "alice")[0])

    def test_writer_accepts_migrated_session_column_order(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("ALTER TABLE runs RENAME TO runs_old")
            db.execute(
                'CREATE TABLE runs (id TEXT PRIMARY KEY,subject_type TEXT NOT NULL,subject_id TEXT NOT NULL,'
                '"by" TEXT NOT NULL,model TEXT NOT NULL,runtime TEXT NOT NULL,started_at TEXT NOT NULL,'
                'ended_at TEXT,result TEXT,fix_rounds INTEGER DEFAULT 0,evidence TEXT,note TEXT)'
            )
            db.execute("ALTER TABLE runs ADD COLUMN session TEXT")
            db.execute("DROP TABLE runs_old")
            db.commit()
        self.assertEqual(0, self.call(self.db, "show", "T1")[0])

    def test_claim_refuses_takeover_and_final_state_reopen(self):
        self.assertEqual(0, self.call(self.db, "claim", "T1", "--by", "alice")[0])
        before = self.counts(self.db)
        code, _, error = self.call(self.db, "claim", "T1", "--by", "bob")
        self.assertEqual(2, code)
        self.assertIn("claimed by alice", error)
        self.assertEqual(before, self.counts(self.db))

        for index, status in enumerate(("done", "canceled"), start=2):
            task = "T" + str(index)
            self.add_task(self.db, task, status=status)
            for verb, extra in (("claim", []), ("block", ["waiting"])):
                code, _, error = self.call(self.db, verb, task, *extra, "--by", "alice")
                self.assertEqual(2, code)
                self.assertIn("final task", error)

    def test_claim_refuses_in_progress_owner_without_claim(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET status='in-progress',owner='alice',claimed_by=NULL WHERE id='T1'")
            db.commit()
        code, _, error = self.call(self.db, "claim", "T1", "--by", "bob")
        self.assertEqual(2, code)
        self.assertIn("in-progress task is owned by alice", error)
        task = self.rows(self.db, "SELECT owner,claimed_by,status FROM tasks WHERE id='T1'")[0]
        self.assertEqual({"owner": "alice", "claimed_by": None, "status": "in-progress"}, task)

    def test_claim_takeover_records_old_claim_and_reason(self):
        self.assertEqual(0, self.call(self.db, "claim", "T1", "--by", "alice")[0])
        code, _, error = self.call(
            self.db, "claim", "T1", "--by", "bob", "--takeover", "alice session ended",
        )
        self.assertEqual((0, ""), (code, error))
        task = self.rows(self.db, "SELECT owner,claimed_by,status FROM tasks WHERE id='T1'")[0]
        self.assertEqual({"owner": "bob", "claimed_by": "bob", "status": "in-progress"}, task)
        takeover = self.rows(
            self.db,
            "SELECT field,old_value,new_value,actor,note FROM activity WHERE field IN ('owner','claimed_by') ORDER BY id",
        )
        self.assertEqual([
            {
                "field": "owner", "old_value": "alice", "new_value": "bob",
                "actor": "bob", "note": "takeover: alice session ended",
            },
            {
                "field": "claimed_by", "old_value": "alice", "new_value": "bob",
                "actor": "bob", "note": "takeover: alice session ended",
            },
        ], takeover)

    def test_comment_appends_comment_and_activity_including_final_task(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET status='done' WHERE id='T1'")
            db.commit()
        code, _, _ = self.call(self.db, "comment", "T1", "correction", "--by", "alice")
        self.assertEqual(0, code)
        comments = self.rows(self.db, "SELECT author,body FROM comments")
        activities = self.rows(self.db, "SELECT field,actor,note FROM activity")
        self.assertEqual([{"author": "alice", "body": "correction"}], comments)
        self.assertEqual([{"field": "comment", "actor": "alice", "note": "correction"}], activities)

    def test_create_uses_next_id_project_order_and_one_activity(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','Stream','todo')")
            db.execute("UPDATE tasks SET project='WS01',ord=4 WHERE id='T1'")
            db.commit()
        code, output, error = self.call(
            self.db, "create", "--title", "New task", "--project", "WS01", "--status", "backlog",
            "--note", "Small note", "--acceptance", "First check", "--acceptance", "Second check", "--by", "alice",
            *self.six(acceptance=False),
        )
        self.assertEqual((0, "T2\n", ""), (code, output, error))
        row = self.rows(
            self.db, "SELECT id,title,status,project,created_by,note,acceptance,ord,parent FROM tasks WHERE id='T2'",
        )[0]
        self.assertEqual(("T2", "New task", "backlog", "WS01", "alice", "Small note", 5, None), (
            row["id"], row["title"], row["status"], row["project"], row["created_by"], row["note"], row["ord"], row["parent"],
        ))
        self.assertEqual(["First check", "Second check"], json.loads(row["acceptance"]))
        self.assertEqual([{"subject_id": "T2", "field": "create", "actor": "alice"}], self.rows(
            self.db, "SELECT subject_id,field,actor FROM activity WHERE subject_id='T2'",
        ))

    def test_create_refuses_missing_superseded_and_parent_projects(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('OLD','Old','superseded')")
            db.commit()
        base = ("create", "--title", "New task", "--by", "alice", *self.six())
        self.assertIn("no such project", self.call(self.db, *base, "--project", "NOPE")[2])
        self.assertIn("project is superseded", self.call(self.db, *base, "--project", "OLD")[2])
        self.assertIn("project is superseded", self.call(self.db, *base, "--project", "OLD", "--parent", "T1")[2])
        self.assertEqual([], self.rows(self.db, "SELECT id FROM tasks WHERE id<>'T1'"))

    def test_create_in_canceled_stream_keeps_existing_behavior(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('STOP','Canceled','canceled')")
            db.commit()
        code, output, error = self.call(self.db, "create", "--title", "Ordinary task", "--project", "STOP", "--by", "lead", *self.six())
        self.assertEqual((code, error), (0, ""))
        self.assertEqual("STOP", self.rows(self.db, "SELECT project FROM tasks WHERE id=?", (output.strip(),))[0]["project"])

    def test_create_accepts_backlog_todo_or_done_with_note(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','Stream','todo')")
            db.commit()
        for status in ("in-progress", "blocked", "canceled"):
            with self.subTest(status=status):
                code, _, error = self.call(
                    self.db, "create", "--title", "Bad state", "--project", "WS01",
                    "--status", status, "--by", "alice",
                )
                self.assertEqual(2, code)
                self.assertIn("must be backlog, todo, or done with --note", error)
        code, _, error = self.call(
            self.db, "create", "--title", "Missing note", "--project", "WS01",
            "--status", "done", "--by", "alice",
        )
        self.assertEqual(2, code)
        self.assertIn("create --status done needs --note", error)

    def test_task_move_writes_one_project_event_and_refuses_repeat(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','First','todo')")
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS02','Second','todo')")
            db.execute("UPDATE tasks SET project='WS01' WHERE id='T1'")
            db.commit()
        code, output, error = self.call(
            self.db, "task-move", "T1", "--project", "WS02", "--by", "lead", "--note", "Wrong stream",
        )
        self.assertEqual((0, "ok task-move T1\n", ""), (code, output, error))
        self.assertEqual("WS02", self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])
        self.assertEqual([{
            "subject_type": "task", "subject_id": "T1", "field": "project",
            "old_value": "WS01", "new_value": "WS02", "actor": "lead", "source": work.SOURCE,
            "note": "moved: Wrong stream",
        }], self.rows(self.db,
            "SELECT subject_type,subject_id,field,old_value,new_value,actor,source,note FROM activity"
        ))
        code, _, error = self.call(self.db, "task-move", "T1", "--project", "WS02", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("already in WS02", error)
        self.assertEqual(1, len(self.rows(self.db, "SELECT id FROM activity")))

    def test_task_move_from_inbox_and_back(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','Stream','todo')")
            db.commit()
        self.assertEqual(0, self.call(self.db, "task-move", "T1", "--project", "WS01", "--by", "lead")[0])
        self.assertEqual(0, self.call(self.db, "task-move", "T1", "--inbox", "--by", "lead")[0])
        self.assertIsNone(self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])
        self.assertEqual([
            {"old_value": None, "new_value": "WS01", "note": "moved"},
            {"old_value": "WS01", "new_value": None, "note": "moved"},
        ], self.rows(self.db, "SELECT old_value,new_value,note FROM activity ORDER BY id"))
        code, _, error = self.call(self.db, "task-move", "T1", "--inbox", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("already in inbox", error)

    def test_task_move_refuses_invalid_task_and_project(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('OLD','Old','superseded')")
            db.execute("INSERT INTO projects (id,title,status) VALUES ('STOP','Canceled','canceled')")
            db.commit()
        for task, target, message in (
            ("T8", "OLD", "no such task"),
            ("T1", "NOPE", "no such project"),
            ("T1", "OLD", "project is superseded"),
            ("T1", "STOP", "project is canceled"),
        ):
            with self.subTest(task=task, target=target):
                code, _, error = self.call(self.db, "task-move", task, "--project", target, "--by", "lead")
                self.assertEqual(2, code)
                self.assertIn(message, error)
        self.assertIsNone(self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])
        self.assertEqual([], self.rows(self.db, "SELECT id FROM activity"))

    def test_task_move_rolls_back_update_if_activity_fails(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','Stream','todo')")
            db.commit()
        with mock.patch.object(work, "record_activity", side_effect=sqlite3.IntegrityError("forced event failure")):
            code, _, error = self.call(self.db, "task-move", "T1", "--project", "WS01", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("forced event failure", error)
        self.assertIsNone(self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])
        self.assertEqual([], self.rows(self.db, "SELECT id FROM activity"))

    def test_program_theme_and_stream_create_rows_ids_and_activity(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO functions (id,name) VALUES ('ops','Operations')")
            db.commit()
        code, output, error = self.call(
            self.db, "program-create", "--name", "Program", "--objective", "One objective", "--by", "lead",
        )
        self.assertEqual((0, "PG1\n", ""), (code, output, error))
        code, output, error = self.call(
            self.db, "theme-create", "--program", "PG1", "--name", "Theme", "--tagline", "One line",
            "--order", "2", "--by", "lead",
        )
        self.assertEqual((0, "TH1\n", ""), (code, output, error))
        code, output, error = self.call(
            self.db, "stream-create", "--program", "PG1", "--theme", "TH1", "--function", "ops",
            "--title", "Stream", "--result", "One result", "--order", "3", "--by", "lead",
        )
        self.assertEqual((0, "WS01\n", ""), (code, output, error))
        self.assertEqual(
            [{"id": "PG1", "name": "Program", "objective": "One objective"}],
            self.rows(self.db, "SELECT id,name,objective FROM programs"),
        )
        self.assertEqual(
            [{"id": "TH1", "program": "PG1", "name": "Theme", "tagline": "One line", "ord": 2}],
            self.rows(self.db, "SELECT id,program,name,tagline,ord FROM themes"),
        )
        stream = self.rows(
            self.db,
            "SELECT id,title,result,status,function,program,theme,ord,order_column,needs,span,alongside FROM projects",
        )[0]
        self.assertEqual(
            {
                "id": "WS01", "title": "Stream", "result": "One result", "status": "todo",
                "function": "ops", "program": "PG1", "theme": "TH1", "ord": 3,
                "order_column": 3, "needs": "[]", "span": 1, "alongside": 0,
            },
            stream,
        )
        self.assertEqual(
            [
                {"subject_type": "program", "subject_id": "PG1", "actor": "lead"},
                {"subject_type": "theme", "subject_id": "TH1", "actor": "lead"},
                {"subject_type": "project", "subject_id": "WS01", "actor": "lead"},
            ],
            self.rows(self.db, "SELECT subject_type,subject_id,actor FROM activity ORDER BY id"),
        )

    def test_program_commands_validate_links_and_required_actor(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Program')")
            db.execute("INSERT INTO themes (id,program,name,ord) VALUES ('TH1','PG1','Theme',1)")
            db.execute("INSERT INTO functions (id,name) VALUES ('ops','Operations')")
            db.commit()
        self.assertIn("--by is required", self.call(self.db, "program-create", "--name", "No actor")[2])
        self.assertIn(
            "no such program",
            self.call(self.db, "theme-create", "--program", "PG9", "--name", "Theme", "--by", "lead")[2],
        )
        self.assertIn(
            "no such function",
            self.call(
                self.db, "stream-create", "--program", "PG1", "--theme", "TH1", "--function", "missing",
                "--title", "Stream", "--by", "lead",
            )[2],
        )

    def test_done_preserves_state_and_same_basename_receipts(self):
        self.receipt("a/result.txt", b"first")
        self.receipt("b/result.txt", b"second")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET status='in-progress',owner='alice',claimed_by='alice' WHERE id='T1'")
            db.execute("INSERT INTO approvals (subject_type,subject_id,call,given_at) VALUES ('task','T1','discuss','2026-09-20T00:00:00-04:00')")
            db.commit()
        code, _, _ = self.call(
            self.db, "done", "T1", "--by", "alice",
            "--receipt", "a/result.txt", "--receipt", "b/result.txt", "--proof", "two files",
        )
        self.assertEqual(0, code)
        task = self.rows(self.db, "SELECT status,acceptance,flag FROM tasks WHERE id='T1'")[0]
        self.assertEqual({"status": "in-progress", "acceptance": "reviewed evidence required", "flag": 1}, task)
        links = self.rows(self.db, "SELECT external_id,path FROM task_links ORDER BY path")
        self.assertEqual([
            {"external_id": str((self.receipts / "a/result.txt").resolve()), "path": str((self.receipts / "a/result.txt").resolve())},
            {"external_id": str((self.receipts / "b/result.txt").resolve()), "path": str((self.receipts / "b/result.txt").resolve())},
        ], links)
        attachments = self.rows(self.db, "SELECT path,hash FROM attachments ORDER BY path")
        self.assertEqual(hashlib.sha256(b"first").hexdigest(), attachments[0]["hash"])
        self.assertEqual(hashlib.sha256(b"second").hexdigest(), attachments[1]["hash"])
        self.assertEqual(1, self.counts(self.db)["approvals"])

    def test_done_refuses_other_claimant_and_final_tasks(self):
        self.receipt("proof.txt")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET status='in-progress',owner='alice',claimed_by='alice' WHERE id='T1'")
            db.commit()
        code, _, error = self.call(self.db, "done", "T1", "--by", "bob", "--receipt", "proof.txt", "--proof", "x")
        self.assertEqual(2, code)
        self.assertIn("claimed by alice", error)
        self.assertEqual(0, self.counts(self.db)["attachments"])

        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET status='done' WHERE id='T1'")
            db.commit()
        code, _, error = self.call(self.db, "done", "T1", "--by", "alice", "--receipt", "proof.txt", "--proof", "x")
        self.assertEqual(2, code)
        self.assertIn("final task", error)
        self.add_task(self.db, "T2", status="canceled")
        code, _, error = self.call(self.db, "done", "T2", "--by", "alice", "--receipt", "proof.txt", "--proof", "x")
        self.assertEqual(2, code)
        self.assertIn("final task", error)

    def test_receipt_boundaries_fail_without_database_writes(self):
        self.receipt("real.txt")
        (self.receipts / "linked.txt").symlink_to(self.receipts / "real.txt")
        self.receipt(".env", b"secret")
        cases = ("missing.txt", "../outside.txt", "linked.txt", ".env")
        initial = self.counts(self.db)
        for value in cases:
            with self.subTest(value=value):
                code, _, _ = self.call(self.db, "done", "T1", "--by", "alice", "--receipt", value, "--proof", "x")
                self.assertEqual(2, code)
                self.assertEqual(initial, self.counts(self.db))

    def test_receipt_change_rolls_back_every_database_write(self):
        path = self.receipt("proof.txt", b"before")

        def change():
            path.write_bytes(b"after")

        before = self.counts(self.db)
        code, _, error = self.call(
            self.db, "done", "T1", "--by", "alice", "--receipt", "proof.txt", "--proof", "x", hook=change,
        )
        self.assertEqual(2, code)
        self.assertIn("changed during the operation", error)
        self.assertEqual(before, self.counts(self.db))
        self.assertEqual(0, self.rows(self.db, "SELECT flag FROM tasks WHERE id='T1'")[0]["flag"])

    def test_done_duplicate_retry_has_no_duplicate_rows(self):
        self.receipt("proof.txt")
        args = ("done", "T1", "--by", "alice", "--receipt", "proof.txt", "--proof", "same")
        self.assertEqual(0, self.call(self.db, *args)[0])
        before = self.counts(self.db)
        code, output, _ = self.call(self.db, *args)
        self.assertEqual(0, code)
        self.assertIn("duplicate", output)
        self.assertEqual(before, self.counts(self.db))

    def test_accept_requires_flag_and_receipt_then_sets_accepted_with_activity(self):
        code, _, error = self.call(self.db, "accept", "T1", "--by", "architect")
        self.assertEqual(2, code)
        self.assertIn("not flagged", error)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET flag=1,owner='worker',claimed_by='worker' WHERE id='T1'")
            db.commit()
        code, _, error = self.call(self.db, "accept", "T1", "--by", "architect")
        self.assertEqual(2, code)
        self.assertIn("no receipt", error)
        self.receipt("proof.txt")
        self.assertEqual(0, self.call(
            self.db, "done", "T1", "--by", "worker", "--receipt", "proof.txt", "--proof", "built",
        )[0])
        code, output, error = self.call(self.db, "accept", "T1", "--by", "architect")
        self.assertEqual((0, "ok accept T1\n", ""), (code, output, error))
        self.assertEqual(
            {"status": "accepted", "flag": 1, "owner": "worker", "claimed_by": "worker"},
            self.rows(self.db, "SELECT status,flag,owner,claimed_by FROM tasks WHERE id='T1'")[0],
        )
        self.assertEqual(
            {"old_value": "todo", "new_value": "accepted", "actor": "architect", "note": "accepted receipt"},
            self.rows(
                self.db,
                "SELECT old_value,new_value,actor,note FROM activity WHERE subject_id='T1' AND field='status' ORDER BY id DESC LIMIT 1",
            )[0],
        )

    def test_accept_retry_is_a_no_op_and_accepted_is_final(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET flag=1,owner='worker',claimed_by='worker' WHERE id='T1'")
            db.commit()
        self.receipt("proof.txt")
        self.assertEqual(0, self.call(
            self.db, "done", "T1", "--by", "worker", "--receipt", "proof.txt", "--proof", "built",
        )[0])
        self.assertEqual((0, "ok accept T1\n", ""), self.call(self.db, "accept", "T1", "--by", "architect"))
        before = self.counts(self.db)
        self.assertEqual((0, "ok accept T1 duplicate\n", ""), self.call(self.db, "accept", "T1", "--by", "architect"))
        self.assertEqual(before, self.counts(self.db))
        for verb in (("claim", "T1", "--by", "worker"), ("block", "T1", "wait", "--by", "worker")):
            code, _, error = self.call(self.db, *verb)
            self.assertEqual(2, code)
            self.assertIn("final task T1: accepted", error)

    def test_accept_upgrades_a_done_task_and_never_touches_canceled(self):
        self.add_task(self.db, "T2", status="done", flag=1)
        self.add_task(self.db, "T3", status="canceled", flag=1)
        with closing(sqlite3.connect(self.db)) as db:
            for task in ("T2", "T3"):
                db.execute(
                    "INSERT INTO activity (subject_type,subject_id,field,new_value,actor,at) VALUES ('task',?,'receipt','x','w','t')",
                    (task,),
                )
            db.commit()
        self.assertEqual((0, "ok accept T2\n", ""), self.call(self.db, "accept", "T2", "--by", "architect"))
        code, _, error = self.call(self.db, "accept", "T3", "--by", "architect")
        self.assertEqual(2, code)
        self.assertIn("final task T3: canceled", error)
        self.assertEqual(
            [{"id": "T2", "status": "accepted"}, {"id": "T3", "status": "canceled"}],
            self.rows(self.db, "SELECT id,status FROM tasks WHERE id IN ('T2','T3') ORDER BY id"),
        )

    def test_accept_on_tracker_without_accepted_status_sets_done_and_warns(self):
        database = self.make_db("legacy.sqlite", legacy_blueprint())
        self.add_task(database, "T1", flag=1)
        with closing(sqlite3.connect(database)) as db:
            db.execute(
                "INSERT INTO activity (subject_type,subject_id,field,new_value,actor,at) VALUES ('task','T1','receipt','x','w','t')"
            )
            db.commit()
        code, output, error = self.call(database, "accept", "T1", "--by", "architect")
        self.assertEqual((0, "ok accept T1\n"), (code, output))
        self.assertIn("upgrade the tracker schema", error.lower())
        self.assertEqual("done", self.rows(database, "SELECT status FROM tasks WHERE id='T1'")[0]["status"])

    def test_comment_field_and_flag(self):
        code, output, error = self.call(
            self.db, "comment", "T1", "Title is too long", "--field", "title", "--flag", "--by", "person",
        )
        self.assertEqual((0, "ok comment T1\n", ""), (code, output, error))
        self.assertEqual(0, self.call(self.db, "comment", "T1", "Looks right", "--field", "acceptance", "--by", "person")[0])
        self.assertEqual(0, self.call(self.db, "comment", "T1", "General note", "--by", "person")[0])
        self.assertEqual([
            {"field": "title", "body": "Flag: Title is too long"},
            {"field": "acceptance", "body": "Looks right"},
            {"field": None, "body": "General note"},
        ], self.rows(self.db, "SELECT field,body FROM comments WHERE subject_id='T1' ORDER BY id"))
        self.assertEqual(
            ["Flag: Title is too long", "Looks right", "General note"],
            [row["note"] for row in self.rows(self.db, "SELECT note FROM activity WHERE field='comment' ORDER BY id")],
        )
        before = self.counts(self.db)
        for bad in (("--field", "Two words"), ("--field", "")):
            code, _, error = self.call(self.db, "comment", "T1", "x", *bad, "--by", "person")
            self.assertEqual(2, code)
            self.assertIn("--field must be one lowercase field name", error)
        code, _, error = self.call(self.db, "claim", "T1", "--flag", "--by", "person")
        self.assertEqual(2, code)
        self.assertIn("belong to comment", error)
        self.assertEqual(before, self.counts(self.db))

    def test_comment_field_needs_the_migrated_column(self):
        database = self.make_db("legacy.sqlite", legacy_blueprint())
        self.add_task(database, "T1")
        code, _, error = self.call(database, "comment", "T1", "x", "--field", "title", "--by", "person")
        self.assertEqual(2, code)
        self.assertIn("upgrade the tracker schema", error.lower())
        self.assertEqual(0, self.call(database, "comment", "T1", "flag only", "--flag", "--by", "person")[0])
        self.assertEqual([{"body": "Flag: flag only"}], self.rows(database, "SELECT body FROM comments"))

    def test_create_without_project_makes_an_inbox_task(self):
        code, output, error = self.call(self.db, "create", "--title", "Loose idea", "--by", "person", *self.six())
        self.assertEqual((0, "T2\n", ""), (code, output, error))
        self.assertEqual(0, self.call(self.db, "create", "--title", "Second idea", "--by", "person", *self.six())[0])
        self.assertEqual(
            [{"id": "T2", "project": None, "ord": 1, "status": "todo"}, {"id": "T3", "project": None, "ord": 2, "status": "todo"}],
            self.rows(self.db, "SELECT id,project,ord,status FROM tasks WHERE id IN ('T2','T3') ORDER BY id"),
        )
        self.assertEqual(
            [{"note": "project=inbox"}],
            self.rows(self.db, "SELECT note FROM activity WHERE subject_id='T2' AND field='create'"),
        )
        code, output, _ = self.call(self.db, "show", "T2")
        self.assertEqual(0, code)
        self.assertIn('"project": null', output)
        self.assertEqual(2, self.call(self.db, "create", "--by", "person")[0])

    def test_same_relative_bytes_from_two_roots_remain_distinct(self):
        second_root = self.root / "other-receipts"
        second_root.mkdir()
        first = self.receipt("same/proof.txt", b"same bytes")
        second = second_root / "same/proof.txt"
        second.parent.mkdir()
        second.write_bytes(b"same bytes")
        args = ("done", "T1", "--by", "alice", "--receipt", "same/proof.txt", "--proof", "same proof")

        self.assertEqual(0, self.call(self.db, *args)[0])
        self.assertEqual(0, self.call(self.db, *args, receipt_root=second_root)[0])

        expected_links = sorted(
            (
                {"scope": str(self.receipts), "external_id": str(first.resolve()), "path": str(first.resolve())},
                {"scope": str(second_root), "external_id": str(second.resolve()), "path": str(second.resolve())},
            ),
            key=lambda row: row["path"],
        )
        expected_paths = [row["path"] for row in expected_links]
        links = self.rows(self.db, "SELECT scope,external_id,path FROM task_links ORDER BY path")
        self.assertEqual(expected_links, links)
        self.assertEqual(expected_paths, [row["path"] for row in self.rows(self.db, "SELECT path FROM attachments ORDER BY path")])
        self.assertEqual(2, self.counts(self.db)["comments"])
        self.assertEqual(2, self.counts(self.db)["activity"])

    def test_block_duplicate_retry_and_activity(self):
        args = ("block", "T1", "waiting", "--by", "alice")
        self.assertEqual(0, self.call(self.db, *args)[0])
        before = self.counts(self.db)
        code, output, _ = self.call(self.db, *args)
        self.assertEqual(0, code)
        self.assertIn("duplicate", output)
        self.assertEqual(before, self.counts(self.db))
        task = self.rows(self.db, "SELECT status,flag FROM tasks WHERE id='T1'")[0]
        self.assertEqual({"status": "blocked", "flag": 1}, task)

    def test_block_takeover_keeps_controller_and_records_reason(self):
        self.assertEqual(0, self.call(self.db, "claim", "T1", "--by", "worker")[0])
        code, output, error = self.call(
            self.db, "block", "T1", "review failed", "--by", "lead", "--takeover", "lead decision",
        )
        self.assertEqual((0, "ok block T1\n", ""), (code, output, error))
        self.assertEqual(
            {"status": "blocked", "owner": "worker", "claimed_by": "worker"},
            self.rows(self.db, "SELECT status,owner,claimed_by FROM tasks WHERE id='T1'")[0],
        )
        self.assertEqual(
            {"actor": "lead", "note": "review failed | takeover: lead decision"},
            self.rows(
                self.db,
                "SELECT actor,note FROM activity WHERE subject_id='T1' AND field='status' ORDER BY id DESC LIMIT 1",
            )[0],
        )

    def test_business_input_block_sets_view_and_later_claim_clears_tag(self):
        code, _, _ = self.call(self.db, "block", "T1", "person must choose", "--by", "alice", "--business-input")
        self.assertEqual(0, code)
        task = self.rows(self.db, "SELECT status,tags FROM tasks WHERE id='T1'")[0]
        self.assertEqual({"status": "blocked", "tags": "business-input"}, task)
        self.assertEqual([{"id": "T1"}], self.rows(self.db, "SELECT id FROM needs_business_input"))

        self.assertEqual(0, self.call(self.db, "claim", "T1", "--by", "alice")[0])
        task = self.rows(self.db, "SELECT status,tags FROM tasks WHERE id='T1'")[0]
        self.assertEqual({"status": "in-progress", "tags": None}, task)
        self.assertEqual([], self.rows(self.db, "SELECT id FROM needs_business_input"))

    def test_close_now_requires_open_flag_and_receipt_activity(self):
        self.receipt("proof.txt")
        self.assertEqual(0, self.call(
            self.db, "done", "T1", "--by", "alice", "--receipt", "proof.txt", "--proof", "built",
        )[0])
        rows = self.rows(self.db, "SELECT id,evidence_path FROM close_now")
        self.assertEqual([{"id": "T1", "evidence_path": str((self.receipts / "proof.txt").resolve())}], rows)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET status='done' WHERE id='T1'")
            db.commit()
        self.assertEqual([], self.rows(self.db, "SELECT id FROM close_now"))

    def test_apply_is_idempotent_on_existing_database(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("DROP VIEW close_now")
            db.execute("DROP VIEW needs_business_input")
            db.executescript(apply_sql())
            db.executescript(apply_sql())
            names = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='view' AND name IN ('close_now','needs_business_input')"
                )
            }
        self.assertEqual({"close_now", "needs_business_input"}, names)

    def test_finish_job_refuses_and_leaves_existing_job_run_untouched(self):
        staffing_root = self.root / "workspace"
        (staffing_root / "state").mkdir(parents=True)
        (staffing_root / "outputs").mkdir()
        log = staffing_root / "state/staffing-runs.jsonl"
        original = b'{"old":true}\n'
        log.write_bytes(original)
        (staffing_root / "outputs/result.md").write_text("evidence", encoding="utf-8")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute(
                'INSERT INTO runs (id,subject_type,subject_id,"by",model,runtime,started_at) '
                "VALUES ('legacy-job','job','Check the task','alice','test-model','codex','2026-09-25')"
            )
            db.commit()
        code, output, error = self.call(
            self.db,
            "finish-job",
            "--run", "test-run",
            "--job", "Check the task",
            "--model", "test-model",
            "--session", "native-session-1",
            "--elapsed-seconds", "12.5",
            "--fix-rounds", "2",
            "--result", "accepted",
            "--evidence", "outputs/result.md",
            "--by", "alice",
            receipt_root=staffing_root,
        )
        self.assertEqual((2, ""), (code, output))
        self.assertIn("finish-job is retired. Use run-start on a task, then run-end.", error)
        self.assertEqual(original, log.read_bytes())
        record = self.rows(self.db, 'SELECT id,subject_type,subject_id,"by",model,runtime,session,result,fix_rounds,evidence,note FROM runs')[0]
        self.assertEqual("legacy-job", record["id"])
        self.assertEqual("job", record["subject_type"])
        self.assertEqual("Check the task", record["subject_id"])
        self.assertEqual("test-model", record["model"])
        self.assertEqual("alice", record["by"])
        self.assertIsNone(record["session"])
        self.assertIsNone(record["result"])

    def test_finish_job_failure_does_not_touch_staffing_log(self):
        staffing_root = self.root / "workspace-failure"
        (staffing_root / "state").mkdir(parents=True)
        log = staffing_root / "state/staffing-runs.jsonl"
        original = b'{"old":true}\n'
        log.write_bytes(original)
        code, _, error = self.call(
            self.db,
            "finish-job", "--job", "x", "--model", "m", "--elapsed-seconds", "1",
            "--fix-rounds", "0", "--result", "blocked", "--evidence", "missing.md", "--by", "alice",
            receipt_root=staffing_root,
        )
        self.assertEqual(2, code)
        self.assertIn("finish-job is retired", error)
        self.assertEqual(original, log.read_bytes())

    def test_finish_job_refuses_even_without_by(self):
        self.receipt("finish.md")
        code, _, error = self.call(
            self.db, "finish-job", "--job", "x", "--model", "m", "--elapsed-seconds", "1",
            "--fix-rounds", "0", "--result", "done", "--evidence", "finish.md",
        )
        self.assertEqual(2, code)
        self.assertIn("finish-job is retired", error)

    def test_finish_job_without_receipt_root_shows_retired_message(self):
        output, error = io.StringIO(), io.StringIO()
        code = work.run(["finish-job"], stdout=output, stderr=error)
        self.assertEqual((2, ""), (code, output.getvalue()))
        self.assertIn("finish-job is retired. Use run-start on a task, then run-end.", error.getvalue())

    def test_retired_job_flags_give_clear_message(self):
        for flag in ("--run", "--job", "--elapsed-seconds"):
            with self.subTest(flag=flag):
                code, output, error = self.call(self.db, "show", "T1", flag, "old")
                self.assertEqual((2, ""), (code, output))
                self.assertIn(f"{flag} is retired", error)

    def test_each_write_command_exports_after_commit(self):
        self.receipt("proof.md")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO functions (id,name) VALUES ('ops','Operations')")
            db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Program')")
            db.execute("INSERT INTO themes (id,program,name,ord) VALUES ('TH1','PG1','Theme',1)")
            db.execute("INSERT INTO projects (id,title,status,program,theme) VALUES ('WS01','Stream','todo','PG1','TH1')")
            db.commit()
        with mock.patch.object(work, "export_after_write") as exported:
            calls = [
                ("claim", "T1", "--by", "alice"),
                ("comment", "T1", "note", "--by", "alice"),
                ("done", "T1", "--by", "alice", "--receipt", "proof.md", "--proof", "built"),
                ("block", "T1", "waiting", "--by", "alice"),
                ("create", "--title", "New", "--project", "WS01", "--by", "alice", *self.six()),
                ("accept", "T1", "--by", "architect"),
                ("program-create", "--name", "Second program", "--by", "lead"),
                ("theme-create", "--program", "PG2", "--name", "Second theme", "--by", "lead"),
                (
                    "stream-create", "--program", "PG2", "--theme", "TH2", "--function", "ops",
                    "--title", "Second stream", "--by", "lead",
                ),
            ]
            for arguments in calls:
                self.assertEqual(0, self.call(self.db, *arguments)[0])
            code, output, _ = self.call(
                self.db, "run-start", "T1", "--by", "alice", "--model", "model", "--runtime", "codex",
            )
            self.assertEqual(0, code)
            self.assertEqual(0, self.call(
                self.db, "run-end", output.strip(), "--result", "done", "--evidence", "proof.md",
            )[0])
        self.assertEqual(11, exported.call_count)

    def test_failed_export_warns_once_and_keeps_write(self):
        with mock.patch.object(work.importlib.util, "spec_from_file_location", side_effect=RuntimeError("boom\nmore")):
            code, _, error = self.call(self.db, "comment", "T1", "saved", "--by", "alice")
        self.assertEqual(0, code)
        self.assertEqual(["warning: state export failed: boom more"], error.splitlines())
        self.assertEqual([{"body": "saved"}], self.rows(self.db, "SELECT body FROM comments"))

    def test_export_rewrites_canonical_files_with_stable_order(self):
        state = self.db.parent / "state"
        state.mkdir()
        (state / "tasks.jsonl").write_text("stale\n", encoding="utf-8")
        self.assertEqual(0, self.call(self.db, "comment", "T1", "saved", "--by", "alice")[0])
        first = (state / "tasks.jsonl").read_bytes()
        self.assertNotEqual(b"stale\n", first)
        self.assertFalse((state / "tasks.new.jsonl").exists())
        work.export_after_write(self.db, self.receipts, io.StringIO())
        self.assertEqual(first, (state / "tasks.jsonl").read_bytes())

    def test_export_belongs_to_database_not_receipt_workspace(self):
        # g-state-export-lives-with-its-database: both tracker kinds use their own state/.
        for name in ("system", "shop"):
            with self.subTest(database=name):
                folder = self.root / name
                folder.mkdir()
                database = folder / "data.db"
                source = sqlite3.connect(self.db)
                with sqlite3.connect(database) as target:
                    source.backup(target)
                source.close()
                code, _, error = self.call(database, "comment", "T1", name, "--by", "alice")
                self.assertEqual((0, ""), (code, error))
                exported = folder / "state/tasks.jsonl"
                self.assertTrue(exported.is_file())
                self.assertEqual("T1", json.loads(exported.read_text().splitlines()[0])["id"])
                self.assertFalse((self.receipts / "state").exists())

    def test_handoff_export_metadata_uses_selected_database(self):
        spec = work.importlib.util.spec_from_file_location(
            "work_test_write_handoff", MODULES_ROOT / "hooks/write_handoff.py")
        hook = work.importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        vault = self.root / "portfolio"
        stale = vault / "workspace/state"
        stale.mkdir(parents=True)
        (stale / "tasks.jsonl").write_text("old copy\n")
        for folder in (self.root / "system", vault / "shop"):
            with self.subTest(database=folder):
                folder.mkdir(parents=True)
                self.assertIsNone(hook.export_metadata(folder / "data.db", vault))
                state = folder / "state"
                state.mkdir()
                (state / "tasks.jsonl").write_text("current export\n")
                exported, stamp = hook.export_metadata(folder / "data.db", vault)
                expected = str(state.relative_to(vault) if state.is_relative_to(vault) else state) + "/"
                self.assertEqual(expected, exported)
                self.assertTrue(stamp)

    def test_run_start_and_end_record_one_run_only(self):
        staffing_root = self.root / "run-workspace"
        (staffing_root / "state").mkdir(parents=True)
        (staffing_root / "outputs").mkdir()
        (staffing_root / "state/staffing-runs.jsonl").write_text("", encoding="utf-8")
        (staffing_root / "outputs/proof.md").write_text("evidence", encoding="utf-8")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute(
                "INSERT INTO programs (id,name) VALUES ('PG1','Program')"
            )
            db.execute(
                "INSERT INTO themes (id,program,name,ord) VALUES ('TH1','PG1','Theme',1)"
            )
            db.execute(
                "INSERT INTO projects (id,title,status,program,theme) VALUES ('WS01','Stream','todo','PG1','TH1')"
            )
            db.commit()
        code, output, error = self.call(
            self.db, "run-start", "T1", "--by", "alice", "--model", "model-a", "--runtime", "codex",
            "--session", "native-session-2",
            receipt_root=staffing_root,
        )
        self.assertEqual((0, ""), (code, error))
        run_id = output.strip()
        code, _, error = self.call(
            self.db, "run-end", run_id, "--result", "built", "--evidence", "outputs/proof.md",
            "--fix-rounds", "1", receipt_root=staffing_root,
        )
        self.assertEqual((0, ""), (code, error))
        row = self.rows(self.db, "SELECT subject_type,subject_id,session,result,fix_rounds,evidence,ended_at FROM runs")[0]
        self.assertEqual(("task", "T1", "native-session-2", "built", 1, "outputs/proof.md"), tuple(row[key] for key in row if key != "ended_at"))
        self.assertTrue(row["ended_at"])
        self.assertEqual("", (staffing_root / "state/staffing-runs.jsonl").read_text(encoding="utf-8"))

    def test_run_start_refuses_stream_and_non_task(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Program')")
            db.execute("INSERT INTO themes (id,program,name,ord) VALUES ('TH1','PG1','Theme',1)")
            db.execute("INSERT INTO projects (id,title,status,program,theme) VALUES ('WS01','Stream','todo','PG1','TH1')")
            db.execute("INSERT INTO goals (id,title,horizon) VALUES ('G1','Goal','quarter')")
            db.commit()
        before = self.rows(self.db, "SELECT id FROM runs")
        for subject, kind in (("WS01", "work stream"), ("PG1", "program"),
                              ("G1", "goal"), ("missing", "unknown"), (None, None)):
            arguments = ["run-start"] + ([subject] if subject else []) + [
                "--by", "alice", "--model", "model-a", "--runtime", "codex",
            ]
            code, output, error = self.call(self.db, *arguments)
            self.assertEqual((2, ""), (code, output))
            expected = (f"{subject} is a {kind}, not a task." if kind != "unknown" else
                        "missing is unknown, not a task.") if subject else "run-start needs a task id."
            self.assertIn(expected, error)
            self.assertIn(work.RUN_TASK_GUIDANCE, error)
        self.assertEqual(before, self.rows(self.db, "SELECT id FROM runs"))

    def test_run_move_writes_one_activity_and_refuses_invalid_targets(self):
        self.add_task(self.db, "T2")
        self.add_task(self.db, "T3", status="done")
        self.add_task(self.db, "T4", status="canceled")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','Stream','todo')")
            db.commit()
        code, run_id, error = self.call(
            self.db, "run-start", "T1", "--by", "alice", "--model", "model-a", "--runtime", "codex",
        )
        self.assertEqual((code, error), (0, ""))
        run_id = run_id.strip()
        for target, message in (("WS01", "work stream, not a task"), ("unknown", "unknown, not a task"),
                                ("T3", "done task"), ("T4", "canceled task")):
            code, _, error = self.call(self.db, "run-move", run_id, "--task", target, "--by", "alice")
            self.assertEqual(code, 2)
            self.assertIn(message, error)
        self.assertEqual(0, self.call(self.db, "run-move", run_id, "--task", "T2", "--by", "alice")[0])
        self.assertEqual(0, self.call(self.db, "run-move", run_id, "--task", "T2", "--by", "alice")[0])
        self.assertEqual(
            [{"subject_type": "run", "subject_id": run_id, "field": "subject", "old_value": "task:T1",
              "new_value": "task:T2", "actor": "alice"}],
            self.rows(self.db, "SELECT subject_type,subject_id,field,old_value,new_value,actor FROM activity"),
        )
        self.assertEqual("T2", self.rows(self.db, "SELECT subject_id FROM runs WHERE id=?", (run_id,))[0]["subject_id"])

    def test_run_note_records_only_on_an_open_run(self):
        code, run_id, error = self.call(
            self.db, "run-start", "T1", "--by", "alice", "--model", "model-a", "--runtime", "codex",
        )
        self.assertEqual((0, ""), (code, error))
        run_id = run_id.strip()
        code, output, error = self.call(self.db, "run-note", run_id, "Built first part", "--by", "alice")
        self.assertEqual((0, f"ok run-note {run_id}\n", ""), (code, output, error))
        self.assertEqual(
            [{"subject_type": "run", "subject_id": run_id, "author": "alice", "body": "Built first part"}],
            self.rows(self.db, "SELECT subject_type,subject_id,author,body FROM comments"),
        )
        self.assertEqual([], self.rows(self.db, "SELECT * FROM activity"))

        code, _, error = self.call(self.db, "run-note", "R-missing", "step", "--by", "alice")
        self.assertEqual(2, code)
        self.assertIn("no such run: R-missing", error)

        self.receipt("proof.md")
        self.assertEqual(0, self.call(
            self.db, "run-end", run_id, "--result", "pass", "--evidence", "proof.md",
        )[0])
        code, _, error = self.call(self.db, "run-note", run_id, "Too late", "--by", "alice")
        self.assertEqual(2, code)
        self.assertIn("run is already ended", error)
        self.assertEqual(1, len(self.rows(self.db, "SELECT id FROM comments")))

    def test_block_reason_reuse_after_other_transitions_is_new_action(self):
        self.assertEqual(0, self.call(self.db, "block", "T1", "A", "--by", "alice")[0])
        self.assertEqual(0, self.call(self.db, "claim", "T1", "--by", "alice")[0])
        self.assertEqual(0, self.call(self.db, "block", "T1", "B", "--by", "alice")[0])
        before = self.counts(self.db)

        code, output, _ = self.call(self.db, "block", "T1", "A", "--by", "alice")
        self.assertEqual(0, code)
        self.assertNotIn("duplicate", output)
        after = self.counts(self.db)
        self.assertEqual(before["comments"] + 1, after["comments"])
        self.assertEqual(before["activity"] + 1, after["activity"])
        latest = self.rows(
            self.db,
            "SELECT new_value,actor,note FROM activity WHERE subject_id='T1' AND field='status' ORDER BY id DESC LIMIT 1",
        )[0]
        self.assertEqual({"new_value": "blocked", "actor": "alice", "note": "A"}, latest)

        retry_before = self.counts(self.db)
        code, output, _ = self.call(self.db, "block", "T1", "A", "--by", "alice")
        self.assertEqual(0, code)
        self.assertIn("duplicate", output)
        self.assertEqual(retry_before, self.counts(self.db))

    def test_foreign_keys_enabled_and_existing_defect_is_only_reported(self):
        db = work.connect_database(self.db, read_only=False)
        self.assertEqual(1, db.execute("PRAGMA foreign_keys").fetchone()[0])
        db.close()
        with closing(sqlite3.connect(self.db)) as raw:
            raw.execute(
                "INSERT INTO comments (subject_type,subject_id,author,at,body,reply_to) VALUES ('task','legacy','old','x','dangling',999)"
            )
            raw.commit()
        code, _, error = self.call(self.db, "comment", "T1", "new", "--by", "alice")
        self.assertEqual(0, code)
        self.assertIn("existing foreign-key defects: 1", error)
        self.assertEqual(1, len(self.rows(self.db, "PRAGMA foreign_key_check")))

    def test_show_is_read_only(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        code, output, _ = self.call(self.db, "show", "T1")
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertEqual(0, code)
        self.assertEqual(before, after)
        self.assertEqual("T1", json.loads(output.split("\n link:", 1)[0])["id"])

    def test_create_tags_normalizes_case_spaces_and_duplicates(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','Stream','todo')")
            db.commit()
        code, output, error = self.call(
            self.db, "create", "--title", "Tagged", "--project", "WS01",
            "--tags", "Jev, replay,jev", "--by", "lead", *self.six(),
        )
        self.assertEqual((0, ""), (code, error))
        self.assertEqual("jev,replay", self.rows(
            self.db, "SELECT tags FROM tasks WHERE id=?", (output.strip(),)
        )[0]["tags"])

    def test_task_update_edits_fields_and_comments_each_old_and_new_value(self):
        code, _, error = self.call(
            self.db, "task-update", "T1", "--by", "lead", "--title", "New title",
            "--note", "First", "--append-note", "Second", "--acceptance", '["Review it"]',
            "--tags", "Jev,review", "--add-tag", "jev", "--remove-tag", "review",
        )
        self.assertEqual((0, ""), (code, error))
        self.assertEqual(
            {"title": "New title", "note": "First\nSecond", "acceptance": '["Review it"]', "tags": "jev"},
            self.rows(self.db, "SELECT title,note,acceptance,tags FROM tasks WHERE id='T1'")[0],
        )
        comments = self.rows(self.db, "SELECT author,body FROM comments WHERE subject_id='T1' ORDER BY id")
        self.assertEqual(4, len(comments))
        self.assertTrue(all(row["author"] == "lead" and " -> " in row["body"] for row in comments))
        self.assertIn('"Synthetic T1" -> "New title"', comments[0]["body"])

    def test_task_update_add_remove_tag_deduplicates_existing_case(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET tags='Jev,jev,Other' WHERE id='T1'")
            db.commit()
        code, _, error = self.call(
            self.db, "task-update", "T1", "--by", "lead", "--add-tag", "JEV",
            "--add-tag", "New", "--remove-tag", "other",
        )
        self.assertEqual(0, code, error)
        self.assertEqual("jev,new", self.rows(self.db, "SELECT tags FROM tasks WHERE id='T1'")[0]["tags"])

    def standing_session_task(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Foundation'),('PG2','Agent Team')")
            db.executemany("INSERT INTO projects (id,title,status,program) VALUES (?,?,?,?)", (
                ("WS01", "Original", "todo", "PG1"),
                ("WS02", "Same program", "todo", "PG1"),
                ("WS03", "Another program", "todo", "PG2"),
                ("OLD", "Retired", "superseded", "PG2"),
                ("STOP", "Canceled", "canceled", "PG2"),
            ))
            db.execute("UPDATE tasks SET title='Session work to place',project='WS01',tags='recurring,ops',idempotency_key='session-holding-task' "
                       "WHERE id='T1'")
            db.execute("INSERT INTO approvals (id,subject_type,subject_id,call,given_at) "
                       "VALUES (1,'task','T1','approve','2026-10-04')")
            db.commit()

    def test_standing_title_is_ordinary_on_create_for_all_task_kinds(self):
        self.standing_session_task()
        for title in ("Session work to place", "  session WORK to PLACE  ", "\tSESSION WORK TO PLACE\t"):
            for tags in ((), ("--tags", "ops"), ("--tags", "recurring")):
                for status in ("todo", "backlog", "done"):
                    with self.subTest(title=title, tags=tags, status=status):
                        code, output, error = self.call(self.db, "create", "--title", title, "--project", "WS03",
                                                       "--status", status, "--note", "Synthetic", "--by", "lead", *tags, *self.six())
                        self.assertEqual((code, error), (0, ""))
                        row = self.rows(self.db, "SELECT title,idempotency_key FROM tasks WHERE id=?", (output.strip(),))[0]
                        self.assertEqual(row, {"title": title.strip(), "idempotency_key": None})

    def test_standing_title_is_ordinary_on_task_update(self):
        self.standing_session_task()
        for task, status, tags in (("T2", "todo", "recurring"), ("T3", "todo", None), ("T4", "done", "recurring")):
            self.add_task(self.db, task, status=status)
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("UPDATE tasks SET tags=? WHERE id=?", (tags, task))
            for title in ("Session work to place", "  SESSION work TO place  "):
                with self.subTest(task=task, title=title):
                    code, _, error = self.call(self.db, "task-update", task, "--title", title, "--by", "lead")
                    self.assertEqual((code, error), (0, ""))
                    self.assertIsNone(self.rows(self.db, "SELECT idempotency_key FROM tasks WHERE id=?", (task,))[0]["idempotency_key"])

    def test_adding_recurring_tag_does_not_adopt_duplicate_title(self):
        self.standing_session_task()
        self.add_task(self.db, "T2", title="  SESSION work TO place  ")
        for tags in (("--add-tag", "recurring"), ("--tags", "ops,RECURRING")):
            with self.subTest(tags=tags):
                code, _, error = self.call(self.db, "task-update", "T2", "--by", "lead", *tags)
                self.assertEqual((code, error), (0, ""))
        self.assertIsNone(self.rows(self.db, "SELECT idempotency_key FROM tasks WHERE id='T2'")[0]["idempotency_key"])
        self.assertEqual(0, self.call(self.db, "task-update", "T2", "--remove-tag", "recurring", "--by", "lead")[0])

    def test_standing_title_create_and_update_keep_behavior_without_live_standing_task(self):
        for existing in ("none", "closed", "untagged", "malformed"):
            for action in ("create", "task-update"):
                with self.subTest(existing=existing, action=action):
                    database = self.make_db(existing + "-" + action + ".sqlite")
                    self.add_task(database, "T1")
                    if existing != "none":
                        self.add_task(database, "T2", title="Session work to place", status="done" if existing == "closed" else "todo")
                        if existing in {"closed", "malformed"}:
                            with closing(sqlite3.connect(database)) as db:
                                db.execute("UPDATE tasks SET tags=? WHERE id='T2'", ("recurring," if existing == "malformed" else "recurring",))
                                db.commit()
                    with closing(sqlite3.connect(database)) as db:
                        db.execute("INSERT INTO projects (id,title,status) VALUES ('WS01','Stream','todo')")
                        db.commit()
                    arguments = ("create", "--project", "WS01", *self.six(database)) if action == "create" else ("task-update", "T1")
                    code, _, error = self.call(database, *arguments, "--title", "Session work to place", "--tags", "recurring", "--by", "lead")
                    self.assertEqual((code, error), (0, ""))

    def test_only_keyed_task_keeps_recurring_and_every_task_can_be_retitled(self):
        self.standing_session_task()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET created_on='2026-10-02' WHERE id='T1'")
            db.commit()
        for task, status, tags, date in (("T2", "todo", "recurring", "2026-10-04"),
                                         ("T3", "todo", None, "2026-10-01"),
                                         ("T4", "done", "recurring", "2020-01-01")):
            self.add_task(self.db, task, title="  SESSION work TO place  ", status=status)
            with closing(sqlite3.connect(self.db)) as db:
                db.execute("UPDATE tasks SET tags=?,created_on=? WHERE id=?", (tags, date, task))
                db.commit()
        for task in ("T2", "T3", "T4"):
            with self.subTest(task=task):
                self.assertEqual(0, self.call(self.db, "task-update", task, "--title", "Repaired " + task, "--by", "lead")[0])
        self.assertEqual(0, self.call(self.db, "task-update", "T1", "--by", "lead", "--title", "Renamed")[0])
        for change in (("--remove-tag", "recurring"), ("--tags", "ops")):
            code, _, error = self.call(self.db, "task-update", "T1", "--by", "lead", *change)
            self.assertEqual(code, 2)
            self.assertIn("standing task", error)

    def test_keyed_task_is_protected_regardless_of_timestamps(self):
        self.standing_session_task()
        self.add_task(self.db, "T9", title="Session work to place")
        dates = (("2026-10-01T15:56:39-04:00", "2026-10-01T15:00:00-05:00"),
                 ("2026-10-04", "2026-10-02"), ("2026-10-04", "2026-10-04"),
                 (None, "2026-10-02"), ("not a timestamp", "1900-01-01"))
        for original, duplicate in dates:
            with self.subTest(original=original, duplicate=duplicate):
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute("UPDATE tasks SET title='Session work to place',created_on=? WHERE id='T1'", (original,))
                    db.execute("UPDATE tasks SET title='Session work to place',tags='recurring',created_on=? WHERE id='T9'", (duplicate,))
                code, _, error = self.call(self.db, "task-update", "T1", "--remove-tag", "recurring", "--by", "lead")
                self.assertEqual(code, 2)
                self.assertIn("standing task", error)
                self.assertEqual(0, self.call(self.db, "task-update", "T9", "--title", "Repaired", "--by", "lead")[0])

    def test_non_candidates_do_not_block_unrelated_edits_and_can_be_repaired(self):
        variants = (("done", "recurring"), ("canceled", "recurring"), ("superseded", "recurring"),
                    ("todo", None), ("todo", "ops"), ("todo", "recurring,"), ("todo", b"recurring,"))
        for index, (status, tags) in enumerate(variants):
            with self.subTest(status=status, tags=tags):
                self.db = self.make_db("non-candidates-" + str(index) + ".sqlite", schema=((Path(__file__).resolve().parent / '../blueprint.sql')).read_text())
                self.add_task(self.db, "T1")
                self.standing_session_task()
                task = "T2"
                self.add_task(self.db, task, title="  SESSION work TO place  ", status=status)
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute("UPDATE tasks SET tags=? WHERE id=?", (tags, task))
                self.add_task(self.db, "T3", title=b"Session work to place")
                self.add_task(self.db, "T4")
                self.assertEqual((0, ""), self.call(self.db, "task-update", "T4", "--title", "Unrelated edit", "--by", "anyone")[::2])
                self.assertEqual((0, ""), self.call(self.db, "task-update", task, "--title", "Repaired " + task, "--by", "anyone")[::2])
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute("UPDATE tasks SET title='Session work to place' WHERE id=?", (task,))
                if status == "todo":
                    self.assertEqual((0, ""), self.call(self.db, "cancel", task, "--reason", "Repair", "--by", "anyone")[::2])

    def test_duplicate_candidates_can_be_retitled_and_canceled_while_primary_stays_protected(self):
        self.db = self.make_db("duplicate-repair.sqlite", schema=((Path(__file__).resolve().parent / '../blueprint.sql')).read_text())
        self.add_task(self.db, "T1")
        self.standing_session_task()
        for task in ("T2", "T3"):
            self.add_task(self.db, task, title="  SESSION work TO place  ")
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("UPDATE tasks SET tags='recurring',created_on='1900-01-01' WHERE id=?", (task,))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE tasks SET created_on='2026-10-04' WHERE id='T1'")
        self.assertEqual((0, ""), self.call(self.db, "task-update", "T2", "--title", "Repaired duplicate", "--by", "anyone")[::2])
        self.assertEqual((0, ""), self.call(self.db, "cancel", "T3", "--reason", "Repair duplicate", "--by", "anyone")[::2])
        for args in (("task-update", "T1", "--remove-tag", "recurring"), ("cancel", "T1", "--reason", "Repair")):
            code, _, error = self.call(self.db, *args, "--by", "anyone")
            self.assertEqual(code, 2)
            self.assertIn("standing task", error)

    def test_standing_session_task_move_requires_approval(self):
        self.standing_session_task()
        before = self.counts(self.db)
        code, _, error = self.call(self.db, "task-move", "T1", "--project", "WS02", "--by", "lead")
        self.assertEqual(code, 2)
        self.assertIn("needs --approval <approvals id> with call=approve on task T1", error)
        self.assertEqual(before, self.counts(self.db))
        self.assertEqual("WS01", self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])

    def test_standing_session_task_move_refuses_wrong_approval_rows(self):
        self.standing_session_task()
        self.add_task(self.db, "T2")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO decisions (id,name,status) VALUES ('move','Move decision','ruled')")
            db.executemany("INSERT INTO approvals (id,subject_type,subject_id,call,given_at) VALUES (?,?,?,?,?)", (
                (2, "task", "T2", "approve", "2026-10-04"),
                (3, "task", "T1", "wrong", "2026-10-04"),
                (4, "task", "T1", "discuss", "2026-10-04"),
                (5, "task", "T1", "edit", "2026-10-04"),
                (6, "decision", "move", "approve", "2026-10-04"),
            ))
            db.commit()
        before = self.counts(self.db)
        for reference, message in (("move", "must name an approvals row"), ("999", "must name an approvals row"),
                                   ("2", "expected T1"), ("3", "expected approve"), ("4", "expected approve"),
                                   ("5", "expected approve"), ("6", "expected task")):
            with self.subTest(reference=reference):
                code, _, error = self.call(self.db, "task-move", "T1", "--project", "WS02", "--by", "lead",
                                          "--approval", reference)
                self.assertEqual(code, 2)
                self.assertIn(message, error)
                self.assertIn("approval-add on standing task T1", error)
                self.assertEqual(before, self.counts(self.db))
                self.assertEqual("WS01", self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])

    def test_standing_session_task_move_refuses_current_and_former_parent_approvals(self):
        self.standing_session_task()
        self.add_task(self.db, "T2")
        self.add_task(self.db, "T3")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET parent='T2' WHERE id='T1'")
            db.execute("INSERT INTO activity (subject_type,subject_id,field,old_value,new_value,actor,at) "
                       "VALUES ('task','T1','parent','T3','T2','lead','2026-10-04')")
            db.executemany("INSERT INTO approvals (id,subject_type,subject_id,call,given_at) VALUES (?,'task',?,'approve','2026-10-04')",
                           ((2, "T2"), (3, "T3")))
            db.commit()
        before = self.counts(self.db)
        for reference in ("2", "3"):
            with self.subTest(reference=reference):
                code, _, error = self.call(self.db, "task-move", "T1", "--project", "WS02", "--by", "lead",
                                          "--approval", reference)
                self.assertEqual(code, 2)
                self.assertIn("expected T1;", error)
                self.assertEqual(before, self.counts(self.db))
        self.assertEqual("WS01", self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])

    def test_standing_session_task_moves_between_streams_and_programs_with_history(self):
        self.standing_session_task()
        previous = "WS01"
        expected = []
        for target in ("WS02", "WS03"):
            with self.subTest(target=target):
                code, output, error = self.call(
                    self.db, "task-move", "T1", "--project", target, "--by", "lead",
                    "--note", "Standing task placement", "--approval", "1",
                )
                self.assertEqual((0, "ok task-move T1\n", ""), (code, output, error))
                self.assertEqual(target, self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])
                expected.append({
                    "subject_type": "task", "subject_id": "T1", "field": "project",
                    "old_value": previous, "new_value": target, "actor": "lead", "source": work.SOURCE,
                    "note": f'approval 1; FROM "{previous}" TO "{target}"; moved: Standing task placement',
                })
                self.assertEqual(expected, self.rows(self.db,
                    "SELECT subject_type,subject_id,field,old_value,new_value,actor,source,note FROM activity ORDER BY id"
                ))
                self.assertTrue(all(row["at"] for row in self.rows(self.db, "SELECT at FROM activity")))
                previous = target

    def test_standing_session_task_refuses_inbox_and_keeps_protections_after_moves(self):
        self.standing_session_task()
        self.receipt("standing-proof.txt")
        commands = (
            ("task-move", "T1", "--inbox", "--by", "lead"),
            ("done", "T1", "--by", "lead", "--receipt", "standing-proof.txt", "--proof", "Checked"),
            ("accept", "T1", "--by", "architect"),
            ("cancel", "T1", "--by", "lead", "--reason", "Retired"),
            ("task-update", "T1", "--by", "lead", "--remove-tag", "recurring"),
            ("task-update", "T1", "--by", "lead", "--tags", "ops"),
        )
        for target in ("WS01", "WS02", "WS03"):
            if target != "WS01":
                self.assertEqual(0, self.call(
                    self.db, "task-move", "T1", "--project", target, "--by", "lead",
                    "--approval", "1",
                )[0])
            before = self.counts(self.db)
            for command in commands:
                for approval in ((), ("--approval", "1")):
                    with self.subTest(target=target, command=command, approval=approval):
                        code, _, error = self.call(self.db, *command, *approval)
                        self.assertEqual(code, 2)
                        self.assertIn("standing task", error)
                        if "--inbox" in command:
                            self.assertIn("must stay in a stream", error)
                            self.assertIn("inbox", error)
                        self.assertEqual(before, self.counts(self.db))
            row = self.rows(self.db, "SELECT title,status,project,tags FROM tasks WHERE id='T1'")[0]
            self.assertEqual((row["title"], row["status"], row["project"], row["tags"]),
                             ("Session work to place", "todo", target, "recurring,ops"))

    def test_standing_session_task_keeps_destination_checks(self):
        self.standing_session_task()
        for target, message in (("NOPE", "no such project"), ("OLD", "project is superseded"),
                                ("STOP", "project is canceled"),
                                ("WS01", "already in WS01")):
            with self.subTest(target=target):
                code, _, error = self.call(self.db, "task-move", "T1", "--project", target, "--by", "lead", "--approval", "1")
                self.assertEqual(code, 2)
                self.assertIn(message, error)
        self.assertEqual("WS01", self.rows(self.db, "SELECT project FROM tasks WHERE id='T1'")[0]["project"])
        self.assertEqual(self.rows(self.db, "SELECT * FROM activity WHERE subject_id='T1'"), [])

    def test_task_update_refuses_control_fields(self):
        for flag, value in (("--status", "done"), ("--project", "WS02"),
                            ("--program", "PG1"), ("--theme", "TH1"), ("--function", "ops")):
            with self.subTest(flag=flag):
                code, _, error = self.call(
                    self.db, "task-update", "T1", "--by", "lead", "--title", "Changed", flag, value,
                )
                self.assertEqual(2, code)
                self.assertIn("task-update refuses " + flag, error)
                if flag == "--project":
                    self.assertIn("task-move", error)
        self.assertEqual("Synthetic T1", self.rows(self.db, "SELECT title FROM tasks WHERE id='T1'")[0]["title"])

    def test_task_update_refuses_bad_acceptance_json(self):
        for value in ("bad", '{"a":1}', '[1]', '[""]'):
            with self.subTest(value=value):
                code, _, error = self.call(self.db, "task-update", "T1", "--by", "lead", "--acceptance", value)
                self.assertEqual(2, code)
                self.assertIn("JSON list", error)
        self.assertEqual([], self.rows(self.db, "SELECT * FROM comments WHERE subject_id='T1'"))

    def test_link_remove_deletes_only_the_exact_identity_and_logs_once(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executemany("INSERT INTO bugs (id,title) VALUES (?,?)", [("B-1", "Defect"), ("B-2", "Other")])
            db.execute("INSERT INTO incidents (id,title) VALUES ('B-1','Incident')")
            db.execute("INSERT INTO projects (id,title) VALUES ('T1','Project')")
            db.commit()
        self.add_task(self.db, "T2")
        links = [
            ("bug", "B-1", "task", "T1", "about"),
            ("incident", "B-1", "task", "T1", "about"),
            ("bug", "B-2", "task", "T1", "about"),
            ("bug", "B-1", "project", "T1", "about"),
            ("bug", "B-1", "task", "T2", "about"),
            ("bug", "B-1", "task", "T1", "fix"),
            ("bug", "B-1", "project", "T1", "about"),
        ]
        for subject_type, subject_id, target_type, target_id, relation in links:
            code, _, error = self.call(
                self.db, "link", subject_id, "--subject-type", subject_type, "--target-type", target_type,
                "--target-id", target_id, "--relation", relation, "--by", "lead",
            )
            self.assertEqual(0, code, error)
        before = self.rows(self.db, "SELECT * FROM record_links ORDER BY id")
        events = self.rows(self.db, "SELECT * FROM activity ORDER BY id")
        arguments = ("link", "B-1", "--subject-type", "bug", "--target-type", "task",
                     "--target-id", "T1", "--relation", "about", "--by", "lead", "--remove")
        code, output, error = self.call(self.db, *arguments)
        self.assertEqual((0, "", "ok link B-1 --remove\n"), (code, error, output))
        self.assertEqual(before[1:], self.rows(self.db, "SELECT * FROM record_links ORDER BY id"))
        after = self.rows(self.db, "SELECT * FROM activity ORDER BY id")
        self.assertEqual(events, after[:-1])
        self.assertEqual(
            {"subject_type": "bug", "subject_id": "B-1", "field": "link", "old_value": "task:T1",
             "new_value": None, "actor": "lead", "note": "about"},
            {key: after[-1][key] for key in
             ("subject_type", "subject_id", "field", "old_value", "new_value", "actor", "note")},
        )
        code, _, error = self.call(self.db, *arguments)
        self.assertEqual(2, code)
        self.assertIn("no matching record link", error)
        self.assertEqual(after, self.rows(self.db, "SELECT * FROM activity ORDER BY id"))
        self.assertEqual(before[1:], self.rows(self.db, "SELECT * FROM record_links ORDER BY id"))

    def test_link_remove_supports_incidents_projects_and_runs(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO incidents (id,title) VALUES ('I-1','Incident')")
            db.execute("INSERT INTO projects (id,title) VALUES ('P1','Project')")
            db.execute("INSERT INTO runs (id,subject_type,subject_id,by,model,runtime,started_at) "
                       "VALUES ('R1','task','T1','lead','inherit','codex','2026-10-22T00:00:00Z')")
            db.commit()
        for target_type, target_id in (("task", "T1"), ("project", "P1"), ("run", "R1")):
            with self.subTest(target_type=target_type):
                arguments = ("link", "I-1", "--subject-type", "incident", "--target-type", target_type,
                             "--target-id", target_id, "--relation", "about", "--by", "lead")
                self.assertEqual(0, self.call(self.db, *arguments)[0])
                code, _, error = self.call(self.db, *arguments, "--remove")
                self.assertEqual(0, code, error)
                self.assertEqual([], self.rows(self.db, "SELECT * FROM record_links"))
                event = self.rows(self.db, "SELECT * FROM activity ORDER BY id DESC LIMIT 1")[0]
                self.assertEqual(("incident", "I-1", target_type + ":" + target_id, None, "about"),
                                 tuple(event[key] for key in ("subject_type", "subject_id", "old_value", "new_value", "note")))

    def test_link_remove_refuses_missing_match_without_writes(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO bugs (id,title) VALUES ('B-1','Defect')")
            db.execute("INSERT INTO record_links (subject_type,subject_id,target_type,target_id,relation) "
                       "VALUES ('bug','B-1','task','T1','about')")
            db.commit()
        before = self.rows(self.db, "SELECT * FROM record_links")
        code, _, error = self.call(
            self.db, "link", "B-1", "--subject-type", "bug", "--target-type", "task",
            "--target-id", "T1", "--relation", "fix", "--by", "lead", "--remove",
        )
        self.assertEqual(2, code)
        self.assertIn("no matching record link", error)
        self.assertEqual(before, self.rows(self.db, "SELECT * FROM record_links"))
        self.assertEqual([], self.rows(self.db, "SELECT * FROM activity"))

    def test_link_remove_rolls_back_when_change_row_fails(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO bugs (id,title) VALUES ('B-1','Defect')")
            db.execute("INSERT INTO record_links (subject_type,subject_id,target_type,target_id,relation) "
                       "VALUES ('bug','B-1','task','T1','fix')")
            db.execute("CREATE TRIGGER refuse_activity BEFORE INSERT ON activity "
                       "BEGIN SELECT RAISE(ABORT, 'synthetic change failure'); END")
            db.commit()
        before = self.rows(self.db, "SELECT * FROM record_links")
        code, _, error = self.call(
            self.db, "link", "B-1", "--subject-type", "bug", "--target-type", "task",
            "--target-id", "T1", "--relation", "fix", "--by", "lead", "--remove",
        )
        self.assertEqual(2, code)
        self.assertIn("synthetic change failure", error)
        self.assertEqual(before, self.rows(self.db, "SELECT * FROM record_links"))
        self.assertEqual([], self.rows(self.db, "SELECT * FROM activity"))

    def test_bug_close_fixed_requires_fix_link_and_comments_reason(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO bugs (id,title,capability) VALUES ('B-1','Defect','work')")
            db.commit()
        code, _, error = self.call(self.db, "bug-close", "B-1", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("fix link", error)
        self.assertEqual("open", self.rows(self.db, "SELECT status FROM bugs WHERE id='B-1'")[0]["status"])
        self.assertEqual(0, self.call(
            self.db, "link", "B-1", "--subject-type", "bug", "--target-type", "task",
            "--target-id", "T1", "--relation", "fix", "--by", "lead",
        )[0])
        code, _, error = self.call(self.db, "bug-close", "B-1", "--by", "lead")
        self.assertEqual(0, code, error)
        self.assertEqual("fixed", self.rows(self.db, "SELECT status FROM bugs WHERE id='B-1'")[0]["status"])
        self.assertEqual(
            [{"author": "lead", "body": "Closed fixed: fix task: T1"}],
            self.rows(self.db, "SELECT author,body FROM comments WHERE subject_type='bug' AND subject_id='B-1'"),
        )

    def test_bug_close_wont_fix_requires_note(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO bugs (id,title,capability) VALUES ('B-1','Defect','work')")
            db.commit()
        code, _, error = self.call(self.db, "bug-close", "B-1", "--by", "lead", "--status", "wont-fix")
        self.assertEqual(2, code)
        self.assertIn("needs --note", error)
        code, _, error = self.call(
            self.db, "bug-close", "B-1", "--by", "lead", "--status", "wont-fix", "--note", "Outside scope",
        )
        self.assertEqual(0, code, error)
        self.assertEqual("wont-fix", self.rows(self.db, "SELECT status FROM bugs WHERE id='B-1'")[0]["status"])

    def test_run_start_appends_desktop_session_to_note(self):
        code, output, error = self.call(
            self.db, "run-start", "T1", "--by", "lead", "--model", "inherit",
            "--runtime", "claude", "--session", "uuid-1", "--note", "Initial note",
            "--desktop-session", "local_abc-123",
        )
        self.assertEqual((0, ""), (code, error))
        self.assertEqual(
            {"session": "uuid-1", "note": "Initial note\ndesktop_session=local_abc-123"},
            self.rows(self.db, "SELECT session,note FROM runs WHERE id=?", (output.strip(),))[0],
        )
        self.assertEqual(2, self.call(
            self.db, "run-start", "T1", "--by", "lead", "--model", "inherit",
            "--runtime", "claude", "--desktop-session", "bad-id",
        )[0])

    def test_help_lists_flags_and_link_relation_examples(self):
        help_text = work.build_parser().format_help()
        self.assertIn("A standing task move needs --approval <approvals id> with call=approve on that task; it cannot leave to the inbox.\n", help_text)
        for flag in ("--receipt", "--proof", "--result", "--evidence", "--fix-rounds",
                     "--tags", "--add-tag", "--remove-tag", "--append-note", "--desktop-session"):
            self.assertIn(flag, help_text)
        for relation in ("fix", "caused-by", "found-in", "updated", "about"):
            self.assertIn("--relation " + relation, help_text)
        for text in ("--field", "--flag", "inbox", "kind and skip are tags"):
            self.assertIn(text, help_text)


    def add_comment(self, body: str = "person: ship it") -> int:
        code, output, error = self.call(self.db, "comment", "T1", "--by", "person", body)
        self.assertEqual((0, ""), (code, error))
        return self.rows(self.db, "SELECT max(id) AS id FROM comments")[0]["id"]

    def test_decision_add_writes_row_and_activity_with_defaults(self):
        comment = self.add_comment()
        code, output, error = self.call(
            self.db, "decision-add", "--id", "ship-it", "--name", "Ship it",
            "--statement", "Ship the build.", "--person-words", "ship it",
            "--source", f"comment:{comment}", "--project", "global-object-model",
            "--tags", "Rule, ship,rule", "--by", "lead",
        )
        self.assertEqual((0, "", "ok decision-add ship-it\n"), (code, error, output))
        row = self.rows(self.db, "SELECT * FROM decisions WHERE id='ship-it'")[0]
        self.assertEqual("ruled", row["status"])
        self.assertEqual(work.now()[:10], row["decided_on"])
        self.assertEqual(("Ship the build.", "ship it", "rule,ship", "global-object-model", f"comment:{comment}"),
                         (row["statement"], row["person_words"], row["tags"], row["project"], row["source"]))
        trail = self.rows(self.db, "SELECT field,new_value,actor,source,note FROM activity WHERE subject_type='decision'")
        self.assertEqual([{"field": "create", "new_value": "Ship it", "actor": "lead",
                           "source": work.SOURCE, "note": f"status=ruled; source=comment:{comment}"}], trail)

    def test_decision_add_sets_status_date_and_replaces(self):
        self.assertEqual(0, self.call(self.db, "decision-add", "--id", "old", "--name", "Old", "--by", "lead")[0])
        code, _, error = self.call(
            self.db, "decision-add", "--id", "new", "--name", "New", "--status", "soft",
            "--decided-on", "2026-09-01", "--replaces", "old", "--by", "lead",
        )
        self.assertEqual((0, ""), (code, error))
        self.assertEqual({"status": "soft", "decided_on": "2026-09-01", "replaces": "old"},
                         self.rows(self.db, "SELECT status,decided_on,replaces FROM decisions WHERE id='new'")[0])
        self.assertEqual("superseded", self.rows(self.db, "SELECT status FROM decisions WHERE id='old'")[0]["status"])

    def test_decision_guard_and_escape(self):
        for word in ("Replaces", "AMENDS", "supersedes", "corrects"):
            with self.subTest(word=word):
                code, _, error = self.call(self.db, "decision-add", "--id", "new", "--name", "New",
                                           "--statement", word + " old guidance", "--by", "lead")
                self.assertEqual(2, code)
                self.assertIn(word, error)
        self.assertEqual(0, self.call(self.db, "decision-add", "--id", "new", "--name", "New",
                                      "--statement", "Corrects old guidance", "--replaces", "none", "--by", "lead")[0])
        self.assertEqual("none", self.rows(self.db, "SELECT replaces FROM decisions WHERE id='new'")[0]["replaces"])
        self.assertEqual(0, self.call(self.db, "decision-add", "--id", "neutral", "--name", "Neutral",
                                      "--statement", "Irreplacesable is not a word match", "--by", "lead")[0])

    def test_decision_update_partial_none_and_idempotence(self):
        for record_id, statement in (("old", "Old"), ("new", "Amends old")):
            args = ("decision-add", "--id", record_id, "--name", record_id, "--statement", statement, "--by", "lead")
            if record_id == "new":
                args += ("--replaces", "none")
            self.assertEqual(0, self.call(self.db, *args)[0])
        code, _, error = self.call(self.db, "decision-update", "missing", "--replaces", "none", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("no such decision", error)
        before = self.counts(self.db)
        code, _, error = self.call(self.db, "decision-update", "new", "--replaces", "missing", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("no such decision to replace", error)
        self.assertEqual(before, self.counts(self.db))
        self.assertEqual(0, self.call(self.db, "decision-update", "new", "--replaces", "old",
                                      "--partial", "--note", "one clause", "--by", "lead")[0])
        self.assertEqual("ruled", self.rows(self.db, "SELECT status FROM decisions WHERE id='old'")[0]["status"])
        trail = self.rows(self.db, "SELECT field,old_value,new_value,note FROM activity WHERE subject_id='new' ORDER BY id")
        self.assertEqual({"field": "replaces", "old_value": "none", "new_value": "old", "note": "one clause"}, trail[-1])
        unchanged = self.counts(self.db)
        self.assertEqual(0, self.call(self.db, "decision-update", "new", "--replaces", "old",
                                      "--partial", "--by", "lead")[0])
        self.assertEqual(unchanged, self.counts(self.db))
        self.assertEqual(0, self.call(self.db, "decision-update", "new", "--status", "soft", "--by", "lead")[0])
        self.assertEqual("soft", self.rows(self.db, "SELECT status FROM decisions WHERE id='new'")[0]["status"])

    def test_decision_update_guard_and_atomic_target_validation(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executemany("INSERT INTO decisions(id,name,status,statement) VALUES (?,?,?,?)", [
                ("old", "Old", "ruled", "Old"),
                ("new", "New", "ruled", "Corrects old guidance"),
            ])
            db.commit()
        before = self.counts(self.db)
        code, _, error = self.call(self.db, "decision-update", "new", "--status", "soft", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("'Corrects'", error)
        self.assertEqual(before, self.counts(self.db))
        code, _, error = self.call(self.db, "decision-update", "new", "--replaces", "old,missing", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("missing", error)
        self.assertEqual("ruled", self.rows(self.db, "SELECT status FROM decisions WHERE id='old'")[0]["status"])
        self.assertEqual(0, self.call(self.db, "decision-update", "new", "--replaces", "none", "--by", "lead")[0])
        self.assertEqual("ruled", self.rows(self.db, "SELECT status FROM decisions WHERE id='old'")[0]["status"])

    def test_decision_add_partial_list_supersedes_nothing(self):
        for record_id in ("old", "other"):
            self.assertEqual(0, self.call(self.db, "decision-add", "--id", record_id,
                                          "--name", record_id, "--by", "lead")[0])
        self.assertEqual(0, self.call(self.db, "decision-add", "--id", "new", "--name", "New",
                                      "--statement", "Replaces one clause", "--replaces", "old,other",
                                      "--partial", "--by", "lead")[0])
        self.assertEqual(["ruled", "ruled"], [row["status"] for row in self.rows(
            self.db, "SELECT status FROM decisions WHERE id IN ('old','other') ORDER BY id")])

    def test_decision_whole_row_list_and_clause(self):
        for record_id in ("old", "other", "new"):
            self.assertEqual(0, self.call(self.db, "decision-add", "--id", record_id,
                                          "--name", record_id, "--by", "lead")[0])
        self.assertEqual(0, self.call(self.db, "decision-update", "new", "--replaces",
                                      "old,other", "--by", "lead")[0])
        self.assertEqual(["superseded", "superseded"], [row["status"] for row in self.rows(
            self.db, "SELECT status FROM decisions WHERE id IN ('old','other') ORDER BY id")])
        self.assertEqual(2, len(self.rows(self.db, "SELECT id FROM activity WHERE field='status' AND subject_type='decision'")))
        self.assertEqual(0, self.call(self.db, "decision-update", "new", "--replaces",
                                      "shaping clause of old", "--by", "lead")[0])
        self.assertEqual("shaping clause of old", self.rows(self.db, "SELECT replaces FROM decisions WHERE id='new'")[0]["replaces"])

    def test_lint_replaces_filters_status_and_empty_column(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executemany("INSERT INTO decisions(id,name,status,statement,replaces) VALUES (?,?,?,?,?)", [
                ("a", "A", "ruled", "Replaces a rule", None),
                ("b", "B", "soft", "AMENDS a rule", ""),
                ("c", "C", "superseded", "Corrects a rule", None),
                ("d", "D", "ruled", "Corrects a rule", "none"),
                ("e", "E", "ruled", "Replacesable", None),
            ])
            db.commit()
        self.assertEqual(["a", "b"], [row["id"] for row in lint_replaces.lint(self.db)])
        command = [sys.executable, str(Path(lint_replaces.__file__)), "--db", str(self.db),
                   "--receipt-root", str(self.receipts), "--json"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertEqual(["a", "b"], [row["id"] for row in json.loads(result.stdout)])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE decisions SET replaces='none' WHERE id IN ('a','b')")
            db.commit()
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual((0, []), (result.returncode, json.loads(result.stdout)))

    def test_old_decisions_fk_is_upgraded_on_write(self):
        old_schema = blueprint_sql().replace("replaces TEXT, path TEXT", "replaces TEXT REFERENCES decisions(id), path TEXT")
        old_db = self.make_db("old-replaces.sqlite", old_schema)
        code, _, error = self.call(old_db, "decision-add", "--id", "old", "--name", "Old", "--by", "lead")
        self.assertEqual(0, code, error)
        self.assertEqual(0, len(self.rows(old_db, 'PRAGMA foreign_key_list("decisions")')))
        self.assertTrue(self.rows(old_db, "SELECT name FROM sqlite_master WHERE type='view' AND name='open_decisions'"))

    def test_decision_add_refusals_write_nothing(self):
        comment = self.add_comment()
        self.assertEqual(0, self.call(self.db, "decision-add", "--id", "one", "--name", "One", "--by", "lead")[0])
        before = self.counts(self.db)
        cases = (
            (("--id", "one", "--name", "Again"), "decision already exists: one"),
            (("--id", "two", "--name", "Two", "--status", "final"), "--status must be one of: open, soft, ruled"),
            (("--id", "two", "--name", "Two", "--replaces", "missing"), "no such decision to replace: missing"),
            (("--id", "two", "--name", "Two", "--function", "nope"), "no such function: nope"),
            (("--id", "two", "--name", "Two", "--source", "comment:999"), "no such comment: 999"),
            (("--id", "two", "--name", "Two", "--decided-on", "9.26"), "--decided-on must be YYYY-MM-DD"),
            (("--id", "G Two", "--name", "Two"), "--id must be a lowercase slug"),
            (("--id", "two"), "decision-add needs --id and --name"),
            (("--id", "two", "--name", "Two", "--call", "approve"), "--call belong to approval-add"),
            (("--name", "Two"), "decision-add needs --id and --name"),
        )
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                code, _, error = self.call(self.db, "decision-add", *arguments, "--by", "lead")
                self.assertEqual(2, code)
                self.assertIn(message, error)
        code, _, error = self.call(self.db, "decision-add", "--id", "two", "--name", "Two")
        self.assertEqual(2, code)
        self.assertIn("--by is required", error)
        self.assertEqual(before, self.counts(self.db))
        self.assertEqual(1, len(self.rows(self.db, "SELECT id FROM decisions")))
        self.assertTrue(comment)

    def test_decision_add_promotion_is_idempotent_per_comment(self):
        first = self.add_comment("person: no subtasks")
        second = self.add_comment("person: tickets on disk")
        promote = ("decision-add", "--id", "no-subtasks", "--name", "No subtasks",
                   "--source", f"comment:{first}", "--by", "lead")
        self.assertEqual(0, self.call(self.db, *promote)[0])
        before = self.counts(self.db)
        code, _, error = self.call(self.db, *promote)
        self.assertEqual(2, code)
        self.assertIn("decision already exists", error)
        code, _, error = self.call(
            self.db, "decision-add", "--id", "other-slug", "--name", "Same words",
            "--source", f"session x; comment:{first}", "--by", "lead",
        )
        self.assertEqual(2, code)
        self.assertIn(f"comment:{first} is already promoted to decision no-subtasks", error)
        self.assertEqual(before, self.counts(self.db))
        # A comment whose id shares a prefix is a different comment.
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO comments (id,subject_type,subject_id,author,at,body) VALUES (?,?,?,?,?,?)",
                       (int(f"{first}0"), "task", "T1", "person", work.now(), "person: other"))
            db.commit()
        self.assertEqual(0, self.call(
            self.db, "decision-add", "--id", "prefix", "--name", "Prefix", "--source", f"comment:{first}0", "--by", "lead",
        )[0])
        self.assertEqual(0, self.call(
            self.db, "decision-add", "--id", "disk", "--name", "Disk", "--source", f"comment:{second}", "--by", "lead",
        )[0])

    def test_t611_approval_add_preserves_exact_person_words(self):
        words = "  Yes, approve this.\nKeep my exact words.\t — Person  "
        code, _, error = self.call(
            self.db, "approval-add", "T1", "--call", "approve",
            "--person-words", words, "--by", "lead",
        )
        self.assertEqual((0, ""), (code, error))
        self.assertEqual(words, self.rows(self.db, "SELECT person_words FROM approvals")[0]["person_words"])

    def test_approval_add_writes_row_and_activity(self):
        comment = self.add_comment("person: approved")
        code, output, error = self.call(
            self.db, "approval-add", "T1", "--call", "approve", "--person-words", "approved",
            "--source", f"comment:{comment}", "--version", "v2", "--by", "lead",
        )
        self.assertEqual((0, ""), (code, error))
        row = self.rows(self.db, "SELECT * FROM approvals")[0]
        self.assertEqual(f"ok approval-add task T1 approval={row['id']}\n", output)
        self.assertEqual(("task", "T1", "v2", "approve", "approved", f"comment:{comment}"),
                         (row["subject_type"], row["subject_id"], row["version"], row["call"], row["person_words"], row["source"]))
        self.assertTrue(row["given_at"].startswith(work.now()[:10]))
        trail = self.rows(self.db, "SELECT subject_type,subject_id,field,new_value,actor,note FROM activity WHERE field='approval'")
        self.assertEqual([{"subject_type": "task", "subject_id": "T1", "field": "approval", "new_value": "approve",
                           "actor": "lead", "note": f"approval={row['id']}; source=comment:{comment}"}], trail)

    def test_approval_add_other_subject_type_and_given_at(self):
        self.assertEqual(0, self.call(self.db, "decision-add", "--id", "one", "--name", "One", "--by", "lead")[0])
        code, _, error = self.call(
            self.db, "approval-add", "one", "--subject-type", "decision", "--call", "discuss",
            "--given-at", "2026-09-25T18:00:00-04:00", "--by", "lead",
        )
        self.assertEqual((0, ""), (code, error))
        self.assertEqual({"subject_type": "decision", "call": "discuss", "given_at": "2026-09-25T18:00:00-04:00", "source": None},
                         self.rows(self.db, "SELECT subject_type,call,given_at,source FROM approvals")[0])

    def test_approval_add_refusals_write_nothing(self):
        self.assertEqual(0, self.call(self.db, "approval-add", "T1", "--call", "approve", "--source", "chat", "--by", "lead")[0])
        self.assertEqual(0, self.call(self.db, "approval-add", "T1", "--call", "approve", "--by", "lead")[0])
        before = self.counts(self.db)
        cases = (
            (("T1", "--call", "approve", "--source", "chat"), "approval already exists"),
            (("T1", "--call", "approve"), "approval already exists"),
            (("T8", "--call", "approve"), "no such task: T8"),
            (("none", "--subject-type", "decision", "--call", "approve"), "no such decision: none"),
            (("T1",), "approval-add needs --call"),
            (("T1", "--call", "approve", "--given-at", "yesterday"), "--given-at must be an ISO time"),
            (("T1", "--call", "approve", "--replaces", "x"), "--replaces belong to decision-add"),
        )
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                code, _, error = self.call(self.db, "approval-add", *arguments, "--by", "lead")
                self.assertEqual(2, code)
                self.assertIn(message, error)
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.call(self.db, "approval-add", "T1", "--call", "maybe", "--by", "lead")
        self.assertEqual(before, self.counts(self.db))
        # A different call or source is a different row.
        self.assertEqual(0, self.call(self.db, "approval-add", "T1", "--call", "edit", "--source", "chat", "--by", "lead")[0])

    def test_task_update_owner_leaves_comment_and_activity_trail(self):
        code, output, error = self.call(self.db, "task-update", "T1", "--by", "lead", "--owner", "legacy-judge")
        self.assertEqual((0, "", "ok task-update T1\n"), (code, error, output))
        self.assertEqual("legacy-judge", self.rows(self.db, "SELECT owner FROM tasks WHERE id='T1'")[0]["owner"])
        self.assertEqual([{"author": "lead", "body": 'Changed owner: null -> "legacy-judge"'}],
                         self.rows(self.db, "SELECT author,body FROM comments WHERE subject_id='T1'"))
        self.assertEqual([{"field": "owner", "old_value": None, "new_value": "legacy-judge", "actor": "lead"}],
                         self.rows(self.db, "SELECT field,old_value,new_value,actor FROM activity WHERE subject_id='T1'"))
        before = self.counts(self.db)
        code, output, _ = self.call(self.db, "task-update", "T1", "--by", "lead", "--owner", "legacy-judge")
        self.assertEqual((0, "ok task-update T1 duplicate\n"), (code, output))
        self.assertEqual(before, self.counts(self.db))
        code, _, error = self.call(self.db, "task-update", "T1", "--by", "lead", "--owner", "  ")
        self.assertEqual(2, code)
        self.assertIn("--owner must be one non-empty line", error)
        code, _, error = self.call(self.db, "comment", "T1", "--by", "lead", "--owner", "x", "hi")
        self.assertEqual(2, code)
        self.assertIn("--owner belongs to task-update", error)

    def test_link_still_refuses_other_subject_types(self):
        code, _, error = self.call(
            self.db, "link", "T1", "--subject-type", "task", "--target-type", "task",
            "--target-id", "T1", "--relation", "about", "--by", "lead",
        )
        self.assertEqual(2, code)
        self.assertIn("link --subject-type must be incident or bug", error)

    def test_help_lists_promotion_flags(self):
        help_text = work.build_parser().format_help()
        for text in ("decision-add", "approval-add", "--owner", "--statement", "--person-words", "--decided-on",
                     "--replaces", "--call", "--given-at", "--version", "--subject-type", "comment:<id>"):
            self.assertIn(text, help_text)



def six_field_arguments(where: str = "where.md", *, acceptance: bool = True) -> list[str]:
    """The six fields every new task and subtask carries (T718)."""
    return ["--problem", "Agents cannot see why the task exists",
            "--job-when", "When I open a task", "--job-want", "I want the problem and the job story",
            "--job-so", "So I can judge the work without asking",
            "--body", "Adds the fields to the row", *(("--acceptance", "Each field is written") if acceptance else ()),
            "--context", "Ruling of 10.19", "--where", where]


def additive_schema(test: unittest.TestCase):
    """The additive schema ships in the product tree; an installed home may not carry it."""
    try:
        import apply_program_schema
    except ImportError:
        test.skipTest("work/apply_program_schema.py is not in this tree")
    return apply_program_schema


def add_six_field_columns(database: Path) -> None:
    with closing(sqlite3.connect(database)) as db, db:
        for name in ("problem", "job_when", "job_want", "job_so"):
            db.execute(f'ALTER TABLE tasks ADD COLUMN "{name}" TEXT')


class SixFieldTests(unittest.TestCase):
    """T718: every task and subtask carries Problem, Job story, What it does, Acceptance, Context, Where."""

    make_db = WorkWriterTests.make_db
    add_task = WorkWriterTests.add_task
    call = WorkWriterTests.call
    rows = WorkWriterTests.rows
    counts = WorkWriterTests.counts

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="work-six-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.receipts = self.root / "receipts"
        self.receipts.mkdir()
        self.db = self.make_db("six.sqlite", schema=(Path(__file__).resolve().parent / "../blueprint.sql").read_text())
        self.add_task(self.db, "T1")
        (self.receipts / "where.md").write_text("spec\n", encoding="utf-8")

    def test_create_refuses_a_task_missing_any_field_and_names_every_one(self):
        before = self.counts(self.db)
        code, output, error = self.call(self.db, "create", "--title", "Bare task", "--by", "lead")
        self.assertEqual((2, ""), (code, output))
        for label in ("Problem (--problem)", "Job story When (--job-when)", "Job story I want (--job-want)",
                      "Job story So I can (--job-so)", "What it does (--body)", "Acceptance (--acceptance",
                      "Context (--context)", "Where (--where"):
            self.assertIn(label, error)
        self.assertEqual(before, self.counts(self.db))

    def test_create_refuses_each_single_missing_field(self):
        full = six_field_arguments()
        for flag in ("--problem", "--job-when", "--job-want", "--job-so", "--body", "--acceptance", "--context", "--where"):
            with self.subTest(flag=flag):
                index = full.index(flag)
                partial = full[:index] + full[index + 2:]
                code, _, error = self.call(self.db, "create", "--title", "Partial", *partial, "--by", "lead")
                self.assertEqual(2, code)
                self.assertIn("(" + flag, error)
                self.assertEqual(1, error.count("(--"), error)
        code, _, error = self.call(self.db, "create", "--title", "  ", *full, "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("Title (--title)", error)

    def test_a_subtask_carries_its_own_fields_and_inherits_none(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE tasks SET problem='Parent problem',job_when='When parent',job_want='I want parent',"
                       "job_so='So parent',body='Parent body',context='Parent context' WHERE id='T1'")
        code, _, error = self.call(self.db, "create", "--title", "Child", "--parent", "T1",
                                   "--acceptance", "One check", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("Problem (--problem)", error)
        self.assertEqual([], self.rows(self.db, "SELECT id FROM tasks WHERE parent='T1'"))
        code, output, error = self.call(self.db, "create", "--title", "Child", "--parent", "T1", *six_field_arguments(), "--by", "lead")
        self.assertEqual((0, ""), (code, error))
        child = self.rows(self.db, "SELECT problem,body FROM tasks WHERE id=?", (output.strip(),))[0]
        self.assertEqual({"problem": "Agents cannot see why the task exists", "body": "Adds the fields to the row"}, child)

    def test_create_writes_each_field_and_links_where(self):
        code, output, error = self.call(self.db, "create", "--title", "Full task", *six_field_arguments(),
                                        "--acceptance", "Second check", "--note", "kept note", "--by", "lead")
        self.assertEqual((0, ""), (code, error))
        task = output.strip()
        row = self.rows(self.db, "SELECT title,problem,job_when,job_want,job_so,body,acceptance,context,note FROM tasks WHERE id=?", (task,))[0]
        self.assertEqual({
            "title": "Full task", "problem": "Agents cannot see why the task exists",
            "job_when": "When I open a task", "job_want": "I want the problem and the job story",
            "job_so": "So I can judge the work without asking", "body": "Adds the fields to the row",
            "acceptance": '["Each field is written","Second check"]', "context": "Ruling of 10.19", "note": "kept note",
        }, row)
        self.assertEqual([{"system": "file", "external_id": str(self.receipts / "where.md"),
                           "path": str(self.receipts / "where.md"), "relation": "where", "active": 1}],
                         self.rows(self.db, "SELECT system,external_id,path,relation,active FROM task_links WHERE task=?", (task,)))

    def test_where_must_exist_and_never_names_a_secret(self):
        for value, words in (("missing.md", "must already exist"), (".env", "secret")):
            with self.subTest(value=value):
                code, _, error = self.call(self.db, "create", "--title", "Bad where", *six_field_arguments(value), "--by", "lead")
                self.assertEqual(2, code)
                self.assertIn(words, error)
        self.assertEqual([{"id": "T1"}], self.rows(self.db, "SELECT id FROM tasks"))

    def test_task_update_writes_each_field_once(self):
        (self.receipts / "second.md").write_text("more\n", encoding="utf-8")
        values = {"--problem": ("problem", "New problem"), "--job-when": ("job_when", "When later"),
                  "--job-want": ("job_want", "I want more"), "--job-so": ("job_so", "So I can rest"),
                  "--body": ("body", "Does the thing"), "--context": ("context", "More context")}
        for flag, (field, value) in values.items():
            with self.subTest(flag=flag):
                self.assertEqual((0, "ok task-update T1\n", ""), self.call(self.db, "task-update", "T1", flag, value, "--by", "lead"))
                self.assertEqual(value, self.rows(self.db, f"SELECT {field} AS value FROM tasks WHERE id='T1'")[0]["value"])
                self.assertEqual(1, len(self.rows(self.db, "SELECT 1 FROM activity WHERE subject_id='T1' AND field=?", (field,))))
                self.assertEqual("ok task-update T1 duplicate\n", self.call(self.db, "task-update", "T1", flag, value, "--by", "lead")[1])
        self.assertEqual((0, "ok task-update T1\n", ""), self.call(self.db, "task-update", "T1", "--where", "second.md", "--by", "lead"))
        self.assertEqual([str(self.receipts / "second.md")],
                         [row["path"] for row in self.rows(self.db, "SELECT path FROM task_links WHERE task='T1' AND relation='where'")])
        self.assertEqual("ok task-update T1 duplicate\n", self.call(self.db, "task-update", "T1", "--where", "second.md", "--by", "lead")[1])

    def test_six_field_flags_belong_to_create_or_task_update(self):
        code, _, error = self.call(self.db, "claim", "T1", "--problem", "x", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("belong to create, task-update, bug-open, or bug-update", error)
        code, _, error = self.call(self.db, "task-rank", "T1", "--ord", "3", "--body", "x", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("task-rank changes only --ord", error)

    def test_a_tracker_without_the_columns_is_refused_until_the_schema_is_applied(self):
        old = self.make_db("old.sqlite")
        code, _, error = self.call(old, "create", "--title", "Full task", *six_field_arguments(), "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("apply work/apply_program_schema.py first", error)
        add_six_field_columns(old)
        code, output, error = self.call(old, "create", "--title", "Full task", *six_field_arguments(), "--by", "lead")
        self.assertEqual((0, ""), (code, error))

    def test_bug_open_refuses_a_bug_missing_any_field_and_tags_stay_optional(self):
        code, output, error = self.call(self.db, "bug-open", "--id", "B-1", "--title", "Broken", "--capability", "work", "--by", "lead")
        self.assertEqual((2, ""), (code, output))
        self.assertIn("bug-open refuses a bug missing", error)
        for label in ("Problem (--problem)", "Job story When (--job-when)", "Job story I want (--job-want)",
                      "Job story So I can (--job-so)", "What it does (--body)", "Acceptance (--acceptance",
                      "Context (--context)", "Where (--where"):
            self.assertIn(label, error)
        self.assertNotIn("--tags", error)
        self.assertEqual([], self.rows(self.db, "SELECT id FROM bugs"))

    def test_bug_open_writes_each_field_tags_and_where(self):
        code, output, error = self.call(self.db, "bug-open", "--id", "B-1", "--title", "Broken", "--capability", "work",
                                        "--tags", "Jev, ops", *six_field_arguments(), "--by", "lead")
        self.assertEqual((0, "ok bug-open B-1\n", ""), (code, output, error))
        self.assertEqual([{"tags": "jev,ops", "problem": "Agents cannot see why the task exists", "job_when": "When I open a task",
                           "job_want": "I want the problem and the job story", "job_so": "So I can judge the work without asking",
                           "body": "Adds the fields to the row", "acceptance": '["Each field is written"]', "context": "Ruling of 10.19"}],
                         self.rows(self.db, "SELECT tags,problem,job_when,job_want,job_so,body,acceptance,context FROM bugs"))
        self.assertEqual([{"subject_id": "B-1", "path": str(self.receipts / "where.md"), "role": "where"}],
                         self.rows(self.db, "SELECT subject_id,path,role FROM attachments WHERE subject_type='bug'"))

    def test_bug_update_changes_tags_and_fields_once(self):
        self.assertEqual(0, self.call(self.db, "bug-open", "--id", "B-1", "--title", "Broken", "--capability", "work",
                                      *six_field_arguments(), "--by", "lead")[0])
        (self.receipts / "second.md").write_text("more\n", encoding="utf-8")
        for arguments, field, value in (
            (("--add-tag", "jev"), "tags", "jev"), (("--tags", "jev,ops"), "tags", "jev,ops"),
            (("--remove-tag", "jev"), "tags", "ops"), (("--problem", "New problem"), "problem", "New problem"),
            (("--job-when", "When later"), "job_when", "When later"), (("--body", "Fix it"), "body", "Fix it"),
            (("--acceptance", '["Two"]'), "acceptance", '["Two"]'), (("--context", "More"), "context", "More"),
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual((0, "ok bug-update B-1\n", ""), self.call(self.db, "bug-update", "B-1", *arguments, "--by", "lead"))
                self.assertEqual(value, self.rows(self.db, f"SELECT {field} AS value FROM bugs")[0]["value"])
                self.assertEqual("ok bug-update B-1 duplicate\n", self.call(self.db, "bug-update", "B-1", *arguments, "--by", "lead")[1])
        self.assertEqual((0, "ok bug-update B-1\n", ""), self.call(self.db, "bug-update", "B-1", "--where", "second.md", "--by", "lead"))
        self.assertEqual(2, len(self.rows(self.db, "SELECT 1 FROM attachments WHERE subject_type='bug' AND role='where'")))
        code, _, error = self.call(self.db, "bug-update", "B-1", "--by", "lead")
        self.assertEqual(2, code)
        self.assertIn("bug-update needs a field to change", error)
        self.assertEqual(2, self.call(self.db, "bug-update", "B-NONE", "--context", "x", "--by", "lead")[0])

    def test_the_additive_schema_adds_the_bug_columns(self):
        apply_program_schema = additive_schema(self)
        old = self.make_db("bugs.sqlite")
        apply_program_schema.apply_schema(old)
        columns = [row["name"] for row in self.rows(old, "PRAGMA table_info(bugs)")]
        self.assertEqual(["tags", "problem", "job_when", "job_want", "job_so", "body", "acceptance", "context"], columns[-8:])

    def test_the_additive_schema_adds_the_four_columns_and_keeps_rows(self):
        apply_program_schema = additive_schema(self)
        old = self.make_db("additive.sqlite")
        self.add_task(old, "T1")
        apply_program_schema.apply_schema(old)
        columns = [row["name"] for row in self.rows(old, "PRAGMA table_info(tasks)")]
        self.assertEqual(["problem", "job_when", "job_want", "job_so"], columns[-4:])
        self.assertEqual([{"id": "T1", "problem": None}], self.rows(old, "SELECT id,problem FROM tasks"))
        apply_program_schema.apply_schema(old)
        self.assertEqual(columns, [row["name"] for row in self.rows(old, "PRAGMA table_info(tasks)")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
