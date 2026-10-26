#!/usr/bin/env python3
"""Shared checked command for module-owned SQLite tables."""

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
from dataclasses import dataclass
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid


MODULES_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str((Path(__file__).resolve().parent / '../work')))
sys.path.insert(0, str(Path(__file__).resolve().parent / '../events'))
from history_actions import write_history
RULES_PATH = (
    (Path(os.environ.get('FOXRUN_PROPOSAL_RULES', str(Path(__file__).resolve().parent / 'proposal-rules.md'))))
)
PROPOSAL_DDL = '''CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY NOT NULL,
  module TEXT NOT NULL,
  table_name TEXT NOT NULL,
  row_id TEXT NOT NULL,
  changes TEXT NOT NULL CHECK (json_valid(changes)),
  base_row TEXT CHECK (base_row IS NULL OR json_valid(base_row)),
  why TEXT NOT NULL CHECK (length(trim(why)) > 0),
  "by" TEXT NOT NULL CHECK (length(trim("by")) > 0),
  at TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','accepted','rejected')),
  decided_by TEXT,
  decided_at TEXT
)'''
PROPOSAL_COLUMNS = {
    "id", "module", "table_name", "row_id", "changes", "base_row",
    "why", "by", "at", "state", "decided_by", "decided_at",
}
COMPLETION_VALUES = {
    "approved", "ordered", "confirmed", "received", "resolved", "closed",
    "granted", "signed", "won", "agreed", "waived", "delivered", "paid",
}
MONEY_NAME = re.compile(
    r"(^value$|amount|price|rate|fee|payment|commission|budget|total_minor|unit_price_minor|line_total_minor)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CommandConfig:
    module: str
    writable: tuple[str, ...]
    mirrors: dict[str, str]
    trends: tuple[str, ...] = ()

    @property
    def declared(self) -> tuple[str, ...]:
        return self.writable + tuple(self.mirrors) + self.trends


@dataclass(frozen=True)
class Rules:
    proposal_fields: dict[str, frozenset[str]]
    gated_transitions: dict[tuple[str, str], frozenset[str]]
    approval_locks: dict[str, frozenset[str]]
    approved_rows: dict[str, tuple[tuple[str, frozenset[str]], ...]]


def fail(message: str) -> None:
    raise SystemExit(message)


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def require_text(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        fail(label + " must not be blank")
    return value.strip()


def machine_block(text: str, name: str) -> list[str]:
    match = re.search(
        r"^```" + re.escape(name) + r"[ \t]*\r?\n(.*?)^```[ \t]*$",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        fail("proposal rules are invalid: missing " + name + " machine block")
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def qualified_name(value: str, size: int, line: str) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in value.split("."))
    if len(parts) != size or any(not part for part in parts):
        fail("proposal rules are invalid: " + line)
    return parts


def module_folder(module: str) -> Path:
    # An add-on may sit in modules/<name> beside the core folders.
    nested = MODULES_ROOT / 'modules' / module
    return nested if nested.is_dir() else MODULES_ROOT / module


def module_schema(module: str) -> dict[str, frozenset[str]]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", module):
        fail("proposal rules are invalid: unknown module " + module)
    folder = module_folder(module)
    metadata = folder / "README.md"
    if not metadata.is_file():
        fail("proposal rules are invalid: unknown module " + module)
    blueprint = folder / "blueprint.sql"
    if not blueprint.is_file():
        fail("proposal rules are invalid: module has no blueprint " + module)
    db = _fox_person.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(blueprint.read_text(encoding="utf-8"))
        result = {
            row[0]: frozenset(
                field["name"]
                for field in db.execute("PRAGMA table_info(" + quote(row[0]) + ")")
            )
            for row in db.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    except (OSError, sqlite3.Error) as error:
        fail("proposal rules are invalid: cannot read module " + module + ": " + str(error))
    finally:
        db.close()
    return result


def validate_rule_target(
    schemas: dict[str, dict[str, frozenset[str]]],
    module: str,
    table: str,
    fields: list[str],
) -> None:
    if module not in schemas:
        schemas[module] = module_schema(module)
    if table not in schemas[module]:
        fail("proposal rules are invalid: unknown table " + module + "." + table)
    for field in fields:
        if field not in schemas[module][table]:
            fail(
                "proposal rules are invalid: unknown field "
                + module + "." + table + "." + field
            )


def unique_target(seen: set[str], target: str) -> None:
    if target in seen:
        fail("proposal rules are invalid: duplicate rule " + target)
    seen.add(target)


def load_rules(path: Path, module: str) -> Rules:
    if not path.is_file():
        fail("proposal rules file is missing: " + str(path))
    text = path.read_text(encoding="utf-8")
    proposal_fields: dict[str, frozenset[str]] = {}
    transitions: dict[tuple[str, str], frozenset[str]] = {}
    locks: dict[str, frozenset[str]] = {}
    approved_rows: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {}
    schemas: dict[str, dict[str, frozenset[str]]] = {}
    lock_targets: set[str] = set()
    approved_targets: set[str] = set()

    seen: set[str] = set()
    for line in machine_block(text, "proposal-fields"):
        if ":" not in line:
            fail("proposal rules are invalid: " + line)
        target, values = (part.strip() for part in line.split(":", 1))
        rule_module, table = qualified_name(target, 2, line)
        fields = split_values(values)
        unique_target(seen, target)
        validate_rule_target(schemas, rule_module, table, fields)
        if rule_module == module:
            proposal_fields[table] = frozenset(fields)

    seen = set()
    for line in machine_block(text, "gated-transitions"):
        if "->" not in line:
            fail("proposal rules are invalid: " + line)
        target, values = (part.strip() for part in line.split("->", 1))
        rule_module, table, field = qualified_name(target, 3, line)
        unique_target(seen, target)
        validate_rule_target(schemas, rule_module, table, [field])
        transition_values = frozenset(split_values(values))
        if rule_module == module:
            transitions[(table, field)] = transition_values

    seen = set()
    for line in machine_block(text, "approval-locks"):
        if ":" not in line:
            fail("proposal rules are invalid: " + line)
        target, values = (part.strip() for part in line.split(":", 1))
        rule_module, table = qualified_name(target, 2, line)
        fields = split_values(values)
        unique_target(seen, target)
        validate_rule_target(schemas, rule_module, table, fields)
        lock_targets.add(target)
        if rule_module == module:
            locks[table] = frozenset(fields)

    seen = set()
    for line in machine_block(text, "approved-rows"):
        if ":" not in line:
            fail("proposal rules are invalid: " + line)
        target, values = (part.strip() for part in line.split(":", 1))
        rule_module, table = qualified_name(target, 2, line)
        unique_target(seen, target)
        predicates: list[tuple[str, frozenset[str]]] = []
        predicate_fields: set[str] = set()
        for condition in split_values(values):
            if "=" not in condition:
                fail("proposal rules are invalid: " + condition)
            field, raw_values = (part.strip() for part in condition.split("=", 1))
            if not field or not raw_values:
                fail("proposal rules are invalid: " + condition)
            if field in predicate_fields:
                fail("proposal rules are invalid: duplicate field " + target + "." + field)
            predicate_fields.add(field)
            choices = frozenset(part.strip() for part in raw_values.split("|") if part.strip())
            if not choices:
                fail("proposal rules are invalid: " + condition)
            predicates.append((field, choices))
        validate_rule_target(schemas, rule_module, table, list(predicate_fields))
        approved_targets.add(target)
        if rule_module == module:
            approved_rows[table] = tuple(predicates)

    missing = sorted(lock_targets - approved_targets)
    extra = sorted(approved_targets - lock_targets)
    if missing:
        fail("proposal rules are invalid: approval lock lacks approved-row rule " + missing[0])
    if extra:
        fail("proposal rules are invalid: approved-row rule lacks approval lock " + extra[0])

    return Rules(proposal_fields, transitions, locks, approved_rows)


def split_values(value: str) -> list[str]:
    result = [item.strip() for item in value.split(",")]
    if not result or any(not item for item in result):
        fail("proposal rules contain an empty field list")
    duplicate = next((item for item in result if result.count(item) > 1), None)
    if duplicate is not None:
        fail("proposal rules are invalid: duplicate value " + duplicate)
    return result


def markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def load_history_tables(module: str) -> set[str]:
    path = module_folder(module) / 'README.md'
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        fail("module metadata cannot be read for " + module + ": " + str(error))
    match = re.search(r"^## Collections\s*$\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        fail("module metadata cannot be read for " + module + ": Collections table is missing")
    lines = [line for line in match.group(1).splitlines() if line.strip().startswith("|")]
    header_index = next(
        (index for index, line in enumerate(lines) if "Lens" in markdown_cells(line)),
        None,
    )
    if header_index is None:
        fail("module metadata cannot be read for " + module + ": Lens column is missing")
    header = [cell.lower() for cell in markdown_cells(lines[header_index])]
    required = ("collection", "supertype", "lens")
    if any(name not in header for name in required):
        fail("module metadata cannot be read for " + module + ": Collections columns are invalid")
    database_header = next(
        (name for name in header if name.startswith("database type")),
        None,
    )
    if database_header is None:
        fail("module metadata cannot be read for " + module + ": Database type column is missing")
    indexes = {name: header.index(name) for name in required}
    indexes["database"] = header.index(database_header)
    history: set[str] = set()
    for line in lines[header_index + 1:]:
        cells = markdown_cells(line)
        if len(cells) != len(header) or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        if cells[indexes["lens"]].strip(" `").lower() != "history":
            continue
        if "database" not in cells[indexes["supertype"]].lower():
            continue
        database_type = cells[indexes["database"]]
        if not re.search(r"\b(table|trend|mirror)\b", database_type, re.IGNORECASE):
            continue
        collection = cells[indexes["collection"]]
        names = re.findall(r"`([^`]+)`", collection)
        if not names:
            names = re.findall(r"`([^`]+)`", database_type)
        if not names and ":" in database_type:
            names = [database_type.rsplit(":", 1)[1].strip()]
        if not names:
            plain = collection.strip(" `")
            if re.fullmatch(r"[a-z][a-z0-9_]*", plain):
                names = [plain]
        if not names:
            fail("module metadata cannot be read for " + module + ": history collection has no table name")
        history.add(names[-1])
    return history


def default_database() -> str:
    candidate = _fox_paths.database()
    if candidate.is_file():
        return str(candidate)
    fail("no system database found; pass --db <path>")


def connect(path: str | None) -> sqlite3.Connection:
    database = path or default_database()
    if not os.path.isfile(database):
        fail("database not found: " + database)
    db = _fox_person.connect(database, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def table_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def valid_tables(db: sqlite3.Connection, config: CommandConfig) -> list[str]:
    present = table_names(db)
    return [table for table in config.declared if table in present]


def require_table(db: sqlite3.Connection, config: CommandConfig, table: str) -> None:
    valid = valid_tables(db, config)
    if table not in valid:
        fail("unknown table: " + table + ". valid tables: " + ", ".join(valid))


def require_write_target(config: CommandConfig, table: str, verb: str) -> None:
    if table in config.mirrors:
        fail(table + " is a mirror; " + config.mirrors[table] + " writes it")
    if table in config.trends and verb != "observe":
        fail(table + " is a trend; use the observe subcommand")
    if verb == "observe" and table not in config.trends:
        fail("observe only appends: " + ", ".join(config.trends))
    if verb != "observe" and table not in config.writable:
        fail("table is not writable: " + table)


def require_evidence_tables(db: sqlite3.Connection) -> None:
    missing = sorted({"activity", "approvals"} - table_names(db))
    if missing:
        fail("database is missing required evidence tables: " + ", ".join(missing))


def ensure_proposals(db: sqlite3.Connection) -> None:
    db.execute(PROPOSAL_DDL)
    found = {row[1] for row in db.execute("PRAGMA table_info(proposals)")}
    missing = sorted(PROPOSAL_COLUMNS - found)
    if missing:
        db.rollback()
        fail("proposals table is incompatible; missing fields: " + ", ".join(missing))
    db.commit()


def columns(db: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in db.execute("PRAGMA table_info(" + quote(table) + ")")}


def require_fields(db: sqlite3.Connection, table: str, fields) -> dict[str, sqlite3.Row]:
    known = columns(db, table)
    unknown = sorted(set(fields) - set(known))
    if unknown:
        fail(
            "unknown field(s) for " + table + ": " + ", ".join(unknown)
            + ". valid fields: " + ", ".join(known)
        )
    return known


def primary_keys(db: sqlite3.Connection, table: str) -> list[str]:
    keyed = sorted(
        (row for row in columns(db, table).values() if row["pk"]),
        key=lambda row: row["pk"],
    )
    if not keyed:
        fail("table has no primary key: " + table)
    return [row["name"] for row in keyed]


def parse_assignments(items: list[str]) -> dict[str, str]:
    changes: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            fail("--set needs field=value: " + item)
        field, value = item.split("=", 1)
        field = field.strip()
        if not field:
            fail("--set needs a field name")
        if field in changes:
            fail("field supplied more than once: " + field)
        changes[field] = value
    if not changes:
        fail("at least one --set field=value is required")
    return changes


def parse_key(db: sqlite3.Connection, table: str, token: str) -> tuple[list[str], list[object]]:
    keys = primary_keys(db, table)
    if len(keys) == 1:
        return keys, [coerce(token, columns(db, table)[keys[0]])]
    try:
        raw = json.loads(token) if token.startswith("[") else token.split("|")
    except json.JSONDecodeError:
        fail("composite id must be a JSON array or pipe-separated values: " + ", ".join(keys))
    if not isinstance(raw, list) or len(raw) != len(keys):
        fail("composite id needs " + "|".join(keys))
    info = columns(db, table)
    return keys, [coerce(str(value), info[key]) for key, value in zip(keys, raw)]


def canonical_id(values: list[object]) -> str:
    return "|".join("null" if value is None else str(value) for value in values)


def row_for_key(
    db: sqlite3.Connection, table: str, keys: list[str], values: list[object]
) -> sqlite3.Row | None:
    where = " AND ".join(quote(key) + "=?" for key in keys)
    return db.execute(
        "SELECT * FROM " + quote(table) + " WHERE " + where, values
    ).fetchone()


def require_row(db: sqlite3.Connection, table: str, token: str):
    keys, values = parse_key(db, table, token)
    row = row_for_key(db, table, keys, values)
    if row is None:
        fail("no such " + table + " row: " + token)
    return row, keys, values, canonical_id(values)


def is_money_field(field: str) -> bool:
    return not field.endswith(("_reason", "_ref", "_id")) and bool(MONEY_NAME.search(field))


def validate_money(field: str, value: object) -> None:
    if value is None:
        return
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("number required for money field " + field + ": " + str(value))
    if not number.is_finite():
        fail("finite number required for " + field + ": " + str(value))


def numeric_type(info: sqlite3.Row) -> bool:
    kind = (info["type"] or "").upper()
    return any(word in kind for word in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC"))


def validate_finite_number(info: sqlite3.Row, value: object) -> None:
    if value is None or not numeric_type(info):
        return
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return
    if not number.is_finite():
        fail("finite number required for " + info["name"] + ": " + str(value))


def validate_evidence_list(value: object, field: str, required: bool) -> str | None:
    if value is None:
        if required:
            fail("evidence is required; evidence is missing: " + field)
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        fail(field + " must be a non-empty JSON list of non-empty strings")
    valid = (
        isinstance(parsed, list)
        and bool(parsed)
        and all(isinstance(item, str) and bool(item.strip()) for item in parsed)
    )
    if not valid:
        fail(
            "evidence is required; evidence is missing or invalid: " + field
            + " must be a non-empty list of non-empty strings"
        )
    return json.dumps([item.strip() for item in parsed], ensure_ascii=False, separators=(",", ":"))


def coerce(value: str, info: sqlite3.Row):
    if value.lower() == "null":
        result = None
    else:
        kind = (info["type"] or "").upper()
        validate_finite_number(info, value)
        try:
            if "INT" in kind:
                result = int(value)
            elif any(word in kind for word in ("REAL", "FLOA", "DOUB", "NUM")):
                result = float(value)
            else:
                result = value
        except ValueError:
            fail("invalid " + (kind.lower() or "typed") + " value for " + info["name"] + ": " + value)
        validate_finite_number(info, result)
    if is_money_field(info["name"]):
        validate_money(info["name"], result)
    if info["name"] == "evidence_refs":
        return validate_evidence_list(result, info["name"], required=result is not None)
    return result


def typed_changes(db: sqlite3.Connection, table: str, raw: dict[str, str]) -> dict[str, object]:
    info = require_fields(db, table, raw)
    return {field: coerce(value, info[field]) for field, value in raw.items()}


def check_lists(db: sqlite3.Connection, table: str) -> dict[str, list[str]]:
    row = db.execute(
        "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)
    ).fetchone()
    sql = row[0] if row and row[0] else ""
    result: dict[str, list[str]] = {}
    for field in columns(db, table):
        match = re.search(
            r'(?:"' + re.escape(field) + r'"|\b' + re.escape(field) + r'\b)\s+IN\s*\(([^()]*)\)',
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        values = [value.replace("''", "'") for value in re.findall(r"'((?:''|[^'])*)'", match.group(1))]
        if values:
            result[field] = values
    return result


def validate_picks(db: sqlite3.Connection, table: str, changes: dict[str, object]) -> None:
    for field, allowed in check_lists(db, table).items():
        if field in changes and changes[field] is not None and str(changes[field]) not in allowed:
            fail(
                field + " must be one of: " + ", ".join(allowed)
                + "; valid values: " + ", ".join(allowed)
            )


def final_evidence(db: sqlite3.Connection, table: str, row: dict[str, object]) -> None:
    info = columns(db, table)
    completion = str(row.get("status", "")).lower() in COMPLETION_VALUES
    if "evidence_refs" in info:
        required = bool(info["evidence_refs"]["notnull"]) or completion
        validate_evidence_list(row.get("evidence_refs"), "evidence_refs", required)
    if completion and "evidence_ref" in info:
        value = row.get("evidence_ref")
        if value is None or not str(value).strip():
            fail("evidence is required; evidence is missing: evidence_ref")


def automatic_fields(db: sqlite3.Connection, table: str, changes: dict[str, object]) -> dict[str, object]:
    result = dict(changes)
    info = columns(db, table)
    stamp = now()
    for field in ("created_at", "updated_at"):
        if field in info and field not in result and info[field]["notnull"] and info[field]["dflt_value"] is None:
            result[field] = stamp
    return result


def row_id_from_changes(db: sqlite3.Connection, table: str, changes: dict[str, object]) -> tuple[list[str], list[object], str]:
    keys = primary_keys(db, table)
    missing = [key for key in keys if key not in changes or changes[key] is None]
    if missing:
        fail("add needs primary key field(s): " + ", ".join(missing))
    values = [changes[key] for key in keys]
    return keys, values, canonical_id(values)


def accepted_proposal_exists(db: sqlite3.Connection, config: CommandConfig, table: str, row_id: str) -> bool:
    if "proposals" not in table_names(db):
        return False
    return db.execute(
        "SELECT 1 FROM proposals WHERE module=? AND table_name=? AND row_id=? AND state='accepted' LIMIT 1",
        (config.module, table, row_id),
    ).fetchone() is not None


def row_is_approved(rules: Rules, table: str, row: sqlite3.Row | None) -> bool:
    predicates = rules.approved_rows.get(table, ())
    if row is None or not predicates:
        return False
    for field, choices in predicates:
        value = row[field]
        if "*" in choices:
            if value is None or (isinstance(value, str) and not value.strip()):
                return False
        elif value is None or str(value) not in choices:
            return False
    return True


def approved_fact_exists(
    db: sqlite3.Connection,
    config: CommandConfig,
    rules: Rules,
    table: str,
    row_id: str,
    row: sqlite3.Row | None,
) -> bool:
    return row_is_approved(rules, table, row) or accepted_proposal_exists(
        db, config, table, row_id
    )


def proposal_needed_fields(
    rules: Rules,
    table: str,
    changes: dict[str, object],
    existing: sqlite3.Row | None,
    has_accepted: bool,
) -> list[str]:
    result: set[str] = set()
    for field, value in changes.items():
        old = existing[field] if existing is not None and field in existing.keys() else None
        changed = existing is None or old != value
        if not changed:
            continue
        if field in rules.proposal_fields.get(table, frozenset()):
            result.add(field)
        if value is not None and str(value) in rules.gated_transitions.get((table, field), frozenset()):
            result.add(field)
        if has_accepted and field in rules.approval_locks.get(table, frozenset()):
            result.add(field)
    return sorted(result)


def activity(
    db: sqlite3.Connection,
    config: CommandConfig,
    subject_type: str,
    subject_id: str,
    field: str,
    old,
    new,
    actor: str,
    stamp: str,
    note: str | None = None,
    *, record_add: bool = False,
) -> None:
    write_history(db, subject_type, subject_id, field, old, new, actor,
                  config.module + ' cli', stamp, note, record_add=record_add, known_field=True)


def schema_failure(db: sqlite3.Connection, verb: str, error: sqlite3.IntegrityError) -> None:
    db.rollback()
    fail(verb + " refused by schema: " + str(error))


def add_row(db, config, rules, table, actor, raw, observe=False):
    require_table(db, config, table)
    require_write_target(config, table, "observe" if observe else "add")
    require_evidence_tables(db)
    actor = require_text(actor, "--by")
    changes = typed_changes(db, table, raw)
    validate_picks(db, table, changes)
    changes = automatic_fields(db, table, changes)
    keys, values, row_id = row_id_from_changes(db, table, changes)
    if not observe:
        gated = proposal_needed_fields(rules, table, changes, None, False)
        if gated:
            fail("proposal field(s) " + ", ".join(gated) + " must use propose")
    fields = list(changes)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO " + quote(table) + " (" + ",".join(quote(field) for field in fields)
            + ") VALUES (" + ",".join("?" for _ in fields) + ")",
            [changes[field] for field in fields],
        )
        written = dict(row_for_key(db, table, keys, values))
        final_evidence(db, table, written)
        stamp = now()
        for field, value in changes.items():
            activity(db, config, table, row_id, field, None, value, actor, stamp, "observed" if observe else "added", record_add=True)
        db.commit()
    except sqlite3.IntegrityError as error:
        schema_failure(db, "observe" if observe else "add", error)
    except BaseException:
        db.rollback()
        raise
    print("ok", "observe" if observe else "add", table, row_id)


def set_row(db, config, rules, history_tables, table, token, actor, raw):
    require_table(db, config, table)
    require_write_target(config, table, "set")
    if table in history_tables:
        fail(table + " is history; set is refused because history is append only")
    require_evidence_tables(db)
    actor = require_text(actor, "--by")
    changes = typed_changes(db, table, raw)
    validate_picks(db, table, changes)
    keys = primary_keys(db, table)
    supplied_keys = sorted(set(keys) & set(changes))
    if supplied_keys:
        fail("set cannot change primary key field(s): " + ", ".join(supplied_keys))
    try:
        db.execute("BEGIN IMMEDIATE")
        existing, keys, values, row_id = require_row(db, table, token)
        gated = proposal_needed_fields(
            rules, table, changes, existing,
            approved_fact_exists(db, config, rules, table, row_id, existing),
        )
        if gated:
            fail("proposal field(s) " + ", ".join(gated) + " must use propose")
        applied = automatic_fields(db, table, changes)
        if "updated_at" in columns(db, table) and "updated_at" not in applied:
            applied["updated_at"] = now()
        where = " AND ".join(quote(key) + "=?" for key in keys)
        db.execute(
            "UPDATE " + quote(table) + " SET "
            + ",".join(quote(field) + "=?" for field in applied) + " WHERE " + where,
            [applied[field] for field in applied] + values,
        )
        written = dict(row_for_key(db, table, keys, values))
        final_evidence(db, table, written)
        stamp = now()
        for field, value in applied.items():
            activity(db, config, table, row_id, field, existing[field], value, actor, stamp, "set")
        db.commit()
    except sqlite3.IntegrityError as error:
        schema_failure(db, "set", error)
    except BaseException:
        db.rollback()
        raise
    print("ok set", table, row_id)


def show_row(db, config, table, token):
    require_table(db, config, table)
    row, _, _, _ = require_row(db, table, token)
    print(json.dumps(dict(row), indent=2, ensure_ascii=False))


def list_rows(db, config, table, where):
    require_table(db, config, table)
    sql = "SELECT * FROM " + quote(table)
    values: list[object] = []
    if where:
        changes = typed_changes(db, table, parse_assignments([where]))
        field, value = next(iter(changes.items()))
        sql += " WHERE " + quote(field) + "=?"
        values.append(value)
    keys = primary_keys(db, table)
    sql += " ORDER BY " + ",".join(quote(key) for key in keys)
    print(json.dumps([dict(row) for row in db.execute(sql, values)], indent=2, ensure_ascii=False))


def candidate_changes(db, table, token, changes):
    keys, values = parse_key(db, table, token)
    existing = row_for_key(db, table, keys, values)
    if existing is None:
        for key, value in zip(keys, values):
            if key in changes and changes[key] != value:
                fail("proposal primary key does not match row id: " + key)
            changes[key] = value
    elif set(keys) & set(changes):
        fail("proposal cannot change primary key field(s): " + ", ".join(keys))
    return existing, keys, values, canonical_id(values), changes


def trial_candidate(db, table, existing, keys, values, changes):
    applied = automatic_fields(db, table, changes)
    db.execute("SAVEPOINT proposal_check")
    try:
        if existing is None:
            fields = list(applied)
            db.execute(
                "INSERT INTO " + quote(table) + " (" + ",".join(quote(field) for field in fields)
                + ") VALUES (" + ",".join("?" for _ in fields) + ")",
                [applied[field] for field in fields],
            )
        else:
            where = " AND ".join(quote(key) + "=?" for key in keys)
            db.execute(
                "UPDATE " + quote(table) + " SET "
                + ",".join(quote(field) + "=?" for field in applied) + " WHERE " + where,
                [applied[field] for field in applied] + values,
            )
        written = dict(row_for_key(db, table, keys, values))
        final_evidence(db, table, written)
    finally:
        db.execute("ROLLBACK TO proposal_check")
        db.execute("RELEASE proposal_check")


def propose(db, config, rules, table, token, actor, raw, why):
    require_table(db, config, table)
    require_write_target(config, table, "propose")
    require_evidence_tables(db)
    actor = require_text(actor, "--by")
    why = require_text(why, "--why")
    ensure_proposals(db)
    changes = typed_changes(db, table, raw)
    validate_picks(db, table, changes)
    existing, keys, values, row_id, changes = candidate_changes(db, table, token, changes)
    has_accepted = existing is not None and approved_fact_exists(
        db, config, rules, table, row_id, existing
    )
    gated = proposal_needed_fields(rules, table, changes, existing, has_accepted)
    if not gated:
        fail("no proposal-controlled change supplied; use add or set for routine fields")
    try:
        trial_candidate(db, table, existing, keys, values, changes)
    except sqlite3.IntegrityError as error:
        fail("propose refused by schema: " + str(error))
    proposal_id = "P-" + uuid.uuid4().hex
    stamp = now()
    base_row = None if existing is None else json.dumps(dict(existing), sort_keys=True, separators=(",", ":"))
    db.execute(
        'INSERT INTO proposals (id,module,table_name,row_id,changes,base_row,why,"by",at,state) '
        "VALUES (?,?,?,?,?,?,?,?,?,'pending')",
        (
            proposal_id, config.module, table, row_id,
            json.dumps(changes, sort_keys=True, separators=(",", ":")),
            base_row, why, actor, stamp,
        ),
    )
    activity(db, config, "proposal", proposal_id, "state", None, "pending", actor, stamp, table + " " + row_id + ": " + why)
    db.commit()
    print("ok propose", proposal_id)


def load_proposal(db, config, proposal_id):
    row = db.execute(
        "SELECT * FROM proposals WHERE id=? AND module=?", (proposal_id, config.module)
    ).fetchone()
    if row is None:
        fail("no such proposal: " + proposal_id)
    return row


def accept(db, config, rules, proposal_id, actor, person_words):
    actor = require_text(actor, "--by")
    require_text(person_words, "--person-words")  # Validate without changing the exact words.
    # fewer-rules: Person's direct request is approval. The workspace owns risk gates.
    require_evidence_tables(db)
    ensure_proposals(db)
    try:
        db.execute("BEGIN IMMEDIATE")
        proposal = load_proposal(db, config, proposal_id)
        if proposal["state"] != "pending":
            fail("proposal is not pending: " + proposal_id)
        table = proposal["table_name"]
        require_table(db, config, table)
        require_write_target(config, table, "propose")
        raw = json.loads(proposal["changes"])
        info = require_fields(db, table, raw)
        changes = {
            field: coerce("null" if value is None else str(value), info[field])
            for field, value in raw.items()
        }
        validate_picks(db, table, changes)
        keys, values = parse_key(db, table, proposal["row_id"])
        existing = row_for_key(db, table, keys, values)
        expected = json.loads(proposal["base_row"]) if proposal["base_row"] else None
        if expected is None and existing is not None:
            fail("approval context changed: proposed row now exists")
        if expected is not None and (existing is None or dict(existing) != expected):
            fail("approval context changed since proposal")
        gated = proposal_needed_fields(
            rules, table, changes, existing,
            existing is not None and approved_fact_exists(
                db, config, rules, table, proposal["row_id"], existing
            ),
        )
        if not gated:
            fail("proposal is no longer controlled by the current rules")
        applied = automatic_fields(db, table, changes)
        if existing is None:
            fields = list(applied)
            db.execute(
                "INSERT INTO " + quote(table) + " (" + ",".join(quote(field) for field in fields)
                + ") VALUES (" + ",".join("?" for _ in fields) + ")",
                [applied[field] for field in fields],
            )
        else:
            if "updated_at" in columns(db, table) and "updated_at" not in applied:
                applied["updated_at"] = now()
            where = " AND ".join(quote(key) + "=?" for key in keys)
            db.execute(
                "UPDATE " + quote(table) + " SET "
                + ",".join(quote(field) + "=?" for field in applied) + " WHERE " + where,
                [applied[field] for field in applied] + values,
            )
        written = dict(row_for_key(db, table, keys, values))
        final_evidence(db, table, written)
        stamp = now()
        changed = db.execute(
            "UPDATE proposals SET state='accepted',decided_by=?,decided_at=? WHERE id=? AND state='pending'",
            (actor, stamp, proposal_id),
        ).rowcount
        if changed != 1:
            fail("proposal is not pending: " + proposal_id)
        for field, value in applied.items():
            old = None if existing is None else existing[field]
            activity(db, config, table, proposal["row_id"], field, old, value, actor, stamp, "accepted " + proposal_id)
        activity(db, config, "proposal", proposal_id, "state", "pending", "accepted", actor, stamp, proposal["why"])
        db.execute(
            "INSERT INTO approvals (subject_type,subject_id,version,call,person_words,given_at,source) "
            "VALUES (?,?,?,?,?,?,?)",
            (table, proposal["row_id"], proposal_id, "approve", person_words, stamp, config.module + " cli by " + actor),
        )
        db.commit()
    except sqlite3.IntegrityError as error:
        schema_failure(db, "accept", error)
    except BaseException:
        db.rollback()
        raise
    print("ok accept", proposal_id)


def reject(db, config, proposal_id, actor, why):
    actor = require_text(actor, "--by")
    why = require_text(why, "--why")
    require_evidence_tables(db)
    ensure_proposals(db)
    try:
        db.execute("BEGIN IMMEDIATE")
        proposal = load_proposal(db, config, proposal_id)
        if proposal["state"] != "pending":
            fail("proposal is not pending: " + proposal_id)
        stamp = now()
        changed = db.execute(
            "UPDATE proposals SET state='rejected',decided_by=?,decided_at=? WHERE id=? AND state='pending'",
            (actor, stamp, proposal_id),
        ).rowcount
        if changed != 1:
            fail("proposal is not pending: " + proposal_id)
        activity(db, config, "proposal", proposal_id, "state", "pending", "rejected", actor, stamp, why)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    print("ok reject", proposal_id)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("--db")
    root.add_argument("--rules", type=Path, default=RULES_PATH, help="proposal rules file; defaults to the shipped base/proposal-rules.md")
    commands = root.add_subparsers(dest="verb", required=True)
    for verb in ("add", "observe"):
        command = commands.add_parser(verb)
        command.add_argument("table")
        command.add_argument("--by", required=True)
        command.add_argument("--set", action="append", default=[], dest="sets")
    command = commands.add_parser("set")
    command.add_argument("table")
    command.add_argument("id")
    command.add_argument("--by", required=True)
    command.add_argument("--set", action="append", default=[], dest="sets")
    command = commands.add_parser("show")
    command.add_argument("table")
    command.add_argument("id")
    command = commands.add_parser("list")
    command.add_argument("table")
    command.add_argument("--where")
    command = commands.add_parser("propose")
    command.add_argument("table")
    command.add_argument("id")
    command.add_argument("--by", required=True)
    command.add_argument("--set", action="append", default=[], dest="sets")
    command.add_argument("--why", required=True)
    command = commands.add_parser("accept")
    command.add_argument("proposal_id")
    command.add_argument("--by", required=True)
    command.add_argument("--person-words", required=True, help="the person's exact approval words")
    command = commands.add_parser("reject")
    command.add_argument("proposal_id")
    command.add_argument("--by", required=True)
    command.add_argument("--why", required=True)
    return root


def main(config: CommandConfig) -> None:
    args = parser().parse_args()
    rules = load_rules(args.rules, config.module)
    history_tables = load_history_tables(config.module)
    db = connect(args.db)
    try:
        if args.verb == "add":
            add_row(db, config, rules, args.table, args.by, parse_assignments(args.sets))
        elif args.verb == "observe":
            add_row(db, config, rules, args.table, args.by, parse_assignments(args.sets), observe=True)
        elif args.verb == "set":
            set_row(
                db, config, rules, history_tables,
                args.table, args.id, args.by, parse_assignments(args.sets),
            )
        elif args.verb == "show":
            show_row(db, config, args.table, args.id)
        elif args.verb == "list":
            list_rows(db, config, args.table, args.where)
        elif args.verb == "propose":
            propose(db, config, rules, args.table, args.id, args.by, parse_assignments(args.sets), args.why)
        elif args.verb == "accept":
            accept(db, config, rules, args.proposal_id, args.by, args.person_words)
        elif args.verb == "reject":
            reject(db, config, args.proposal_id, args.by, args.why)
    finally:
        db.close()
