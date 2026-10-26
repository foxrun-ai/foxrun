#!/usr/bin/env python3
"""Read and freeze source-qualified AgentOS history without changing sources."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


FORMAT = "foxrun-private-subject-history"
FORMAT_VERSION = 1
STORE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TABLES = {
    "activity": (
        "id", "subject_type", "subject_id", "field", "old_value",
        "new_value", "actor", "source", "at", "note",
    ),
    "approvals": (
        "id", "subject_type", "subject_id", "version", "call",
        "person_words", "given_at", "source",
    ),
}
TIME_COLUMN = {"activity": "at", "approvals": "given_at"}


class HistoryError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$blob": base64.b64encode(value).decode("ascii")}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _jsonable(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HistoryError(f"value is not canonically encodable: {exc}") from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_existing_file(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    mode = resolved.stat().st_mode
    if not stat.S_ISREG(mode):
        raise HistoryError(f"database is not a regular file: {path}")
    return resolved


def _validated_store_paths(stores: Mapping[str, Path]) -> dict[str, Path]:
    if not stores:
        raise HistoryError("at least one explicit store is required")
    validated: dict[str, Path] = {}
    identities: dict[tuple[int, int], str] = {}
    for name, raw_path in sorted(stores.items()):
        if not isinstance(name, str) or not STORE_RE.fullmatch(name):
            raise HistoryError(f"invalid store name: {name!r}")
        path = _regular_existing_file(Path(raw_path))
        status = path.stat()
        identity = (status.st_dev, status.st_ino)
        if identity in identities:
            raise HistoryError(
                f"stores {identities[identity]!r} and {name!r} refer to the same physical database"
            )
        validated[name] = path
        identities[identity] = name
    return validated


def parse_store_specs(specs: Sequence[str]) -> dict[str, Path]:
    stores: dict[str, Path] = {}
    for spec in specs:
        if "=" not in spec:
            raise HistoryError("store must use NAME=PATH")
        name, raw_path = spec.split("=", 1)
        if not STORE_RE.fullmatch(name):
            raise HistoryError(f"invalid store name: {name!r}")
        if name in stores:
            raise HistoryError(f"duplicate store name: {name}")
        stores[name] = Path(raw_path)
    return _validated_store_paths(stores)


def qualified_id(store: str, table: str, source_id: int) -> str:
    return f"{store}:{table}:{source_id}"


def parse_qualified_id(value: str) -> tuple[str, str, int]:
    parts = value.split(":")
    if len(parts) != 3 or not STORE_RE.fullmatch(parts[0]) or parts[1] not in TABLES:
        raise HistoryError(f"invalid qualified ID: {value!r}")
    try:
        source_id = int(parts[2])
    except ValueError as exc:
        raise HistoryError(f"invalid qualified ID: {value!r}") from exc
    if source_id < 1 or str(source_id) != parts[2]:
        raise HistoryError(f"invalid qualified ID: {value!r}")
    return parts[0], parts[1], source_id


def parse_scope(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise HistoryError("scope must use SUBJECT_TYPE=SUBJECT_ID")
    subject_type, subject_id = value.split("=", 1)
    if not subject_type or not subject_id or "\x00" in value:
        raise HistoryError("scope values must be nonempty text")
    return subject_type, subject_id


def _table_info(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _schema_record(connection: sqlite3.Connection) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for table, expected in TABLES.items():
        columns = _table_info(connection, table)
        if tuple(columns) != expected:
            raise HistoryError(
                f"unsupported {table} schema: expected {list(expected)!r}, got {columns!r}"
            )
        row = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if row is None or not row[0]:
            raise HistoryError(f"missing schema SQL for {table}")
        tables[table] = {"columns": columns, "sql": str(row[0])}
    record = {
        "sqlite_user_version": connection.execute("PRAGMA user_version").fetchone()[0],
        "sqlite_application_id": connection.execute("PRAGMA application_id").fetchone()[0],
        "tables": tables,
    }
    record["schema_sha256"] = sha256_bytes(canonical_bytes(record))
    return record


@contextmanager
def readonly_stores(stores: Mapping[str, Path]) -> Iterator[dict[str, sqlite3.Connection]]:
    connections: dict[str, sqlite3.Connection] = {}
    try:
        validated = _validated_store_paths(stores)
        for name, path in validated.items():
            uri = path.as_uri() + "?mode=ro"
            connection = _fox_person.connect(uri, uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connections[name] = connection
        for connection in connections.values():
            connection.execute("BEGIN")
        yield connections
    finally:
        for connection in connections.values():
            try:
                connection.rollback()
            finally:
                connection.close()


def _row_record(store: str, table: str, row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    expected = TABLES[table]
    raw = {column: row[column] for column in expected}
    source_id = raw["id"]
    if not isinstance(source_id, int) or source_id < 1:
        raise HistoryError(f"unsupported ID in {store}.{table}: {source_id!r}")
    encoded = _jsonable(raw)
    return {
        "source_store": store,
        "table": table,
        "source_id": source_id,
        "qualified_id": qualified_id(store, table, source_id),
        "event_time": raw[TIME_COLUMN[table]],
        "row": encoded,
        "row_sha256": sha256_bytes(canonical_bytes(encoded)),
    }


def _record_sort_key(record: Mapping[str, Any]) -> tuple[str, str, str, int]:
    event_time = record.get("event_time")
    return (
        "" if event_time is None else str(event_time),
        str(record["source_store"]), str(record["table"]), int(record["source_id"]),
    )


def subject_history(
    connections: Mapping[str, sqlite3.Connection], subject_type: str, subject_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for store, connection in sorted(connections.items()):
        for table, columns in TABLES.items():
            projection = ",".join(f'"{column}"' for column in columns)
            rows = connection.execute(
                f'SELECT {projection} FROM "{table}" '
                'WHERE subject_type=? AND subject_id=? ORDER BY id',
                (subject_type, subject_id),
            )
            records.extend(_row_record(store, table, row) for row in rows)
    return sorted(records, key=_record_sort_key)


def lookup_qualified(
    connections: Mapping[str, sqlite3.Connection], store: str, table: str, source_id: int,
) -> dict[str, Any]:
    if store not in connections:
        raise HistoryError(f"store is not declared: {store}")
    if table not in TABLES:
        raise HistoryError(f"unsupported table: {table}")
    columns = TABLES[table]
    projection = ",".join(f'"{column}"' for column in columns)
    row = connections[store].execute(
        f'SELECT {projection} FROM "{table}" WHERE id=?', (source_id,)
    ).fetchone()
    if row is None:
        raise HistoryError(f"qualified ID not found: {qualified_id(store, table, source_id)}")
    return _row_record(store, table, row)


def lookup_bare(
    connections: Mapping[str, sqlite3.Connection], table: str, source_id: int,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for store in sorted(connections):
        try:
            matches.append(lookup_qualified(connections, store, table, source_id))
        except HistoryError as exc:
            if "not found" not in str(exc):
                raise
    if not matches:
        raise HistoryError(f"bare ID not found: {table}:{source_id}")
    if len(matches) > 1:
        labels = ", ".join(record["qualified_id"] for record in matches)
        raise HistoryError(f"ambiguous bare ID {table}:{source_id}; use one of: {labels}")
    return matches[0]


def _counts(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for record in records:
        store = str(record["source_store"])
        table = str(record["table"])
        result.setdefault(store, {}).setdefault(table, 0)
        result[store][table] += 1
    return {store: dict(sorted(tables.items())) for store, tables in sorted(result.items())}


def build_bundle(
    stores: Mapping[str, Path], scopes: Sequence[tuple[str, str]],
    qualified: Sequence[tuple[str, str, int]],
) -> tuple[dict[str, Any], dict[str, str]]:
    if not scopes and not qualified:
        raise HistoryError("at least one scope or qualified ID is required")
    with readonly_stores(stores) as connections:
        schemas = {name: _schema_record(connection) for name, connection in connections.items()}
        records_by_id: dict[str, dict[str, Any]] = {}
        for subject_type, subject_id in sorted(set(scopes)):
            for record in subject_history(connections, subject_type, subject_id):
                records_by_id[record["qualified_id"]] = record
        for store, table, source_id in sorted(set(qualified)):
            record = lookup_qualified(connections, store, table, source_id)
            records_by_id[record["qualified_id"]] = record
        records = sorted(records_by_id.values(), key=_record_sort_key)
        snapshot_hashes = {record["qualified_id"]: record["row_sha256"] for record in records}
    public_scopes = [
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "scope_sha256": sha256_bytes(canonical_bytes([subject_type, subject_id])),
        }
        for subject_type, subject_id in sorted(set(scopes))
    ]
    bundle: dict[str, Any] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "created_at": utc_now(),
        "identity_rule": ["source_store", "table", "source_id"],
        "scopes": public_scopes,
        "stores": schemas,
        "counts": _counts(records),
        "records": records,
    }
    bundle["records_sha256"] = sha256_bytes(canonical_bytes(records))
    return bundle, snapshot_hashes


def _exclusive_write(path: Path, data: bytes) -> tuple[int, int, int, str]:
    path = path.expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HistoryError(f"refusing to overwrite: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            status = os.fstat(handle.fileno())
    except Exception as exc:
        # Preserve a partial capture or another writer's replacement for review.
        # This helper cannot safely infer path ownership after a failed write.
        raise HistoryError(f"write failed; output path retained for review: {path}") from exc
    return status.st_dev, status.st_ino, status.st_size, sha256_bytes(data)


def _remove_created_file_if_unchanged(
    path: Path, created: tuple[int, int, int, str], expected_data: bytes,
) -> None:
    path = path.expanduser().absolute()
    expected_dev, expected_ino, expected_size, expected_digest = created
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow)
    except (FileNotFoundError, OSError) as exc:
        raise HistoryError(f"cleanup refused; created bundle is missing or replaced: {path}") from exc
    try:
        status = os.fstat(descriptor)
        if (status.st_dev, status.st_ino, status.st_size) != (
            expected_dev, expected_ino, expected_size,
        ):
            raise HistoryError(f"cleanup refused; created bundle inode or size changed: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            actual = handle.read()
        if actual != expected_data or sha256_bytes(actual) != expected_digest:
            raise HistoryError(f"cleanup refused; created bundle content changed: {path}")
        path_status = path.lstat()
        if (path_status.st_dev, path_status.st_ino) != (expected_dev, expected_ino):
            raise HistoryError(f"cleanup refused; created bundle path was replaced: {path}")
    finally:
        os.close(descriptor)
    path.unlink()


def export_bundle(
    stores: Mapping[str, Path], scopes: Sequence[tuple[str, str]],
    qualified: Sequence[tuple[str, str, int]], bundle_path: Path, receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    if bundle_path.expanduser().absolute() == receipt_path.expanduser().absolute():
        raise HistoryError("bundle and receipt paths must differ")
    bundle, snapshot_hashes = build_bundle(stores, scopes, qualified)
    bundle_bytes = canonical_bytes(bundle) + b"\n"
    digest = sha256_bytes(bundle_bytes)
    created_bundle = _exclusive_write(bundle_path, bundle_bytes)
    receipt = {
        "receipt_type": "private-history-export-digest",
        "created_at": utc_now(),
        "bundle_path": str(bundle_path.expanduser().absolute()),
        "expected_bundle_sha256": digest,
        "bundle_bytes": len(bundle_bytes),
        "record_counts": bundle["counts"],
        "records_sha256": bundle["records_sha256"],
        "schema_sha256": {
            store: schema["schema_sha256"] for store, schema in bundle["stores"].items()
        },
        "scope_sha256": [scope["scope_sha256"] for scope in bundle["scopes"]],
        "integrity_note": "Expected digest is independent drift evidence. It is not a signature or authentication.",
    }
    try:
        _exclusive_write(receipt_path, canonical_bytes(receipt) + b"\n")
    except Exception as receipt_error:
        try:
            _remove_created_file_if_unchanged(bundle_path, created_bundle, bundle_bytes)
        except Exception as cleanup_error:
            raise HistoryError(f"receipt write failed: {receipt_error}; {cleanup_error}") from receipt_error
        raise
    return receipt, snapshot_hashes


def _validate_record(record: Mapping[str, Any], stores: Mapping[str, Any]) -> None:
    required = {
        "source_store", "table", "source_id", "qualified_id", "event_time", "row", "row_sha256"
    }
    if set(record) != required:
        raise HistoryError("bundle record has unsupported fields")
    store = record["source_store"]
    table = record["table"]
    source_id = record["source_id"]
    if not isinstance(store, str) or not STORE_RE.fullmatch(store):
        raise HistoryError("bundle record has invalid store")
    if table not in TABLES or type(source_id) is not int or source_id < 1:
        raise HistoryError("bundle record has invalid table or ID")
    if store not in stores:
        raise HistoryError(f"bundle record refers to undeclared store: {store}")
    schema_tables = stores[store]["tables"]
    if table not in schema_tables:
        raise HistoryError(f"bundle record table is not declared for store {store}: {table}")
    if record["qualified_id"] != qualified_id(store, table, source_id):
        raise HistoryError("bundle record qualified ID mismatch")
    if not isinstance(record["row"], dict):
        raise HistoryError("bundle row must be an object")
    declared_columns = schema_tables[table]["columns"]
    if set(record["row"]) != set(declared_columns) or len(record["row"]) != len(declared_columns):
        raise HistoryError("bundle row columns do not match declared schema")
    if type(record["row"].get("id")) is not int or record["row"].get("id") != source_id:
        raise HistoryError("bundle row ID mismatch")
    if record["event_time"] != record["row"].get(TIME_COLUMN[table]):
        raise HistoryError("bundle event time does not match source row")
    digest = sha256_bytes(canonical_bytes(record["row"]))
    if record["row_sha256"] != digest:
        raise HistoryError("bundle row hash mismatch")


def read_bundle(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise HistoryError("expected SHA-256 must be 64 lowercase hex characters")
    raw = path.read_bytes()
    actual = sha256_bytes(raw)
    if actual != expected_sha256:
        raise HistoryError(f"bundle digest mismatch: expected {expected_sha256}, got {actual}")
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HistoryError(f"bundle is not valid JSON: {exc}") from exc
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        raise HistoryError("unsupported bundle format")
    if bundle.get("format_version") != FORMAT_VERSION:
        raise HistoryError("unsupported bundle version")
    stores = bundle.get("stores")
    if not isinstance(stores, dict):
        raise HistoryError("bundle stores must be an object")
    for store, schema in stores.items():
        if not STORE_RE.fullmatch(store) or not isinstance(schema, dict):
            raise HistoryError("bundle store schema is invalid")
        tables = schema.get("tables")
        if not isinstance(tables, dict):
            raise HistoryError(f"bundle store tables are invalid for {store}")
        for table, table_schema in tables.items():
            if table not in TABLES or not isinstance(table_schema, dict):
                raise HistoryError(f"bundle store table is unsupported for {store}: {table}")
            if table_schema.get("columns") != list(TABLES[table]):
                raise HistoryError(f"bundle store columns are unsupported for {store}.{table}")
            if not isinstance(table_schema.get("sql"), str) or not table_schema["sql"]:
                raise HistoryError(f"bundle store SQL is invalid for {store}.{table}")
        claimed = schema.get("schema_sha256")
        payload = {key: value for key, value in schema.items() if key != "schema_sha256"}
        if claimed != sha256_bytes(canonical_bytes(payload)):
            raise HistoryError(f"bundle schema hash mismatch for {store}")
    records = bundle.get("records")
    if not isinstance(records, list):
        raise HistoryError("bundle records must be a list")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise HistoryError("bundle record must be an object")
        _validate_record(record, stores)
        key = str(record["qualified_id"])
        if key in seen:
            raise HistoryError(f"duplicate qualified ID: {key}")
        seen.add(key)
    if records != sorted(records, key=_record_sort_key):
        raise HistoryError("bundle records are not in deterministic order")
    if bundle.get("records_sha256") != sha256_bytes(canonical_bytes(records)):
        raise HistoryError("bundle records hash mismatch")
    if bundle.get("counts") != _counts(records):
        raise HistoryError("bundle row counts mismatch")
    return bundle


def bundle_lookup(bundle: Mapping[str, Any], value: str) -> dict[str, Any]:
    store, table, source_id = parse_qualified_id(value)
    for record in bundle["records"]:
        if (record["source_store"], record["table"], record["source_id"]) == (
            store, table, source_id,
        ):
            return dict(record)
    raise HistoryError(f"qualified ID not found in bundle: {value}")


def bundle_subject_history(
    bundle: Mapping[str, Any], subject_type: str, subject_id: str,
) -> list[dict[str, Any]]:
    result = [
        dict(record) for record in bundle["records"]
        if record["row"].get("subject_type") == subject_type
        and record["row"].get("subject_id") == subject_id
    ]
    return sorted(result, key=_record_sort_key)


def find_common_subject(connections: Mapping[str, sqlite3.Connection]) -> tuple[str, str]:
    names = sorted(connections)
    if len(names) < 2:
        raise HistoryError("common-subject proof requires at least two stores")
    shared: set[tuple[str, str]] | None = None
    for connection in connections.values():
        current: set[tuple[str, str]] = set()
        for table in TABLES:
            current.update(
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    f'SELECT DISTINCT subject_type, subject_id FROM "{table}"'
                )
            )
        shared = current if shared is None else shared & current
    if not shared:
        raise HistoryError("no subject is present in every declared store")
    return min(shared, key=lambda item: sha256_bytes(canonical_bytes(item)))


def find_store_subject(connection: sqlite3.Connection) -> tuple[str, str]:
    subjects: set[tuple[str, str]] = set()
    for table in TABLES:
        subjects.update(
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                f'SELECT DISTINCT subject_type, subject_id FROM "{table}"'
            )
        )
    if not subjects:
        raise HistoryError("store contains no activity or approval subject")
    return min(subjects, key=lambda item: sha256_bytes(canonical_bytes(item)))


def run_real_proof(
    stores: Mapping[str, Path], bundle_path: Path, receipt_path: Path,
) -> dict[str, Any]:
    before_files = {name: file_sha256(path) for name, path in stores.items()}
    with readonly_stores(stores) as connections:
        try:
            scopes = [find_common_subject(connections)]
            common_subject = True
        except HistoryError as exc:
            if "no subject is present" not in str(exc):
                raise
            scopes = sorted({find_store_subject(connection) for connection in connections.values()})
            common_subject = False
        for name in sorted(stores):
            lookup_qualified(connections, name, "approvals", 17)
    qualified = [(name, "approvals", 17) for name in sorted(stores)]
    receipt, live_hashes = export_bundle(stores, scopes, qualified, bundle_path, receipt_path)
    bundle = read_bundle(bundle_path, receipt["expected_bundle_sha256"])
    offline_hashes = {record["qualified_id"]: record["row_sha256"] for record in bundle["records"]}
    if live_hashes != offline_hashes:
        raise HistoryError("live and offline row hashes differ")
    approval_hashes = {
        name: bundle_lookup(bundle, qualified_id(name, "approvals", 17))["row_sha256"]
        for name in sorted(stores)
    }
    after_files = {name: file_sha256(path) for name, path in stores.items()}
    if before_files != after_files:
        raise HistoryError("a source database file changed during proof")
    scope_hash = sha256_bytes(canonical_bytes(scopes))
    stores_in_scope = sorted({
        record["source_store"]
        for scope in scopes
        for record in bundle_subject_history(bundle, *scope)
    })
    if stores_in_scope != sorted(stores):
        raise HistoryError("selected subject is not represented in every store")
    return {
        "proof": "private-retained-history-dependency",
        "created_at": utc_now(),
        "source_file_sha256_before_after": {
            name: {"before": before_files[name], "after": after_files[name], "unchanged": True}
            for name in sorted(stores)
        },
        "source_snapshot": {
            "consistency": "per-store read transactions; not a cross-store atomic snapshot",
            "scope_sha256": scope_hash,
            "scope_count": len(scopes),
            "common_subject_across_all_stores": common_subject,
            "stores_in_scope": stores_in_scope,
            "record_counts": bundle["counts"],
            "records_sha256": bundle["records_sha256"],
            "schema_sha256": receipt["schema_sha256"],
        },
        "approval_17": {
            "qualified_id_sha256": {
                name: sha256_bytes(qualified_id(name, "approvals", 17).encode("utf-8"))
                for name in sorted(stores)
            },
            "row_sha256": approval_hashes,
            "distinct_qualified_rows": len(approval_hashes) == len(stores),
        },
        "offline_verification": {
            "expected_bundle_sha256": receipt["expected_bundle_sha256"],
            "live_offline_row_hashes_equal": True,
            "external_digest_required": True,
        },
        "limits": [
            "This proves retained source-qualified history for selected rows only.",
            "It does not migrate ownership or create a mutable canonical history store.",
            "The digest is drift evidence, not a signature or authentication.",
            "Physical database hashes do not identify a WAL snapshot; selected logical rows do.",
            "Each store has its own read transaction. The stores are not one atomic snapshot.",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export", help="freeze selected history into a private bundle")
    export.add_argument("--store", action="append", required=True, metavar="NAME=PATH")
    export.add_argument("--scope", action="append", default=[], metavar="TYPE=ID")
    export.add_argument("--qualified", action="append", default=[], metavar="STORE:TABLE:ID")
    export.add_argument("--bundle", type=Path, required=True)
    export.add_argument("--receipt", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="verify a private bundle with an external digest")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--expected-sha256", required=True)

    lookup = subparsers.add_parser("lookup", help="write one exact offline row to a new private file")
    lookup.add_argument("--bundle", type=Path, required=True)
    lookup.add_argument("--expected-sha256", required=True)
    lookup.add_argument("--qualified", required=True)
    lookup.add_argument("--output", type=Path, required=True)

    proof = subparsers.add_parser("real-proof", help="run bounded proof against explicit readonly stores")
    proof.add_argument("--store", action="append", required=True, metavar="NAME=PATH")
    proof.add_argument("--bundle", type=Path, required=True)
    proof.add_argument("--receipt", type=Path, required=True)
    proof.add_argument("--proof-receipt", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "export":
            receipt, _ = export_bundle(
                parse_store_specs(args.store), [parse_scope(value) for value in args.scope],
                [parse_qualified_id(value) for value in args.qualified], args.bundle, args.receipt,
            )
            print(json.dumps({"record_counts": receipt["record_counts"], "expected_bundle_sha256": receipt["expected_bundle_sha256"]}, sort_keys=True))
        elif args.command == "verify":
            bundle = read_bundle(args.bundle, args.expected_sha256)
            print(json.dumps({"record_counts": bundle["counts"], "records_sha256": bundle["records_sha256"]}, sort_keys=True))
        elif args.command == "lookup":
            bundle = read_bundle(args.bundle, args.expected_sha256)
            record = bundle_lookup(bundle, args.qualified)
            _exclusive_write(args.output, canonical_bytes(record) + b"\n")
            print(json.dumps({"qualified_id": record["qualified_id"], "row_sha256": record["row_sha256"]}, sort_keys=True))
        elif args.command == "real-proof":
            proof = run_real_proof(parse_store_specs(args.store), args.bundle, args.receipt)
            _exclusive_write(args.proof_receipt, canonical_bytes(proof) + b"\n")
            print(json.dumps({"record_counts": proof["source_snapshot"]["record_counts"], "records_sha256": proof["source_snapshot"]["records_sha256"]}, sort_keys=True))
        return 0
    except (HistoryError, OSError, sqlite3.Error) as exc:
        raise SystemExit(f"error: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
