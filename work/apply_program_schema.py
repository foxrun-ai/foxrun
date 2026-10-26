#!/usr/bin/env python3
"""Apply the additive program-control schema to a work database."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import importlib.util
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

PROJECT_COLUMNS = (
    ("program", "TEXT REFERENCES programs(id)"),
    ("theme", "TEXT REFERENCES themes(id)"),
    ("needs", "TEXT"),
    ("order_column", "INTEGER"),
    ("span", "INTEGER DEFAULT 1"),
    ("alongside", "INTEGER DEFAULT 0"),
    ("replaces", "TEXT"),
)
TASK_COLUMNS = (("prior_project", "TEXT"),)
# T718: every task and subtask carries Problem and a job story of its own.
SIX_FIELD_TASK_COLUMNS = (("problem", "TEXT"), ("job_when", "TEXT"), ("job_want", "TEXT"), ("job_so", "TEXT"))
# T718: a bug carries the same fields as a task, plus tags.
SIX_FIELD_BUG_COLUMNS = tuple((name, "TEXT") for name in (
    "tags", "problem", "job_when", "job_want", "job_so", "body", "acceptance", "context"))
COMMENT_COLUMNS = (("field", "TEXT"),)
RUN_COLUMNS = (("session", "TEXT"),)

GOAL_SCHEMA = """CREATE TABLE goals__program_control_new (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  horizon TEXT NOT NULL CHECK (horizon IN ('north-star','3-year','1-year','quarter')), period TEXT,
  function TEXT REFERENCES functions(id), owner TEXT,
  status TEXT NOT NULL DEFAULT 'on-track' CHECK (status IN ('on-track','at-risk','off-track','done','dropped','superseded')),
  tags TEXT, created_on TEXT, replaced_by TEXT)"""

PROJECT_SCHEMA = """CREATE TABLE projects__program_control_new (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, result TEXT, goal TEXT REFERENCES goals(id),
  status TEXT NOT NULL DEFAULT 'backlog' CHECK (status IN ('backlog','todo','in-progress','blocked','in-review','done','canceled','superseded')),
  function TEXT REFERENCES functions(id), owner TEXT, due TEXT, page TEXT, tags TEXT, created_on TEXT, extra TEXT,
  description TEXT, problem TEXT, job_when TEXT, job_want TEXT, job_so TEXT, done_when TEXT, context TEXT, ord INTEGER,
  program TEXT REFERENCES programs(id), theme TEXT REFERENCES themes(id), needs TEXT,
  order_column INTEGER, span INTEGER DEFAULT 1, alongside INTEGER DEFAULT 0, replaces TEXT)"""


def statements(script: str):
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                yield statement
            pending = ""
    if pending.strip():
        raise ValueError("incomplete program schema SQL")


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def custom_column_sql(row: sqlite3.Row, table: str) -> str:
    name = row[1]
    if row[6] != 0 or row[5] != 0:
        raise ValueError("cannot preserve unsupported column on " + table + ": " + name)
    parts = [quote_identifier(name)]
    if row[2]:
        parts.append(row[2])
    if row[3]:
        parts.append("NOT NULL")
    if row[4] is not None:
        parts.extend(("DEFAULT", row[4]))
    return " ".join(parts)


def rebuild_table(db: sqlite3.Connection, table: str, create_sql: str, target_columns: tuple[str, ...]) -> None:
    temporary = table + "__program_control_new"
    if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (temporary,)).fetchone():
        raise ValueError("program schema temporary object already exists: " + temporary)
    columns = list(db.execute(f'PRAGMA table_xinfo("{table}")'))
    if not columns:
        raise ValueError("work table is missing: " + table)
    present = {row[1] for row in columns}
    custom = [row for row in columns if row[1] not in target_columns]
    if custom:
        definitions = ", ".join(custom_column_sql(row, table) for row in custom)
        create_sql = create_sql[:-1] + ", " + definitions + ")"
    copied_columns = (*target_columns, *(row[1] for row in custom))
    db.execute(create_sql)
    selected = ",".join(quote_identifier(name) if name in present else "NULL" for name in copied_columns)
    names = ",".join(quote_identifier(name) for name in copied_columns)
    db.execute(f'INSERT INTO "{temporary}" ({names}) SELECT {selected} FROM "{table}"')
    db.execute(f'DROP TABLE "{table}"')
    db.execute(f'ALTER TABLE "{temporary}" RENAME TO "{table}"')


def apply_schema_to_connection(db: sqlite3.Connection) -> None:
    sql_path = (Path(__file__).resolve().parent / 'apply-program-control.sql')
    db.execute("CREATE TABLE IF NOT EXISTS programs (id TEXT PRIMARY KEY, name TEXT NOT NULL, objective TEXT, created_on TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS themes (id TEXT PRIMARY KEY, program TEXT NOT NULL REFERENCES programs(id), name TEXT NOT NULL, tagline TEXT, ord INTEGER)")
    db.execute("DROP VIEW IF EXISTS program_plan")
    db.execute("DROP VIEW IF EXISTS stream_brief")

    goal_columns = tuple(row[1] for row in db.execute('PRAGMA table_info("goals")'))
    goal_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='goals'").fetchone()
    if "replaced_by" not in goal_columns or not goal_sql or "superseded" not in goal_sql[0]:
        rebuild_table(db, "goals", GOAL_SCHEMA, (
            "id", "title", "horizon", "period", "function", "owner", "status", "tags", "created_on", "replaced_by",
        ))

    project_columns = tuple(row[1] for row in db.execute('PRAGMA table_info("projects")'))
    project_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='projects'").fetchone()
    if "replaces" not in project_columns or not project_sql or "superseded" not in project_sql[0]:
        rebuild_table(db, "projects", PROJECT_SCHEMA, (
            "id", "title", "result", "goal", "status", "function", "owner", "due", "page", "tags",
            "created_on", "extra", "description", "problem", "job_when", "job_want", "job_so", "done_when",
            "context", "ord", "program", "theme", "needs", "order_column", "span", "alongside", "replaces",
        ))

    present_tasks = {row[1] for row in db.execute('PRAGMA table_info("tasks")')}
    if not present_tasks:
        raise ValueError("work table is missing: tasks")
    for name, definition in TASK_COLUMNS:
        if name not in present_tasks:
            db.execute(f'ALTER TABLE "tasks" ADD COLUMN "{name}" {definition}')
    present_comments = {row[1] for row in db.execute('PRAGMA table_info("comments")')}
    for name, definition in COMMENT_COLUMNS:
        if present_comments and name not in present_comments:
            db.execute(f'ALTER TABLE "comments" ADD COLUMN "{name}" {definition}')
    for statement in statements(sql_path.read_text(encoding="utf-8")):
        db.execute(statement)
    present_runs = {row[1] for row in db.execute('PRAGMA table_info("runs")')}
    for name, definition in RUN_COLUMNS:
        if name not in present_runs:
            db.execute(f'ALTER TABLE "runs" ADD COLUMN "{name}" {definition}')
    present_tasks = {row[1] for row in db.execute('PRAGMA table_info("tasks")')}
    for name, definition in SIX_FIELD_TASK_COLUMNS:
        if name not in present_tasks:
            db.execute(f'ALTER TABLE "tasks" ADD COLUMN "{name}" {definition}')

    work_root = (Path(__file__).resolve().parent)
    for statement in statements(((Path(__file__).resolve().parent / 'apply.sql')).read_text(encoding="utf-8")):
        command = statement.lstrip("- \n\t").upper()
        if "BEGIN IMMEDIATE;" in command or command == "COMMIT;":
            continue
        db.execute(statement)
    present_bugs = {row[1] for row in db.execute('PRAGMA table_info("bugs")')}
    for name, definition in SIX_FIELD_BUG_COLUMNS:
        if present_bugs and name not in present_bugs:
            db.execute(f'ALTER TABLE "bugs" ADD COLUMN "{name}" {definition}')

    dictionary_path = (Path(__file__).resolve().parent / '../base/apply_dictionary.py')
    if {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('object_types','fields')"
    )} == {"object_types", "fields"}:
        spec = importlib.util.spec_from_file_location("work_additive_dictionary", dictionary_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("apply_dictionary.py could not be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.seed_current_schema(db, update_existing=False)


def blueprint_shape() -> tuple[dict[str, tuple[str, ...]], set[tuple[str, str]]]:
    blueprint = (Path(__file__).resolve().parent / 'blueprint.sql')
    with closing(_fox_person.connect(":memory:")) as expected:
        expected.executescript(blueprint.read_text(encoding="utf-8"))
        tables = {
            row[0]: tuple(item[1] for item in expected.execute(f'PRAGMA table_info("{row[0]}")'))
            for row in expected.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        }
        objects = {
            (row[0], row[1]) for row in expected.execute(
                "SELECT type,name FROM sqlite_master WHERE type IN ('view','index') AND name NOT LIKE 'sqlite_%'"
            )
        }
    return tables, objects


def verify_blueprint(db: sqlite3.Connection) -> dict:
    expected_tables, expected_objects = blueprint_shape()
    legacy_additions = {
        "programs": {"status", "canceled_reason"},
        "projects": {"canceled_reason"},
        "tasks": {"check_by", "canceled_reason", "folded_into", "problem", "job_when", "job_want", "job_so"},
        "activity": {"verb"},
        "bugs": {"tags", "problem", "job_when", "job_want", "job_so", "body", "acceptance", "context"},
    }
    expected_tables = {
        name: tuple(column for column in columns if column not in legacy_additions.get(name, set()) or column in {
            row[1] for row in db.execute(f'PRAGMA table_info("{name}")')
        })
        for name, columns in expected_tables.items()
    }
    missing_tables = []
    wrong_columns = []
    for table, columns in expected_tables.items():
        live = tuple(row[1] for row in db.execute(f'PRAGMA table_info("{table}")'))
        if not live:
            missing_tables.append(table)
        elif not set(columns).issubset(live):
            wrong_columns.append(table)
    live_objects = {
        (row[0], row[1]) for row in db.execute(
            "SELECT type,name FROM sqlite_master WHERE type IN ('view','index') AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing_objects = sorted(expected_objects - live_objects)
    if missing_tables or wrong_columns or missing_objects:
        raise ValueError(
            "blueprint verification failed: missing tables=" + ",".join(sorted(missing_tables))
            + "; wrong columns=" + ",".join(sorted(wrong_columns))
            + "; missing objects=" + ",".join(name for _, name in missing_objects)
        )
    quick = db.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        raise ValueError("quick_check failed: " + quick)
    return {
        "blueprint_tables": len(expected_tables),
        "blueprint_views": sum(kind == "view" for kind, _ in expected_objects),
        "blueprint_indexes": sum(kind == "index" for kind, _ in expected_objects),
        "quick_check": quick,
    }


def apply_schema(database: Path) -> None:
    if not database.is_file():
        raise ValueError("database must already exist: " + str(database))
    with closing(_fox_person.connect(database)) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN IMMEDIATE")
        try:
            apply_schema_to_connection(db)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")


from base.backups import (schema_snapshot, timestamped_backups, archive_old_backups,
                          make_backup_locked, newest_backup, restore)
import hashlib
import json
import shlex
import sys
from base import paths
DEFAULT_BACKUPS = paths.state() / 'backups/program-schema'

def read_state_connection(db: sqlite3.Connection) -> dict:
    tasks = {
        row[0]: {"status": row[1], "project": row[2], "title": row[3], "ord": row[4]}
        for row in db.execute("SELECT id,status,project,title,ord FROM tasks")
    }
    foreign_keys = {tuple(row) for row in db.execute("PRAGMA foreign_key_check")}
    quick = [row[0] for row in db.execute("PRAGMA quick_check")]
    blueprint_tables, _ = blueprint_shape()
    fingerprints = {}
    counts = {}
    columns = {}
    for table in blueprint_tables:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        columns[table] = tuple(row[1] for row in db.execute(f'PRAGMA table_info("{table}")'))
        rows = sorted(repr(tuple(row)) for row in db.execute(f'SELECT * FROM "{table}"'))
        fingerprints[table] = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
        counts[table] = len(rows)
    return {
        "tasks": tasks, "foreign_keys": foreign_keys, "quick": quick,
        "work_table_counts": counts, "work_table_columns": columns,
        "work_table_fingerprints": fingerprints,
    }

def verify_schema_only(db: sqlite3.Connection, before: dict, after: dict) -> dict:
    preserved_fingerprints = {}
    for table, columns in before["work_table_columns"].items():
        selected = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
        rows = sorted(repr(tuple(row)) for row in db.execute(f'SELECT {selected} FROM "{table}"'))
        preserved_fingerprints[table] = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    checks = {
        "preexisting_work_counts_same": before["work_table_counts"] == {
            table: after["work_table_counts"].get(table) for table in before["work_table_counts"]
        },
        "preexisting_work_rows_same": before["work_table_fingerprints"] == preserved_fingerprints,
        "no_new_foreign_key_findings": after["foreign_keys"].issubset(before["foreign_keys"]),
        "quick_check_ok": after["quick"] == ["ok"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("verification failed: " + ", ".join(failed))
    report = verify_blueprint(db)
    report.update({
        "before_work_table_counts": before["work_table_counts"],
        "after_work_table_counts": {
            table: after["work_table_counts"][table] for table in before["work_table_counts"]
        },
        "before_foreign_key_findings": len(before["foreign_keys"]),
        "after_foreign_key_findings": len(after["foreign_keys"]),
        "checks": checks,
    })
    return report

def safe_apply(database: Path, backup_dir: Path, receipt_root: Path | None = None) -> dict:
    if not database.is_file():
        raise ValueError("database must already exist: " + str(database))
    with closing(sqlite3.connect(database, timeout=0, isolation_level=None)) as db:
        if db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise ValueError("database uses WAL; checkpoint it before an exact backup")
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.execute("BEGIN EXCLUSIVE")
            before = read_state_connection(db)
            changes_before = db.total_changes
            schema_before = schema_snapshot(db)
            db.execute("SAVEPOINT preview")
            apply_schema_to_connection(db)
            preview_after = read_state_connection(db)
            verify_schema_only(db, before, preview_after)
            changed = (
                db.total_changes != changes_before
                or schema_snapshot(db) != schema_before
            )
            db.execute("ROLLBACK TO preview")
            db.execute("RELEASE preview")

            backup = None
            archived = archive_old_backups(database, backup_dir)
            if changed:
                backup = make_backup_locked(database, backup_dir, db)
                archived.extend(archive_old_backups(database, backup_dir))
                apply_schema_to_connection(db)
                after = read_state_connection(db)
                report = verify_schema_only(db, before, after)
            else:
                report = verify_schema_only(db, before, before)
            if db.in_transaction:
                db.execute("COMMIT")
        except sqlite3.OperationalError as error:
            if db.in_transaction:
                db.execute("ROLLBACK")
            if "locked" in str(error).lower():
                raise ValueError("database is locked; stop all workers and retry") from error
            raise
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")

    undo_backup = backup
    if undo_backup is None:
        matches = timestamped_backups(database, backup_dir)
        undo_backup = matches[0][1] if matches else None
    report["backup"] = str(backup) if backup else None
    report["backup_created"] = backup is not None
    report["archived_backups"] = archived
    undo_parts = ["python3", str((Path(__file__).resolve().parent / 'apply_program_schema.py')), "--db", str(database)]
    if receipt_root is not None:
        undo_parts.extend(("--receipt-root", str(receipt_root)))
    undo_parts.extend(("--backup-dir", str(backup_dir), "--undo", str(undo_backup)))
    report["undo_command"] = None if undo_backup is None else " ".join(shlex.quote(part) for part in undo_parts)
    return report

def export_after_write(database: Path, receipt_root: Path, errors) -> None:
    script = (Path(__file__).resolve().parent / '../base/backup.py')
    try:
        spec = importlib.util.spec_from_file_location("program_control_export_state", script)
        if spec is None or spec.loader is None:
            raise RuntimeError("backup.py could not be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.export_state(database, receipt_root / "state")
    except Exception as error:
        message = " ".join(str(error).splitlines())
        print("warning: state export failed: " + message, file=errors)

def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUPS)
    parser.add_argument("--undo")
    args = parser.parse_args(argv)
    database = args.db.expanduser().resolve()
    receipt_root = args.receipt_root.expanduser().resolve()
    backup_dir = args.backup_dir.expanduser().resolve()
    try:
        if args.undo:
            if args.undo == "latest":
                backup = newest_backup(database, backup_dir)
            else:
                backup = Path(args.undo).expanduser().resolve()
            restore(database, backup)
            export_after_write(database, receipt_root, sys.stderr)
            print("ok restored " + str(backup))
            return 0
        report = safe_apply(database, backup_dir, receipt_root)
        export_after_write(database, receipt_root, sys.stderr)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print("program apply failed; database unchanged: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
