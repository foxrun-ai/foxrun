#!/usr/bin/env python3
"""Create and restore one private, source-bound SQLite recovery bundle."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import base64
from collections import Counter
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile


HERE = (Path(__file__).resolve().parent)
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import recovery_values as core


FORMAT = "foxrun-private-recovery-v2"
SCHEMA_TYPES = ("table", "index", "view", "trigger")
ROWID_FIELD = "$foxrun_rowid"


class BundleError(RuntimeError):
    """The recovery bundle cannot be created or restored safely."""


def canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_digest(manifest: dict) -> str:
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    return sha256_bytes(canonical_json(unsigned).encode("utf-8"))


def _write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _load_build_tool(path: Path):
    if path.is_symlink() or not path.is_file():
        raise BundleError("build tool must be a regular file: " + str(path))
    name = "foundation_recovery_build_database"
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise BundleError("cannot load build tool: " + str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _schema_entries(db: sqlite3.Connection) -> list[dict]:
    return [
        {"type": row[0], "name": row[1], "table": row[2], "sql": row[3]}
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE type IN ('table','index','view','trigger') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    ]


def _schema_digest(entries: list[dict]) -> str:
    return sha256_bytes(canonical_json(entries).encode("utf-8"))


def _canonical_sql(value: str | None) -> str | None:
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
        raise BundleError("schema SQL has an unterminated quoted value")
    return "".join(result).strip()


def _schema_map(entries: list[dict]) -> dict[tuple[str, str], dict]:
    result = {}
    for entry in entries:
        key = (entry["type"], entry["name"])
        if key in result:
            raise BundleError("duplicate schema object: " + repr(key))
        result[key] = entry
    return result


def _physical_tables(db: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _columns(db: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(db.execute("PRAGMA table_xinfo(" + core.quote_identifier(table) + ")"))


def _implicit_rowid_accessor(
    db: sqlite3.Connection, table: str, columns: list[sqlite3.Row]
) -> str | None:
    table_row = next(
        (
            row
            for row in db.execute("PRAGMA table_list")
            if row[0] == "main" and row[1] == table and row[2] == "table"
        ),
        None,
    )
    if table_row is None:
        raise BundleError("table is missing from table_list: " + table)
    if table_row[4]:
        return None
    primary = [row for row in columns if row["pk"] > 0]
    has_primary_index = any(
        row[3] == "pk"
        for row in db.execute(
            "PRAGMA index_list(" + core.quote_identifier(table) + ")"
        )
    )
    if (
        len(primary) == 1
        and primary[0]["type"].strip().upper() == "INTEGER"
        and not has_primary_index
    ):
        return None
    names = {row["name"].casefold() for row in columns}
    if ROWID_FIELD.casefold() in names:
        raise BundleError("table uses reserved recovery column name: " + table)
    for candidate in ("rowid", "_rowid_", "oid"):
        if candidate.casefold() not in names:
            return candidate
    raise BundleError("implicit rowid is inaccessible because all aliases are shadowed: " + table)


def _refuse_unsupported_schema(db: sqlite3.Connection) -> None:
    for row in db.execute("PRAGMA table_list"):
        schema, name, kind = row[0], row[1], row[2]
        if schema == "main" and not name.lower().startswith("sqlite_") and kind in {
            "virtual",
            "shadow",
        }:
            raise BundleError("unsupported virtual schema object: " + name)
    for table in _physical_tables(db):
        hidden = [row["name"] for row in _columns(db, table) if row["hidden"] != 0]
        if hidden:
            raise BundleError(
                "unsupported generated or hidden columns in "
                + table
                + ": "
                + ", ".join(hidden)
            )


def _module_reference(build_tool, modules: str, root: Path) -> dict:
    plan = ["base", *build_tool._ordered_modules(modules)]
    target = root / "module-reference.sqlite"
    try:
        build_tool.build_database(target, modules, actor="recovery-bundle")
    except Exception as error:
        raise BundleError("module reference build failed: " + str(error)) from error
    db = _fox_person.connect(target)
    db.row_factory = sqlite3.Row
    try:
        _refuse_unsupported_schema(db)
        entries = _schema_entries(db)
    finally:
        db.close()
    hashes = {
        module: build_tool._module_hash(build_tool._blueprints(module))
        for module in plan
    }
    return {
        "modules": plan,
        "blueprint_hashes": hashes,
        "schema": entries,
        "schema_digest": _schema_digest(entries),
    }


def _verify_source_modules(
    db: sqlite3.Connection, source_entries: list[dict], reference: dict
) -> list[dict]:
    source_map = _schema_map(source_entries)
    reference_map = _schema_map(reference["schema"])
    for key, expected in reference_map.items():
        actual = source_map.get(key)
        if actual is None:
            raise BundleError("source is missing module schema object: " + repr(key))
        if _canonical_sql(actual["sql"]) != _canonical_sql(expected["sql"]):
            raise BundleError("source module schema differs from blueprint: " + repr(key))
    if "installed_modules" not in _physical_tables(db):
        raise BundleError("source has no installed_modules identity table")
    installed_names = {
        row[0]
        for row in db.execute(
            "SELECT DISTINCT module FROM installed_modules WHERE status='complete'"
        )
    }
    if installed_names != set(reference["modules"]):
        raise BundleError(
            "source installed module set does not match selection; missing="
            + repr(sorted(set(reference["modules"]) - installed_names))
            + ", extra="
            + repr(sorted(installed_names - set(reference["modules"])))
        )
    for module in reference["modules"]:
        matched = db.execute(
            "SELECT 1 FROM installed_modules "
            "WHERE module=? AND blueprint_hash=? AND status='complete' LIMIT 1",
            (module, reference["blueprint_hashes"][module]),
        ).fetchone()
        if matched is None:
            raise BundleError(
                "source module identity is missing or stale: " + module
            )
    return [
        entry
        for key, entry in source_map.items()
        if key not in reference_map
    ]


def _encode_value(value):
    if isinstance(value, bytes):
        return {"$blob": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        raise BundleError("non-finite SQLite value cannot enter JSONL")
    return value


def _export_table(db: sqlite3.Connection, table: str, path: Path) -> dict:
    info = _columns(db, table)
    fields = [row["name"] for row in info]
    rowid_accessor = _implicit_rowid_accessor(db, table, info)
    primary = [
        row["name"]
        for row in sorted(info, key=lambda item: item["pk"])
        if row["pk"] > 0
    ]
    ordering = primary + sorted(set(fields) - set(primary))
    selected = [core.quote_identifier(field) for field in fields]
    if rowid_accessor is not None:
        selected.insert(
            0,
            core.quote_identifier(rowid_accessor)
            + " AS "
            + core.quote_identifier(ROWID_FIELD),
        )
    query = (
        "SELECT "
        + ",".join(selected)
        + " FROM "
        + core.quote_identifier(table)
    )
    if rowid_accessor is not None:
        query += " ORDER BY " + core.quote_identifier(rowid_accessor)
    elif ordering:
        query += " ORDER BY " + ",".join(
            core.quote_identifier(field) + " COLLATE BINARY" for field in ordering
        )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    count = 0
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for row in db.execute(query):
                record = {field: _encode_value(row[field]) for field in fields}
                if rowid_accessor is not None:
                    record[ROWID_FIELD] = row[ROWID_FIELD]
                stream.write(canonical_json(record) + "\n")
                count += 1
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return {
        "table": table,
        "file": "tables/" + path.name,
        "sha256": sha256_file(path),
        "row_count": count,
        "columns": fields,
        "primary_key": primary,
        "implicit_rowid_accessor": rowid_accessor,
    }


def _sqlite_metadata(db: sqlite3.Connection) -> dict:
    tables = _physical_tables(db)
    sequences = []
    if db.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone():
        sequences = [
            {"table": row[0], "sequence": row[1]}
            for row in db.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name")
        ]
    return {
        "user_version": db.execute("PRAGMA user_version").fetchone()[0],
        "application_id": db.execute("PRAGMA application_id").fetchone()[0],
        "sqlite_sequence": sequences,
        "table_count": len(tables),
    }


def _online_snapshot(source: Path, snapshot: Path) -> None:
    source = source.expanduser().resolve(strict=True)
    if not source.is_file():
        raise BundleError("source must be a SQLite file")
    source_db = _fox_person.connect(source.as_uri() + "?mode=ro", uri=True)
    target_db = _fox_person.connect(snapshot)
    try:
        source_db.execute("PRAGMA query_only = ON")
        source_db.backup(target_db)
    except sqlite3.Error as error:
        raise BundleError("SQLite online backup failed: " + str(error)) from error
    finally:
        target_db.close()
        source_db.close()


def _publish_bundle(stage: Path, bundle: Path, table_files: list[dict]) -> None:
    if os.path.lexists(bundle):
        raise BundleError("bundle directory already exists; nothing was overwritten")
    created = False
    try:
        os.mkdir(bundle, 0o700)
        created = True
        os.mkdir(bundle / "tables", 0o700)
        for item in table_files:
            os.link(stage / item["file"], bundle / item["file"])
        os.link(stage / "manifest.json", bundle / "manifest.json")
    except BaseException:
        if created:
            shutil.rmtree(bundle)
        raise


def create_bundle(
    source: Path,
    bundle: Path,
    modules: str,
    *,
    build_tool,
) -> dict:
    source = Path(source).expanduser().resolve(strict=True)
    bundle = Path(bundle).expanduser().absolute()
    if os.path.lexists(bundle):
        raise BundleError("bundle directory already exists; nothing was overwritten")
    if not bundle.parent.is_dir() or bundle.parent.is_symlink():
        raise BundleError("bundle parent must be an existing regular directory")
    if bundle.parent.resolve(strict=True) != bundle.parent:
        raise BundleError("bundle parent must not traverse symbolic links")
    with tempfile.TemporaryDirectory(
        prefix=".recovery-bundle-stage-", dir=bundle.parent
    ) as directory:
        stage = Path(directory)
        (stage / "tables").mkdir(mode=0o700)
        snapshot = stage / "source-snapshot.sqlite"
        _online_snapshot(source, snapshot)
        reference = _module_reference(build_tool, modules, stage)
        db = _fox_person.connect(snapshot)
        db.row_factory = sqlite3.Row
        try:
            _refuse_unsupported_schema(db)
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise BundleError("source integrity check failed: " + str(integrity))
            violations = list(db.execute("PRAGMA foreign_key_check"))
            if violations:
                raise BundleError(
                    "source foreign key defect: " + repr(tuple(violations[0]))
                )
            entries = _schema_entries(db)
            runtime_schema = _verify_source_modules(db, entries, reference)
            table_files = []
            for number, table in enumerate(_physical_tables(db), start=1):
                payload = stage / "tables" / f"{number:04d}.jsonl"
                table_files.append(_export_table(db, table, payload))
            metadata = _sqlite_metadata(db)
        finally:
            db.close()
        manifest = {
            "format": FORMAT,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source_path": str(source),
            "snapshot_sha256": sha256_file(snapshot),
            "modules": reference["modules"],
            "blueprint_hashes": reference["blueprint_hashes"],
            "known_schema_digest": reference["schema_digest"],
            "schema": entries,
            "schema_digest": _schema_digest(entries),
            "runtime_schema": [
                {"type": item["type"], "name": item["name"]}
                for item in runtime_schema
            ],
            "metadata": metadata,
            "tables": table_files,
            "row_count": sum(item["row_count"] for item in table_files),
        }
        manifest["manifest_sha256"] = _manifest_digest(manifest)
        _write_private(
            stage / "manifest.json",
            (canonical_json(manifest) + "\n").encode("utf-8"),
        )
        _publish_bundle(stage, bundle, table_files)
        return {
            "status": "private_recovery_bundle_created",
            "bundle": str(bundle),
            "manifest_sha256": manifest["manifest_sha256"],
            "schema_digest": manifest["schema_digest"],
            "tables": len(table_files),
            "rows": manifest["row_count"],
            "runtime_schema": manifest["runtime_schema"],
        }


def _read_manifest(bundle: Path) -> dict:
    path = bundle / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise BundleError("bundle manifest is missing or not a regular file")
    try:
        manifest = core.strict_json(path.read_text(encoding="utf-8"), str(path))
    except (OSError, UnicodeError, core.RestoreError) as error:
        raise BundleError("bundle manifest is invalid: " + str(error)) from error
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BundleError("unsupported recovery bundle format")
    digest = manifest.get("manifest_sha256")
    if not isinstance(digest, str) or digest != _manifest_digest(manifest):
        raise BundleError("bundle manifest digest mismatch")
    schema = manifest.get("schema")
    if not isinstance(schema, list) or manifest.get("schema_digest") != _schema_digest(schema):
        raise BundleError("bundle schema digest mismatch")
    _validate_manifest_shape(manifest)
    return manifest


def _is_sha256(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_manifest_shape(manifest: dict) -> None:
    required = {
        "format",
        "created_at",
        "source_path",
        "snapshot_sha256",
        "modules",
        "blueprint_hashes",
        "known_schema_digest",
        "schema",
        "schema_digest",
        "runtime_schema",
        "metadata",
        "tables",
        "row_count",
        "manifest_sha256",
    }
    if set(manifest) != required:
        raise BundleError("bundle manifest fields are invalid")
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"]:
        raise BundleError("bundle created_at is invalid")
    if (
        not isinstance(manifest["source_path"], str)
        or not Path(manifest["source_path"]).is_absolute()
    ):
        raise BundleError("bundle source_path is invalid")
    for key in (
        "snapshot_sha256",
        "known_schema_digest",
        "schema_digest",
        "manifest_sha256",
    ):
        if not _is_sha256(manifest[key]):
            raise BundleError("bundle " + key + " is invalid")
    modules = manifest["modules"]
    if (
        not isinstance(modules, list)
        or any(not isinstance(value, str) or not value for value in modules)
        or len(set(modules)) != len(modules)
    ):
        raise BundleError("bundle modules are invalid")
    hashes = manifest["blueprint_hashes"]
    if (
        not isinstance(hashes, dict)
        or set(hashes) != set(modules)
        or any(not _is_sha256(value) for value in hashes.values())
    ):
        raise BundleError("bundle blueprint_hashes are invalid")
    for number, entry in enumerate(manifest["schema"], start=1):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"type", "name", "table", "sql"}
            or entry["type"] not in SCHEMA_TYPES
            or not isinstance(entry["name"], str)
            or not entry["name"]
            or not isinstance(entry["table"], str)
            or not entry["table"]
            or not isinstance(entry["sql"], str)
            or not entry["sql"].strip()
        ):
            raise BundleError(f"bundle schema entry {number} is invalid")
    runtime = manifest["runtime_schema"]
    if not isinstance(runtime, list):
        raise BundleError("bundle runtime_schema is invalid")
    for number, entry in enumerate(runtime, start=1):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"type", "name"}
            or entry["type"] not in SCHEMA_TYPES
            or not isinstance(entry["name"], str)
            or not entry["name"]
        ):
            raise BundleError(f"bundle runtime schema entry {number} is invalid")
    metadata = manifest["metadata"]
    if not isinstance(metadata, dict) or set(metadata) != {
        "user_version",
        "application_id",
        "sqlite_sequence",
        "table_count",
    }:
        raise BundleError("bundle SQLite metadata is invalid")
    for key in ("user_version", "application_id", "table_count"):
        if isinstance(metadata[key], bool) or not isinstance(metadata[key], int):
            raise BundleError("bundle SQLite metadata has an invalid " + key)
    if not isinstance(metadata["sqlite_sequence"], list):
        raise BundleError("bundle sqlite_sequence is invalid")
    if (
        isinstance(manifest["row_count"], bool)
        or not isinstance(manifest["row_count"], int)
        or manifest["row_count"] < 0
    ):
        raise BundleError("bundle row_count is invalid")


def _verify_module_binding(manifest: dict, reference: dict) -> None:
    if manifest.get("modules") != reference["modules"]:
        raise BundleError("bundle module list does not match supplied modules")
    if manifest.get("blueprint_hashes") != reference["blueprint_hashes"]:
        raise BundleError("bundle blueprint hashes do not match supplied blueprints")
    if manifest.get("known_schema_digest") != reference["schema_digest"]:
        raise BundleError("bundle known-schema digest does not match supplied blueprints")
    source_map = _schema_map(manifest["schema"])
    reference_map = _schema_map(reference["schema"])
    for key, expected in reference_map.items():
        actual = source_map.get(key)
        if actual is None or _canonical_sql(actual["sql"]) != _canonical_sql(expected["sql"]):
            raise BundleError("bundle module schema binding failed: " + repr(key))
    extras = [
        {"type": entry["type"], "name": entry["name"]}
        for key, entry in source_map.items()
        if key not in reference_map
    ]
    if manifest.get("runtime_schema") != extras:
        raise BundleError("bundle runtime schema list does not match captured schema")


DDL_PREFIXES = {
    "table": re.compile(r"^\s*CREATE\s+TABLE\b", re.IGNORECASE),
    "index": re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\b", re.IGNORECASE),
    "view": re.compile(r"^\s*CREATE\s+VIEW\b", re.IGNORECASE),
    "trigger": re.compile(r"^\s*CREATE\s+TRIGGER\b", re.IGNORECASE),
}

DDL_ACTIONS = {
    "table": sqlite3.SQLITE_CREATE_TABLE,
    "index": sqlite3.SQLITE_CREATE_INDEX,
    "view": sqlite3.SQLITE_CREATE_VIEW,
    "trigger": sqlite3.SQLITE_CREATE_TRIGGER,
}


def _validate_schema_ddl(entries: list[dict]) -> None:
    _schema_map(entries)
    for entry in entries:
        kind = entry.get("type")
        sql = entry.get("sql")
        if (
            kind not in DDL_PREFIXES
            or not isinstance(sql, str)
            or "\x00" in sql
            or DDL_PREFIXES[kind].match(sql) is None
        ):
            raise BundleError(
                "unsafe or mismatched schema statement: "
                + repr((kind, entry.get("name")))
            )


def _schema_authorizer(kind: str, name: str):
    expected_action = DDL_ACTIONS[kind]

    def authorize(action, argument1, argument2, database, source):
        if action == expected_action and argument1 == name and database == "main":
            return sqlite3.SQLITE_OK
        if (
            kind == "table"
            and action == sqlite3.SQLITE_CREATE_TABLE
            and argument1 == "sqlite_sequence"
            and database == "main"
        ):
            return sqlite3.SQLITE_OK
        if (
            kind == "table"
            and action == sqlite3.SQLITE_CREATE_INDEX
            and isinstance(argument1, str)
            and argument1.startswith("sqlite_autoindex_" + name + "_")
            and argument2 == name
            and database == "main"
        ):
            return sqlite3.SQLITE_OK
        if (
            action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
            and argument1 in {"sqlite_master", "sqlite_schema"}
            and database == "main"
        ):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and database in {None, "main"}:
            return sqlite3.SQLITE_OK
        if (
            action == sqlite3.SQLITE_FUNCTION
            and isinstance(argument2, str)
            and argument2.lower() not in {"load_extension", "readfile", "writefile"}
        ):
            return sqlite3.SQLITE_OK
        if (
            kind == "index"
            and action == sqlite3.SQLITE_REINDEX
            and argument1 == name
            and database == "main"
        ):
            return sqlite3.SQLITE_OK
        if kind in {"view", "trigger"} and action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return authorize


def _create_schema(
    db: sqlite3.Connection, entries: list[dict], kinds: tuple[str, ...]
) -> None:
    for kind in kinds:
        for entry in entries:
            if entry.get("type") != kind:
                continue
            sql = entry.get("sql")
            before = _schema_map(_schema_entries(db))
            db.set_authorizer(_schema_authorizer(kind, entry["name"]))
            try:
                db.execute(sql)
            except sqlite3.Error as error:
                raise BundleError(
                    "captured schema cannot be recreated: "
                    + repr((kind, entry.get("name")))
                    + ": "
                    + str(error)
                ) from error
            finally:
                db.set_authorizer(lambda *arguments: sqlite3.SQLITE_OK)
            after = _schema_map(_schema_entries(db))
            new_keys = set(after) - set(before)
            key = (kind, entry["name"])
            if new_keys != {key}:
                raise BundleError(
                    "schema statement created unexpected objects: " + repr(key)
                )
            actual = after[key]
            if (
                actual["table"] != entry["table"]
                or _canonical_sql(actual["sql"]) != _canonical_sql(sql)
            ):
                raise BundleError(
                    "schema statement did not create its declared object: " + repr(key)
                )


def _validate_table_payloads(bundle: Path, manifest: dict) -> dict[str, list[dict]]:
    items = manifest.get("tables")
    if not isinstance(items, list):
        raise BundleError("bundle tables must be a list")
    parsed = {}
    total = 0
    seen_files = set()
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict) or set(item) != {
            "table",
            "file",
            "sha256",
            "row_count",
            "columns",
            "primary_key",
            "implicit_rowid_accessor",
        }:
            raise BundleError(f"bundle table entry {number} is invalid")
        table = item["table"]
        relative = item["file"]
        expected_file = f"tables/{number:04d}.jsonl"
        if not isinstance(table, str) or relative != expected_file:
            raise BundleError(f"bundle table entry {number} has an invalid identity")
        if (
            not _is_sha256(item["sha256"])
            or isinstance(item["row_count"], bool)
            or not isinstance(item["row_count"], int)
            or item["row_count"] < 0
            or not isinstance(item["columns"], list)
            or not item["columns"]
            or any(not isinstance(value, str) or not value for value in item["columns"])
            or len(set(item["columns"])) != len(item["columns"])
            or not isinstance(item["primary_key"], list)
            or any(value not in item["columns"] for value in item["primary_key"])
            or item["implicit_rowid_accessor"] not in {None, "rowid", "_rowid_", "oid"}
        ):
            raise BundleError(f"bundle table entry {number} has invalid metadata")
        path = bundle / relative
        if path.is_symlink() or not path.is_file() or path.resolve(strict=True).parent != (bundle / "tables"):
            raise BundleError("bundle payload is missing or unsafe: " + str(path))
        if path in seen_files:
            raise BundleError("bundle payload is mapped twice: " + str(path))
        seen_files.add(path)
        if item["sha256"] != sha256_file(path):
            raise BundleError("bundle payload digest mismatch: " + table)
        try:
            records = core._read_jsonl(path, table)
        except core.RestoreError as error:
            raise BundleError("bundle payload is invalid: " + str(error)) from error
        if item["row_count"] != len(records):
            raise BundleError("bundle row count mismatch: " + table)
        if table in parsed:
            raise BundleError("duplicate bundle table: " + table)
        parsed[table] = records
        total += len(records)
    if manifest.get("row_count") != total:
        raise BundleError("bundle total row count mismatch")
    return parsed


def _validate_payload_records(
    table: str,
    records: list[dict],
    fields: list[str],
    rowid_accessor: str | None,
) -> None:
    expected = set(fields)
    if rowid_accessor is not None:
        expected.add(ROWID_FIELD)
    for number, record in enumerate(records, start=1):
        if set(record) != expected:
            missing = sorted(expected - set(record))
            extra = sorted(set(record) - expected)
            raise BundleError(
                f"{table} row {number} fields do not match schema; "
                f"missing={missing!r}, extra={extra!r}"
            )
        if rowid_accessor is not None:
            rowid = record[ROWID_FIELD]
            if isinstance(rowid, bool) or not isinstance(rowid, int):
                raise BundleError(
                    f"{table} row {number} has an invalid implicit rowid"
                )


def _insert_table_records(
    db: sqlite3.Connection,
    table: str,
    fields: list[str],
    records: list[dict],
    rowid_accessor: str | None,
) -> None:
    if not records:
        return
    insert_fields = list(fields)
    record_fields = list(fields)
    if rowid_accessor is not None:
        insert_fields.insert(0, rowid_accessor)
        record_fields.insert(0, ROWID_FIELD)
    sql = (
        "INSERT INTO "
        + core.quote_identifier(table)
        + " ("
        + ",".join(core.quote_identifier(field) for field in insert_fields)
        + ") VALUES ("
        + ",".join("?" for _ in insert_fields)
        + ")"
    )
    db.executemany(
        sql,
        ([record[field] for field in record_fields] for record in records),
    )


def _assert_table_rows(
    db: sqlite3.Connection,
    table: str,
    fields: list[str],
    records: list[dict],
    rowid_accessor: str | None,
) -> None:
    selected = [core.quote_identifier(field) for field in fields]
    record_fields = list(fields)
    if rowid_accessor is not None:
        selected.insert(0, core.quote_identifier(rowid_accessor))
        record_fields.insert(0, ROWID_FIELD)
    actual = Counter(
        tuple(row)
        for row in db.execute(
            "SELECT "
            + ",".join(selected)
            + " FROM "
            + core.quote_identifier(table)
        )
    )
    expected = Counter(
        tuple(record[field] for field in record_fields) for record in records
    )
    if actual != expected:
        raise BundleError(
            "restored rows or implicit rowids do not match bundle for " + table
        )


def _restore_metadata(db: sqlite3.Connection, metadata: dict) -> None:
    if not isinstance(metadata, dict) or set(metadata) != {
        "user_version",
        "application_id",
        "sqlite_sequence",
        "table_count",
    }:
        raise BundleError("bundle SQLite metadata is invalid")
    for key in ("user_version", "application_id", "table_count"):
        if isinstance(metadata[key], bool) or not isinstance(metadata[key], int):
            raise BundleError("bundle SQLite metadata has an invalid " + key)
    sequences = metadata["sqlite_sequence"]
    if not isinstance(sequences, list):
        raise BundleError("bundle sqlite_sequence must be a list")
    if db.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone():
        db.execute("DELETE FROM sqlite_sequence")
        for item in sequences:
            if (
                not isinstance(item, dict)
                or set(item) != {"table", "sequence"}
                or not isinstance(item["table"], str)
                or isinstance(item["sequence"], bool)
                or not isinstance(item["sequence"], int)
            ):
                raise BundleError("bundle sqlite_sequence row is invalid")
            db.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)",
                (item["table"], item["sequence"]),
            )
    elif sequences:
        raise BundleError("bundle has sequences but captured schema has no AUTOINCREMENT")
    db.execute("PRAGMA user_version = " + str(metadata["user_version"]))
    db.execute("PRAGMA application_id = " + str(metadata["application_id"]))


def restore_bundle(
    bundle: Path,
    target: Path,
    modules: str,
    *,
    build_tool,
) -> dict:
    bundle = Path(bundle).expanduser().absolute()
    if bundle.is_symlink() or not bundle.is_dir() or bundle.resolve(strict=True) != bundle:
        raise BundleError("bundle must be a regular canonical directory")
    target = Path(target).expanduser().absolute()
    if os.path.lexists(target):
        raise BundleError("target already exists; restore never overwrites")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise BundleError("target parent must be an existing regular directory")
    if target.parent.resolve(strict=True) != target.parent:
        raise BundleError("target parent must not traverse symbolic links")
    manifest = _read_manifest(bundle)
    _validate_schema_ddl(manifest["schema"])
    with tempfile.TemporaryDirectory(
        prefix=".recovery-reference-", dir=target.parent
    ) as reference_directory:
        reference = _module_reference(build_tool, modules, Path(reference_directory))
    _verify_module_binding(manifest, reference)
    payloads = _validate_table_payloads(bundle, manifest)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".recovery-target-", suffix=".sqlite", dir=target.parent
    )
    os.close(descriptor)
    temp_target = Path(temp_name)
    try:
        db = _fox_person.connect(temp_target, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE")
            db.execute("PRAGMA defer_foreign_keys = ON")
            try:
                _create_schema(db, manifest["schema"], ("table", "index", "view"))
                _refuse_unsupported_schema(db)
                tables = _physical_tables(db)
                if set(tables) != set(payloads):
                    raise BundleError(
                        "bundle table payloads do not match captured schema"
                    )
                if manifest["metadata"]["table_count"] != len(tables):
                    raise BundleError("bundle table count does not match captured schema")
                fields = {}
                rowid_accessors = {}
                for table in tables:
                    info = _columns(db, table)
                    fields[table] = [row["name"] for row in info]
                    item = next(
                        value for value in manifest["tables"]
                        if value["table"] == table
                    )
                    if item["columns"] != fields[table]:
                        raise BundleError(
                            "bundle columns do not match captured schema: " + table
                        )
                    primary = [
                        row["name"]
                        for row in sorted(info, key=lambda value: value["pk"])
                        if row["pk"] > 0
                    ]
                    if item["primary_key"] != primary:
                        raise BundleError(
                            "bundle primary key does not match captured schema: " + table
                        )
                    rowid_accessors[table] = _implicit_rowid_accessor(
                        db, table, info
                    )
                    if (
                        item["implicit_rowid_accessor"]
                        != rowid_accessors[table]
                    ):
                        raise BundleError(
                            "bundle implicit rowid mode does not match captured schema: "
                            + table
                        )
                    _validate_payload_records(
                        table,
                        payloads[table],
                        fields[table],
                        rowid_accessors[table],
                    )
                for table in tables:
                    _insert_table_records(
                        db,
                        table,
                        fields[table],
                        payloads[table],
                        rowid_accessors[table],
                    )
                _restore_metadata(db, manifest["metadata"])
                _create_schema(db, manifest["schema"], ("trigger",))
                restored_schema_digest = _schema_digest(_schema_entries(db))
                if restored_schema_digest != manifest["schema_digest"]:
                    raise BundleError("recreated schema digest does not match bundle")
                violations = list(db.execute("PRAGMA foreign_key_check"))
                if violations:
                    raise BundleError(
                        "bundle foreign key defect: " + repr(tuple(violations[0]))
                    )
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise BundleError("restored integrity check failed: " + str(integrity))
                for table in tables:
                    _assert_table_rows(
                        db,
                        table,
                        fields[table],
                        payloads[table],
                        rowid_accessors[table],
                    )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            restored_metadata = _sqlite_metadata(db)
            if restored_metadata != manifest["metadata"]:
                raise BundleError("restored SQLite metadata does not match bundle")
            restored_schema_digest = _schema_digest(_schema_entries(db))
            if restored_schema_digest != manifest["schema_digest"]:
                raise BundleError("restored schema does not match bundle")
        except sqlite3.Error as error:
            raise BundleError("bundle restore failed: " + str(error)) from error
        finally:
            db.close()
        result = {
            "status": "logical_same_database_restored",
            "bundle": str(bundle),
            "target": str(target),
            "manifest_sha256": manifest["manifest_sha256"],
            "schema_digest": restored_schema_digest,
            "modules": manifest["modules"],
            "runtime_schema": manifest["runtime_schema"],
            "tables": len(payloads),
            "rows": manifest["row_count"],
            "foreign_key_violations": 0,
            "integrity": "ok",
        }
        try:
            os.link(temp_target, target)
        except FileExistsError as error:
            raise BundleError(
                "target appeared during restore; nothing was overwritten"
            ) from error
        return result
    finally:
        try:
            temp_target.unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-tool",
        type=Path,
        default=(Path(__file__).resolve().parent / 'build_database.py'),
        help="Candidate override. Integrated default is the sibling build tool.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("source", type=Path)
    create.add_argument("bundle", type=Path)
    create.add_argument("--modules", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("target", type=Path)
    restore.add_argument("--modules", required=True)
    args = parser.parse_args(argv)
    try:
        build_tool = _load_build_tool(args.build_tool.expanduser().absolute())
        if args.command == "create":
            result = create_bundle(
                args.source, args.bundle, args.modules, build_tool=build_tool
            )
        else:
            result = restore_bundle(
                args.bundle, args.target, args.modules, build_tool=build_tool
            )
    except (BundleError, OSError, sqlite3.Error) as error:
        print("Recovery failed: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
