#!/usr/bin/env python3
"""Regressions for approved subtask edits and task blocker links."""

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
from pathlib import Path
import sqlite3
import tempfile
import unittest

import program
import work


BLUEPRINT = (Path(__file__).resolve().parent / '../blueprint.sql')


class TrackerGapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tracker-gaps-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / "tracker.sqlite"
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(BLUEPRINT.read_text())
            db.execute("INSERT INTO tasks (id,title,status,owner) VALUES ('T1','Parent','todo','lead')")
            db.execute("INSERT INTO tasks (id,title,status,owner) VALUES ('T2','Child','todo','lead')")
            db.execute("INSERT INTO tasks (id,title,status,owner) VALUES ('T3','person work','todo','person')")
            db.execute("INSERT INTO tasks (id,title,status,owner) VALUES ('T4','Blocked work','blocked','lead')")
            db.execute("INSERT INTO decisions (id,name,status) VALUES ('d-yes','Yes','ruled')")
            db.execute("INSERT INTO decisions (id,name,status) VALUES ('d-open','Open','open')")
            db.execute("INSERT INTO approvals (id,subject_type,subject_id,call,given_at) VALUES (7,'task','T2','approve','2026-10-02')")
            db.commit()

    def call(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        code = work.run(["--db", str(self.db), "--receipt-root", str(self.root), *arguments],
                        stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def rows(self, sql):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute(sql).fetchall()

    def test_unparent_rename_reparent_bypass_is_closed(self):
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--parent", "T1")[0], 0)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--parent", "none")[0], 2)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--parent", "none", "--approval", "7")[0], 0)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--title", "Bypass")[0], 2)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--title", "Bypass", "--approval", "d-open")[0], 2)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--title", "Bypass", "--approval", "d-yes")[0], 2)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--title", "Approved", "--approval", "7")[0], 0)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--parent", "T1")[0], 2)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--parent", "T1", "--approval", "7")[0], 0)
        self.assertEqual(self.rows("SELECT title,parent FROM tasks WHERE id='T2'"), [("Approved", "T1")])
        history = self.rows("SELECT field,old_value,new_value,note FROM activity WHERE subject_id='T2' ORDER BY id")
        self.assertEqual([row[0] for row in history], ["parent", "parent", "title", "parent"])
        self.assertIn('approval 7; FROM "Child" TO "Approved"', history[2][3])
        self.assertEqual(self.rows("SELECT count(*) FROM tasks"), [(4,)])

    def test_created_subtask_stays_guarded_after_approved_unparent(self):
        (self.root / "where.md").write_text("spec\n", encoding="utf-8")
        six = ("--problem", "The child has its own problem", "--job-when", "When the parent splits",
               "--job-want", "I want a child step", "--job-so", "So I can check it alone", "--body", "Does one step",
               "--acceptance", "The step is checked", "--context", "T718 fixture", "--where", "where.md")
        self.assertEqual(self.call("create", "--title", "New child", "--parent", "T1", "--by", "lead", *six)[0], 0)
        child = self.rows("SELECT id FROM tasks WHERE parent='T1'")[0][0]
        self.assertEqual(self.call("task-update", child, "--parent", "none", "--by", "lead", "--approval", "7")[0], 2)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO approvals (id,subject_type,subject_id,call,given_at) VALUES (8,'task','T1','approve','2026-10-02')")
            db.commit()
        self.assertEqual(self.call("task-update", child, "--parent", "none", "--by", "lead", "--approval", "8")[0], 0)
        for arguments in (("--title", "Bypass"), ("--parent", "T1")):
            with self.subTest(arguments=arguments):
                code, _, error = self.call("task-update", child, *arguments, "--by", "lead")
                self.assertEqual(code, 2)
                self.assertIn("needs --approval", error)
        self.assertEqual(self.rows(f"SELECT title,parent FROM tasks WHERE id='{child}'"), [("New child", None)])

    def test_approval_scope_and_call(self):
        self.assertEqual(self.call("task-update", "T2", "--parent", "T1", "--by", "lead")[0], 0)
        with closing(sqlite3.connect(self.db)) as db:
            db.executemany(
                "INSERT INTO approvals (id,subject_type,subject_id,call,given_at) VALUES (?,?,?,?,?)",
                [(8, "task", "T3", "approve", "2026-10-02"),
                 (9, "task", "T2", "wrong", "2026-10-02"),
                 (10, "task", "T2", "discuss", "2026-10-02"),
                 (11, "task", "T2", "edit", "2026-10-02"),
                 (12, "project", "T2", "approve", "2026-10-02"),
                 (13, "task", "T1", "approve", "2026-10-02")],
            )
            db.commit()
        for reference, reason in (("8", "for T3"), ("9", "call=wrong"),
                                  ("10", "call=discuss"), ("11", "call=edit"),
                                  ("12", "subject_type=project"),
                                  ("d-open", "must name an approvals row"),
                                  ("d-yes", "must name an approvals row"),
                                  ("999", "must name an approvals row")):
            with self.subTest(reference=reference):
                code, _, error = self.call("task-update", "T2", "--title", "Bypass", "--by", "lead", "--approval", reference)
                self.assertEqual(code, 2)
                self.assertIn(reason, error)
                self.assertIn("record Person's yes with approval-add on the parent task, then pass that id", error)
        self.assertEqual(self.rows("SELECT title FROM tasks WHERE id='T2'"), [("Child",)])
        self.assertEqual(self.call("task-update", "T2", "--title", "Parent approved", "--by", "lead", "--approval", "13")[0], 0)
        self.assertEqual(self.call("task-update", "T2", "--parent", "none", "--by", "lead", "--approval", "7")[0], 0)
        self.assertEqual(self.call("task-update", "T2", "--title", "Former parent approved", "--by", "lead", "--approval", "13")[0], 0)

    def test_each_rewrite_field_has_one_from_to_event(self):
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--parent", "T1")[0], 0)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--title", "New title",
                                   "--note", "New note", "--acceptance", '["Proof"]', "--approval", "7")[0], 0)
        self.assertEqual(self.call("task-update", "T2", "--by", "lead", "--append-note", "More", "--approval", "7")[0], 0)
        history = self.rows("SELECT field,old_value,new_value,note FROM activity WHERE subject_id='T2' AND field!='parent' ORDER BY id")
        self.assertEqual([row[0] for row in history], ["title", "note", "acceptance", "note"])
        self.assertTrue(all("approval 7; FROM " in row[3] and " TO " in row[3] for row in history))
        self.assertEqual(history[-1][1:3], ("New note", "New note\nMore"))

    def test_many_blockers_idempotence_remove_and_readers(self):
        for blocker in ("T1", "T3"):
            self.assertEqual(self.call("link-task", blocker, "--blocks", "T4", "--by", "lead")[0], 0)
        self.assertIn("duplicate", self.call("link-task", "T1", "--blocks", "T4", "--by", "lead")[1])
        self.assertEqual(self.rows("SELECT task,external_id,relation FROM task_links ORDER BY id"),
                         [("T1", "T4", "blocks"), ("T3", "T4", "blocks")])
        self.assertEqual(self.rows("SELECT id FROM needs_me ORDER BY id"), [("T3",), ("T4",)])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET blocked_by='T3' WHERE id='T4'")
            db.commit()
        with closing(program.connect(self.db)) as db:
            self.assertEqual(program.task_blockers(db, "T4", "T3"), ["T1", "T3"])
        self.assertEqual(self.call("link-task", "T3", "--blocks", "T4", "--by", "lead", "--remove")[0], 0)
        self.assertIn("duplicate", self.call("link-task", "T3", "--blocks", "T4", "--by", "lead", "--remove")[1])
        self.assertEqual(self.rows("SELECT count(*) FROM tasks"), [(4,)])
        self.assertEqual(self.rows("SELECT field,old_value,new_value FROM activity WHERE subject_id='T4'"),
                         [("blocks", None, "T1"), ("blocks", None, "T3"), ("blocks", "T3", None)])

    def test_blocker_links_reject_reverse_and_long_cycles(self):
        self.assertEqual(self.call("link-task", "T1", "--blocks", "T2", "--by", "lead")[0], 0)
        code, _, error = self.call("link-task", "T2", "--blocks", "T1", "--by", "lead")
        self.assertEqual(code, 2)
        self.assertIn("blocker cycle: T2 -> T1 -> T2", error)
        self.assertEqual(self.call("link-task", "T2", "--blocks", "T3", "--by", "lead")[0], 0)
        code, _, error = self.call("link-task", "T3", "--blocks", "T1", "--by", "lead")
        self.assertEqual(code, 2)
        self.assertIn("blocker cycle: T3 -> T1 -> T2 -> T3", error)
        self.assertEqual(self.rows("SELECT task,external_id FROM task_links ORDER BY id"), [("T1", "T2"), ("T2", "T3")])
        self.assertEqual(self.rows("SELECT count(*) FROM activity WHERE field='blocks'"), [(2,)])

    def test_blocker_cycle_checks_legacy_column(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE tasks SET blocked_by='T1' WHERE id='T2'")
            db.commit()
        code, _, error = self.call("link-task", "T2", "--blocks", "T1", "--by", "lead")
        self.assertEqual(code, 2)
        self.assertIn("blocker cycle", error)



if __name__ == "__main__":
    unittest.main()
