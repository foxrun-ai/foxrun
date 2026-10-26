"""Reusable SQLite backup and exact restore helpers."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
from pathlib import Path
from datetime import datetime
from contextlib import closing
from urllib.parse import quote
import json, os, sqlite3, subprocess, tempfile
BACKUP_STAMP = "%Y%m%dT%H%M%S%f%z"

def schema_snapshot(db: sqlite3.Connection) -> list[tuple]:
    return [tuple(row) for row in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    )]


def timestamped_backups(database: Path, backup_dir: Path) -> list[tuple[datetime, Path]]:
    prefix = database.stem + "-"
    matches = []
    for path in backup_dir.glob(prefix + "*.sqlite"):
        stamp = path.name[len(prefix):-len(".sqlite")]
        try:
            matches.append((datetime.strptime(stamp, BACKUP_STAMP), path))
        except ValueError:
            continue
    return sorted(matches, key=lambda item: item[0], reverse=True)


def archive_old_backups(database: Path, backup_dir: Path) -> list[str]:
    archived = []
    old = timestamped_backups(database, backup_dir)[5:]
    if not old:
        return archived
    archive = backup_dir / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    for _, path in old:
        target = archive / path.name
        if target.exists():
            raise ValueError("backup archive target already exists: " + str(target))
        path.replace(target)
        archived.append(str(target))
    return archived


def make_backup_locked(database: Path, backup_dir: Path, db: sqlite3.Connection) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime(BACKUP_STAMP)
    backup = backup_dir / f"{database.stem}-{stamp}.sqlite"
    if backup.exists():
        raise ValueError("backup already exists: " + str(backup))
    if not db.in_transaction:
        raise ValueError("backup requires the active apply lock")
    data_version = db.execute("PRAGMA data_version").fetchone()[0]
    before_schema = schema_snapshot(db)
    db.execute("ROLLBACK")
    # sqlite3 .backup opens its target by name and follows links. Write it inside a new private folder
    # (mkdtemp: 0700, unique, never a planted path), then move it into place (T750 F07).
    staging = Path(tempfile.mkdtemp(prefix="." + backup.name + ".", dir=str(backup_dir)))
    partial = staging / "partial.sqlite"
    try:
        command = '.backup ' + json.dumps(str(partial))
        result = subprocess.run(
            ["sqlite3", "-cmd", ".timeout 0", str(database), command],
            text=True, capture_output=True, check=False,
        )
        if result.returncode != 0:
            message = " ".join((result.stderr or result.stdout).splitlines())
            if "locked" in message.lower():
                raise ValueError("database is locked; stop all workers and retry")
            raise ValueError("sqlite backup failed: " + message)
        with closing(_fox_person.connect(partial.as_uri() + "?mode=ro", uri=True)) as check:
            if check.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("backup quick_check failed: " + str(partial))
        os.chmod(partial, 0o600)
        os.replace(partial, backup)
        db.execute("BEGIN EXCLUSIVE")
        if db.execute("PRAGMA data_version").fetchone()[0] != data_version or schema_snapshot(db) != before_schema:
            db.execute("ROLLBACK")
            raise ValueError("database changed during backup; retry")
    finally:
        partial.unlink(missing_ok=True)
        for leftover in staging.iterdir():
            leftover.unlink()
        staging.rmdir()
    return backup


def restore(database: Path, backup: Path) -> None:
    if not database.is_file():
        raise ValueError("database must already exist: " + str(database))
    if not backup.is_file():
        raise ValueError("backup does not exist: " + str(backup))
    with closing(_fox_person.connect("file:" + quote(str(backup), safe="/:@") + "?mode=ro", uri=True)) as source:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("backup quick_check failed: " + str(backup))
    descriptor, temporary = tempfile.mkstemp(prefix="." + database.name + ".restore-", dir=database.parent)
    os.close(descriptor)
    replacement = Path(temporary)
    target = None
    incoming = None
    try:
        replacement.unlink()
        command = '.backup ' + json.dumps(str(replacement))
        result = subprocess.run(
            ["sqlite3", "-cmd", ".timeout 0", str(backup), command],
            text=True, capture_output=True, check=False,
        )
        if result.returncode != 0:
            raise ValueError("sqlite restore staging failed: " + " ".join((result.stderr or result.stdout).splitlines()))
        target = _fox_person.connect(database, timeout=0, isolation_level=None)
        if target.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise ValueError("database uses WAL; checkpoint it before an exact restore")
        target.execute("BEGIN EXCLUSIVE")
        incoming = _fox_person.connect(replacement, timeout=0, isolation_level=None)
        incoming.execute("BEGIN EXCLUSIVE")
        os.replace(replacement, database)
        target.execute("ROLLBACK")
        target.close()
        target = None
        incoming.execute("ROLLBACK")
        incoming.close()
        incoming = None
    except sqlite3.OperationalError as error:
        if "locked" in str(error).lower():
            raise ValueError("database is locked; stop all workers and retry") from error
        raise
    finally:
        if target is not None:
            target.close()
        if incoming is not None:
            incoming.close()
        try:
            replacement.unlink()
        except FileNotFoundError:
            pass


def newest_backup(database: Path, backup_dir: Path) -> Path:
    matches = timestamped_backups(database, backup_dir)
    if not matches:
        raise ValueError("no timestamped backup found for " + database.name)
    return matches[0][1]
