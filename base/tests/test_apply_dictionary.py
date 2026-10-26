#!/usr/bin/env python3
"""Tests for the tracker data-dictionary apply tool."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import importlib.util
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path

from base import apply_dictionary
import work


TOOLS = Path(__file__).resolve().parent.parent
BLUEPRINT = (Path(__file__).resolve().parent / '../../work/blueprint.sql')
EXPORT_SPEC = importlib.util.spec_from_file_location("dictionary_test_export", (Path(__file__).resolve().parent / '../backup.py'))
assert EXPORT_SPEC and EXPORT_SPEC.loader
export_state = importlib.util.module_from_spec(EXPORT_SPEC)
EXPORT_SPEC.loader.exec_module(export_state)


class ApplyDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dictionary-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "tracker.sqlite"
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(BLUEPRINT.read_text(encoding="utf-8"))
        self.backups = self.root / "backups"

    def rows(self, sql: str, values=()):
        with closing(sqlite3.connect(self.db)) as db:
            return list(db.execute(sql, values))

    def test_new_dictionary_sources_name_no_ruling_slug_or_task_id(self):
        import re
        apply_dictionary.apply(self.db, self.backups)
        cells = self.rows("SELECT name,source FROM object_types UNION ALL "
                          "SELECT object_type||'.'||field,source FROM fields")
        owner = [(name, source) for name, source in cells
                 if re.search(r'decision:|\bg-[a-z]+-[a-z]+-[a-z]|\b[TB][0-9]+\b', source or '')]
        self.assertEqual([], owner)
        self.assertEqual([('Ruled',)], self.rows("SELECT source FROM fields WHERE object_type='lessons' AND field='id'"))

    def test_apply_seeds_current_live_schema_and_task_query(self):
        report = apply_dictionary.apply(self.db, self.backups)
        self.assertEqual(54, report["object_types"])  # T260: lessons and active_lessons
        self.assertEqual(508, report["fields"])  # T718: 4 task fields and 8 bug fields; T260: 9 + 6 lesson fields
        self.assertEqual(197, report["current_fields"])
        self.assertEqual("ok", report["quick_check"])
        # T260 (433bc3d): a dictionary view definition must execute, not only exist as text.
        definition = self.rows("SELECT definition FROM object_types WHERE name='active_lessons'")[0][0]
        with closing(sqlite3.connect(':memory:')) as proof:
            proof.execute('CREATE TABLE lessons (id TEXT, text TEXT, workspace TEXT, applies_to TEXT, source TEXT, created_on TEXT, status TEXT)')
            proof.execute(definition)
            proof.execute("INSERT INTO lessons VALUES ('L1','Fixture','all','all','test','2026-10-20','active')")
            self.assertEqual(proof.execute('SELECT id FROM active_lessons').fetchone()[0], 'L1')

        for table in apply_dictionary.CURRENT_OBJECTS:
            live = [row[1] for row in self.rows(f'PRAGMA table_info("{table}")')]
            fields = {row[0] for row in self.rows(
                "SELECT field FROM fields WHERE object_type=?", (table,)
            )}
            self.assertTrue(set(live).issubset(fields), table)

        task_fields = self.rows(
            "SELECT field,field_type,required,pick_values FROM v_dictionary "
            "WHERE object_type='tasks' ORDER BY ordinal"
        )
        self.assertEqual(36, len(task_fields))  # T718 adds problem, job_when, job_want, job_so
        self.assertEqual(("id", "key", 1, None), task_fields[0])
        status = next(row for row in task_fields if row[0] == "status")
        self.assertEqual(
            '["backlog","todo","in-progress","blocked","in-review","done","canceled","superseded"]', status[3]
        )
        project_status = self.rows(
            "SELECT pick_values FROM fields WHERE object_type='projects' AND field='status'"
        )[0][0]
        decision_status = self.rows(
            "SELECT pick_values FROM fields WHERE object_type='decisions' AND field='status'"
        )[0][0]
        self.assertIn('"superseded"', project_status)
        self.assertIn('"superseded"', decision_status)
        description = self.rows(
            "SELECT description FROM object_types WHERE name='projects'"
        )[0][0]
        self.assertIn("Inside a program, its label is work stream.", description)
        self.assertEqual(
            [("Names the native agent session for the run, such as a Codex thread id.",)],
            self.rows("SELECT description FROM fields WHERE object_type='runs' AND field='session'"),
        )
        glossary = self.rows(
            "SELECT why,example FROM object_types WHERE name='glossary'"
        )[0]
        self.assertEqual(
            "Without one glossary, agents can use the same word differently.",
            glossary[0],
        )
        self.assertIn("GLOSSARY.md", glossary[1])

    def test_apply_keeps_written_rows_and_touches_only_what_it_is_told(self):
        # T712: a second run must not rewrite why, example, or field text that a person wrote.
        apply_dictionary.apply(self.db, self.backups)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE object_types SET why='Written why.', example='Written example.' WHERE name='tasks'")
            db.execute("UPDATE fields SET pick_values='[\"a\", \"b\"]', description='Written field.' "
                       "WHERE object_type='tasks' AND field='status'")
            db.commit()
            before_types = list(db.execute("SELECT * FROM object_types ORDER BY name"))
            before_fields = list(db.execute("SELECT * FROM fields ORDER BY object_type, field"))
        report = apply_dictionary.apply(self.db, self.backups)
        self.assertFalse(report["backup_created"])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(before_types, list(db.execute("SELECT * FROM object_types ORDER BY name")))
            self.assertEqual(before_fields, list(db.execute("SELECT * FROM fields ORDER BY object_type, field")))

    def test_import_works_from_a_path_that_starts_at_the_system_home(self):
        # T712: a backups/ folder in the system home must not hide base/backups.py.
        import subprocess, sys
        home = self.root / "home"
        (home / "backups").mkdir(parents=True)
        (home / "base").symlink_to(TOOLS)
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from base.apply_dictionary import apply, make_backup_locked; print('ok')")
        result = subprocess.run([sys.executable, "-B", "-c", code, str(home)], cwd=str(home),
                                capture_output=True, text=True)
        self.assertEqual("ok", result.stdout.strip(), result.stderr)

    def test_second_apply_is_idempotent_and_exports_dictionary_tables(self):
        first = apply_dictionary.apply(self.db, self.backups)
        first_bytes = self.db.read_bytes()
        second = apply_dictionary.apply(self.db, self.backups)
        self.assertTrue(first["backup_created"])
        self.assertFalse(second["backup_created"])
        self.assertEqual(first_bytes, self.db.read_bytes())
        self.assertEqual(1, len(list(self.backups.glob("*.sqlite"))))

        result = export_state.export_state(self.db, self.root / "state")
        self.assertIn("object_types", result["files"])
        self.assertIn("fields", result["files"])
        self.assertTrue((self.root / "state/object_types.jsonl").is_file())
        self.assertTrue((self.root / "state/fields.jsonl").is_file())

    def test_work_validation_and_export_accept_trackers_with_and_without_dictionary(self):
        with closing(sqlite3.connect(self.db)) as db:
            work.validate_schema(db)
        before = export_state.export_state(self.db, self.root / "before")
        self.assertNotIn("object_types", before["files"])
        apply_dictionary.apply(self.db, self.backups)
        with closing(sqlite3.connect(self.db)) as db:
            work.validate_schema(db)
        after = export_state.export_state(self.db, self.root / "after")
        self.assertIn("object_types", after["files"])
        self.assertIn("fields", after["files"])

    def test_latest_and_exact_path_undo_restore_schema_and_counts(self):
        with closing(sqlite3.connect(self.db)) as db:
            original_schema = apply_dictionary.schema_snapshot(db)
            original_counts = {
                row[0]: db.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            }
        first = apply_dictionary.apply(self.db, self.backups)
        applied = self.db.read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, apply_dictionary.run([
                "--db", str(self.db), "--backup-dir", str(self.backups), "--undo", "latest",
            ]))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(original_schema, apply_dictionary.schema_snapshot(db))
            self.assertEqual(original_counts, {
                row[0]: db.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            })

        self.db.write_bytes(applied)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, apply_dictionary.run([
                "--db", str(self.db), "--backup-dir", str(self.backups),
                "--undo", first["backup"],
            ]))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(original_schema, apply_dictionary.schema_snapshot(db))
            self.assertEqual(original_counts, {
                row[0]: db.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            })

    def test_cli_exports_after_apply_and_refuses_locked_database(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = apply_dictionary.run([
                "--db", str(self.db), "--backup-dir", str(self.backups),
            ])
        self.assertEqual(0, code)
        self.assertEqual("", errors.getvalue())
        self.assertTrue((self.root / "state/object_types.jsonl").is_file())
        self.assertTrue((self.root / "state/fields.jsonl").is_file())

        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, apply_dictionary.run([
                "--db", str(self.db), "--backup-dir", str(self.backups), "--undo", "latest",
            ]))
        self.assertFalse((self.root / "state/object_types.jsonl").exists())
        self.assertFalse((self.root / "state/fields.jsonl").exists())

        locked = self.root / "locked.sqlite"
        locked.write_bytes((self.root / "backups").glob("*.sqlite").__next__().read_bytes())
        with closing(sqlite3.connect(locked, timeout=0, isolation_level=None)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                code = apply_dictionary.run([
                    "--db", str(locked), "--backup-dir", str(self.root / "locked-backups"),
                ])
        self.assertEqual(2, code)
        self.assertIn("database is locked", errors.getvalue())
        self.assertFalse((self.root / "locked-backups").exists())

    def test_backup_never_writes_through_a_planted_partial_link(self):
        # T750 F07: the apply tools wrote sqlite's .backup to a fixed .<name>.partial path that followed a link.
        import os
        from datetime import datetime
        from unittest.mock import patch
        import backups
        fixed = datetime.now().astimezone()

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        self.backups.mkdir()
        victim = self.root / "victim.sqlite"
        victim.write_bytes(b"")
        name = f"{self.db.stem}-{fixed.strftime(backups.BACKUP_STAMP)}.sqlite"
        planted = self.backups / ("." + name + ".partial")
        planted.symlink_to(victim)
        db = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(db.close)
        db.execute("BEGIN EXCLUSIVE")
        with patch.object(backups, "datetime", Clock):
            made = backups.make_backup_locked(self.db, self.backups, db)
        db.execute("ROLLBACK")
        self.assertEqual(made, self.backups / name)
        self.assertEqual(victim.read_bytes(), b"")
        self.assertTrue(planted.is_symlink())
        self.assertEqual(os.stat(made).st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(made)) as check:
            self.assertEqual(check.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.assertEqual(sorted(p.name for p in self.backups.iterdir()), sorted([name, planted.name]))


if __name__ == "__main__":
    unittest.main()
