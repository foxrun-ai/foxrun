#!/usr/bin/env python3
"""Audit proposed split-work relationships and guard explicit disposable copies."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from base.paths import resolve_portfolio_path
import sqlite3
import stat
import sys
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).resolve().parent / '../events'))
from history_actions import write_history, database_action


FORMAT = "foxrun-work-relationships/v1"
REFRESH_FORMAT = "foxrun-goal-mirror-refresh/v1"
REFRESH_GUARDS = (
    "goal_mirror_row_no_update",
    "goal_mirror_metadata_no_update",
)
ACTIVITY_COLUMNS = (
    "id", "subject_type", "subject_id", "field", "old_value", "new_value",
    "actor", "source", "at", "note",
)
ACTIVITY_SCHEMA = (
    ("id", "INTEGER", 0, None, 1),
    ("subject_type", "TEXT", 1, None, 0),
    ("subject_id", "TEXT", 1, None, 0),
    ("field", "TEXT", 0, None, 0),
    ("old_value", "TEXT", 0, None, 0),
    ("new_value", "TEXT", 0, None, 0),
    ("actor", "TEXT", 1, None, 0),
    ("source", "TEXT", 0, None, 0),
    ("at", "TEXT", 1, None, 0),
    ("note", "TEXT", 0, None, 0),
)

LINK_COLUMNS = (
    ("id", "INTEGER", 0, None, 1),
    ("subject_type", "TEXT", 1, None, 0),
    ("subject_id", "TEXT", 1, None, 0),
    ("original_task", "TEXT", 1, None, 0),
    ("system", "TEXT", 1, None, 0),
    ("scope", "TEXT", 0, None, 0),
    ("external_id", "TEXT", 1, None, 0),
    ("path", "TEXT", 0, None, 0),
    ("relation", "TEXT", 1, None, 0),
    ("active", "INTEGER", 1, None, 0),
    ("created_on", "TEXT", 1, None, 0),
    ("source_store", "TEXT", 1, None, 0),
    ("source_table", "TEXT", 1, None, 0),
    ("source_row_hash", "TEXT", 1, None, 0),
)

MIRROR_COLUMNS = (
    ("goal_id", "TEXT", 0, None, 1),
    ("source_store", "TEXT", 1, None, 0),
    ("source_hash", "TEXT", 1, None, 0),
    ("source_captured_at", "TEXT", 1, None, 0),
    ("mirror_created_at", "TEXT", 1, None, 0),
)

MIRROR_FOREIGN_KEYS = {
    ("goals", "goal_id", "id", "NO ACTION", "RESTRICT", "NONE"),
}

TABLE_SQL = {
    "goal_mirrors": """
        CREATE TABLE goal_mirrors (
          goal_id TEXT PRIMARY KEY REFERENCES goals(id) ON DELETE RESTRICT,
          source_store TEXT NOT NULL,
          source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
          source_captured_at TEXT NOT NULL,
          mirror_created_at TEXT NOT NULL
        )
    """,
    "links": """
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
        )
    """,
}

TRIGGERS = {
    "goal_mirror_row_no_update": """
        CREATE TRIGGER goal_mirror_row_no_update
        BEFORE UPDATE ON goals
        WHEN EXISTS (SELECT 1 FROM goal_mirrors WHERE goal_id=OLD.id)
        BEGIN SELECT RAISE(ABORT, 'goal mirror update refused'); END
    """,
    "goal_mirror_row_no_delete": """
        CREATE TRIGGER goal_mirror_row_no_delete
        BEFORE DELETE ON goals
        WHEN EXISTS (SELECT 1 FROM goal_mirrors WHERE goal_id=OLD.id)
        BEGIN SELECT RAISE(ABORT, 'goal mirror delete refused'); END
    """,
    "goal_mirror_metadata_no_update": """
        CREATE TRIGGER goal_mirror_metadata_no_update
        BEFORE UPDATE ON goal_mirrors
        BEGIN SELECT RAISE(ABORT, 'goal mirror metadata update refused'); END
    """,
    "goal_mirror_metadata_no_delete": """
        CREATE TRIGGER goal_mirror_metadata_no_delete
        BEFORE DELETE ON goal_mirrors
        BEGIN SELECT RAISE(ABORT, 'goal mirror metadata delete refused'); END
    """,
    "goal_mirror_metadata_no_insert": """
        CREATE TRIGGER goal_mirror_metadata_no_insert
        BEFORE INSERT ON goal_mirrors
        BEGIN SELECT RAISE(ABORT, 'goal mirror metadata insert refused'); END
    """,
    "goal_mirror_row_no_insert_replace": """
        CREATE TRIGGER goal_mirror_row_no_insert_replace
        BEFORE INSERT ON goals
        WHEN EXISTS (SELECT 1 FROM goal_mirrors WHERE goal_id=NEW.id)
        BEGIN SELECT RAISE(ABORT, 'goal mirror replace refused'); END
    """,
    "goal_mirror_destination_no_key_update": """
        CREATE TRIGGER goal_mirror_destination_no_key_update
        BEFORE UPDATE OF id ON goals
        WHEN NEW.id IS NOT OLD.id
          AND EXISTS (SELECT 1 FROM goal_mirrors WHERE goal_id=NEW.id)
        BEGIN SELECT RAISE(ABORT, 'goal mirror destination key change refused'); END
    """,
    "links_subject_insert": """
        CREATE TRIGGER links_subject_insert
        BEFORE INSERT ON links
        WHEN NEW.subject_type NOT IN ('goal','project')
          OR (NEW.subject_type='goal' AND NOT EXISTS (SELECT 1 FROM goals WHERE id=NEW.subject_id))
          OR (NEW.subject_type='project' AND NOT EXISTS (SELECT 1 FROM projects WHERE id=NEW.subject_id))
          OR NEW.active NOT IN (0,1)
          OR length(NEW.source_row_hash)<>64
          OR lower(NEW.source_row_hash)<>NEW.source_row_hash
          OR NEW.source_row_hash GLOB '*[^0-9a-f]*'
        BEGIN SELECT RAISE(ABORT, 'generic link subject invalid'); END
    """,
    "links_subject_update": """
        CREATE TRIGGER links_subject_update
        BEFORE UPDATE ON links
        WHEN NEW.subject_type NOT IN ('goal','project')
          OR (NEW.subject_type='goal' AND NOT EXISTS (SELECT 1 FROM goals WHERE id=NEW.subject_id))
          OR (NEW.subject_type='project' AND NOT EXISTS (SELECT 1 FROM projects WHERE id=NEW.subject_id))
          OR NEW.active NOT IN (0,1)
          OR length(NEW.source_row_hash)<>64
          OR lower(NEW.source_row_hash)<>NEW.source_row_hash
          OR NEW.source_row_hash GLOB '*[^0-9a-f]*'
        BEGIN SELECT RAISE(ABORT, 'generic link subject invalid'); END
    """,
    "links_goal_no_delete": """
        CREATE TRIGGER links_goal_no_delete
        BEFORE DELETE ON goals
        WHEN EXISTS (SELECT 1 FROM links WHERE subject_type='goal' AND subject_id=OLD.id)
        BEGIN SELECT RAISE(ABORT, 'linked goal delete refused'); END
    """,
    "links_goal_no_key_update": """
        CREATE TRIGGER links_goal_no_key_update
        BEFORE UPDATE OF id ON goals
        WHEN NEW.id IS NOT OLD.id
          AND EXISTS (SELECT 1 FROM links WHERE subject_type='goal' AND subject_id=OLD.id)
        BEGIN SELECT RAISE(ABORT, 'linked goal key change refused'); END
    """,
    "links_goal_destination_no_key_update": """
        CREATE TRIGGER links_goal_destination_no_key_update
        BEFORE UPDATE OF id ON goals
        WHEN NEW.id IS NOT OLD.id
          AND EXISTS (SELECT 1 FROM links WHERE subject_type='goal' AND subject_id=NEW.id)
        BEGIN SELECT RAISE(ABORT, 'linked goal destination key change refused'); END
    """,
    "links_goal_no_insert_replace": """
        CREATE TRIGGER links_goal_no_insert_replace
        BEFORE INSERT ON goals
        WHEN EXISTS (SELECT 1 FROM links WHERE subject_type='goal' AND subject_id=NEW.id)
        BEGIN SELECT RAISE(ABORT, 'linked goal replace refused'); END
    """,
    "links_project_no_delete": """
        CREATE TRIGGER links_project_no_delete
        BEFORE DELETE ON projects
        WHEN EXISTS (SELECT 1 FROM links WHERE subject_type='project' AND subject_id=OLD.id)
        BEGIN SELECT RAISE(ABORT, 'linked project delete refused'); END
    """,
    "links_project_no_key_update": """
        CREATE TRIGGER links_project_no_key_update
        BEFORE UPDATE OF id ON projects
        WHEN NEW.id IS NOT OLD.id
          AND EXISTS (SELECT 1 FROM links WHERE subject_type='project' AND subject_id=OLD.id)
        BEGIN SELECT RAISE(ABORT, 'linked project key change refused'); END
    """,
    "links_project_destination_no_key_update": """
        CREATE TRIGGER links_project_destination_no_key_update
        BEFORE UPDATE OF id ON projects
        WHEN NEW.id IS NOT OLD.id
          AND EXISTS (SELECT 1 FROM links WHERE subject_type='project' AND subject_id=NEW.id)
        BEGIN SELECT RAISE(ABORT, 'linked project destination key change refused'); END
    """,
    "links_project_no_insert_replace": """
        CREATE TRIGGER links_project_no_insert_replace
        BEFORE INSERT ON projects
        WHEN EXISTS (SELECT 1 FROM links WHERE subject_type='project' AND subject_id=NEW.id)
        BEGIN SELECT RAISE(ABORT, 'linked project replace refused'); END
    """,
}


class RelationshipError(ValueError):
    """The requested audit or guard installation is unsafe or unsupported."""


def canonical_json(value) -> bytes:
    def jsonable(item):
        if isinstance(item, bytes):
            return {"$blob": base64.b64encode(item).decode("ascii")}
        if isinstance(item, dict):
            return {str(key): jsonable(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [jsonable(child) for child in item]
        return item

    return json.dumps(
        jsonable(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def row_hash(row: sqlite3.Row) -> str:
    return hashlib.sha256(canonical_json(dict(row))).hexdigest()


def canonical_sql(value: str | None) -> str | None:
    """Normalize SQL tokens while preserving quoted identifier and literal bytes."""
    if value is None:
        return None
    result = []
    quote = None
    pending_space = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote is not None:
            result.append(character)
            if quote == "[":
                if character == "]":
                    quote = None
            elif character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    result.append(value[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if character in ("'", '"', "`"):
            if pending_space and result:
                result.append(" ")
            pending_space = False
            quote = character
            result.append(character)
        elif character == "[":
            if pending_space and result:
                result.append(" ")
            pending_space = False
            quote = "["
            result.append(character)
        elif character.isspace():
            pending_space = True
        else:
            if pending_space and result:
                result.append(" ")
            pending_space = False
            result.append(character.lower())
        index += 1
    if quote is not None:
        raise RelationshipError("schema SQL has an unterminated quoted value")
    return "".join(result).strip()


def canonical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def existing_database(path: Path) -> Path:
    try:
        path = resolve_portfolio_path(path)
    except ValueError as error:
        raise RelationshipError(str(error)) from error
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise RelationshipError("database path crosses a symlink: " + str(current))
    try:
        value = path.stat()
    except OSError as error:
        raise RelationshipError("database must already exist: " + str(path)) from error
    if not stat.S_ISREG(value.st_mode):
        raise RelationshipError("database is not a regular file: " + str(path))
    return path


def connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    path = existing_database(path)
    mode = "rw" if writable else "ro"
    uri = "file:" + quote(str(path), safe="/:@") + "?mode=" + mode
    db = _fox_person.connect(uri, uri=True, timeout=20, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RelationshipError("SQLite foreign-key enforcement is unavailable")
        if not writable:
            db.execute("PRAGMA query_only=ON")
        return db
    except Exception:
        db.close()
        raise


def table_columns(db: sqlite3.Connection, name: str) -> tuple[tuple, ...]:
    identifier = '"' + name.replace('"', '""') + '"'
    return tuple((row[1], row[2], row[3], row[4], row[5]) for row in db.execute(f"PRAGMA table_info({identifier})"))


def schema_findings(db: sqlite3.Connection) -> list[str]:
    findings = []
    if table_columns(db, "links") != LINK_COLUMNS:
        findings.append("links columns differ from the proposed schema")
    if table_columns(db, "goal_mirrors") != MIRROR_COLUMNS:
        findings.append("goal_mirrors columns differ from the proposed schema")
    links_fks = {
        (row[2], row[3], row[4], row[5], row[6], row[7])
        for row in db.execute('PRAGMA foreign_key_list("links")')
    }
    mirror_fks = {
        (row[2], row[3], row[4], row[5], row[6], row[7])
        for row in db.execute('PRAGMA foreign_key_list("goal_mirrors")')
    }
    if links_fks:
        findings.append("links has unsupported declared foreign keys")
    if mirror_fks != MIRROR_FOREIGN_KEYS:
        findings.append("goal_mirrors foreign key differs from the proposed schema")
    for table, expected_sql in TABLE_SQL.items():
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        actual = canonical_sql(str(row[0])) if row and row[0] else None
        if actual != canonical_sql(expected_sql):
            findings.append(table + " SQL differs from the exact proposed definition")
    for table in ("goals", "projects"):
        columns = table_columns(db, table)
        if not columns or columns[0][0:2] != ("id", "TEXT") or columns[0][4] != 1:
            findings.append(table + " lacks the expected text primary key")
    return findings


def trigger_state(db: sqlite3.Connection) -> dict:
    actual = {
        row[0]: row[1]
        for row in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")
        if row[0] in TRIGGERS
    }

    matching = sorted(name for name, sql in actual.items() if canonical_sql(sql) == canonical_sql(TRIGGERS[name]))
    conflicts = sorted(name for name, sql in actual.items() if canonical_sql(sql) != canonical_sql(TRIGGERS[name]))
    missing = sorted(set(TRIGGERS) - set(actual))
    return {"matching": matching, "missing": missing, "conflicts": conflicts, "complete": not missing and not conflicts}


def invariant_counts(db: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "unsupported_subject_type": "SELECT count(*) FROM links WHERE subject_type NOT IN ('goal','project')",
        "missing_goal_subject": "SELECT count(*) FROM links l LEFT JOIN goals g ON g.id=l.subject_id WHERE l.subject_type='goal' AND g.id IS NULL",
        "missing_project_subject": "SELECT count(*) FROM links l LEFT JOIN projects p ON p.id=l.subject_id WHERE l.subject_type='project' AND p.id IS NULL",
        "invalid_link_active": "SELECT count(*) FROM links WHERE active NOT IN (0,1)",
        "invalid_link_source_hash": "SELECT count(*) FROM links WHERE length(source_row_hash)<>64 OR lower(source_row_hash)<>source_row_hash OR source_row_hash GLOB '*[^0-9a-f]*'",
        "missing_mirror_goal": "SELECT count(*) FROM goal_mirrors m LEFT JOIN goals g ON g.id=m.goal_id WHERE g.id IS NULL",
        "invalid_mirror_source_hash": "SELECT count(*) FROM goal_mirrors WHERE length(source_hash)<>64 OR lower(source_hash)<>source_hash OR source_hash GLOB '*[^0-9a-f]*'",
    }
    return {name: int(db.execute(sql).fetchone()[0]) for name, sql in queries.items()}


def parse_sources(values: list[str]) -> dict[str, Path]:
    result = {}
    identities = set()
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or name in result:
            raise RelationshipError("source must be a unique NAME=/existing/database.sqlite binding")
        path = existing_database(Path(raw_path))
        identity = (path.stat().st_dev, path.stat().st_ino)
        if identity in identities:
            raise RelationshipError("two source names point to the same physical database")
        identities.add(identity)
        result[name] = path
    return result


def validate_sources(target: Path, sources: dict[str, Path]) -> dict[str, Path]:
    target = existing_database(target)
    target_identity = (target.stat().st_dev, target.stat().st_ino)
    result = {}
    identities = set()
    for name, raw_path in sources.items():
        if not isinstance(name, str) or not name or name in result:
            raise RelationshipError("source names must be unique nonempty strings")
        path = existing_database(Path(raw_path))
        identity = (path.stat().st_dev, path.stat().st_ino)
        if identity == target_identity:
            raise RelationshipError("a mirror source cannot be the target database or its hardlink")
        if identity in identities:
            raise RelationshipError("two source names point to the same physical database")
        identities.add(identity)
        result[name] = path
    return result


def mirror_freshness(db: sqlite3.Connection, sources: dict[str, Path]) -> dict:
    counts = {"fresh": 0, "stale": 0, "missing_source_goal": 0, "source_unavailable": 0, "non_authoritative_source": 0}
    opened = {}
    try:
        for name, path in sources.items():
            source = connect(path, writable=False)
            opened[name] = source
            source.execute("BEGIN")
        for mirror in db.execute("SELECT goal_id,source_store,source_hash FROM goal_mirrors ORDER BY goal_id"):
            local = db.execute("SELECT * FROM goals WHERE id=?", (mirror["goal_id"],)).fetchone()
            source = opened.get(mirror["source_store"])
            if source is None:
                counts["source_unavailable"] += 1
                continue
            has_mirror_table = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='goal_mirrors'"
            ).fetchone()
            if has_mirror_table and source.execute(
                "SELECT 1 FROM goal_mirrors WHERE goal_id=?", (mirror["goal_id"],)
            ).fetchone():
                counts["non_authoritative_source"] += 1
                continue
            authority = source.execute("SELECT * FROM goals WHERE id=?", (mirror["goal_id"],)).fetchone()
            if authority is None:
                counts["missing_source_goal"] += 1
                continue
            if local is not None and row_hash(local) == mirror["source_hash"] == row_hash(authority):
                counts["fresh"] += 1
            else:
                counts["stale"] += 1
    finally:
        for source in opened.values():
            try:
                if source.in_transaction:
                    source.rollback()
            finally:
                source.close()
    state = "fresh" if counts["fresh"] and not any(counts[name] for name in counts if name != "fresh") else "unknown"
    if counts["stale"] or counts["missing_source_goal"]:
        state = "stale"
    if counts["non_authoritative_source"] or counts["source_unavailable"]:
        state = "uncheckable"
    return {
        "state": state,
        "counts": counts,
        "blocking": bool(counts["stale"] or counts["missing_source_goal"] or (sources and (counts["source_unavailable"] or counts["non_authoritative_source"]))),
        "authentication": False,
        "evidence": "hash comparison across explicit per-store read snapshots; hashes do not authenticate a writer",
    }


def audit_connection(db: sqlite3.Connection, sources: dict[str, Path] | None = None) -> dict:
    schema = schema_findings(db)
    if schema:
        return {
            "format": FORMAT,
            "schema_valid": False,
            "schema_findings": schema,
            "invariants": {},
            "foreign_key_defects": None,
            "guards": trigger_state(db),
            "mirror_freshness": {"state": "uncheckable", "authentication": False, "evidence": "schema validation failed"},
        }
    invariants = invariant_counts(db)
    fk_defects = len(db.execute("PRAGMA foreign_key_check").fetchall())
    return {
        "format": FORMAT,
        "schema_valid": True,
        "schema_findings": [],
        "invariants": invariants,
        "foreign_key_defects": fk_defects,
        "guards": trigger_state(db),
        "mirror_freshness": mirror_freshness(db, sources or {}),
    }


def audit_database(path: Path, sources: dict[str, Path] | None = None) -> dict:
    path = existing_database(path)
    sources = validate_sources(path, sources or {})
    db = connect(path, writable=False)
    try:
        db.execute("BEGIN")
        try:
            report = audit_connection(db, sources)
            report["read_only"] = True
            report["database"] = str(path)
            return report
        finally:
            if db.in_transaction:
                db.rollback()
    finally:
        db.close()


def report_ok(report: dict) -> bool:
    return bool(
        report.get("schema_valid")
        and report.get("foreign_key_defects") == 0
        and not any(report.get("invariants", {}).values())
        and not report.get("guards", {}).get("conflicts")
        and not report.get("mirror_freshness", {}).get("blocking", report.get("mirror_freshness", {}).get("state") == "stale")
    )


def install_guards(path: Path, *, disposable_copy: bool) -> dict:
    if not disposable_copy:
        raise RelationshipError("guard installation requires the explicit --disposable-copy attestation")
    path = existing_database(path)
    db = connect(path, writable=True)
    try:
        try:
            db.execute("BEGIN IMMEDIATE")
            before = audit_connection(db)
            if before["guards"]["conflicts"]:
                raise RelationshipError("conflicting guard trigger definitions: " + ", ".join(before["guards"]["conflicts"]))
            if not report_ok(before):
                raise RelationshipError("database schema or existing relationships failed audit")
            installed = []
            for name in before["guards"]["missing"]:
                db.execute(TRIGGERS[name])
                installed.append(name)
            after = audit_connection(db)
            if not after["guards"]["complete"] or not report_ok(after):
                raise RelationshipError("post-install relationship audit failed")
            db.commit()
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
    finally:
        db.close()
    return {
        "format": FORMAT,
        "read_only": False,
        "database": str(path),
        "disposable_copy_attested": True,
        "installed": installed,
        "guards": after["guards"],
    }


def schema_digest(db: sqlite3.Connection) -> str:
    rows = [
        dict(row)
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    ]
    return hashlib.sha256(canonical_json(rows)).hexdigest()


def table_rows(db: sqlite3.Connection, name: str) -> list[dict]:
    quoted = '"' + name.replace('"', '""') + '"'
    columns = [row[1] for row in db.execute(f"PRAGMA table_info({quoted})")]
    if not columns:
        raise RelationshipError("table has no readable columns: " + name)
    primary = [
        row[1]
        for row in sorted(db.execute(f"PRAGMA table_info({quoted})"), key=lambda row: row[5])
        if row[5]
    ]
    order = ",".join('"' + column.replace('"', '""') + '"' for column in primary)
    if primary:
        query = f"SELECT * FROM {quoted} ORDER BY {order}"
        return [dict(row) for row in db.execute(query)]
    query = f"SELECT rowid AS __rowid__,* FROM {quoted} ORDER BY rowid"
    return [dict(row) for row in db.execute(query)]


def database_rows_state(db: sqlite3.Connection) -> dict[str, list[dict]]:
    names = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {name: table_rows(db, name) for name in names}


def rows_state_hashes(state: dict[str, list[dict]]) -> dict[str, str]:
    return {
        name: hashlib.sha256(canonical_json(rows)).hexdigest()
        for name, rows in sorted(state.items())
    }


def database_table_hashes(db: sqlite3.Connection) -> dict[str, str]:
    return rows_state_hashes(database_rows_state(db))


def physical_identity(path: Path) -> dict[str, int]:
    value = existing_database(path).stat()
    return {"device": value.st_dev, "inode": value.st_ino}


def activity_supported(db: sqlite3.Connection) -> bool:
    schema = table_columns(db, "activity")
    return schema == ACTIVITY_SCHEMA or schema == ACTIVITY_SCHEMA + (("verb", "TEXT", 0, None, 0),)


def source_authority_sha256(db: sqlite3.Connection) -> str:
    row = db.execute(
        "SELECT sql FROM sqlite_schema WHERE type='table' AND name='goal_mirrors'"
    ).fetchone()
    state = {"present": row is not None}
    if row is not None:
        state["definition"] = canonical_sql(row[0])
        state["rows"] = table_rows(db, "goal_mirrors")
    return hashlib.sha256(canonical_json(state)).hexdigest()


def maintenance_id(target: Path, captured_at: str, actions: list[dict]) -> str:
    material = {
        "target": str(target),
        "captured_at": captured_at,
        "actions": [
            {
                "goal_id": action["goal_id"],
                "source_store": action["source_store"],
                "target_before_hash": action["target_before_hash"],
                "source_hash": action["source_hash"],
            }
            for action in actions
        ],
    }
    return "goal-mirror-refresh:" + hashlib.sha256(canonical_json(material)).hexdigest()


def validate_captured_at(value: str) -> str:
    if not isinstance(value, str):
        raise RelationshipError("refresh capture time must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RelationshipError("refresh capture time must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RelationshipError("refresh capture time must include an offset")
    return value


def planned_receipts(
    target: sqlite3.Connection,
    target_path: Path,
    captured_at: str,
    actions: list[dict],
) -> list[dict]:
    if not actions or not activity_supported(target):
        return []
    next_id = int(target.execute("SELECT COALESCE(MAX(id),0)+1 FROM activity").fetchone()[0])
    batch_id = maintenance_id(target_path, captured_at, actions)
    has_verb = len(table_columns(target, "activity")) == len(ACTIVITY_SCHEMA) + 1
    return [
        {
            "id": next_id + index,
            "subject_type": "goal",
            "subject_id": action["goal_id"],
            "field": "mirror_source_hash",
            "old_value": action["target_before_hash"],
            "new_value": action["source_hash"],
            "actor": "work_relationships",
            "source": "mirror-maintenance",
            "at": captured_at,
            "note": "source-owned goal mirror refreshed; batch " + batch_id,
            **({'verb': database_action('goal', 'mirror_source_hash', action['target_before_hash'], action['source_hash'])} if has_verb else {}),
        }
        for index, action in enumerate(actions)
    ]


def _replace_row(rows: list[dict], key: str, value, replacement: dict) -> None:
    matches = [index for index, row in enumerate(rows) if row.get(key) == value]
    if len(matches) != 1:
        raise RelationshipError(f"planned row identity is not unique: {key}={value}")
    rows[matches[0]] = deepcopy(replacement)


def _plan_from_connections(
    target_path: Path,
    target: sqlite3.Connection,
    source_paths: dict[str, Path],
    source_connections: dict[str, sqlite3.Connection],
    captured_at: str,
) -> dict:
    validate_captured_at(captured_at)
    before_audit = audit_connection(target)
    if not report_ok(before_audit):
        raise RelationshipError("target schema or relationships failed audit")
    if not before_audit["guards"]["complete"]:
        raise RelationshipError("refresh planning requires every reviewed guard")

    target_goal_columns = table_columns(target, "goals")
    source_bindings = {}
    for name, source in source_connections.items():
        if table_columns(source, "goals") != target_goal_columns:
            raise RelationshipError("source goals schema differs from target: " + name)
        source_bindings[name] = {
            "path": str(source_paths[name]),
            "identity": physical_identity(source_paths[name]),
            "schema_sha256": schema_digest(source),
            "goals_sha256": hashlib.sha256(canonical_json(table_rows(source, "goals"))).hexdigest(),
            "authority_sha256": source_authority_sha256(source),
        }

    actions = []
    for mirror in target.execute("SELECT * FROM goal_mirrors ORDER BY goal_id"):
        source_name = mirror["source_store"]
        source = source_connections.get(source_name)
        if source is None:
            raise RelationshipError("missing source binding for mirror: " + source_name)
        if source.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='goal_mirrors'"
        ).fetchone() and source.execute(
            "SELECT 1 FROM goal_mirrors WHERE goal_id=?", (mirror["goal_id"],)
        ).fetchone():
            raise RelationshipError("mirror source is not authoritative for goal: " + mirror["goal_id"])
        source_goal = source.execute("SELECT * FROM goals WHERE id=?", (mirror["goal_id"],)).fetchone()
        target_goal = target.execute("SELECT * FROM goals WHERE id=?", (mirror["goal_id"],)).fetchone()
        if source_goal is None:
            raise RelationshipError("source goal is missing: " + mirror["goal_id"])
        if target_goal is None:
            raise RelationshipError("target mirror goal is missing: " + mirror["goal_id"])
        source_hash = row_hash(source_goal)
        target_hash = row_hash(target_goal)
        if target_hash == source_hash == mirror["source_hash"]:
            continue
        mirror_before = dict(mirror)
        mirror_after = dict(mirror)
        mirror_after["source_hash"] = source_hash
        mirror_after["source_captured_at"] = captured_at
        actions.append({
            "goal_id": mirror["goal_id"],
            "source_store": source_name,
            "target_before_hash": target_hash,
            "recorded_before_source_hash": mirror["source_hash"],
            "source_hash": source_hash,
            "target_before_row": dict(target_goal),
            "source_row": dict(source_goal),
            "mirror_before_row": mirror_before,
            "mirror_after_row": mirror_after,
        })

    before_rows = database_rows_state(target)
    after_rows = deepcopy(before_rows)
    for action in actions:
        _replace_row(after_rows["goals"], "id", action["goal_id"], action["source_row"])
        _replace_row(after_rows["goal_mirrors"], "goal_id", action["goal_id"], action["mirror_after_row"])

    receipts = planned_receipts(target, target_path, captured_at, actions)
    if receipts:
        after_rows["activity"].extend(deepcopy(receipts))
        after_rows["activity"].sort(key=lambda row: row["id"])

    plan = {
        "format": REFRESH_FORMAT,
        "captured_at": captured_at,
        "source_snapshots": "independent read transactions; not cross-store atomic",
        "authentication": False,
        "target": {
            "path": str(target_path),
            "identity": physical_identity(target_path),
            "schema_sha256": schema_digest(target),
            "before_table_sha256": rows_state_hashes(before_rows),
            "after_table_sha256": rows_state_hashes(after_rows),
        },
        "sources": source_bindings,
        "actions": actions,
        "receipts": receipts,
    }
    plan["plan_sha256"] = refresh_plan_digest(plan)
    return plan


def refresh_plan_digest(plan: dict) -> str:
    unsigned = deepcopy(plan)
    unsigned.pop("plan_sha256", None)
    return hashlib.sha256(canonical_json(unsigned)).hexdigest()


def create_refresh_plan(
    target_path: Path,
    sources: dict[str, Path],
    *,
    captured_at: str | None = None,
) -> dict:
    target_path = existing_database(target_path)
    sources = validate_sources(target_path, sources)
    captured_at = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_connections = {}
    target = None
    try:
        for name, path in sources.items():
            source = connect(path, writable=False)
            source.execute("BEGIN")
            source_connections[name] = source
        target = connect(target_path, writable=False)
        target.execute("BEGIN")
        return _plan_from_connections(target_path, target, sources, source_connections, captured_at)
    finally:
        if target is not None:
            try:
                if target.in_transaction:
                    target.rollback()
            finally:
                target.close()
        for source in source_connections.values():
            try:
                if source.in_transaction:
                    source.rollback()
            finally:
                source.close()


def write_private_plan(path: Path, plan: dict) -> Path:
    try:
        path = resolve_portfolio_path(path)
    except ValueError as error:
        raise RelationshipError(str(error)) from error
    if not path.is_absolute() or path.suffix != ".json":
        raise RelationshipError("plan output must be an absolute JSON path")
    parent = path.parent
    current = Path(parent.anchor)
    for part in parent.parts[1:]:
        current /= part
        if current.is_symlink():
            raise RelationshipError("plan output path crosses a symlink: " + str(current))
    if not parent.is_dir():
        raise RelationshipError("plan output parent must be an existing non-symlink directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        data = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return path


def load_refresh_plan(path: Path, expected_sha256: str) -> dict:
    path = existing_database(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise RelationshipError("refresh plan exceeds the size limit")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RelationshipError("refresh plan is not valid UTF-8 JSON") from error
    if not isinstance(plan, dict) or plan.get("format") != REFRESH_FORMAT:
        raise RelationshipError("unsupported refresh plan format")
    validate_captured_at(plan.get("captured_at"))
    actual = refresh_plan_digest(plan)
    if plan.get("plan_sha256") != actual or expected_sha256 != actual:
        raise RelationshipError("refresh plan digest does not match exact confirmation")
    required = {
        "format", "captured_at", "source_snapshots", "authentication", "target",
        "sources", "actions", "receipts", "plan_sha256",
    }
    if set(plan) != required or not isinstance(plan["actions"], list) or len(plan["actions"]) > 1000:
        raise RelationshipError("refresh plan structure is unsupported")
    if not isinstance(plan["sources"], dict) or not plan["sources"]:
        raise RelationshipError("refresh plan has no source bindings")
    return plan


def _assert_identity(path: Path, expected: dict, label: str) -> None:
    if physical_identity(path) != expected:
        raise RelationshipError(label + " physical identity changed")


def _validate_action(action: dict, source_row: sqlite3.Row, target_row: sqlite3.Row, mirror_row: sqlite3.Row) -> None:
    required = {
        "goal_id", "source_store", "target_before_hash", "recorded_before_source_hash",
        "source_hash", "target_before_row", "source_row", "mirror_before_row", "mirror_after_row",
    }
    if not isinstance(action, dict) or set(action) != required:
        raise RelationshipError("refresh action structure is unsupported")
    goal_id = action["goal_id"]
    if action["source_row"].get("id") != goal_id or action["target_before_row"].get("id") != goal_id:
        raise RelationshipError("refresh action changes a stable goal ID")
    if action["mirror_before_row"].get("goal_id") != goal_id or action["mirror_after_row"].get("goal_id") != goal_id:
        raise RelationshipError("refresh action changes a stable mirror ID")
    if action["source_store"] != mirror_row["source_store"]:
        raise RelationshipError("refresh action changes the mirror source authority")
    if row_hash(source_row) != action["source_hash"] or dict(source_row) != action["source_row"]:
        raise RelationshipError("source goal changed after planning: " + str(goal_id))
    if row_hash(target_row) != action["target_before_hash"] or dict(target_row) != action["target_before_row"]:
        raise RelationshipError("target goal changed after planning: " + str(goal_id))
    if dict(mirror_row) != action["mirror_before_row"]:
        raise RelationshipError("target mirror metadata changed after planning: " + str(goal_id))
    expected_mirror = dict(mirror_row)
    expected_mirror["source_hash"] = action["source_hash"]
    expected_mirror["source_captured_at"] = action["mirror_after_row"].get("source_captured_at")
    if expected_mirror != action["mirror_after_row"]:
        raise RelationshipError("refresh action changes unsupported mirror metadata")
    if action["recorded_before_source_hash"] != mirror_row["source_hash"]:
        raise RelationshipError("recorded mirror hash changed after planning")


def _receipts_match(db: sqlite3.Connection, receipts: list[dict]) -> bool:
    return all(
        (row := db.execute("SELECT * FROM activity WHERE id=?", (receipt["id"],)).fetchone()) is not None
        and dict(row) == receipt
        for receipt in receipts
    )


def _assert_plan_identities(plan: dict, target_path: Path, sources: dict[str, Path]) -> None:
    _assert_identity(target_path, plan["target"]["identity"], "target")
    for name, path in sources.items():
        _assert_identity(path, plan["sources"][name]["identity"], "source " + name)


def apply_refresh_plan(
    plan_path: Path,
    expected_sha256: str,
    *,
    disposable_copy: bool,
    failure_hook=None,
) -> dict:
    if not disposable_copy:
        raise RelationshipError("refresh application requires the explicit --disposable-copy attestation")
    plan = load_refresh_plan(plan_path, expected_sha256)
    target_path = existing_database(Path(plan["target"]["path"]))
    raw_sources = {name: Path(binding["path"]) for name, binding in plan["sources"].items()}
    sources = validate_sources(target_path, raw_sources)
    _assert_plan_identities(plan, target_path, sources)
    source_connections = {}
    target = None
    committed = False
    replayed = False
    try:
        for name, path in sources.items():
            _assert_identity(path, plan["sources"][name]["identity"], "source " + name)
            source = connect(path, writable=False)
            source.execute("BEGIN")
            source_connections[name] = source
            if schema_digest(source) != plan["sources"][name]["schema_sha256"]:
                raise RelationshipError("source schema changed after planning: " + name)
            if hashlib.sha256(canonical_json(table_rows(source, "goals"))).hexdigest() != plan["sources"][name]["goals_sha256"]:
                raise RelationshipError("source goals changed after planning: " + name)
            if source_authority_sha256(source) != plan["sources"][name]["authority_sha256"]:
                raise RelationshipError("source authority metadata changed after planning: " + name)

        target = connect(target_path, writable=True)
        target.execute("BEGIN IMMEDIATE")
        if failure_hook:
            failure_hook("after_target_begin", target)
        _assert_plan_identities(plan, target_path, sources)
        audit = audit_connection(target)
        if not report_ok(audit) or not audit["guards"]["complete"]:
            raise RelationshipError("target schema, relationships, or guards failed audit")
        if schema_digest(target) != plan["target"]["schema_sha256"]:
            raise RelationshipError("target schema changed after planning")
        current_hashes = database_table_hashes(target)
        if current_hashes == plan["target"]["after_table_sha256"]:
            if not _receipts_match(target, plan["receipts"]):
                raise RelationshipError("refresh after-state lacks its exact maintenance receipts")
            _assert_plan_identities(plan, target_path, sources)
            replayed = True
            target.rollback()
            return {
                "format": REFRESH_FORMAT, "applied": False, "replayed": True,
                "action_count": len(plan["actions"]), "plan_sha256": expected_sha256,
            }
        if current_hashes != plan["target"]["before_table_sha256"]:
            raise RelationshipError("target rows changed after planning")

        current_rows = database_rows_state(target)
        expected_after = deepcopy(current_rows)
        seen_goal_ids = set()
        for action in plan["actions"]:
            source = source_connections.get(action.get("source_store"))
            if source is None:
                raise RelationshipError("refresh action lacks a bound source")
            if source.execute(
                "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='goal_mirrors'"
            ).fetchone() and source.execute(
                "SELECT 1 FROM goal_mirrors WHERE goal_id=?", (action.get("goal_id"),)
            ).fetchone():
                raise RelationshipError("refresh source is mirrored, not authoritative")
            source_row = source.execute("SELECT * FROM goals WHERE id=?", (action.get("goal_id"),)).fetchone()
            target_row = target.execute("SELECT * FROM goals WHERE id=?", (action.get("goal_id"),)).fetchone()
            mirror_row = target.execute("SELECT * FROM goal_mirrors WHERE goal_id=?", (action.get("goal_id"),)).fetchone()
            if source_row is None or target_row is None or mirror_row is None:
                raise RelationshipError("planned source or target goal is missing")
            _validate_action(action, source_row, target_row, mirror_row)
            if action["goal_id"] in seen_goal_ids:
                raise RelationshipError("refresh plan repeats a goal ID")
            seen_goal_ids.add(action["goal_id"])
            _replace_row(expected_after["goals"], "id", action["goal_id"], action["source_row"])
            _replace_row(expected_after["goal_mirrors"], "goal_id", action["goal_id"], action["mirror_after_row"])
        if plan["receipts"] != planned_receipts(target, target_path, plan["captured_at"], plan["actions"]):
            raise RelationshipError("maintenance receipts differ from the exact refresh semantics")
        if plan["receipts"]:
            if not activity_supported(target):
                raise RelationshipError("planned activity receipt schema is unavailable")
            expected_after["activity"].extend(deepcopy(plan["receipts"]))
            expected_after["activity"].sort(key=lambda row: row["id"])
        if rows_state_hashes(expected_after) != plan["target"]["after_table_sha256"]:
            raise RelationshipError("refresh plan after-state is not semantically valid")

        guard_sql = {}
        for name in REFRESH_GUARDS:
            row = target.execute("SELECT sql FROM sqlite_schema WHERE type='trigger' AND name=?", (name,)).fetchone()
            if row is None or canonical_sql(row[0]) != canonical_sql(TRIGGERS[name]):
                raise RelationshipError("required refresh guard is missing or conflicting: " + name)
            guard_sql[name] = row[0]
        for name in REFRESH_GUARDS:
            target.execute(f'DROP TRIGGER "{name}"')
        if failure_hook:
            failure_hook("after_guard_drop", target)

        goal_columns = [row[1] for row in target.execute('PRAGMA table_info("goals")')]
        update_columns = [column for column in goal_columns if column != "id"]
        assignment = ",".join('"' + column.replace('"', '""') + '"=?' for column in update_columns)
        for action in plan["actions"]:
            target.execute(
                f'UPDATE goals SET {assignment} WHERE id=?',
                tuple(action["source_row"][column] for column in update_columns) + (action["goal_id"],),
            )
            target.execute(
                "UPDATE goal_mirrors SET source_hash=?,source_captured_at=? WHERE goal_id=?",
                (action["source_hash"], action["mirror_after_row"]["source_captured_at"], action["goal_id"]),
            )
        for receipt in plan["receipts"]:
            write_history(target, receipt['subject_type'], receipt['subject_id'], receipt['field'],
                          receipt['old_value'], receipt['new_value'], receipt['actor'], receipt['source'],
                          receipt['at'], receipt['note'], row_id=receipt['id'], known_field=True)
        if failure_hook:
            failure_hook("before_guard_restore", target)
        for name in REFRESH_GUARDS:
            target.execute(guard_sql[name])
        if failure_hook:
            failure_hook("before_validation", target)

        final_audit = audit_connection(target)
        if not report_ok(final_audit) or not final_audit["guards"]["complete"]:
            raise RelationshipError("post-refresh relationship audit failed")
        if schema_digest(target) != plan["target"]["schema_sha256"]:
            raise RelationshipError("refresh did not restore the exact guarded schema")
        if database_table_hashes(target) != plan["target"]["after_table_sha256"]:
            raise RelationshipError("refresh result differs from the exact plan")
        if failure_hook:
            failure_hook("before_commit_identity_check", target)
        _assert_plan_identities(plan, target_path, sources)
        target.commit()
        committed = True
    except Exception:
        if target is not None and target.in_transaction:
            target.rollback()
        raise
    finally:
        if target is not None:
            target.close()
        for source in source_connections.values():
            try:
                if source.in_transaction:
                    source.rollback()
            finally:
                source.close()
    return {
        "format": REFRESH_FORMAT, "applied": committed, "replayed": replayed,
        "action_count": len(plan["actions"]), "plan_sha256": expected_sha256,
        "receipt_count": len(plan["receipts"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="explicit existing SQLite database")
    parser.add_argument("--source", action="append", default=[], metavar="NAME=PATH", help="explicit read-only mirror source")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true", help="install reviewed guards on an explicit disposable copy")
    mode.add_argument("--plan-refresh", type=Path, metavar="PRIVATE.json", help="create an exact read-only refresh plan")
    mode.add_argument("--apply-refresh", type=Path, metavar="PRIVATE.json", help="apply an exact refresh plan")
    parser.add_argument("--plan-sha256", help="exact externally retained refresh plan digest")
    parser.add_argument("--disposable-copy", action="store_true", help="attest that --db is a disposable copy")
    args = parser.parse_args(argv)
    try:
        sources = parse_sources(args.source)
        if args.apply_refresh:
            if args.db or sources:
                raise RelationshipError("--apply-refresh uses only the target and sources sealed in its plan")
            if not args.plan_sha256:
                raise RelationshipError("--apply-refresh requires --plan-sha256")
            report = apply_refresh_plan(
                args.apply_refresh,
                args.plan_sha256,
                disposable_copy=args.disposable_copy,
            )
            exit_code = 0
        elif args.plan_refresh:
            if not args.db:
                raise RelationshipError("--plan-refresh requires --db")
            if args.disposable_copy or args.plan_sha256:
                raise RelationshipError("planning is read-only and does not accept apply attestations")
            plan = create_refresh_plan(args.db, sources)
            output = write_private_plan(args.plan_refresh, plan)
            report = {
                "format": REFRESH_FORMAT,
                "read_only": True,
                "plan": str(output),
                "plan_sha256": plan["plan_sha256"],
                "action_count": len(plan["actions"]),
                "source_count": len(plan["sources"]),
                "private_details_omitted": True,
            }
            exit_code = 0
        elif args.install:
            if not args.db:
                raise RelationshipError("--install requires --db")
            if sources:
                raise RelationshipError("--source is audit-only")
            if args.plan_sha256:
                raise RelationshipError("--plan-sha256 is valid only with --apply-refresh")
            report = install_guards(args.db, disposable_copy=args.disposable_copy)
            exit_code = 0
        else:
            if not args.db:
                raise RelationshipError("audit requires --db")
            if args.disposable_copy:
                raise RelationshipError("--disposable-copy is valid only with a write mode")
            if args.plan_sha256:
                raise RelationshipError("--plan-sha256 is valid only with --apply-refresh")
            report = audit_database(args.db, sources)
            exit_code = 0 if report_ok(report) else 1
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    except (OSError, sqlite3.Error, RelationshipError) as error:
        print("Work relationship check failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
