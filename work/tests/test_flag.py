#!/usr/bin/env python3
"""T7 attention flags on synthetic current and legacy trackers."""

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
from test_work import blueprint_sql, MODULES_ROOT, pre_t264


class FlagVerbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="work-flag-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.receipts = self.root / "receipts"
        self.receipts.mkdir()
        (self.receipts / "proof.txt").write_text("synthetic proof\n")
        self.db = self.make_db("current.sqlite", (MODULES_ROOT / "work/blueprint.sql").read_text())

    def make_db(self, name, schema):
        path = self.root / name
        with closing(sqlite3.connect(path)) as db:
            db.executescript(schema)
            db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Test program')")
            db.execute("INSERT INTO themes (id,program,name) VALUES ('TH1','PG1','Test theme')")
            db.execute("INSERT INTO projects (id,title,program,theme,status) "
                       "VALUES ('WS01','Test stream','PG1','TH1','todo')")
            db.execute("INSERT INTO tasks (id,title,project,owner,claimed_by) "
                       "VALUES ('T1','Task','WS01','sol','sol')")
            db.execute("INSERT INTO tasks (id,title,project,parent) VALUES ('T2','Subtask','WS01','T1')")
            for bug in ("B-1", "issue-one"):
                db.execute("INSERT INTO bugs (id,title,capability) VALUES (?, 'Bug', 'Test')", (bug,))
            db.commit()
        return path

    def call(self, *args, database=None):
        out, err = io.StringIO(), io.StringIO()
        code = work.run(["--db", str(database or self.db), "--receipt-root", str(self.receipts), *args],
                        stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def rows(self, sql, params=(), database=None):
        with closing(sqlite3.connect(database or self.db)) as db:
            return db.execute(sql, params).fetchall()

    def snapshot(self, database=None):
        return {table: self.rows(f"SELECT * FROM {table}", database=database)
                for table in ("tasks", "bugs", "comments", "activity", "approvals", "sqlite_master")}

    def test_flag_writes_one_comment_and_one_history_row(self):
        before = self.rows("SELECT title,status,owner,claimed_by,parent,acceptance FROM tasks WHERE id='T1'")
        schema = self.rows("SELECT name,sql FROM sqlite_master ORDER BY name")
        self.assertEqual(self.call("flag", "T1", "Check the title", "--by", "person"),
                         (0, "ok flag T1\n", ""))
        self.assertEqual(self.rows("SELECT flag FROM tasks WHERE id='T1'"), [(1,)])
        self.assertEqual(self.rows("SELECT title,status,owner,claimed_by,parent,acceptance FROM tasks WHERE id='T1'"), before)
        self.assertEqual(self.rows("SELECT subject_type,subject_id,author,body FROM comments"),
                         [("task", "T1", "person", "Flag: Check the title")])
        self.assertEqual(self.rows("SELECT subject_type,subject_id,field,old_value,new_value,actor,source,note,verb FROM activity"),
                         [("task", "T1", "flag", "0", "1", "person", work.SOURCE, "Flag: Check the title", "updated")])
        self.assertEqual(self.rows("SELECT comments.at=activity.at FROM comments CROSS JOIN activity"), [(1,)])
        self.assertEqual(self.rows("SELECT name,sql FROM sqlite_master ORDER BY name"), schema)

    def test_reflag_adds_one_reason_without_another_history_row(self):
        self.assertEqual(self.call("flag", "T1", "First reason", "--by", "sol")[0], 0)
        history = self.rows("SELECT * FROM activity")
        code, output, error = self.call("flag", "T1", "New reason", "--by", "person")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("already flagged; reason added; flag unchanged", output)
        self.assertEqual(self.rows("SELECT flag FROM tasks WHERE id='T1'"), [(1,)])
        self.assertEqual(self.rows("SELECT author,body FROM comments ORDER BY id"),
                         [("sol", "Flag: First reason"), ("person", "Flag: New reason")])
        self.assertEqual(self.rows("SELECT * FROM activity"), history)

    def test_unflag_writes_one_comment_and_one_history_row(self):
        self.assertEqual(self.call("flag", "T1", "Check", "--by", "sol")[0], 0)
        self.assertEqual(self.call("unflag", "T1", "Checked", "--by", "person"),
                         (0, "ok unflag T1\n", ""))
        self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'"), [("todo", 0)])
        self.assertEqual(self.rows("SELECT author,body FROM comments ORDER BY id"),
                         [("sol", "Flag: Check"), ("person", "Unflag: Checked")])
        self.assertEqual(self.rows("SELECT field,old_value,new_value,actor,source,note FROM activity ORDER BY id"),
                         [("flag", "0", "1", "sol", work.SOURCE, "Flag: Check"),
                          ("flag", "1", "0", "person", work.SOURCE, "Unflag: Checked")])

    def test_unflag_without_flag_is_refused_without_writes(self):
        before = self.snapshot()
        code, _, error = self.call("unflag", "T1", "Checked", "--by", "person")
        self.assertEqual(code, 2)
        self.assertIn("task is not flagged: T1", error)
        self.assertEqual(self.snapshot(), before)

    def test_reason_is_required_and_not_blank(self):
        for verb in ("flag", "unflag"):
            if verb == "unflag":
                self.assertEqual(self.call("flag", "T1", "Check", "--by", "sol")[0], 0)
            for reason in (None, "", "   ", "\t"):
                with self.subTest(verb=verb, reason=reason):
                    before = self.snapshot()
                    args = [verb, "T1", *([] if reason is None else [reason]), "--by", "sol"]
                    code, _, error = self.call(*args)
                    self.assertEqual(code, 2)
                    self.assertIn(verb + " reason is required and must not be blank", error)
                    self.assertEqual(self.snapshot(), before)

    def test_nonblank_multiline_reasons_are_preserved(self):
        for verb, prefix in (("flag", "Flag: "), ("unflag", "Unflag: ")):
            self.assertEqual(self.call(verb, "T1", "First line\nSecond line", "--by", "sol")[0], 0)
            self.assertEqual(self.rows("SELECT body FROM comments ORDER BY id DESC LIMIT 1"),
                             [(prefix + "First line\nSecond line",)])

    def test_actor_is_required_and_not_blank(self):
        for verb in ("flag", "unflag"):
            for actor in (None, "", "   "):
                with self.subTest(verb=verb, actor=actor):
                    before = self.snapshot()
                    code, _, error = self.call(verb, "T1", "Reason", *([] if actor is None else ["--by", actor]))
                    self.assertEqual(code, 2)
                    self.assertIn("--by", error)
                    self.assertEqual(self.snapshot(), before)

    def test_unknown_task_is_refused_without_writes(self):
        for verb in ("flag", "unflag"):
            before = self.snapshot()
            code, _, error = self.call(verb, "T8", "Reason", "--by", "sol")
            self.assertEqual(code, 2)
            self.assertIn("no such task: T8", error)
            self.assertEqual(self.snapshot(), before)

    def test_bugs_are_refused_without_schema_changes(self):
        for verb in ("flag", "unflag"):
            for bug in ("B-1", "issue-one", "B-unknown"):
                with self.subTest(verb=verb, bug=bug):
                    before = self.snapshot()
                    code, _, error = self.call(verb, bug, "Reason", "--by", "sol")
                    self.assertEqual(code, 2)
                    self.assertIn("flags are for tasks; bugs have no flag yet", error)
                    self.assertEqual(self.snapshot(), before)

    def test_subtask_flags_need_no_approval_and_do_not_rewrite(self):
        before = self.rows("SELECT title,status,parent,note,acceptance FROM tasks WHERE id='T2'")
        self.assertEqual(self.call("task-update", "T2", "--title", "Rewrite", "--by", "sol")[0], 2)
        self.assertEqual(self.call("flag", "T2", "Check this line", "--by", "sol")[0], 0)
        self.assertEqual(self.call("unflag", "T2", "Line checked", "--by", "person")[0], 0)
        self.assertEqual(self.rows("SELECT title,status,parent,note,acceptance FROM tasks WHERE id='T2'"), before)
        self.assertEqual(self.rows("SELECT count(*) FROM approvals"), [(0,)])
        self.assertEqual(self.rows("SELECT subject_id,field,old_value,new_value FROM activity ORDER BY id"),
                         [("T2", "flag", "0", "1"), ("T2", "flag", "1", "0")])
        self.assertEqual(self.rows("SELECT body FROM comments ORDER BY id"),
                         [("Flag: Check this line",), ("Unflag: Line checked",)])

    def test_existing_task_is_allowed_regardless_of_id_prefix(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO tasks (id,title) VALUES ('B-task','Task with custom id')")
            db.commit()
        self.assertEqual(self.call("flag", "B-task", "Attention", "--by", "sol")[0], 0)
        self.assertEqual(self.call("unflag", "B-task", "Checked", "--by", "person")[0], 0)
        self.assertEqual(self.rows("SELECT field,old_value,new_value FROM activity WHERE subject_id='B-task' ORDER BY id"),
                         [("flag", "0", "1"), ("flag", "1", "0")])

    def test_flag_and_unflag_preserve_every_task_status(self):
        for status in ("backlog", "todo", "in-progress", "blocked", "in-review", "done", "canceled", "superseded"):
            with self.subTest(status=status):
                with closing(sqlite3.connect(self.db)) as db:
                    db.execute("UPDATE tasks SET status=? WHERE id='T1'", (status,))
                    db.commit()
                self.assertEqual(self.call("flag", "T1", "Attention", "--by", "person")[0], 0)
                self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'"), [(status, 1)])
                self.assertEqual(self.call("unflag", "T1", "Checked", "--by", "person")[0], 0)
                self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'"), [(status, 0)])

    def test_comment_flag_prefix_is_added_once_and_sets_no_task_flag(self):
        for text in ("Flag: Check", "flag: Check", "FLAG: Check", "  fLaG:   Check", "Flag:Check", "  Flag : Check"):
            with self.subTest(text=text):
                self.assertEqual(self.call("comment", "T1", text, "--flag", "--by", "sol")[0], 0)
                self.assertEqual(self.rows("SELECT body FROM comments ORDER BY id DESC LIMIT 1"), [(text,)])
        self.assertEqual(self.call("comment", "T1", "Check", "--flag", "--by", "sol")[0], 0)
        self.assertEqual(self.rows("SELECT body FROM comments ORDER BY id DESC LIMIT 1"), [("Flag: Check",)])
        self.assertEqual(self.rows("SELECT flag FROM tasks WHERE id='T1'"), [(0,)])
        self.assertEqual(self.rows("SELECT DISTINCT field FROM activity"), [("comment",)])
        self.assertEqual(self.rows("SELECT count(*) FROM comments"), [(7,)])

    def test_comment_without_flag_keeps_its_body(self):
        self.assertEqual(self.call("comment", "T1", "Check", "--by", "sol")[0], 0)
        self.assertEqual(self.rows("SELECT body FROM comments"), [("Check",)])
        self.assertEqual(self.rows("SELECT flag FROM tasks WHERE id='T1'"), [(0,)])

    def test_help_names_both_verbs_and_comment_only_behavior(self):
        parser = work.build_parser()
        help_text = " ".join(parser.format_help().split())
        for verb in ("flag", "unflag"):
            self.assertIn(verb + " <task> <reason> --by <actor>", help_text)
            self.assertEqual(parser.parse_args(["--receipt-root", str(self.receipts), verb, "T1", "Reason", "--by", "sol"]).verb, verb)
        self.assertIn("comment only", help_text)
        self.assertIn("does not set tasks.flag", help_text)
        self.assertIn("use flag to set tasks.flag", help_text)
        self.assertIn("no --approval", help_text)

    def test_legacy_flag_and_unflag_use_existing_history_shape(self):
        legacy = self.make_db("legacy.sqlite", pre_t264(blueprint_sql()))
        schema = self.rows("SELECT name,sql FROM sqlite_master ORDER BY name", database=legacy)
        for task in ("T1", "T2"):
            self.assertEqual(self.call("flag", task, "Check", "--by", "sol", database=legacy)[0], 0)
            self.assertEqual(self.call("unflag", task, "Checked", "--by", "person", database=legacy)[0], 0)
        self.assertEqual(self.rows("SELECT field,old_value,new_value FROM activity ORDER BY id", database=legacy),
                         [("flag", "0", "1"), ("flag", "1", "0"), ("flag", "0", "1"), ("flag", "1", "0")])
        self.assertEqual(self.rows("SELECT name,sql FROM sqlite_master ORDER BY name", database=legacy), schema)

    def test_t309_done_and_accept_preserve_attention_flag(self):
        self.assertEqual(self.call("flag", "T1", "person must check", "--by", "sol")[0], 0)
        for verb, args, status in (("done", ["--by", "sol", "--receipt", "proof.txt", "--proof", "Checked file"], "in-review"),
                                  ("accept", ["--by", "architect"], "done")):
            self.assertEqual(self.call(verb, "T1", *args)[0], 0)
            self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'"), [(status, 1)])
        self.assertEqual(self.rows("SELECT old_value,new_value FROM activity WHERE field='flag'"), [("0", "1")])
        self.assertEqual(self.call("unflag", "T1", "person checked", "--by", "person")[0], 0)
        self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'"), [("done", 0)])

    def test_t309_done_does_not_set_flag_and_accept_needs_no_flag(self):
        self.assertEqual(self.call("done", "T1", "--by", "sol", "--receipt", "proof.txt", "--proof", "Checked file")[0], 0)
        self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'"), [("in-review", 0)])
        self.assertEqual(self.call("accept", "T1", "--by", "architect")[0], 0)
        self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'"), [("done", 0)])
        self.assertEqual(self.rows("SELECT count(*) FROM activity WHERE field='flag'"), [(0,)])

    def test_legacy_done_sets_flag_and_accept_still_requires_it(self):
        legacy = self.make_db("legacy.sqlite", blueprint_sql())
        self.assertEqual(self.call("done", "T1", "--by", "sol", "--receipt", "proof.txt", "--proof", "Checked file", database=legacy)[0], 0)
        self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'", database=legacy), [("todo", 1)])
        self.assertEqual(self.call("unflag", "T1", "Checked", "--by", "person", database=legacy)[0], 0)
        code, _, error = self.call("accept", "T1", "--by", "architect", database=legacy)
        self.assertEqual(code, 2)
        self.assertIn("task is not flagged for acceptance", error)
        self.assertEqual(self.call("flag", "T1", "Review", "--by", "sol", database=legacy)[0], 0)
        self.assertEqual(self.call("accept", "T1", "--by", "architect", database=legacy)[0], 0)
        self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'", database=legacy), [("accepted", 1)])

    def test_block_keeps_legacy_and_t309_flag_behavior(self):
        for name, schema, expected in (("legacy", blueprint_sql(), 1),
                                       ("T9", (MODULES_ROOT / "work/blueprint.sql").read_text(), 0)):
            for flag in (0, 1):
                with self.subTest(schema=name, flag=flag):
                    database = self.make_db(f"{name}-{flag}.sqlite", schema)
                    with closing(sqlite3.connect(database)) as db:
                        db.execute("UPDATE tasks SET flag=? WHERE id='T1'", (flag,))
                        db.commit()
                    self.assertEqual(self.call("block", "T1", "Waiting", "--by", "sol", database=database)[0], 0)
                    self.assertEqual(self.rows("SELECT status,flag FROM tasks WHERE id='T1'", database=database),
                                     [("blocked", expected or flag)])

    def test_program_show_is_unchanged_by_attention_flags(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            before = program.show(db)
        self.assertEqual(self.call("flag", "T1", "Attention", "--by", "person")[0], 0)
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            self.assertEqual(program.show(db), before)

    def test_needs_me_uses_t309_checker_or_legacy_flag(self):
        self.assertEqual(self.call("flag", "T1", "Attention", "--by", "person")[0], 0)
        self.assertEqual(self.rows("SELECT id FROM needs_me"), [])
        self.assertEqual(self.call("task-update", "T1", "--check-by", "person", "--by", "lead")[0], 0)
        self.assertEqual(self.call("done", "T1", "--by", "sol", "--receipt", "proof.txt", "--proof", "Checked file")[0], 0)
        self.assertEqual(self.call("unflag", "T1", "Checked", "--by", "person")[0], 0)
        self.assertEqual(self.rows("SELECT id FROM needs_me"), [("T1",)])
        legacy = self.make_db("legacy.sqlite", blueprint_sql())
        self.assertEqual(self.call("flag", "T1", "Attention", "--by", "person", database=legacy)[0], 0)
        self.assertEqual(self.rows("SELECT id FROM needs_me", database=legacy), [("T1",)])
        self.assertEqual(self.call("unflag", "T1", "Checked", "--by", "person", database=legacy)[0], 0)
        self.assertEqual(self.rows("SELECT id FROM needs_me", database=legacy), [])

    def test_history_failure_rolls_back_flag_and_comment(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TRIGGER refuse_flag_history BEFORE INSERT ON activity "
                       "WHEN NEW.field='flag' BEGIN SELECT RAISE(ABORT, 'history refused'); END")
            db.commit()
        before = self.snapshot()
        code, _, error = self.call("flag", "T1", "Attention", "--by", "sol")
        self.assertEqual(code, 2)
        self.assertIn("history refused", error)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
