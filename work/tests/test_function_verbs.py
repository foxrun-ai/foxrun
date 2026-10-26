#!/usr/bin/env python3
"""T9 function-create and function-update on a synthetic tracker."""

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

import work
from test_work import MODULES_ROOT

CHANGE_ROWS = "SELECT subject_type,subject_id,field,old_value,new_value,actor,source,note FROM activity ORDER BY id"
FUNCTION_ROWS = "SELECT id,name,organization,parent,owner,page,tags FROM functions ORDER BY rowid"


class FunctionVerbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="work-function-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.receipts = self.root / "receipts"
        self.receipts.mkdir()
        self.db = self.root / "tracker.sqlite"
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript((MODULES_ROOT / "work/blueprint.sql").read_text(encoding="utf-8"))
            db.execute("INSERT INTO functions (id,name,organization,owner,tags,created_on) "
                       "VALUES ('amazon','amazon','cedar-shop','reviewer','rank-1','2026-09-18')")
            db.execute("INSERT INTO functions (id,name,organization,parent,owner,created_on) "
                       "VALUES ('amazon-na','amazon-na','cedar-shop','amazon','reviewer','2026-09-18')")
            db.execute("INSERT INTO projects (id,title,status,function) VALUES ('WS01','Stream','todo','amazon')")
            db.execute("INSERT INTO tasks (id,title,function) VALUES ('T1','Task','amazon')")
            db.commit()

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = work.run(["--db", str(self.db), "--receipt-root", str(self.receipts), *args],
                        stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def rows(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute(sql, params).fetchall()

    def snapshot(self):
        return {table: self.rows(f"SELECT * FROM {table}")
                for table in ("functions", "activity", "comments", "projects", "tasks", "sqlite_master")}

    def refused(self, message, *args):
        before = self.snapshot()
        code, output, error = self.call(*args)
        self.assertEqual((code, output), (2, ""))
        self.assertIn(message, error)
        self.assertEqual(self.snapshot(), before)

    def test_create_writes_one_function_row_and_one_change_row(self):
        self.assertEqual(
            self.call("function-create", "--id", "communications", "--name", "Communications",
                      "--owner", "comms-lead", "--by", "chief-of-staff"),
            (0, "ok function-create communications\n", ""),
        )
        self.assertEqual(
            self.rows(FUNCTION_ROWS + " LIMIT 1 OFFSET 2"),
            [("communications", "Communications", None, None, "comms-lead", None, None)],
        )
        created_on, = self.rows("SELECT created_on FROM functions WHERE id='communications'")[0]
        self.assertRegex(created_on, r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(
            self.rows(CHANGE_ROWS),
            [("function", "communications", "create", None, "Communications", "chief-of-staff",
              work.SOURCE, "owner=comms-lead")],
        )
        self.assertEqual(self.rows("SELECT substr(at,1,10) FROM activity"), [(created_on,)])
        self.assertEqual(self.rows("SELECT count(*) FROM comments"), [(0,)])

    def test_create_stores_every_column_and_names_them_on_the_change_row(self):
        self.assertEqual(
            self.call("function-create", "--id", "amazon-eu", "--name", "amazon-eu", "--organization", "cedar-shop",
                      "--parent", "amazon", "--owner", "reviewer", "--page", "amazon-eu.md", "--tags", "Rank-4,eu",
                      "--note", "third market", "--by", "reviewer")[0],
            0,
        )
        self.assertEqual(
            self.rows(FUNCTION_ROWS + " LIMIT 1 OFFSET 2"),
            [("amazon-eu", "amazon-eu", "cedar-shop", "amazon", "reviewer", "amazon-eu.md", "rank-4,eu")],
        )
        self.assertEqual(
            self.rows("SELECT note FROM activity"),
            [("organization=cedar-shop; parent=amazon; owner=reviewer; page=amazon-eu.md; tags=rank-4,eu; "
              "note=third market",)],
        )

    def test_create_refuses_a_duplicate_id(self):
        self.refused("function already exists: amazon",
                     "function-create", "--id", "amazon", "--name", "Second amazon", "--by", "reviewer")

    def test_create_refuses_bad_values(self):
        cases = (
            ("--owner must be a plain name", ("--owner", "comms lead")),
            ("--owner must be a plain name", ("--owner", "comms-lead.")),
            ("--organization must be a lowercase slug", ("--organization", "Cedar Shop")),
            ("--organization must be a lowercase slug", ("--organization", "cedar_shop")),
            ("no such function: missing", ("--parent", "missing")),
            ("a function cannot be its own parent", ("--parent", "communications")),
            ("tags must be non-empty comma-separated words without spaces", ("--tags", "two words")),
            ("--page must be one non-empty line", ("--page", " ")),
            ("function-create takes --tags", ("--add-tag", "rank-4")),
        )
        for message, extra in cases:
            with self.subTest(extra=extra):
                self.refused(message, "function-create", "--id", "communications", "--name", "Communications",
                             *extra, "--by", "chief-of-staff")

    def test_create_refuses_a_bad_id_a_missing_name_and_a_missing_actor(self):
        self.refused("--id must be a lowercase slug",
                     "function-create", "--id", "Communications", "--name", "Communications", "--by", "lead")
        self.refused("function-create needs --id and --name",
                     "function-create", "--id", "communications", "--by", "lead")
        self.refused("function-create needs --id and --name",
                     "function-create", "--name", "Communications", "--by", "lead")
        self.refused("function-create takes --id, not a positional id",
                     "function-create", "communications", "--name", "Communications", "--by", "lead")
        self.refused("--by is required",
                     "function-create", "--id", "communications", "--name", "Communications")

    def test_update_changes_one_field_alone_with_one_change_row(self):
        cases = (
            ("name", ("--name", "Amazon"), "amazon", "Amazon"),
            ("organization", ("--organization", "foxrun"), "cedar-shop", "foxrun"),
            ("owner", ("--owner", "comms-lead"), "reviewer", "comms-lead"),
            ("page", ("--page", "amazon.md"), None, "amazon.md"),
            ("tags", ("--add-tag", "core"), "rank-1", "rank-1,core"),
        )
        for count, (field, flags, old, new) in enumerate(cases, start=1):
            with self.subTest(field=field):
                before = self.rows("SELECT * FROM functions WHERE id='amazon'")[0]
                self.assertEqual(self.call("function-update", "amazon", *flags, "--by", "maintainer"),
                                 (0, "ok function-update amazon\n", ""))
                after = self.rows("SELECT * FROM functions WHERE id='amazon'")[0]
                self.assertEqual(sum(1 for left, right in zip(before, after) if left != right), 1)
                self.assertEqual(self.rows(f'SELECT "{field}" FROM functions WHERE id=?', ("amazon",)), [(new,)])
                self.assertEqual(self.rows(CHANGE_ROWS)[count - 1],
                                 ("function", "amazon", field, old, new, "maintainer", work.SOURCE, None))
                self.assertEqual(self.rows("SELECT count(*) FROM activity"), [(count,)])
        self.assertEqual(self.rows("SELECT id,function FROM projects"), [("WS01", "amazon")])
        self.assertEqual(self.rows("SELECT id,function FROM tasks"), [("T1", "amazon")])
        self.assertEqual(self.rows("SELECT count(*) FROM comments"), [(0,)])

    def test_update_parent_none_empties_it_and_the_note_lands_on_the_change_row(self):
        self.assertEqual(self.call("function-update", "amazon-na", "--parent", "none",
                                   "--note", "stands alone", "--by", "maintainer")[0], 0)
        self.assertEqual(self.rows("SELECT parent FROM functions WHERE id='amazon-na'"), [(None,)])
        self.assertEqual(self.rows(CHANGE_ROWS),
                         [("function", "amazon-na", "parent", "amazon", None, "maintainer", work.SOURCE, "stands alone")])
        self.assertEqual(self.call("function-update", "amazon-na", "--owner", "none", "--by", "maintainer")[0], 0)
        self.assertEqual(self.rows("SELECT owner FROM functions WHERE id='amazon-na'"), [(None,)])

    def test_update_with_the_same_value_writes_no_change_row(self):
        self.assertEqual(self.call("function-update", "amazon", "--owner", "reviewer", "--by", "maintainer"),
                         (0, "ok function-update amazon duplicate\n", ""))
        self.assertEqual(self.rows("SELECT count(*) FROM activity"), [(0,)])

    def test_update_refuses_a_change_of_id(self):
        self.refused("function-update refuses --id: a function id never changes",
                     "function-update", "amazon", "--id", "amazon-us", "--by", "maintainer")
        self.refused("function-update refuses --id: a function id never changes",
                     "function-update", "amazon", "--id", "amazon-us", "--name", "Amazon US", "--by", "maintainer")

    def test_update_refuses_bad_values(self):
        cases = (
            ("no such function: missing", ("missing", "--name", "Missing")),
            ("--owner must be a plain name", ("amazon", "--owner", "reviewer + claude")),
            ("--organization must be a lowercase slug", ("amazon", "--organization", "Cedar-Shop")),
            ("no such function: missing", ("amazon", "--parent", "missing")),
            ("a function cannot be its own parent", ("amazon", "--parent", "amazon")),
            ("function parent cycle: amazon -> amazon-na -> amazon", ("amazon", "--parent", "amazon-na")),
            ("--name must be one non-empty line", ("amazon", "--name", " ")),
            ("--add-tag needs one tag", ("amazon", "--add-tag", "a,b")),
            ("function-update needs a field to change", ("amazon",)),
            ("function-update needs a field to change", ("amazon", "--note", "no field")),
            ("function-update takes one positional function id", ("amazon", "extra", "--name", "Amazon")),
            ("--by is required", ("amazon", "--name", "Amazon")),
        )
        for message, arguments in cases:
            with self.subTest(arguments=arguments):
                extra = () if message == "--by is required" else ("--by", "maintainer")
                self.refused(message, "function-update", *arguments, *extra)

    def test_function_flags_are_refused_on_other_verbs(self):
        self.refused("--organization and --page belong to function-create or function-update",
                     "create", "--title", "Task", "--organization", "foxrun", "--by", "maintainer")
        self.refused("--organization and --page belong to function-create or function-update",
                     "task-update", "T1", "--title", "New title", "--page", "amazon.md", "--by", "maintainer")
        self.refused("--owner belongs to task-update, function-create, or function-update",
                     "create", "--title", "Task", "--owner", "maintainer", "--by", "maintainer")

    def test_new_function_takes_a_work_stream_and_a_decision(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Program')")
            db.execute("INSERT INTO themes (id,program,name,ord) VALUES ('TH1','PG1','Theme',1)")
            db.commit()
        self.assertEqual(self.call("function-create", "--id", "communications", "--name", "Communications",
                                   "--owner", "comms-lead", "--by", "chief-of-staff")[0], 0)
        self.assertEqual(
            self.call("stream-create", "--program", "PG1", "--theme", "TH1", "--function", "communications",
                      "--title", "Messages", "--by", "chief-of-staff")[:2],
            (0, "WS02\n"),
        )
        self.assertEqual(
            self.call("decision-add", "--id", "comms", "--name", "Communications function",
                      "--function", "communications", "--by", "chief-of-staff")[0],
            0,
        )
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_help_gives_one_worked_example_for_each_verb(self):
        text = work.build_parser().format_help()
        self.assertIn("function-create --id communications --name Communications --owner comms-lead "
                      "--by chief-of-staff", text)
        self.assertIn('function-update communications --owner comms-lead --note "owner named" '
                      "--by chief-of-staff", text)


if __name__ == "__main__":
    unittest.main()
