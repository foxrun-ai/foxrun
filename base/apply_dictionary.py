#!/usr/bin/env python3
"""Back up, install, seed, verify, and export the tracker data dictionary."""

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
import re
import shlex
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


TOOLS = (Path(__file__).resolve().parent)
BASE = (Path(__file__).resolve().parent)
WORK_TOOLS = (Path(__file__).resolve().parent / '../work')
if str(WORK_TOOLS) not in sys.path:
    sys.path.insert(0, str(WORK_TOOLS))

if str(BASE) not in sys.path:
    # backups.py sits beside this file. Without this line a caller whose path starts at the system home
    # imports the backups/ folder there instead (T712).
    sys.path.insert(0, str(BASE))

from backups import (  # noqa: E402
    archive_old_backups,
    make_backup_locked,
    newest_backup,
    restore,
    schema_snapshot,
    timestamped_backups,
)


DEFAULT_BACKUPS = _fox_paths.state() / 'backups/dictionary'
DICTIONARY_SQL = (Path(__file__).resolve().parent / 'dictionary.sql')
DICTIONARY_SEED = (Path(__file__).resolve().parent / 'dictionary-seed.sql')

CURRENT_OBJECTS = {
    "programs": ("records", "A program is one large initiative. It groups themes and work streams."),
    "themes": ("records", "A theme is a lasting topic. The tracker links it to the current program."),
    "projects": ("records", "A project is one finite result. Inside a program, its label is work stream."),
    "tasks": ("records", "A task is one unit of work. It can stand alone or belong to a project."),
    "runs": ("history", "A run records one agent execution. It links the execution to its subject and evidence."),
    "decisions": ("records", "A decision records a choice and its standing. A new decision can replace an earlier decision."),
    "approvals": ("history", f"An approval records {_fox_person.display_name()}'s response to an exact version. It does not send or apply the work."),
    "functions": ("records", "A function is an ongoing area of responsibility. It can contain a subfunction."),
    "goals": ("records", "A goal is an owned target for a stated period. A newer goal can replace it."),
    "comments": ("history", "A comment adds discussion to one record. A comment can reply to another comment."),
    "activity": ("history", "An activity row records one accepted change or event. It keeps the tracker history."),
    "attachments": ("history", "An attachment links one file to one record. It records the file's role and author."),
    "task_links": ("records", "A task link connects one task to an outside record or file. It keeps the outside identity."),
    "bugs": ("records", "A bug is one lasting defect. It can explain many incidents and track the capability that owns it."),
    "incidents": ("history", "An incident records one break in service, its impact, restoration, and root cause."),
    "record_links": ("records", "A record link connects an incident or bug to related work and history."),
}

BOOLEAN_FIELDS = {"active", "alongside", "flag", "important", "in_artifact", "urgent"}
DATE_FIELDS = {"created_on", "deadline", "decided_on", "due", "given_at", "planned"}
TIME_FIELDS = {"at", "claimed_at", "ended_at", "started_at"}
FILE_FIELDS = {"evidence", "page", "path"}
LIST_FIELDS = {"acceptance", "needs", "replaces", "tags"}


def sql_statements(path: Path):
    pending = ""
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            pending = ""
            if statement:
                yield statement
    if pending.strip():
        raise ValueError("incomplete SQL in " + str(path))


def apply_sql_file(db: sqlite3.Connection, path: Path) -> None:
    for statement in sql_statements(path):
        command = statement.lstrip("- \n\t").upper()
        if command.startswith("PRAGMA FOREIGN_KEYS") or command in {"BEGIN;", "COMMIT;"}:
            continue
        db.execute(statement)


def ensure_dictionary_columns(db: sqlite3.Connection) -> None:
    field_columns = {row[1] for row in db.execute("PRAGMA table_info(fields)")}
    if field_columns and "required" not in field_columns:
        db.execute("ALTER TABLE fields ADD COLUMN required INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1))")
    present = {
        row[1] for row in db.execute("PRAGMA table_info(object_types)")
    }
    if not present:
        return
    for name in ("why", "example"):
        if name not in present:
            db.execute(f'ALTER TABLE object_types ADD COLUMN "{name}" TEXT')


def ensure_dictionary_view(db: sqlite3.Connection) -> None:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name='v_dictionary'"
    ).fetchone()
    if row and "o.why" in row[0] and "o.example" in row[0]:
        return
    db.execute("DROP VIEW IF EXISTS v_dictionary")
    apply_sql_file(db, DICTIONARY_SQL)


def split_definitions(schema: str) -> list[str]:
    start, end = schema.find("("), schema.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("cannot parse table schema")
    body = schema[start + 1:end]
    parts, pending = [], []
    depth = 0
    quote = None
    index = 0
    while index < len(body):
        char = body[index]
        pending.append(char)
        if quote == "'":
            if char == "'" and index + 1 < len(body) and body[index + 1] == "'":
                pending.append(body[index + 1])
                index += 1
            elif char == "'":
                quote = None
        elif quote:
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "[":
            quote = "]"
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append("".join(pending[:-1]).strip())
            pending = []
        index += 1
    if pending:
        parts.append("".join(pending).strip())
    return parts


def unquote_identifier(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('""', '"')
    if len(value) >= 2 and value[0] == "`" and value[-1] == "`":
        return value[1:-1].replace("``", "`")
    if len(value) >= 2 and value[0] == "[" and value[-1] == "]":
        return value[1:-1]
    return value


def column_definitions(schema: str) -> dict[str, str]:
    definitions = {}
    for definition in split_definitions(schema):
        match = re.match(r'\s*("(?:""|[^"])+"|`(?:``|[^`])+`|\[[^]]+\]|[^\s]+)', definition)
        if not match:
            continue
        name = unquote_identifier(match.group(1))
        if name.upper() not in {"CHECK", "CONSTRAINT", "FOREIGN", "PRIMARY", "UNIQUE"}:
            definitions[name] = definition[len(match.group(0)):].strip()
    return definitions


def check_values(schema: str, column: str) -> list[str] | None:
    identifier = rf'(?:"{re.escape(column)}"|`{re.escape(column)}`|\[{re.escape(column)}\]|\b{re.escape(column)}\b)'
    match = re.search(identifier + r"\s+IN\s*\(([^()]*)\)", schema, re.IGNORECASE)
    if not match:
        return None
    text = match.group(1)
    tokens = re.findall(r"'(?:''|[^'])*'", text)
    remainder = re.sub(r"'(?:''|[^'])*'", "", text).replace(",", "").strip()
    if not tokens or remainder:
        return None
    return [token[1:-1].replace("''", "'") for token in tokens]


def infer_field_type(name: str, storage_type: str, primary_key: int, foreign_key: bool, picks) -> str:
    if primary_key:
        return "key"
    if picks:
        return "pick"
    if foreign_key:
        return "link"
    if name in BOOLEAN_FIELDS:
        return "yes/no"
    if name in DATE_FIELDS:
        return "date"
    if name in TIME_FIELDS:
        return "time"
    if name in FILE_FIELDS:
        return "file"
    if name in LIST_FIELDS:
        return "list"
    if storage_type.upper() in {"INTEGER", "REAL", "NUMERIC", "FLOAT", "DOUBLE"}:
        return "number"
    return "text"


def fallback_description(name: str, field_type: str, picks: list[str] | None, target: str | None) -> str:
    words = name.replace("_", " ")
    if name == "idempotency_key":
        return "Prevents repeated intake from creating the same task twice. The reserved session-holding-task value marks the session holding task; only session_run setup and backfill-key may set it."
    if name == "id":
        return "Identifies this record."
    if name in {"name", "title"}:
        return "Names this record."
    if name == "session":
        return "Names the native agent session for the run, such as a Codex thread id."
    if picks:
        return "Sets " + words + ". Allowed values: " + ", ".join(picks) + "."
    if target:
        return "Links this record to " + target + "."
    if field_type == "yes/no":
        return "States whether " + words + " is true."
    if field_type in {"date", "time"}:
        return "Records " + words + "."
    return "Stores the " + words + " value."


def different_clause(columns: tuple[str, ...]) -> str:
    return " OR ".join(f'object_types."{name}" IS NOT excluded."{name}"' for name in columns)


def seed_current_schema(db: sqlite3.Connection, *, update_existing: bool = False) -> None:
    # Insert-only by default (T712): a run adds the rows that are missing and never rewrites a written row.
    # A sweep that overwrote every current table's why and example text was bug B-20261019-dictionary-writer-rewrites-every-table-row.
    object_columns = (
        "supertype", "subtype", "lens", "container", "module", "database_type",
        "storage_name", "description", "definition", "source", "why", "example",
    )
    object_updates = ",".join(f'"{name}"=excluded."{name}"' for name in object_columns)
    object_sql = "INSERT " + ("" if update_existing else "OR IGNORE ") + "INTO object_types(name," + ",".join(object_columns) + ") VALUES (" + ",".join("?" for _ in range(13)) + ")"
    if update_existing:
        object_sql += " ON CONFLICT(name) DO UPDATE SET " + object_updates + " WHERE " + different_clause(object_columns)
    desired_field_columns = (
        "ordinal", "required", "field_type", "pick_values", "pick_source", "description",
        "storage_type", "sql_definition", "source",
    )
    live_field_columns = {row[1] for row in db.execute("PRAGMA table_info(fields)")}
    field_columns = tuple(name for name in desired_field_columns if name in live_field_columns)
    field_updates = ",".join(f'"{name}"=excluded."{name}"' for name in field_columns)
    field_difference = " OR ".join(f'fields."{name}" IS NOT excluded."{name}"' for name in field_columns)
    field_sql = "INSERT " + ("" if update_existing else "OR IGNORE ") + "INTO fields(object_type,field," + ",".join(field_columns) + ") VALUES (" + ",".join("?" for _ in range(2 + len(field_columns))) + ")"
    if update_existing:
        field_sql += " ON CONFLICT(object_type,field) DO UPDATE SET " + field_updates + " WHERE " + field_difference

    for table, (lens, description) in CURRENT_OBJECTS.items():
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if row is None or not row[0]:
            raise ValueError("current tracker table is missing: " + table)
        schema = row[0]
        source = "tracker sqlite_schema and PRAGMA table_info(" + table + ")"
        db.execute(object_sql, (
            table, "database", "table", lens, "collection", "work", "table", table,
            description, schema, source, "Stable dictionary key for shipped commands.", "Read " + table + ".",
        ))
        definitions = column_definitions(schema)
        foreign_keys = {
            item[3]: item[2] for item in db.execute(f'PRAGMA foreign_key_list("{table}")')
        }
        live_fields = []
        for column in db.execute(f'PRAGMA table_info("{table}")'):
            name = column[1]
            existing = db.execute(
                "SELECT description,source FROM fields WHERE object_type=? AND field=?",
                (table, name),
            ).fetchone()
            if name == "idempotency_key":
                existing = None
            if existing and not existing[1].startswith("tracker sqlite_schema"):
                live_fields.append(name)
                continue
            picks = check_values(schema, name)
            field_type = infer_field_type(name, column[2], column[5], name in foreign_keys, picks)
            field_description = (
                existing[0] if existing else fallback_description(name, field_type, picks, foreign_keys.get(name))
            )
            ordinal = db.execute("SELECT ordinal FROM fields WHERE object_type=? AND field=?", (table, name)).fetchone()
            ordinal = ordinal[0] if ordinal else column[0] + 1
            if db.execute("SELECT 1 FROM fields WHERE object_type=? AND ordinal=? AND field<>?", (table, ordinal, name)).fetchone():
                ordinal = db.execute("SELECT coalesce(max(ordinal),0)+1 FROM fields WHERE object_type=?", (table,)).fetchone()[0]
            values = {
                "ordinal": ordinal,
                "required": int(bool(column[3] or column[5])),
                "field_type": field_type,
                "pick_values": json.dumps(picks, ensure_ascii=False, separators=(",", ":")) if picks else None,
                "pick_source": source + " CHECK" if picks else None,
                "description": field_description,
                "storage_type": column[2] or "",
                "sql_definition": definitions.get(name, column[2] or ""),
                "source": source,
            }
            db.execute(field_sql, (table, name, *(values[field] for field in field_columns)))
            live_fields.append(name)
def install_dictionary(db: sqlite3.Connection) -> None:
    ensure_dictionary_columns(db)
    apply_sql_file(db, DICTIONARY_SQL)
    ensure_dictionary_view(db)
    prune_dictionary_columns(db)
    seed_current_schema(db)
    apply_sql_file(db, DICTIONARY_SEED)
    prune_dictionary_columns(db)


def prune_dictionary_columns(db: sqlite3.Connection) -> None:
    # A bundled definition can describe a later schema. Installed columns win.
    for object_type, storage, field in missing_dictionary_columns(db):
        db.execute("DELETE FROM fields WHERE object_type=? AND field=?", (object_type, field))


def missing_dictionary_columns(db: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Check database definitions; optional uninstalled modules and files have no local columns."""
    errors = []
    for object_type, storage, field in db.execute(
        "SELECT o.name,o.storage_name,f.field FROM fields f "
        "JOIN object_types o ON o.name=f.object_type "
        "WHERE o.database_type IN ('table','mirror','trend','view') "
        "ORDER BY o.name,f.field"
    ):
        if db.execute("SELECT 1 FROM sqlite_schema WHERE name=? AND type IN ('table','view')", (storage,)).fetchone() is None:
            continue
        quoted = '"' + storage.replace('"', '""') + '"'
        columns = {row[1] for row in db.execute('PRAGMA table_xinfo(' + quoted + ')')}
        if field not in columns:
            errors.append((object_type, storage, field))
    return errors


def dictionary_column_errors(db: sqlite3.Connection) -> list[str]:
    return [object_type + ": " + storage + "." + field
            for object_type, storage, field in missing_dictionary_columns(db)]


def verify(db: sqlite3.Connection, prior_foreign_keys: set[tuple]) -> dict:
    errors = dictionary_column_errors(db)
    if errors:
        raise ValueError("dictionary names missing columns: " + ", ".join(errors))
    for table in CURRENT_OBJECTS:
        live = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
        dictionary = {row[0] for row in db.execute(
            "SELECT field FROM fields WHERE object_type=?", (table,)
        )}
        if not set(live).issubset(dictionary):
            raise ValueError("field verification failed: " + table)
    foreign_keys = {tuple(row) for row in db.execute("PRAGMA foreign_key_check")}
    if not foreign_keys.issubset(prior_foreign_keys):
        raise ValueError("dictionary added foreign-key findings")
    quick = db.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        raise ValueError("quick_check failed: " + quick)
    return {
        "object_types": db.execute("SELECT count(*) FROM object_types").fetchone()[0],
        "fields": db.execute("SELECT count(*) FROM fields").fetchone()[0],
        "current_fields": db.execute(
            "SELECT count(*) FROM fields WHERE object_type IN (" + ",".join("?" for _ in CURRENT_OBJECTS) + ")",
            tuple(CURRENT_OBJECTS),
        ).fetchone()[0],
        "foreign_key_findings": len(foreign_keys),
        "quick_check": quick,
    }


def apply(database: Path, backup_dir: Path) -> dict:
    if not database.is_file():
        raise ValueError("database must already exist: " + str(database))
    with closing(_fox_person.connect(database, timeout=0, isolation_level=None)) as db:
        if db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise ValueError("database uses WAL; checkpoint it before an exact backup")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN EXCLUSIVE")
            prior_foreign_keys = {tuple(row) for row in db.execute("PRAGMA foreign_key_check")}
            changes_before = db.total_changes
            schema_before = schema_snapshot(db)
            db.execute("SAVEPOINT preview")
            install_dictionary(db)
            preview = verify(db, prior_foreign_keys)
            changed = db.total_changes != changes_before or schema_snapshot(db) != schema_before
            db.execute("ROLLBACK TO preview")
            db.execute("RELEASE preview")

            backup = None
            archived = archive_old_backups(database, backup_dir)
            if changed:
                backup = make_backup_locked(database, backup_dir, db)
                archived.extend(archive_old_backups(database, backup_dir))
                install_dictionary(db)
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

    undo_backup = backup
    if undo_backup is None:
        matches = timestamped_backups(database, backup_dir)
        undo_backup = matches[0][1] if matches else None
    report.update({
        "backup": str(backup) if backup else None,
        "backup_created": backup is not None,
        "archived_backups": archived,
        "undo_command": None if undo_backup is None else " ".join(shlex.quote(part) for part in (
            "python3", str((Path(__file__).resolve().parent / 'apply_dictionary.py')), "--db", str(database), "--undo", str(undo_backup),
        )),
    })
    return report


def export_after_write(database: Path) -> None:
    script = (Path(__file__).resolve().parent / 'backup.py')
    spec = importlib.util.spec_from_file_location("dictionary_export_state", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("backup.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.export_state(database)
    with closing(_fox_person.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        present = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('object_types','fields')"
            )
        }
    for table in {"object_types", "fields"} - present:
        Path(result["output_dir"], table + ".jsonl").unlink(missing_ok=True)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUPS)
    parser.add_argument("--undo")
    parser.add_argument("--check", action="store_true", help="Check dictionary columns without writes or exports")
    args = parser.parse_args(argv)
    database = args.db.expanduser().resolve()
    backup_dir = args.backup_dir.expanduser().resolve()
    try:
        if args.check:
            with closing(_fox_person.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                errors = dictionary_column_errors(db)
            print(json.dumps({"column_errors": errors, "check": "fail" if errors else "pass"}, indent=2))
            return 2 if errors else 0
        if args.undo:
            backup = newest_backup(database, backup_dir) if args.undo == "latest" else Path(args.undo).expanduser().resolve()
            restore(database, backup)
            export_after_write(database)
            print("ok restored " + str(backup))
            return 0
        report = apply(database, backup_dir)
        export_after_write(database)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print("dictionary apply failed; database unchanged: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
