#!/usr/bin/env python3
"""Back up, install, verify, export, or undo incident and bug tables."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_sys.path.insert(0, str(_FoxPath(__file__).resolve().parent / '..'))
from base import paths as _fox_paths

import argparse
import importlib.util
import json
import shlex
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

TOOLS = (Path(__file__).resolve().parent)
BASE_TOOLS = (Path(__file__).resolve().parent / '../base')
if str(BASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(BASE_TOOLS))

import apply_dictionary  # noqa: E402
from backups import (  # noqa: E402
    archive_old_backups,
    make_backup_locked,
    newest_backup,
    restore,
    schema_snapshot,
    timestamped_backups,
)

SCHEMA = (Path(__file__).resolve().parent / 'apply-incidents.sql')
DEFAULT_BACKUPS = _fox_paths.state() / 'backups/incidents'
EXPECTED = {
    "bugs": ("id", "title", "description", "capability", "status", "reports", "created_on"),
    "incidents": ("id", "title", "started_at", "ended_at", "impact", "restored_by", "status", "rca_cause", "bug", "created_on", "source"),
    "record_links": ("id", "subject_type", "subject_id", "target_type", "target_id", "relation"),
}


def install(db: sqlite3.Connection) -> None:
    apply_dictionary.apply_sql_file(db, SCHEMA)
    apply_dictionary.install_dictionary(db)


# T718 adds the six fields and tags to bugs; either shape is a known shape.
BUG_FIELD_COLUMNS = ("tags", "problem", "job_when", "job_want", "job_so", "body", "acceptance", "context")


def verify(db: sqlite3.Connection, prior_foreign_keys: set[tuple]) -> dict:
    for table, columns in EXPECTED.items():
        live = tuple(row[1] for row in db.execute(f'PRAGMA table_info("{table}")'))
        if table == "bugs" and live == columns + BUG_FIELD_COLUMNS:
            columns = live
        if live != columns:
            raise ValueError("incident schema verification failed: " + table)
        described = tuple(row[0] for row in db.execute(
            "SELECT field FROM fields WHERE object_type=? ORDER BY ordinal", (table,)
        ))
        if described != columns:
            raise ValueError("dictionary verification failed: " + table)
    foreign_keys = {tuple(row) for row in db.execute("PRAGMA foreign_key_check")}
    if not foreign_keys.issubset(prior_foreign_keys):
        raise ValueError("incident schema added foreign-key findings")
    quick = db.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        raise ValueError("quick_check failed: " + quick)
    return {
        "incidents": db.execute("SELECT count(*) FROM incidents").fetchone()[0],
        "bugs": db.execute("SELECT count(*) FROM bugs").fetchone()[0],
        "record_links": db.execute("SELECT count(*) FROM record_links").fetchone()[0],
        "quick_check": quick,
        "foreign_key_findings": len(foreign_keys),
    }


def apply(database: Path, backup_dir: Path, receipt_root: Path | None = None) -> dict:
    if not database.is_file():
        raise ValueError("database must already exist: " + str(database))
    with closing(_fox_person.connect(database, timeout=0, isolation_level=None)) as db:
        if db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise ValueError("database uses WAL; checkpoint it before an exact backup")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN EXCLUSIVE")
            prior_foreign_keys = {tuple(row) for row in db.execute("PRAGMA foreign_key_check")}
            before = schema_snapshot(db)
            changes = db.total_changes
            db.execute("SAVEPOINT preview")
            install(db)
            preview = verify(db, prior_foreign_keys)
            changed = schema_snapshot(db) != before or db.total_changes != changes
            db.execute("ROLLBACK TO preview")
            db.execute("RELEASE preview")
            backup = None
            archived = archive_old_backups(database, backup_dir)
            if changed:
                backup = make_backup_locked(database, backup_dir, db)
                archived.extend(archive_old_backups(database, backup_dir))
                install(db)
                report = verify(db, prior_foreign_keys)
            else:
                report = preview
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
    latest = backup or (timestamped_backups(database, backup_dir)[0][1] if timestamped_backups(database, backup_dir) else None)
    undo_parts = ["python3", str((Path(__file__).resolve().parent / 'apply_incidents.py')), "--db", str(database)]
    if receipt_root is not None:
        undo_parts.extend(("--receipt-root", str(receipt_root)))
    if latest is not None:
        undo_parts.extend(("--backup-dir", str(backup_dir), "--undo", str(latest)))
    report.update({
        "backup": str(backup) if backup else None,
        "backup_created": backup is not None,
        "archived_backups": archived,
        "undo_command": None if latest is None else " ".join(shlex.quote(part) for part in undo_parts),
    })
    return report


def export_after_write(database: Path, receipt_root: Path) -> None:
    script = (Path(__file__).resolve().parent / '../base/backup.py')
    spec = importlib.util.spec_from_file_location("incident_export_state", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("backup.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.export_state(database, receipt_root / "state")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUPS)
    parser.add_argument("--undo")
    args = parser.parse_args(argv)
    database = args.db.expanduser().resolve()
    receipt_root = args.receipt_root.expanduser().resolve()
    backups = args.backup_dir.expanduser().resolve()
    try:
        if args.undo:
            backup = newest_backup(database, backups) if args.undo == "latest" else Path(args.undo).expanduser().resolve()
            restore(database, backup)
            export_after_write(database, receipt_root)
            print("ok restored " + str(backup))
            return 0
        report = apply(database, backups, receipt_root)
        export_after_write(database, receipt_root)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print("incident apply failed; database unchanged: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
