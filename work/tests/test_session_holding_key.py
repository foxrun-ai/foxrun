#!/usr/bin/env python3
"""T374: key identity, guarded migration, and writer/logger boundaries."""

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
import unittest

import work
from test_work import six_field_arguments
# Recheck 2 (T742): load the fixture from this folder by path. With base/ first on the path,
# 'tests' meant base/tests when the suite runs as discover -s work/tests from the home.
import importlib.util as _fixture_util
_fixture_spec = _fixture_util.spec_from_file_location('work_tests_fixtures', Path(__file__).with_name('__init__.py'))
_fixtures = _fixture_util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixtures)
native_hooks = _fixtures.native_hooks


TOOLS = Path(__file__).resolve().parent.parent
KEY = "session-holding-task"


class HoldingKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="holding-key-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.hooks = native_hooks(self.root)
        self.workspace = self.root / "system-workspace"
        self.workspace.mkdir()
        self.db = self.workspace / "system-workspace.sqlite"
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(((Path(__file__).resolve().parent / '../blueprint.sql')).read_text())
            db.execute("INSERT INTO projects(id,title,status) VALUES ('WS01','Original','todo'),('WS22','Upkeep','todo')")
            db.execute("INSERT INTO tasks(id,title,status,project,tags,owner) "
                       "VALUES ('T9','Session work to place','todo','WS22','recurring','person')")
            db.execute("INSERT INTO tasks(id,title,status,project,tags,idempotency_key) "
                       "VALUES ('T1','Ordinary','todo','WS01','ops','intake:keep-me')")
            db.execute("INSERT INTO approvals(id,subject_type,subject_id,call,given_at) VALUES (1,'task','T9','approve','2026-10-04')")
            db.commit()
        self.env = {**os.environ, "FOX_SESSION_TRACKED_ROOT": str(self.root),
                    "FOXRUN_NO_SESSION_LOG": "0", "CLAUDE_CODE_ENTRYPOINT": "cli",
                    "PYTHONDONTWRITEBYTECODE": "1"}

    def sql(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as db, db:
            return db.execute(sql, params).fetchall()

    def snapshot(self):
        return {table: self.sql(f'SELECT * FROM "{table}" ORDER BY rowid')
                for table in ("tasks", "runs", "activity", "comments", "approvals", "attachments", "task_links")}

    def call(self, *args):
        return subprocess.run([sys.executable, str((Path(__file__).resolve().parent / '../../events/session_run.py')), *args],
                              capture_output=True, text=True, env=self.env)

    def backfill(self, task="T9"):
        return self.call("backfill-key", "--db", str(self.db), "--task", task)

    def seed_key(self):
        # Seed directly so regression tests reach main's wrong behavior without
        # first depending on the new backfill CLI being present.
        self.sql("UPDATE tasks SET idempotency_key=? WHERE id='T9'", (KEY,))

    def start(self, name="session"):
        return self.call("start", "--runtime", "codex", "--session", name, "--cwd", str(self.workspace))

    def end(self, name="session"):
        return self.call("end", "--session", name, "--cwd", str(self.workspace))

    def write(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = work.run(["--db", str(self.db), "--receipt-root", str(self.workspace), *args], stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def assert_ok(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_unkeyed_setup_and_start_fail_loud_without_writes(self):
        for title in ("Session work to place", "Retitled before migration"):
            with self.subTest(title=title):
                self.sql("UPDATE tasks SET title=? WHERE id='T9'", (title,))
                before = self.snapshot()
                for flags in ((), ("--create",)):
                    result = self.call("setup", "--db", str(self.db), *flags)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("backfill required", result.stderr)
                result = self.start()
                self.assertEqual(result.returncode, 0)
                self.assertIn("backfill required", result.stderr)
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertEqual(before, self.snapshot())

    def test_unkeyed_native_hooks_say_why_and_write_nothing(self):
        before = self.snapshot()
        for runtime in ("claude", "codex"):
            payload = {"hook_event_name": "SessionStart", "session_id": runtime,
                       "source": "startup", "cwd": str(self.workspace)}
            result = subprocess.run([str(self.hooks / runtime / (runtime + "_session_start.sh"))],
                                    input=json.dumps(payload), text=True, capture_output=True, env=self.env)
            self.assertEqual(result.returncode, 0)
            self.assertIn("backfill required", result.stderr)
            self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertEqual(before, self.snapshot())

    def test_setup_creates_text_key_only_with_explicit_empty_install(self):
        self.sql("DELETE FROM tasks")
        result = self.call("setup", "--db", str(self.db))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backfill required", result.stderr)
        result = self.call("setup", "--db", str(self.db), "--create")
        self.assert_ok(result)
        self.assertEqual(self.sql("SELECT title,tags,idempotency_key,typeof(idempotency_key) FROM tasks"),
                         [("Session work to place", "recurring", KEY, "text")])
        before = self.snapshot()
        self.assert_ok(self.call("setup", "--db", str(self.db)))
        self.assertEqual(before, self.snapshot())

    def test_backfill_once_preserves_fields_and_intake_keys_with_one_history_row(self):
        before = self.sql("SELECT id,title,status,project,tags FROM tasks ORDER BY id")
        self.assert_ok(self.backfill())
        self.assertEqual(before, self.sql("SELECT id,title,status,project,tags FROM tasks ORDER BY id"))
        self.assertEqual(self.sql("SELECT idempotency_key,typeof(idempotency_key) FROM tasks WHERE id='T9'"), [(KEY, "text")])
        self.assertEqual(self.sql("SELECT idempotency_key FROM tasks WHERE id='T1'"), [("intake:keep-me",)])
        self.assertEqual(self.sql("SELECT subject_type,subject_id,field,old_value,new_value,actor,source FROM activity"),
                         [("task", "T9", "idempotency_key", None, KEY, "session-run-backfill", "session_run backfill-key")])
        self.assertTrue(self.sql("SELECT at FROM activity")[0][0])
        before = self.snapshot()
        result = self.backfill()
        self.assert_ok(result)
        self.assertIn("already keyed; no changes", result.stdout)
        self.assertEqual(before, self.snapshot())
        self.assert_ok(self.call("setup", "--db", str(self.db)))
        self.assert_ok(self.start())
        self.assert_ok(self.end())
        self.assertEqual(self.sql("SELECT subject_id,ended_at IS NOT NULL FROM runs"), [("T9", 1)])

    def test_backfill_refuses_another_holder_and_never_rekeys(self):
        self.seed_key()
        before = self.snapshot()
        result = self.backfill("T1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already belongs to T9", result.stderr)
        self.assertEqual(before, self.snapshot())
        for key in ("intake:existing", "", b"unrelated-key"):
            with self.subTest(key=key):
                self.sql("UPDATE tasks SET idempotency_key=? WHERE id='T9'", (key,))
                before = self.snapshot()
                result = self.backfill()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("never replaces a key", result.stderr)
                self.assertEqual(before, self.snapshot())

    def test_backfill_requires_named_live_recurring_task(self):
        before = self.snapshot()
        result = self.backfill("T8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no such task", result.stderr)
        self.assertEqual(before, self.snapshot())
        variants = [(status, "recurring") for status in ("done", "canceled", "superseded")]
        variants += [("todo", tag) for tag in (None, "ops", "recurring,", b"recurring")]
        for status, tags in variants:
            with self.subTest(status=status, tags=tags):
                self.sql("UPDATE tasks SET status=?,tags=? WHERE id='T9'", (status, tags))
                before = self.snapshot()
                result = self.backfill()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertEqual(before, self.snapshot())

    def test_blob_key_alone_or_beside_text_is_diagnosed_without_writes(self):
        self.sql("UPDATE tasks SET idempotency_key=CAST(? AS BLOB) WHERE id='T1'", (KEY,))
        for keyed in (False, True):
            with self.subTest(text_key_also_present=keyed):
                if keyed:
                    self.seed_key()
                before = self.snapshot()
                for args in (("setup", "--db", str(self.db)),
                             ("setup", "--db", str(self.db), "--create"),
                             ("backfill-key", "--db", str(self.db), "--task", "T9")):
                    result = self.call(*args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("must be TEXT, not BLOB", result.stderr)
                result = self.start()
                self.assertEqual(result.returncode, 0)
                self.assertIn("must be TEXT, not BLOB", result.stderr)
                code, _, error = self.write("task-update", "T9", "--title", "Changed", "--by", "builder")
                self.assertEqual(code, 2)
                self.assertIn("must be TEXT, not BLOB", error)
                self.assertEqual(before, self.snapshot())

    def test_closed_key_is_not_replaced_or_ignored(self):
        self.seed_key()
        for status in ("done", "canceled", "superseded"):
            with self.subTest(status=status):
                self.sql("UPDATE tasks SET status=? WHERE id='T9'", (status,))
                before = self.snapshot()
                for args in (("setup", "--db", str(self.db)),
                             ("setup", "--db", str(self.db), "--create"),
                             ("backfill-key", "--db", str(self.db), "--task", "T9")):
                    result = self.call(*args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("keyed task T9 is " + status, result.stderr)
                result = self.start()
                self.assertEqual(result.returncode, 0)
                self.assertIn("keyed task T9 is " + status, result.stderr)
                self.assertEqual(before, self.snapshot())

    def test_key_is_exact_not_trimmed_or_casefolded(self):
        for key in ("SESSION-HOLDING-TASK", " session-holding-task", "session-holding-task "):
            with self.subTest(key=key):
                self.sql("UPDATE tasks SET idempotency_key=? WHERE id='T9'", (key,))
                before = self.snapshot()
                result = self.start()
                self.assertEqual(result.returncode, 0)
                self.assertIn("backfill required", result.stderr)
                self.assertEqual(before, self.snapshot())

    def test_logger_needs_only_live_identity_not_title_tags_or_placement(self):
        self.seed_key()
        for index, tags in enumerate((None, "ops", "recurring,", b"recurring,")):
            self.sql("UPDATE tasks SET title=?,tags=?,project=NULL WHERE id='T9'", (b"Renamed", tags))
            self.assert_ok(self.start("raw-fields-" + str(index)))
        self.assertEqual(self.sql("SELECT subject_id FROM runs"), [("T9",)] * 4)

    def test_unrelated_blob_title_or_tags_do_not_break_logging_or_edits(self):
        self.seed_key()
        for index, (title, tags) in enumerate(((b"Session work to place", "recurring"),
                                               ("Session work to place", b"recurring,"))):
            with self.subTest(title=title, tags=tags):
                self.sql("UPDATE tasks SET title=?,tags=? WHERE id='T1'", (title, tags))
                self.assert_ok(self.start("blob-decoy-" + str(index)))
                code, _, error = self.write("task-update", "T9", "--note", "Unrelated edit " + str(index), "--by", "builder")
                self.assertEqual((code, error), (0, ""))
        self.assertEqual(self.sql("SELECT subject_id FROM runs"), [("T9",)] * 2)

    def test_end_remains_session_based_after_run_move_and_identity_damage(self):
        self.seed_key()
        self.assert_ok(self.start())
        run = self.sql("SELECT id FROM runs")[0][0]
        self.assertEqual(self.write("run-move", run, "--task", "T1", "--by", "builder")[0], 0)
        self.sql("UPDATE tasks SET status='canceled',idempotency_key=CAST(? AS BLOB) WHERE id='T9'", (KEY,))
        self.assert_ok(self.end())
        self.assertEqual(self.sql("SELECT subject_id,ended_at IS NOT NULL FROM runs"), [("T1", 1)])

    def test_retitle_and_other_tags_work_then_logging_and_protections_still_hold(self):
        self.seed_key()
        self.assertEqual(self.write("task-update", "T9", "--title", "Holding sessions", "--tags", "recurring,ops",
                                    "--by", "builder")[0], 0)
        self.assertEqual(self.write("task-update", "T9", "--remove-tag", "ops", "--add-tag", "upkeep",
                                    "--by", "builder")[0], 0)
        self.assert_ok(self.start())
        self.assert_ok(self.end())
        self.assertEqual(self.sql("SELECT subject_id,ended_at IS NOT NULL FROM runs"), [("T9", 1)])
        (self.workspace / "proof.txt").write_text("Copy-only proof")
        commands = (("task-update", "--remove-tag", "recurring"), ("task-update", "--tags", "upkeep"),
                    ("done", "--receipt", "proof.txt", "--proof", "Checked"), ("accept",),
                    ("cancel", "--reason", "Test"), ("task-move", "--inbox"),
                    ("task-move", "--project", "WS01"))
        before = self.snapshot()
        for verb, *args in commands:
            with self.subTest(verb=verb, args=args):
                code, _, error = self.write(verb, "T9", *args, "--by", "builder")
                self.assertEqual(code, 2)
                self.assertIn("standing task", error)
                self.assertEqual(before, self.snapshot())
        self.assertEqual(self.sql("SELECT idempotency_key FROM tasks WHERE id='T9'"), [(KEY,)])

    def test_duplicate_old_title_is_ordinary_and_unprotected(self):
        self.seed_key()
        self.sql("UPDATE tasks SET title='Holding sessions' WHERE id='T9'")
        # 404941a (T718): every new task carries the six fields; Where names a file in the workspace.
        (self.workspace / "where.md").write_text("where\n", encoding="utf-8")
        code, output, error = self.write("create", "--title", "Session work to place", "--tags", "recurring",
                                        "--project", "WS01", "--by", "builder", *six_field_arguments())
        self.assertEqual((code, error), (0, ""))
        task = output.strip()
        for args in (("task-update", "--remove-tag", "recurring"), ("task-move", "--inbox"),
                     ("cancel", "--reason", "Ordinary task")):
            self.assertEqual(self.write(args[0], task, *args[1:], "--by", "builder")[0], 0)
        self.assertEqual(self.sql("SELECT idempotency_key,status FROM tasks WHERE id=?", (task,)), [(None, "canceled")])
        self.assert_ok(self.start())
        self.assertEqual(self.sql("SELECT subject_id FROM runs"), [("T9",)])

    def test_public_work_verbs_cannot_set_change_or_clear_keys(self):
        self.seed_key()
        before = self.snapshot()
        for verb in ("create", "task-update", "task-move", "claim", "block", "cancel", "done", "accept"):
            for value in (KEY, "replacement", ""):
                result = subprocess.run([sys.executable, str((Path(__file__).resolve().parent / '../work.py')), "--db", str(self.db),
                                         "--receipt-root", str(self.workspace), verb,
                                         "--idempotency-key", value, "--by", "builder"],
                                        capture_output=True, text=True, env=self.env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unrecognized arguments: --idempotency-key", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_backfill_and_approved_move_roll_back_when_history_insert_fails(self):
        self.sql("CREATE TRIGGER reject_history BEFORE INSERT ON activity BEGIN SELECT RAISE(ABORT,'history unavailable'); END")
        before = self.snapshot()
        result = self.backfill()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("history unavailable", result.stderr)
        self.assertEqual(before, self.snapshot())
        self.seed_key()
        before = self.snapshot()
        code, _, error = self.write("task-move", "T9", "--project", "WS01", "--approval", "1", "--by", "builder")
        self.assertEqual(code, 2)
        self.assertIn("history unavailable", error)
        self.assertEqual(before, self.snapshot())

    def test_keyed_current_and_former_subtask_keeps_t348_rewrite_approval(self):
        self.seed_key()
        self.sql("UPDATE tasks SET parent='T1',project='WS01' WHERE id='T9'")
        for former in (False, True):
            with self.subTest(former=former):
                if former:
                    self.assertEqual(self.write("task-update", "T9", "--parent", "none", "--approval", "1", "--by", "builder")[0], 0)
                before = self.snapshot()
                code, _, error = self.write("task-update", "T9", "--title", "New title", "--by", "builder")
                self.assertEqual(code, 2)
                self.assertIn("needs --approval", error)
                self.assertEqual(before, self.snapshot())
                self.assertEqual(self.write("task-update", "T9", "--title", "Approved " + str(former),
                                            "--approval", "1", "--by", "builder")[0], 0)


if __name__ == "__main__":
    unittest.main()
