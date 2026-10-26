#!/usr/bin/env python3
"""Synthetic tests for the bounded work relationship guard candidate."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

import work_relationships as guards


CHECKOUT_ENV = "WORK_RELATIONSHIPS_CHECKOUT"
PRIVATE_TARGETS_ENV = "WORK_RELATIONSHIPS_PRIVATE_TARGETS"
MODULES_ROOT = Path(__file__).resolve().parent.parent.parent


def load_work_module():
    path = (Path(__file__).resolve().parent / '../work.py')
    spec = importlib.util.spec_from_file_location("work_relationships_test_work", path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load work.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def sqlite_file(path: Path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


SIDE_TABLES = """
CREATE TABLE goal_mirrors (
  goal_id TEXT PRIMARY KEY REFERENCES goals(id) ON DELETE RESTRICT,
  source_store TEXT NOT NULL,
  source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
  source_captured_at TEXT NOT NULL,
  mirror_created_at TEXT NOT NULL
);
CREATE TABLE links (
  id INTEGER PRIMARY KEY,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  original_task TEXT NOT NULL,
  system TEXT NOT NULL,
  scope TEXT,
  external_id TEXT NOT NULL,
  path TEXT,
  relation TEXT NOT NULL,
  active INTEGER NOT NULL,
  created_on TEXT NOT NULL,
  source_store TEXT NOT NULL,
  source_table TEXT NOT NULL,
  source_row_hash TEXT NOT NULL CHECK(length(source_row_hash)=64)
);
CREATE TRIGGER goal_mirror_row_no_update
BEFORE UPDATE ON goals
WHEN EXISTS (SELECT 1 FROM goal_mirrors WHERE goal_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'goal mirror update refused'); END;
CREATE TRIGGER goal_mirror_row_no_delete
BEFORE DELETE ON goals
WHEN EXISTS (SELECT 1 FROM goal_mirrors WHERE goal_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'goal mirror delete refused'); END;
CREATE TRIGGER goal_mirror_metadata_no_update
BEFORE UPDATE ON goal_mirrors
BEGIN SELECT RAISE(ABORT, 'goal mirror metadata update refused'); END;
CREATE TRIGGER goal_mirror_metadata_no_delete
BEFORE DELETE ON goal_mirrors
BEGIN SELECT RAISE(ABORT, 'goal mirror metadata delete refused'); END;
"""


class WorkRelationshipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="work-relationships-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db_path = self.root / "target.sqlite"
        self.make_database(self.db_path)

    def make_database(self, path: Path, *, side_tables: bool = True) -> None:
        db = sqlite3.connect(path)
        try:
            db.executescript(((Path(__file__).resolve().parent / '../blueprint.sql')).read_text())
            if side_tables:
                db.executescript(SIDE_TABLES)
            db.execute("INSERT INTO goals(id,title,horizon,status) VALUES ('G1','Goal','quarter','on-track')")
            db.execute("INSERT INTO goals(id,title,horizon,status) VALUES ('G2','Linked goal','quarter','on-track')")
            db.execute("INSERT INTO goals(id,title,horizon,status) VALUES ('GM','Mirror','quarter','on-track')")
            db.execute("INSERT INTO projects(id,title,goal,status) VALUES ('P1','Project','G1','todo')")
            db.execute("INSERT INTO projects(id,title,status) VALUES ('P2','Linked project','todo')")
            db.execute("INSERT INTO tasks(id,title,status,project) VALUES ('T1','Task','todo','P1')")
            if side_tables:
                link_values = self.link_values(1, "goal", "G2")
                db.execute("INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", link_values)
                link_values = self.link_values(2, "project", "P2")
                db.execute("INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", link_values)
                mirror = db.execute("SELECT * FROM goals WHERE id='GM'").fetchone()
                columns = [row[1] for row in db.execute('PRAGMA table_info("goals")')]
                digest = hashlib.sha256(guards.canonical_json(dict(zip(columns, mirror)))).hexdigest()
                db.execute(
                    "INSERT INTO goal_mirrors VALUES ('GM','authority',?,'2026-09-20T00:00:00Z','2026-09-20T00:01:00Z')",
                    (digest,),
                )
            db.commit()
        finally:
            db.close()

    def link_values(self, link_id: int, subject_type: str, subject_id: str) -> tuple:
        return (
            link_id, subject_type, subject_id, "legacy-value", "synthetic", None,
            f"external-{link_id}", None, "related", 1, "2026-09-20T00:00:00Z",
            "system-workspace", "task_links", str(link_id) * 64,
        )

    @contextmanager
    def rw(self):
        db = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    def install(self):
        return guards.install_guards(self.db_path, disposable_copy=True)

    def make_stale_authority(self, name: str = "authority.sqlite") -> Path:
        source = self.root / name
        self.make_database(source, side_tables=False)
        with sqlite_file(source) as db:
            db.execute(
                "UPDATE goals SET title='Authority mirror',status='at-risk',tags='source-owned' "
                "WHERE id='GM'"
            )
        return source

    def make_refresh_plan(self, source: Path) -> tuple[dict, Path]:
        self.install()
        plan = guards.create_refresh_plan(
            self.db_path,
            {"authority": source},
            captured_at="2026-09-20T13:00:00+00:00",
        )
        path = self.root / "refresh-plan.json"
        guards.write_private_plan(path, plan)
        return plan, path

    def logical_state(self, path: Path) -> dict:
        db = guards.connect(path, writable=False)
        try:
            db.execute("BEGIN")
            return guards.database_rows_state(db)
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    def assert_rejected(self, db: sqlite3.Connection, sql: str, params: tuple = (), message: str | None = None) -> None:
        db.execute("BEGIN")
        if message:
            with self.assertRaisesRegex(sqlite3.IntegrityError, message):
                db.execute(sql, params)
        else:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(sql, params)
        db.rollback()

    def test_default_audit_is_read_only_and_schema_exact(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            exit_code = guards.main(["--db", str(self.db_path)])
        report = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(report["read_only"])
        self.assertTrue(report["schema_valid"])
        self.assertFalse(any(report["invariants"].values()))
        self.assertEqual("uncheckable", report["mirror_freshness"]["state"])
        self.assertEqual(1, report["mirror_freshness"]["counts"]["source_unavailable"])
        self.assertFalse(report["mirror_freshness"]["blocking"])
        self.assertFalse(report["mirror_freshness"]["authentication"])
        self.assertEqual(before, hashlib.sha256(self.db_path.read_bytes()).hexdigest())

    def test_install_requires_disposable_attestation_and_is_idempotent(self):
        with self.assertRaisesRegex(guards.RelationshipError, "disposable-copy"):
            guards.install_guards(self.db_path, disposable_copy=False)
        first = self.install()
        self.assertTrue(first["guards"]["complete"])
        self.assertGreater(len(first["installed"]), 0)
        second = self.install()
        self.assertEqual([], second["installed"])
        self.assertTrue(second["guards"]["complete"])

    def test_invalid_link_insert_update_and_replace_roll_back(self):
        self.install()
        with self.rw() as db:
            self.assert_rejected(db, "INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self.link_values(3, "task", "T1"), "generic link subject invalid")
            self.assert_rejected(db, "INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self.link_values(3, "goal", "missing"), "generic link subject invalid")
            self.assert_rejected(db, "UPDATE links SET subject_id='missing' WHERE id=1", message="generic link subject invalid")
            before = tuple(db.execute("SELECT * FROM links WHERE id=1").fetchone())
            self.assert_rejected(db, "INSERT OR REPLACE INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self.link_values(1, "project", "missing"), "generic link subject invalid")
            self.assertEqual(before, tuple(db.execute("SELECT * FROM links WHERE id=1").fetchone()))

    def test_link_insert_and_any_update_enforce_active_and_hex_hash(self):
        self.install()
        with self.rw() as db:
            invalid_active = list(self.link_values(3, "goal", "G2"))
            invalid_active[9] = 2
            self.assert_rejected(db, "INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(invalid_active), "generic link subject invalid")
            invalid_hash = list(self.link_values(3, "goal", "G2"))
            invalid_hash[13] = "A" * 64
            self.assert_rejected(db, "INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(invalid_hash), "generic link subject invalid")
            self.assert_rejected(db, "UPDATE links SET active=2 WHERE id=1", message="generic link subject invalid")
            self.assert_rejected(db, "UPDATE links SET source_row_hash=? WHERE id=1", ("A" * 64,), "generic link subject invalid")
            self.assert_rejected(db, "INSERT OR REPLACE INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(invalid_active), "generic link subject invalid")

    def test_sql_literal_case_change_is_conflict_and_fails_read_only_exit(self):
        self.install()
        changed = guards.TRIGGERS["links_subject_insert"].replace("'goal'", "'GOAL'", 1)
        self.assertNotEqual(guards.canonical_sql(changed), guards.canonical_sql(guards.TRIGGERS["links_subject_insert"]))
        with self.rw() as db:
            db.execute("DROP TRIGGER links_subject_insert")
            db.execute(changed)
        report = guards.audit_database(self.db_path)
        self.assertEqual(["links_subject_insert"], report["guards"]["conflicts"])
        self.assertFalse(guards.report_ok(report))
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(1, guards.main(["--db", str(self.db_path)]))

    def test_freshness_refuses_target_hardlinks_and_mirror_sources(self):
        with self.assertRaisesRegex(guards.RelationshipError, "target database"):
            guards.audit_database(self.db_path, {"authority": self.db_path})
        hardlink = self.root / "target-hardlink.sqlite"
        os.link(self.db_path, hardlink)
        with self.assertRaisesRegex(guards.RelationshipError, "hardlink"):
            guards.audit_database(self.db_path, {"authority": hardlink})

        mirror_source = self.root / "mirror-source.sqlite"
        shutil.copy2(self.db_path, mirror_source)
        report = guards.audit_database(self.db_path, {"authority": mirror_source})
        self.assertEqual("uncheckable", report["mirror_freshness"]["state"])
        self.assertEqual(1, report["mirror_freshness"]["counts"]["non_authoritative_source"])
        self.assertTrue(report["mirror_freshness"]["blocking"])
        self.assertFalse(guards.report_ok(report))

    def test_audit_and_install_connections_close_on_success_and_error(self):
        original_connect = guards.connect

        class Tracked:
            def __init__(self, inner, closed):
                self.inner = inner
                self.closed = closed

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def close(self):
                self.closed.append(True)
                return self.inner.close()

        def run_tracked(action):
            closed = []

            def connect(path, *, writable):
                return Tracked(original_connect(path, writable=writable), closed)

            with mock.patch.object(guards, "connect", side_effect=connect):
                action()
            self.assertEqual([True], closed)

        run_tracked(lambda: guards.audit_database(self.db_path))
        install_copy = self.root / "install-close.sqlite"
        shutil.copy2(self.db_path, install_copy)
        run_tracked(lambda: guards.install_guards(install_copy, disposable_copy=True))

        def audit_error():
            with mock.patch.object(guards, "audit_connection", side_effect=RuntimeError("synthetic")):
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    guards.audit_database(self.db_path)

        run_tracked(audit_error)
        bad_schema = self.root / "bad-close.sqlite"
        self.make_database(bad_schema, side_tables=False)

        def install_error():
            with self.assertRaisesRegex(guards.RelationshipError, "failed audit"):
                guards.install_guards(bad_schema, disposable_copy=True)

        run_tracked(install_error)

    def test_linked_subject_delete_key_change_and_replace_are_refused(self):
        self.install()
        with self.rw() as db:
            self.assert_rejected(db, "DELETE FROM goals WHERE id='G2'", message="linked goal delete refused")
            self.assert_rejected(db, "UPDATE goals SET id='G3' WHERE id='G2'", message="linked goal key change refused")
            self.assert_rejected(db, "INSERT OR REPLACE INTO goals(id,title,horizon) VALUES ('G2','Changed','quarter')", message="linked goal replace refused")
            self.assert_rejected(db, "DELETE FROM projects WHERE id='P2'", message="linked project delete refused")
            self.assert_rejected(db, "UPDATE projects SET id='P3' WHERE id='P2'", message="linked project key change refused")
            self.assert_rejected(db, "INSERT OR REPLACE INTO projects(id,title) VALUES ('P2','Changed')", message="linked project replace refused")

    def test_update_or_replace_cannot_overwrite_guarded_destination_keys(self):
        self.install()
        with self.rw() as db:
            db.execute("PRAGMA recursive_triggers=OFF")
            self.assertEqual(0, db.execute("PRAGMA recursive_triggers").fetchone()[0])
            db.execute("INSERT INTO goals(id,title,horizon,status) VALUES ('GU','Unlinked','quarter','on-track')")
            db.execute("INSERT INTO projects(id,title,status) VALUES ('PU','Unlinked','todo')")

            mirror_before = tuple(db.execute("SELECT * FROM goals WHERE id='GM'").fetchone())
            goal_source_before = tuple(db.execute("SELECT * FROM goals WHERE id='GU'").fetchone())
            self.assert_rejected(
                db,
                "UPDATE OR REPLACE goals SET id='GM' WHERE id='GU'",
                message="goal mirror destination key change refused",
            )
            self.assertEqual(mirror_before, tuple(db.execute("SELECT * FROM goals WHERE id='GM'").fetchone()))
            self.assertEqual(goal_source_before, tuple(db.execute("SELECT * FROM goals WHERE id='GU'").fetchone()))

            linked_goal_before = tuple(db.execute("SELECT * FROM goals WHERE id='G2'").fetchone())
            self.assert_rejected(
                db,
                "UPDATE OR REPLACE goals SET id='G2' WHERE id='GU'",
                message="linked goal destination key change refused",
            )
            self.assertEqual(linked_goal_before, tuple(db.execute("SELECT * FROM goals WHERE id='G2'").fetchone()))
            self.assertEqual(goal_source_before, tuple(db.execute("SELECT * FROM goals WHERE id='GU'").fetchone()))

            linked_project_before = tuple(db.execute("SELECT * FROM projects WHERE id='P2'").fetchone())
            project_source_before = tuple(db.execute("SELECT * FROM projects WHERE id='PU'").fetchone())
            self.assert_rejected(
                db,
                "UPDATE OR REPLACE projects SET id='P2' WHERE id='PU'",
                message="linked project destination key change refused",
            )
            self.assertEqual(linked_project_before, tuple(db.execute("SELECT * FROM projects WHERE id='P2'").fetchone()))
            self.assertEqual(project_source_before, tuple(db.execute("SELECT * FROM projects WHERE id='PU'").fetchone()))

            db.execute("UPDATE goals SET title='Allowed' WHERE id='G2'")
            db.execute("UPDATE projects SET title='Allowed' WHERE id='P2'")
            db.execute("UPDATE tasks SET status='in-progress' WHERE id='T1'")
            self.assertEqual("Allowed", db.execute("SELECT title FROM goals WHERE id='G2'").fetchone()[0])
            self.assertEqual("Allowed", db.execute("SELECT title FROM projects WHERE id='P2'").fetchone()[0])
            self.assertEqual("in-progress", db.execute("SELECT status FROM tasks WHERE id='T1'").fetchone()[0])

    def test_mirror_rows_metadata_and_replace_are_refused(self):
        self.install()
        with self.rw() as db:
            original_goal = tuple(db.execute("SELECT * FROM goals WHERE id='GM'").fetchone())
            original_mirror = tuple(db.execute("SELECT * FROM goal_mirrors WHERE goal_id='GM'").fetchone())
            self.assert_rejected(db, "UPDATE goals SET status=status WHERE id='GM'", message="goal mirror update refused")
            self.assert_rejected(db, "DELETE FROM goals WHERE id='GM'", message="goal mirror delete refused")
            self.assert_rejected(db, "INSERT OR REPLACE INTO goals(id,title,horizon) VALUES ('GM','Changed','quarter')", message="goal mirror replace refused")
            self.assert_rejected(db, "UPDATE goal_mirrors SET source_captured_at='later' WHERE goal_id='GM'", message="goal mirror metadata update refused")
            self.assert_rejected(db, "DELETE FROM goal_mirrors WHERE goal_id='GM'", message="goal mirror metadata delete refused")
            self.assert_rejected(
                db,
                "INSERT INTO goal_mirrors VALUES ('G1','authority',?,'now','now')",
                ("a" * 64,),
                "goal mirror metadata insert refused",
            )
            self.assert_rejected(
                db,
                "INSERT OR REPLACE INTO goal_mirrors VALUES ('GM','authority',?,'now','now')",
                ("a" * 64,),
                "goal mirror metadata insert refused",
            )
            self.assertEqual(original_goal, tuple(db.execute("SELECT * FROM goals WHERE id='GM'").fetchone()))
            self.assertEqual(original_mirror, tuple(db.execute("SELECT * FROM goal_mirrors WHERE goal_id='GM'").fetchone()))

    def test_existing_task_writes_and_work_schema_validation_still_work(self):
        self.install()
        with self.rw() as db:
            load_work_module().validate_schema(db)
            db.execute("INSERT INTO tasks(id,title,status,project) VALUES ('T2','Second','todo','P1')")
            db.execute("UPDATE tasks SET status='in-progress' WHERE id='T2'")
            self.assertEqual("in-progress", db.execute("SELECT status FROM tasks WHERE id='T2'").fetchone()[0])

    def test_explicit_source_hash_check_reports_fresh_then_stale_without_authentication(self):
        source_path = self.root / "authority.sqlite"
        self.make_database(source_path, side_tables=False)
        fresh = guards.audit_database(self.db_path, {"authority": source_path})
        self.assertEqual("fresh", fresh["mirror_freshness"]["state"])
        self.assertEqual(1, fresh["mirror_freshness"]["counts"]["fresh"])
        self.assertFalse(fresh["mirror_freshness"]["authentication"])
        with sqlite_file(source_path) as source:
            source.execute("UPDATE goals SET status='at-risk' WHERE id='GM'")
        stale = guards.audit_database(self.db_path, {"authority": source_path})
        self.assertEqual("stale", stale["mirror_freshness"]["state"])
        self.assertEqual(1, stale["mirror_freshness"]["counts"]["stale"])

    def test_refresh_copies_only_planned_goal_and_records_receipt(self):
        source = self.make_stale_authority("authority-2.sqlite")
        with sqlite_file(self.db_path) as db:
            db.execute(
                "INSERT INTO activity(id,subject_type,subject_id,actor,source,at,note) "
                "VALUES (7,'task','T1','tester','synthetic','2026-09-20T12:00:00Z','retained history')"
            )
        source_before = hashlib.sha256(source.read_bytes()).hexdigest()
        before = self.logical_state(self.db_path)
        plan, plan_path = self.make_refresh_plan(source)
        self.assertEqual(1, len(plan["actions"]))
        self.assertFalse(plan["authentication"])
        self.assertIn("not cross-store atomic", plan["source_snapshots"])

        result = guards.apply_refresh_plan(
            plan_path,
            plan["plan_sha256"],
            disposable_copy=True,
        )
        self.assertTrue(result["applied"])
        self.assertFalse(result["replayed"])
        self.assertEqual(1, result["receipt_count"])
        self.assertEqual(source_before, hashlib.sha256(source.read_bytes()).hexdigest())

        with sqlite_file(self.db_path) as db:
            db.row_factory = sqlite3.Row
            source_goal = db.execute("ATTACH DATABASE ? AS authority", (str(source),))
            del source_goal
            local = dict(db.execute("SELECT * FROM goals WHERE id='GM'").fetchone())
            authoritative = dict(db.execute("SELECT * FROM authority.goals WHERE id='GM'").fetchone())
            self.assertEqual(authoritative, local)
            mirror = db.execute("SELECT * FROM goal_mirrors WHERE goal_id='GM'").fetchone()
            self.assertEqual(guards.row_hash(db.execute("SELECT * FROM goals WHERE id='GM'").fetchone()), mirror["source_hash"])
            self.assertEqual("2026-09-20T00:01:00Z", mirror["mirror_created_at"])
            self.assertEqual("retained history", db.execute("SELECT note FROM activity WHERE id=7").fetchone()[0])
            receipt = db.execute(
                "SELECT * FROM activity WHERE subject_type='goal' AND subject_id='GM' "
                "AND field='mirror_source_hash' AND source='mirror-maintenance'"
            ).fetchone()
            self.assertIsNotNone(receipt)
            self.assertEqual(plan["actions"][0]["target_before_hash"], receipt["old_value"])
            self.assertEqual(plan["actions"][0]["source_hash"], receipt["new_value"])
            self.assertEqual(before["tasks"], guards.table_rows(db, "tasks"))
            self.assertEqual(before["links"], guards.table_rows(db, "links"))
            self.assertTrue(guards.trigger_state(db)["complete"])
            load_work_module().validate_schema(db)

    def test_refresh_retry_is_exact_and_does_not_duplicate_receipt(self):
        source = self.make_stale_authority()
        plan, plan_path = self.make_refresh_plan(source)
        guards.apply_refresh_plan(plan_path, plan["plan_sha256"], disposable_copy=True)
        first_state = self.logical_state(self.db_path)
        retry = guards.apply_refresh_plan(plan_path, plan["plan_sha256"], disposable_copy=True)
        self.assertFalse(retry["applied"])
        self.assertTrue(retry["replayed"])
        self.assertEqual(first_state, self.logical_state(self.db_path))

    def test_refresh_records_one_goal_history_row_per_changed_goal(self):
        source = self.make_stale_authority()
        with sqlite_file(self.db_path) as db:
            db.row_factory = sqlite3.Row
            digest = guards.row_hash(db.execute("SELECT * FROM goals WHERE id='G1'").fetchone())
            db.execute(
                "INSERT INTO goal_mirrors VALUES ('G1','authority',?,'2026-09-20T00:00:00Z','2026-09-20T00:01:00Z')",
                (digest,),
            )
        with sqlite_file(source) as db:
            db.execute("UPDATE goals SET title='Authority first goal' WHERE id='G1'")
        plan, plan_path = self.make_refresh_plan(source)
        self.assertEqual(["G1", "GM"], [action["goal_id"] for action in plan["actions"]])
        self.assertEqual(["G1", "GM"], [receipt["subject_id"] for receipt in plan["receipts"]])
        self.assertTrue(all(receipt["subject_type"] == "goal" for receipt in plan["receipts"]))
        guards.apply_refresh_plan(plan_path, plan["plan_sha256"], disposable_copy=True)
        with sqlite_file(self.db_path) as db:
            rows = list(db.execute(
                "SELECT subject_id FROM activity WHERE source='mirror-maintenance' ORDER BY subject_id"
            ))
            self.assertEqual([("G1",), ("GM",)], rows)

    def test_refresh_refuses_stale_source_target_and_resealed_plan(self):
        source = self.make_stale_authority()
        plan, plan_path = self.make_refresh_plan(source)
        before = self.logical_state(self.db_path)
        with sqlite_file(source) as db:
            db.execute("UPDATE goals SET status='off-track' WHERE id='GM'")
        with self.assertRaisesRegex(guards.RelationshipError, "source goals changed"):
            guards.apply_refresh_plan(plan_path, plan["plan_sha256"], disposable_copy=True)
        self.assertEqual(before, self.logical_state(self.db_path))

        source = self.make_stale_authority("authority-second.sqlite")
        plan_path.unlink()
        plan, plan_path = self.make_refresh_plan(source)
        with sqlite_file(self.db_path) as db:
            db.execute("UPDATE tasks SET title='Concurrent unrelated change' WHERE id='T1'")
        changed = self.logical_state(self.db_path)
        with self.assertRaisesRegex(guards.RelationshipError, "target rows changed"):
            guards.apply_refresh_plan(plan_path, plan["plan_sha256"], disposable_copy=True)
        self.assertEqual(changed, self.logical_state(self.db_path))

        forged = json.loads(plan_path.read_text())
        forged["actions"][0]["source_row"]["title"] = "Forged"
        forged["plan_sha256"] = guards.refresh_plan_digest(forged)
        forged_path = self.root / "forged.json"
        guards.write_private_plan(forged_path, forged)
        with self.assertRaisesRegex(guards.RelationshipError, "exact confirmation"):
            guards.apply_refresh_plan(forged_path, plan["plan_sha256"], disposable_copy=True)

    def test_refresh_refuses_mirrored_source_and_target_hardlink(self):
        self.install()
        mirrored_source = self.root / "mirrored-source.sqlite"
        self.make_database(mirrored_source, side_tables=True)
        with self.assertRaisesRegex(guards.RelationshipError, "not authoritative"):
            guards.create_refresh_plan(self.db_path, {"authority": mirrored_source})
        hardlink = self.root / "target-hardlink.sqlite"
        os.link(self.db_path, hardlink)
        with self.assertRaisesRegex(guards.RelationshipError, "hardlink"):
            guards.create_refresh_plan(self.db_path, {"authority": hardlink})

    def test_refresh_failure_rolls_back_rows_receipt_and_guard_removal(self):
        source = self.make_stale_authority()
        plan, plan_path = self.make_refresh_plan(source)
        before = self.logical_state(self.db_path)

        def fail(phase, _db):
            if phase == "before_guard_restore":
                raise RuntimeError("synthetic refresh failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic refresh failure"):
            guards.apply_refresh_plan(
                plan_path,
                plan["plan_sha256"],
                disposable_copy=True,
                failure_hook=fail,
            )
        self.assertEqual(before, self.logical_state(self.db_path))
        with sqlite_file(self.db_path) as db:
            db.row_factory = sqlite3.Row
            self.assertTrue(guards.trigger_state(db)["complete"])
            self.assertEqual(0, db.execute("SELECT count(*) FROM activity WHERE source='mirror-maintenance'").fetchone()[0])

    def test_refresh_binds_source_authority_metadata_before_zero_action_replay(self):
        source = self.root / "authority-metadata.sqlite"
        self.make_database(source, side_tables=False)
        with sqlite_file(source) as db:
            db.execute(guards.TABLE_SQL["goal_mirrors"])
            goal = db.execute("SELECT * FROM goals WHERE id='G1'").fetchone()
            columns = [row[1] for row in db.execute('PRAGMA table_info("goals")')]
            digest = hashlib.sha256(guards.canonical_json(dict(zip(columns, goal)))).hexdigest()
            db.execute(
                "INSERT INTO goal_mirrors VALUES ('G1','upstream',?,'2026-09-20T00:00:00Z','2026-09-20T00:00:00Z')",
                (digest,),
            )
        self.install()
        plan = guards.create_refresh_plan(
            self.db_path,
            {"authority": source},
            captured_at="2026-09-20T13:00:00+00:00",
        )
        self.assertEqual([], plan["actions"])
        plan_path = self.root / "authority-plan.json"
        guards.write_private_plan(plan_path, plan)
        with sqlite_file(source) as db:
            goal = db.execute("SELECT * FROM goals WHERE id='GM'").fetchone()
            columns = [row[1] for row in db.execute('PRAGMA table_info("goals")')]
            digest = hashlib.sha256(guards.canonical_json(dict(zip(columns, goal)))).hexdigest()
            db.execute(
                "INSERT INTO goal_mirrors VALUES ('GM','upstream',?,'2026-09-20T00:00:00Z','2026-09-20T00:00:00Z')",
                (digest,),
            )
        with self.assertRaisesRegex(guards.RelationshipError, "authority metadata changed"):
            guards.apply_refresh_plan(plan_path, plan["plan_sha256"], disposable_copy=True)

    def test_refresh_preserves_unrelated_quoted_table_name(self):
        source = self.make_stale_authority()
        odd_name = 'unrelated"table'
        with sqlite_file(self.db_path) as db:
            db.execute('CREATE TABLE "unrelated""table" (value TEXT)')
            db.execute('INSERT INTO "unrelated""table" VALUES (?)', ("retained",))
        plan, plan_path = self.make_refresh_plan(source)
        guards.apply_refresh_plan(plan_path, plan["plan_sha256"], disposable_copy=True)
        with sqlite_file(self.db_path) as db:
            db.row_factory = sqlite3.Row
            self.assertEqual([{"__rowid__": 1, "value": "retained"}], guards.table_rows(db, odd_name))

    def test_refresh_rechecks_physical_identity_after_lock_and_before_commit(self):
        source = self.make_stale_authority()
        plan, plan_path = self.make_refresh_plan(source)
        source_replacement = self.root / "source-replacement.sqlite"
        shutil.copy2(source, source_replacement)

        def replace_source(phase, _db):
            if phase == "after_target_begin":
                os.replace(source_replacement, source)

        with self.assertRaisesRegex(guards.RelationshipError, "source authority physical identity changed"):
            guards.apply_refresh_plan(
                plan_path, plan["plan_sha256"], disposable_copy=True,
                failure_hook=replace_source,
            )

        source = self.make_stale_authority("authority-commit.sqlite")
        plan_path.unlink()
        plan, plan_path = self.make_refresh_plan(source)
        target_replacement = self.root / "target-replacement.sqlite"
        shutil.copy2(self.db_path, target_replacement)

        def replace_target(phase, _db):
            if phase == "before_commit_identity_check":
                os.replace(target_replacement, self.db_path)

        with self.assertRaisesRegex(guards.RelationshipError, "target physical identity changed"):
            guards.apply_refresh_plan(
                plan_path, plan["plan_sha256"], disposable_copy=True,
                failure_hook=replace_target,
            )
        with sqlite_file(self.db_path) as db:
            db.row_factory = sqlite3.Row
            self.assertTrue(guards.trigger_state(db)["complete"])

    def test_refresh_cli_keeps_details_in_create_only_private_plan(self):
        source = self.make_stale_authority()
        self.install()
        output_path = self.root / "cli-plan.json"
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = guards.main([
                "--db", str(self.db_path),
                "--source", "authority=" + str(source),
                "--plan-refresh", str(output_path),
            ])
        self.assertEqual(0, code)
        summary = json.loads(output.getvalue())
        self.assertTrue(summary["private_details_omitted"])
        self.assertNotIn("Authority mirror", output.getvalue())
        self.assertEqual(0o600, output_path.stat().st_mode & 0o777)
        before = output_path.read_bytes()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(2, guards.main([
                "--db", str(self.db_path),
                "--source", "authority=" + str(source),
                "--plan-refresh", str(output_path),
            ]))
        self.assertEqual(before, output_path.read_bytes())

    def test_schema_and_existing_relationship_defects_refuse_install(self):
        bad_schema = self.root / "bad-schema.sqlite"
        self.make_database(bad_schema, side_tables=False)
        with sqlite_file(bad_schema) as db:
            db.execute("CREATE TABLE links(id INTEGER PRIMARY KEY)")
            db.execute("CREATE TABLE goal_mirrors(goal_id TEXT PRIMARY KEY)")
        report = guards.audit_database(bad_schema)
        self.assertFalse(report["schema_valid"])
        with self.assertRaisesRegex(guards.RelationshipError, "failed audit"):
            guards.install_guards(bad_schema, disposable_copy=True)

        defective = self.root / "defective.sqlite"
        shutil.copy2(self.db_path, defective)
        with sqlite_file(defective) as db:
            db.execute("INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self.link_values(9, "goal", "missing"))
        report = guards.audit_database(defective)
        self.assertEqual(1, report["invariants"]["missing_goal_subject"])
        with self.assertRaisesRegex(guards.RelationshipError, "failed audit"):
            guards.install_guards(defective, disposable_copy=True)

    def test_actual_proposed_private_schemas_read_only_when_supplied(self):
        raw = os.environ.get(PRIVATE_TARGETS_ENV)
        if not raw:
            self.skipTest("private proposed target directory was not supplied")
        root = Path(raw)
        paths = sorted(root.glob("*.sqlite"))
        self.assertEqual(3, len(paths))
        for path in paths:
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            report = guards.audit_database(path)
            self.assertTrue(report["schema_valid"])
            self.assertEqual(0, report["foreign_key_defects"])
            self.assertFalse(any(report["invariants"].values()))
            self.assertFalse(report["guards"]["conflicts"])
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
