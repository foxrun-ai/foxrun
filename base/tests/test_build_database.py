#!/usr/bin/env python3
"""Tests for build_database.py."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import hashlib
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parent / '../build_database.py')
SPEC = importlib.util.spec_from_file_location("build_database", SCRIPT)
assert SPEC and SPEC.loader
build_database = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_database)

ALL_MODULES = "work"  # the core; People ships with Small Talk, the packs never ship
EXPECTED_TABLES = {
    "installed_modules", "module_install_activity", "object_types", "fields",
    "functions", "goals", "measures", "measure_history", "projects", "tasks",
    "programs", "themes", "runs", "task_links", "activity", "comments",
    "attachments", "decisions", "approvals", "incidents", "bugs", "record_links",
}
EXPECTED_VIEWS = {
    "v_dictionary", "open_decisions", "open_tasks", "needs_me", "this_week",
    "next_step", "eisenhower", "program_plan", "stream_brief", "close_now",
    "needs_business_input",
}


class BuildDatabaseTest(unittest.TestCase):
    def test_cli_builds_all_objects_and_second_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cedar-shop.sqlite"
            command = [
                sys.executable, str(SCRIPT), str(target),
                "--modules", ALL_MODULES, "--by", "sol",
            ]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertIn("applied: base, work\n", first.stdout)

            with sqlite3.connect(target) as db:
                tables = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                views = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='view'"
                    )
                }
                installed = db.execute("SELECT COUNT(*) FROM installed_modules").fetchone()[0]
            self.assertEqual(EXPECTED_TABLES, tables)
            self.assertEqual(EXPECTED_VIEWS, views)
            self.assertEqual(2, installed)
            with sqlite3.connect(target) as db:
                actors = {
                    row[0] for row in db.execute(
                        "SELECT actor FROM module_install_activity"
                    )
                }
            self.assertEqual({"sol"}, actors)

            before = hashlib.sha256(target.read_bytes()).hexdigest()
            second = subprocess.run(command, check=True, capture_output=True, text=True)
            after = hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertIn("applied: none", second.stdout)
            self.assertEqual(before, after)

    def addon_root(self, directory: str) -> Path:
        """A modules root with two add-ons beside the real core: b, and a that requires b."""
        root = Path(directory) / "root"
        for name, sql, requires in (
            ("b", "CREATE TABLE IF NOT EXISTS persons (id TEXT PRIMARY KEY, display_name TEXT NOT NULL);\n", None),
            ("a", "CREATE VIEW IF NOT EXISTS v_named AS SELECT id FROM persons;\n", ["b"]),
        ):
            folder = root / "modules" / name
            folder.mkdir(parents=True)
            (folder / "blueprint.sql").write_text(sql, encoding="utf-8")
            if requires:
                (folder / "install.json").write_text('{"requires": %s}' % str(requires).replace("'", '"'))
        return root

    def test_dependency_and_unknown_module_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bad.sqlite"
            with mock.patch.object(build_database, "MODULES_DIR", self.addon_root(directory)):
                with self.assertRaisesRegex(build_database.BuildError, "a requires module: b"):
                    build_database.build_database(target, "work,a", actor="sol")
                with self.assertRaisesRegex(build_database.BuildError, "unknown module: nope"):
                    build_database.build_database(target, "nope", actor="sol")
                # An add-on comes after the add-ons it requires, whatever the request order.
                _, applied, _ = build_database.build_database(target, "a,work,b", actor="sol")
            self.assertEqual(["base", "work", "b", "a"], applied)

    def test_core_names_no_business_pack_or_people(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "core.sqlite"
            # 231264d / g-people-ships-with-small-talk: use a fixture module root, never live add-ons.
            with mock.patch.object(build_database, "MODULES_DIR", self.addon_root(directory)):
                for name in ("people", "commerce", "amazon", "ugc", "tiktok-shop"):
                    with self.assertRaisesRegex(build_database.BuildError, "unknown module: " + name):
                        build_database.build_database(target, "work," + name, actor="sol")

    def test_add_only_adds_an_addon_to_a_book_with_rows(self) -> None:
        # The core seed refreshes dictionary rows with UPDATE; add-only leaves an existing dictionary alone.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "home.sqlite"
            build_database.build_database(target, "work", actor="sol")
            with sqlite3.connect(target) as db:
                db.execute("CREATE TABLE keep_me(id INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO keep_me VALUES (1)")
            with mock.patch.object(build_database, "MODULES_DIR", self.addon_root(directory)):
                _, applied, skipped = build_database.build_database(target, "b,a", actor="sol", add_only=True)
            self.assertEqual(["b", "a"], applied)
            self.assertEqual([], skipped)
            with sqlite3.connect(target) as db:
                self.assertEqual(1, db.execute("SELECT count(*) FROM keep_me").fetchone()[0])
                self.assertEqual(0, db.execute("SELECT count(*) FROM persons").fetchone()[0])

    def test_existing_rows_require_add_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing.sqlite"
            with sqlite3.connect(target) as db:
                db.execute("CREATE TABLE existing_record (id INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO existing_record VALUES (1)")
            with self.assertRaisesRegex(build_database.BuildError, "already has rows"):
                build_database.build_database(target, "work", actor="sol")

            blueprints = {
                **build_database.BLUEPRINTS,
                "base": (build_database.BLUEPRINTS["base"][0],),
            }
            with mock.patch.object(build_database, "BLUEPRINTS", blueprints):
                summary, applied, skipped = build_database.build_database(
                    target, "work", actor="sol", add_only=True
                )
            self.assertEqual(["base", "work"], applied)
            self.assertEqual([], skipped)
            self.assertTrue(any(line.startswith("work: tables 11") for line in summary))
            with sqlite3.connect(target) as db:
                self.assertEqual(1, db.execute("SELECT id FROM existing_record").fetchone()[0])
                self.assertIsNotNone(
                    db.execute("SELECT 1 FROM sqlite_master WHERE name='open_tasks'").fetchone()
                )


    def test_add_only_refuses_unsafe_sql_before_any_change(self) -> None:
        unsafe_statements = {
            "newline drop": "DROP\nTABLE victim;",
            "column add": "ALTER TABLE victim ADD COLUMN added TEXT;",
            "update": "UPDATE victim SET value='changed' WHERE id=1;",
        }
        for label, unsafe_sql in unsafe_statements.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "existing.sqlite"
                base = root / "base.sql"
                work = root / "work.sql"
                base.write_text("-- no statements\n", encoding="utf-8")
                work.write_text(unsafe_sql, encoding="utf-8")
                with sqlite3.connect(target) as db:
                    db.executescript(
                        "CREATE TABLE victim(id INTEGER PRIMARY KEY, value TEXT);"
                        "INSERT INTO victim VALUES(1, 'safe');"
                    )
                objects = {
                    name: {"tables": (), "mirrors": (), "trends": (), "views": ()}
                    for name in ("base", "work")
                }
                with (
                    mock.patch.object(build_database, "MODULES_DIR", root),
                    mock.patch.object(
                        build_database,
                        "BLUEPRINTS",
                        {"base": (base,), "work": (work,)},
                    ),
                    mock.patch.object(build_database, "OBJECTS", objects),
                    self.assertRaisesRegex(build_database.BuildError, "add-only refused unsafe statement"),
                ):
                    build_database.build_database(
                        target, "work", actor="sol", add_only=True
                    )
                with sqlite3.connect(target) as db:
                    columns = [row[1] for row in db.execute("PRAGMA table_info(victim)")]
                    value = db.execute("SELECT value FROM victim WHERE id=1").fetchone()[0]
                    install_table = db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='installed_modules'"
                    ).fetchone()
                self.assertEqual(["id", "value"], columns)
                self.assertEqual("safe", value)
                self.assertIsNone(install_table)

    def test_add_only_refuses_upserts_and_replacements_before_any_change(self) -> None:
        unsafe_statements = {
            "reviewer conflict update": """
                INSERT OR IGNORE INTO object_types
                SELECT * FROM object_types WHERE name='activity'
                ON CONFLICT(name) DO UPDATE SET description='changed by add-only';
            """,
            "insert or replace": """
                INSERT OR REPLACE INTO object_types(name, description)
                VALUES ('activity', 'changed by add-only');
            """,
            "replace into": """
                REPLACE INTO object_types(name, description)
                VALUES ('activity', 'changed by add-only');
            """,
            "comment split conflict update": """
                INSERT OR IGNORE INTO object_types
                SELECT * FROM object_types WHERE name='activity'
                on /* x */ conflict(name) do update
                SET description='changed by add-only';
            """,
        }
        for label, unsafe_sql in unsafe_statements.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "existing.sqlite"
                base = root / "base.sql"
                work = root / "work.sql"
                base.write_text("-- no statements\n", encoding="utf-8")
                work.write_text(unsafe_sql, encoding="utf-8")
                with sqlite3.connect(target) as db:
                    db.executescript(
                        "CREATE TABLE object_types("
                        "name TEXT PRIMARY KEY, description TEXT NOT NULL);"
                        "INSERT INTO object_types VALUES('activity', 'safe');"
                    )
                before = target.read_bytes()
                objects = {
                    name: {"tables": (), "mirrors": (), "trends": (), "views": ()}
                    for name in ("base", "work")
                }
                with (
                    mock.patch.object(build_database, "MODULES_DIR", root),
                    mock.patch.object(
                        build_database,
                        "BLUEPRINTS",
                        {"base": (base,), "work": (work,)},
                    ),
                    mock.patch.object(build_database, "OBJECTS", objects),
                    self.assertRaisesRegex(
                        build_database.BuildError,
                        "add-only refused unsafe statement",
                    ),
                ):
                    build_database.build_database(
                        target, "work", actor="sol", add_only=True
                    )
                self.assertEqual(before, target.read_bytes())

    def test_add_only_allows_dictionary_insert_where_not_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "existing.sqlite"
            base = root / "base.sql"
            work = root / "work.sql"
            base.write_text("-- no statements\n", encoding="utf-8")
            work.write_text(
                "INSERT INTO object_types(name, description) "
                "SELECT 'fields', 'safe' WHERE NOT EXISTS ("
                "SELECT 1 FROM object_types WHERE name='fields');\n",
                encoding="utf-8",
            )
            with sqlite3.connect(target) as db:
                db.executescript(
                    "CREATE TABLE object_types("
                    "name TEXT PRIMARY KEY, description TEXT NOT NULL);"
                    "INSERT INTO object_types VALUES('activity', 'safe');"
                )
            objects = {
                name: {"tables": (), "mirrors": (), "trends": (), "views": ()}
                for name in ("base", "work")
            }
            with (
                mock.patch.object(build_database, "MODULES_DIR", root),
                mock.patch.object(
                    build_database,
                    "BLUEPRINTS",
                    {"base": (base,), "work": (work,)},
                ),
                mock.patch.object(build_database, "OBJECTS", objects),
            ):
                build_database.build_database(
                    target, "work", actor="sol", add_only=True
                )
            with sqlite3.connect(target) as db:
                rows = db.execute(
                    "SELECT name, description FROM object_types ORDER BY name"
                ).fetchall()
            self.assertEqual([("activity", "safe"), ("fields", "safe")], rows)

    def test_incompatible_populated_persons_is_partial_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing.sqlite"
            with sqlite3.connect(target) as db:
                db.executescript(
                    "CREATE TABLE persons(id TEXT PRIMARY KEY);"
                    "INSERT INTO persons VALUES('p1');"
                )
            blueprints = {
                **build_database.BLUEPRINTS,
                "base": (build_database.BLUEPRINTS["base"][0],),
            }
            with (
                mock.patch.object(build_database, "BLUEPRINTS", blueprints),
                mock.patch.object(build_database, "MODULES_DIR", self.addon_root(directory)),
            ):
                _, applied, skipped = build_database.build_database(
                    target, "b", actor="sol", add_only=True
                )
            self.assertIn("b", applied)
            self.assertTrue(any("incompatible table persons" in item for item in skipped))
            with sqlite3.connect(target) as db:
                installed = db.execute(
                    "SELECT status, actor, reason FROM installed_modules WHERE module='b'"
                ).fetchone()
                activity = db.execute(
                    "SELECT status, actor, reason FROM module_install_activity "
                    "WHERE module='b' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertEqual("partial", installed[0])
            self.assertEqual("sol", installed[1])
            self.assertIn("incompatible table persons", installed[2])
            self.assertEqual(installed, activity)


if __name__ == "__main__":
    unittest.main()
