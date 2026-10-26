#!/usr/bin/env python3
"""Build one workspace SQLite database from the selected module blueprints.

Usage:
  build_database.py <target.sqlite> --modules work --by sol
  build_database.py <target.sqlite> --modules <add-on> --add-only --by sol

The core module is work. Any other name is an add-on: a folder <name>/ or
modules/<name>/ beside base/ that holds blueprint.sql. Its install.json may
list "requires": add-ons that must be in the same request.
"""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path


MODULES_DIR = Path(__file__).resolve().parent.parent
MODULE_ORDER = ("work",)
BLUEPRINTS = {
    "base": (
        (Path(__file__).resolve().parent / 'dictionary.sql'),
        (Path(__file__).resolve().parent / 'dictionary-seed.sql'),
    ),
    "work": (MODULES_DIR / 'work' / 'blueprint.sql',),
}
ADDON_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


def _addon_folder(name: str) -> Path | None:
    """An add-on is a folder beside base/ (or in modules/) that holds blueprint.sql."""
    if name == "base" or not ADDON_NAME.match(name):
        return None
    for folder in (MODULES_DIR / name, MODULES_DIR / 'modules' / name):
        if (folder / 'blueprint.sql').is_file():
            return folder
    return None


def _requires(name: str) -> list[str]:
    folder = _addon_folder(name)
    manifest = folder / 'install.json' if folder else None
    if not manifest or not manifest.is_file():
        return []
    return list(json.loads(manifest.read_text(encoding="utf-8")).get("requires", []))


def _blueprints(name: str) -> tuple[Path, ...]:
    if name in BLUEPRINTS:
        return BLUEPRINTS[name]
    folder = _addon_folder(name)
    if folder is None:
        raise BuildError("unknown module: " + name)
    return (folder / 'blueprint.sql',)


# A table has one category in the summary. Mirrors copy mutable outside state.
# Trends retain dated observations. The remaining physical tables are tables.
OBJECTS = {
    "base": {
        "tables": ("object_types", "fields"),
        "mirrors": (),
        "trends": (),
        "views": ("v_dictionary",),
    },
    "work": {
        "tables": (
            "functions", "goals", "measures", "projects", "tasks",
            "task_links", "activity", "comments", "attachments",
            "decisions", "approvals",
        ),
        "mirrors": (),
        "trends": ("measure_history",),
        "views": (
            "open_decisions", "open_tasks", "needs_me", "this_week",
            "next_step", "eisenhower",
        ),
    },
}


class BuildError(RuntimeError):
    """The requested database build cannot continue safely."""


DICTIONARY_TABLES = {"object_types", "fields"}


def _module_hash(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _ordered_modules(raw_modules: str) -> list[str]:
    requested = [item.strip() for item in raw_modules.split(",") if item.strip()]
    if not requested:
        raise BuildError("--modules must name at least one module")
    unknown = sorted(name for name in set(requested) if name not in MODULE_ORDER and not _addon_folder(name))
    if unknown:
        raise BuildError("unknown module: " + ", ".join(unknown))
    requested_set = set(requested)
    addons = [name for name in dict.fromkeys(requested) if name not in MODULE_ORDER]
    for module in addons:
        missing = set(_requires(module)) - requested_set
        if missing:
            raise BuildError(f"{module} requires module: " + ", ".join(sorted(missing)))
    # Core first, then each add-on after the add-ons it requires.
    ordered = [module for module in MODULE_ORDER if module in requested_set]
    placing: set[str] = set()

    def place(module: str) -> None:
        if module in ordered:
            return
        if module in placing:
            raise BuildError("module requirement loop: " + module)
        placing.add(module)
        for dependency in _requires(module):
            place(dependency)
        ordered.append(module)

    for module in addons:
        place(module)
    return ordered


def _statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip() and not all(
        line.lstrip().startswith("--") or not line.strip()
        for line in buffer.splitlines()
    ):
        raise BuildError("incomplete SQL statement at end of blueprint")
    return statements


def _leading_sql(statement: str) -> str:
    return re.sub(r"\A(?:\s*--[^\n]*(?:\n|\Z))*\s*", "", statement)


def _sql_tokens(statement: str) -> list[tuple[str, int, int]]:
    """Return SQL tokens outside comments and string literals, with source spans."""
    tokens: list[tuple[str, int, int]] = []
    index = 0
    while index < len(statement):
        char = statement[index]
        if char.isspace():
            index += 1
            continue
        if statement.startswith("--", index):
            newline = statement.find("\n", index + 2)
            index = len(statement) if newline < 0 else newline + 1
            continue
        if statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            if end < 0:
                raise BuildError("unterminated SQL comment")
            index = end + 2
            continue
        if char == "'":
            start = index
            index += 1
            while index < len(statement):
                if statement[index] == "'":
                    if index + 1 < len(statement) and statement[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                raise BuildError("unterminated SQL string")
            tokens.append(("<string>", start, index))
            continue
        if char in {'"', '`', '['}:
            start = index
            close = ']' if char == '[' else char
            index += 1
            value: list[str] = []
            while index < len(statement):
                if statement[index] == close:
                    if close != ']' and index + 1 < len(statement) and statement[index + 1] == close:
                        value.append(close)
                        index += 2
                        continue
                    index += 1
                    break
                value.append(statement[index])
                index += 1
            else:
                raise BuildError("unterminated quoted SQL identifier")
            tokens.append(("".join(value), start, index))
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_$-]*", statement[index:])
        if match:
            start = index
            index += len(match.group(0))
            tokens.append((match.group(0), start, index))
            continue
        tokens.append((char, index, index + 1))
        index += 1
    return tokens


def _token_values(statement: str) -> list[str]:
    return [value.upper() for value, _, _ in _sql_tokens(statement)]


def _has_token_sequence(values: list[str], sequence: tuple[str, ...]) -> bool:
    width = len(sequence)
    return any(tuple(values[index:index + width]) == sequence for index in range(len(values) - width + 1))


def _add_only_statement(statement: str, *, path: Path, number: int) -> str | None:
    """Return the only safe executable form of one add-only statement."""
    tokens = _sql_tokens(statement)
    values = [value.upper() for value, _, _ in tokens]
    if not values:
        return None
    if values in (["BEGIN", ";"], ["COMMIT", ";"], ["END", ";"]):
        return None
    if values[:2] == ["PRAGMA", "FOREIGN_KEYS"]:
        return None
    allowed_create = (
        ["CREATE", "TABLE", "IF", "NOT", "EXISTS"],
        ["CREATE", "VIEW", "IF", "NOT", "EXISTS"],
        ["CREATE", "INDEX", "IF", "NOT", "EXISTS"],
    )
    if any(values[:5] == prefix for prefix in allowed_create):
        return statement
    insert_target_index: int | None = None
    safe_missing_row_insert = False
    if values[:4] == ["INSERT", "OR", "IGNORE", "INTO"]:
        insert_target_index = 4
        safe_missing_row_insert = True
    elif values[:2] == ["INSERT", "INTO"]:
        insert_target_index = 2
        safe_missing_row_insert = _has_token_sequence(values, ("WHERE", "NOT", "EXISTS"))
    if insert_target_index is not None:
        target = (
            tokens[insert_target_index][0]
            if len(tokens) > insert_target_index
            else "missing target"
        )
        if target.lower() not in DICTIONARY_TABLES:
            raise BuildError(
                f"{path}: statement {number}: add-only INSERT is limited to dictionary tables; got {target}"
            )
        if (
            not safe_missing_row_insert
            or _has_token_sequence(values, ("ON", "CONFLICT"))
        ):
            head = " ".join(value for value in values[:5] if value != ";")
            raise BuildError(
                f"{path}: statement {number}: add-only refused unsafe statement: {head}"
            )
        return statement
    head = " ".join(value for value in values[:5] if value != ";")
    raise BuildError(
        f"{path}: statement {number}: add-only refused unsafe statement: {head}"
    )


def _created_object(statement: str) -> tuple[str, str] | None:
    tokens = _sql_tokens(statement)
    values = [value.upper() for value, _, _ in tokens]
    if len(tokens) >= 6 and values[:5] in (
        ["CREATE", "TABLE", "IF", "NOT", "EXISTS"],
        ["CREATE", "VIEW", "IF", "NOT", "EXISTS"],
        ["CREATE", "INDEX", "IF", "NOT", "EXISTS"],
    ):
        return values[1].lower(), tokens[5][0]
    return None


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_signature(db: sqlite3.Connection, name: str) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row[1:7])
        for row in db.execute(f"PRAGMA table_xinfo({_quote_identifier(name)})")
    )


def _expected_table_signature(statement: str, name: str) -> tuple[tuple[object, ...], ...]:
    expected = _fox_person.connect(":memory:")
    try:
        expected.execute(statement)
        return _table_signature(expected, name)
    finally:
        expected.close()


def _canonical_sql(sql: str) -> str:
    sql = re.sub(
        r"\A(\s*CREATE\s+(?:TABLE|VIEW|INDEX)\s+)IF\s+NOT\s+EXISTS\s+",
        r"\1",
        sql,
        flags=re.IGNORECASE,
    )
    return " ".join(sql.strip().rstrip(";").split()).lower()


def _existing_object(db: sqlite3.Connection, name: str) -> tuple[str, str | None] | None:
    row = db.execute(
        "SELECT type, sql FROM sqlite_master WHERE lower(name)=lower(?)",
        (name,),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _compatibility_reason(
    db: sqlite3.Connection,
    statement: str,
    *,
    path: Path,
    number: int,
) -> str | None:
    created = _created_object(statement)
    if not created:
        return None
    kind, name = created
    existing = _existing_object(db, name)
    if not existing:
        return None
    if existing[0] != kind:
        return f"{path}: statement {number}: {name} exists as {existing[0]}, expected {kind}"
    if kind == "table":
        expected = _expected_table_signature(statement, name)
        actual = _table_signature(db, name)
        if actual != expected:
            expected_names = ", ".join(str(row[0]) for row in expected)
            actual_names = ", ".join(str(row[0]) for row in actual)
            return (
                f"{path}: statement {number}: incompatible table {name}; "
                f"expected columns [{expected_names}], found [{actual_names}]"
            )
    if kind == "view" and existing[1] and _canonical_sql(existing[1]) != _canonical_sql(statement):
        return f"{path}: statement {number}: incompatible existing view {name}"
    return None


def _existing_tables(db: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _has_rows(db: sqlite3.Connection) -> bool:
    for table in _existing_tables(db):
        quoted = table.replace('"', '""')
        if db.execute(f'SELECT 1 FROM "{quoted}" LIMIT 1').fetchone():
            return True
    return False


def _installed(db: sqlite3.Connection) -> set[tuple[str, str]]:
    if "installed_modules" not in _existing_tables(db):
        return set()
    return {
        (row[0], row[1])
        for row in db.execute(
            "SELECT module, blueprint_hash FROM installed_modules "
            "WHERE status='complete'"
        )
    }


def _apply_statement(
    db: sqlite3.Connection,
    statement: str,
    *,
    module: str,
    path: Path,
    number: int,
    add_only: bool,
    skip_broken: bool,
) -> str | None:
    leading = _leading_sql(statement).strip()
    if not leading:
        return None
    tokens = [value for value in _token_values(leading) if value != ";"]
    if tokens in (["BEGIN"], ["BEGIN", "TRANSACTION"], ["COMMIT"], ["END"], ["END", "TRANSACTION"]):
        return None
    if tokens[:2] == ["PRAGMA", "FOREIGN_KEYS"]:
        return None
    if tokens[:1] == ["DROP"]:
        raise BuildError(f"{path}: statement {number}: DROP is not allowed")
    savepoint = f"blueprint_{number}"
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        db.execute(statement)
    except sqlite3.Error as exc:
        db.execute(f"ROLLBACK TO {savepoint}")
        db.execute(f"RELEASE {savepoint}")
        failure = f"{path}: statement {number}: {exc}"
        if skip_broken:
            return failure
        raise BuildError(failure) from exc
    db.execute(f"RELEASE {savepoint}")
    return None


def _objects(module: str) -> dict[str, tuple[str, ...]]:
    """Core modules name their categories; an add-on counts what its blueprint creates."""
    if module in OBJECTS:
        return OBJECTS[module]
    created = [
        _created_object(statement)
        for path in _blueprints(module)
        for statement in _statements(path.read_text(encoding="utf-8"))
    ]
    return {
        "tables": tuple(name for kind, name in filter(None, created) if kind == "table"),
        "mirrors": (),
        "trends": (),
        "views": tuple(name for kind, name in filter(None, created) if kind == "view"),
    }


def _summary(db: sqlite3.Connection, modules: list[str]) -> list[str]:
    objects = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    lines = []
    for module in modules:
        counts = {}
        for category, names in _objects(module).items():
            expected_type = "view" if category == "views" else "table"
            counts[category] = sum(objects.get(name) == expected_type for name in names)
        lines.append(
            f"{module}: tables {counts['tables']}, mirrors {counts['mirrors']}, "
            f"trends {counts['trends']}, views {counts['views']}"
        )
    return lines


def build_database(
    target: Path,
    raw_modules: str,
    *,
    actor: str,
    add_only: bool = False,
    skip_broken: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """Build target and return (summary lines, applied modules, skipped failures)."""
    if not actor.strip():
        raise BuildError("--by must name the installer")
    modules = _ordered_modules(raw_modules)
    plan = ["base", *modules]
    paths_by_module = {module: _blueprints(module) for module in plan}
    hashes = {module: _module_hash(paths) for module, paths in paths_by_module.items()}
    for paths in paths_by_module.values():
        for path in paths:
            if not path.is_file():
                raise BuildError(f"blueprint not found: {path}")
    if not target.parent.is_dir():
        raise BuildError(f"target directory does not exist: {target.parent}")

    # Add-only adds modules. The core dictionary is applied only where it is missing:
    # its seed refreshes rows with UPDATE, which add-only never runs on an existing dictionary.
    keep_dictionary = False
    if add_only and target.is_file():
        probe = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            keep_dictionary = DICTIONARY_TABLES <= set(_existing_tables(probe))
        finally:
            probe.close()

    prepared: dict[str, list[tuple[Path, int, str]]] = {}
    for module, paths in paths_by_module.items():
        prepared[module] = []
        if module == "base" and keep_dictionary:
            continue
        statement_number = 0
        for path in paths:
            sql = path.read_text(encoding="utf-8")
            for statement in _statements(sql):
                statement_number += 1
                safe_statement = (
                    _add_only_statement(statement, path=path, number=statement_number)
                    if add_only
                    else statement
                )
                if safe_statement is not None:
                    prepared[module].append((path, statement_number, safe_statement))

    db = _fox_person.connect(target, isolation_level=None)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        installed = _installed(db)
        if add_only:
            pending = [module for module in plan if not (module == "base" and keep_dictionary)]
        else:
            pending = [module for module in plan if (module, hashes[module]) not in installed]
        if not pending:
            return _summary(db, plan), [], []
        if _has_rows(db) and not add_only:
            raise BuildError("target already has rows; use --add-only to create only missing objects")

        applied: list[str] = []
        skipped: list[str] = []
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS installed_modules ("
                "module TEXT NOT NULL, blueprint_hash TEXT NOT NULL, "
                "blueprint_paths TEXT NOT NULL, applied_at TEXT NOT NULL, "
                "status TEXT NOT NULL CHECK (status IN ('complete','partial')), "
                "skipped_statements INTEGER NOT NULL DEFAULT 0, actor TEXT NOT NULL, "
                "reason TEXT, "
                "PRIMARY KEY (module, blueprint_hash))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS module_install_activity ("
                "id INTEGER PRIMARY KEY, module TEXT NOT NULL, blueprint_hash TEXT NOT NULL, "
                "actor TEXT NOT NULL, applied_at TEXT NOT NULL, "
                "status TEXT NOT NULL CHECK (status IN ('complete','partial')), "
                "reason TEXT)"
            )
            for module in pending:
                module_skipped = 0
                module_reasons: list[str] = []
                module_views: list[tuple[Path, int, str]] = []
                for path, statement_number, statement in prepared[module]:
                    created = _created_object(statement)
                    if created and created[0] == "view":
                        module_views.append((path, statement_number, created[1]))
                    if add_only:
                        reason = _compatibility_reason(
                            db,
                            statement,
                            path=path,
                            number=statement_number,
                        )
                        if reason:
                            skipped.append(reason)
                            module_reasons.append(reason)
                            module_skipped += 1
                            continue
                    failure = _apply_statement(
                        db,
                        statement,
                        module=module,
                        path=path,
                        number=statement_number,
                        add_only=add_only,
                        skip_broken=skip_broken,
                    )
                    if failure:
                        skipped.append(failure)
                        module_reasons.append(failure)
                        module_skipped += 1
                for path, statement_number, view_name in module_views:
                    try:
                        db.execute(f"EXPLAIN QUERY PLAN SELECT * FROM {_quote_identifier(view_name)} LIMIT 0")
                    except sqlite3.Error as exc:
                        reason = (
                            f"{path}: statement {statement_number}: invalid view {view_name}: {exc}"
                        )
                        if reason not in module_reasons:
                            skipped.append(reason)
                            module_reasons.append(reason)
                            module_skipped += 1
                applied_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                status = "partial" if module_skipped else "complete"
                reason_text = " | ".join(module_reasons) or None
                install_columns = {
                    row[1] for row in db.execute("PRAGMA table_info(installed_modules)")
                }
                values = {
                    "module": module,
                    "blueprint_hash": hashes[module],
                    "blueprint_paths": ",".join(
                        str(path.relative_to(MODULES_DIR)) if path.is_relative_to(MODULES_DIR) else str(path)
                        for path in paths_by_module[module]
                    ),
                    "applied_at": applied_at,
                    "status": status,
                    "skipped_statements": module_skipped,
                    "actor": actor.strip(),
                    "reason": reason_text,
                }
                names = [name for name in values if name in install_columns]
                db.execute(
                    f"INSERT OR IGNORE INTO installed_modules ({', '.join(names)}) "
                    f"VALUES ({', '.join('?' for _ in names)})",
                    tuple(values[name] for name in names),
                )
                db.execute(
                    "INSERT INTO module_install_activity "
                    "(module, blueprint_hash, actor, applied_at, status, reason) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (module, hashes[module], actor.strip(), applied_at, status, reason_text),
                )
                applied.append(module)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return _summary(db, plan), applied, skipped
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build one SQLite database from module blueprints."
    )
    parser.add_argument("target", type=Path)
    parser.add_argument("--modules", required=True)
    parser.add_argument("--by", required=True, help="Actor installing the modules.")
    parser.add_argument("--add-only", action="store_true")
    parser.add_argument("--skip-broken", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary, applied, skipped = build_database(
            args.target,
            args.modules,
            actor=args.by,
            add_only=args.add_only,
            skip_broken=args.skip_broken,
        )
    except (BuildError, sqlite3.Error, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("applied: " + (", ".join(applied) if applied else "none"))
    for line in summary:
        print(line)
    for failure in skipped:
        print("skipped: " + failure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
