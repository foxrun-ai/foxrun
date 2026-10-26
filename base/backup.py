#!/usr/bin/env python3
"""Export a read-only SQLite snapshot to stable, non-overwriting JSONL files."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def json_value(value):
    if isinstance(value, bytes):
        return {"$blob": base64.b64encode(value).decode("ascii")}
    return value


def json_line(record):
    return json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ) + "\n"


def rewrite(path, records):
    """Atomically replace one canonical export file."""
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary_path = Path(temporary)
    count = 0
    try:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(json_line(record))
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
        return count
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def export_state(database, output_dir=None):
    database = Path(database).expanduser().resolve(strict=True)
    if not database.is_file():
        raise ValueError("The database must be a SQLite file.")
    output_dir = (
        Path(output_dir).expanduser() if output_dir is not None
        else database.parent / "state"
    )
    if output_dir.is_symlink():
        raise ValueError("The output directory must not be a symbolic link.")
    output_dir = output_dir.resolve()
    connection = _fox_person.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("BEGIN")
        # Exclude views, SQLite internals, and virtual-table backing tables.
        tables = sorted(
            row["name"] for row in connection.execute("PRAGMA table_list")
            if row["schema"] == "main" and row["type"] in ("table", "virtual")
            and not row["name"].lower().startswith("sqlite_")
        )
        plans = []
        mirrors = []
        for table in tables:
            if table.lower() == "_mirrors" or any(c in table for c in ("/", "\\", "\x00")):
                raise ValueError("Table name cannot be used as an export filename: " + repr(table))
            quoted = quote_identifier(table)
            columns = list(connection.execute("PRAGMA table_xinfo(" + quoted + ")"))
            fields = [row["name"] for row in columns if row["hidden"] != 1]
            pulled_at = next((name for name in fields if name.lower() == "pulled_at"), None)
            if pulled_at is not None:
                count = connection.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
                pulled = quote_identifier(pulled_at)
                # Compare ISO dates as instants, including different UTC offsets.
                newest = connection.execute(
                    "SELECT " + pulled + " FROM " + quoted
                    + " WHERE " + pulled + " IS NOT NULL ORDER BY julianday("
                    + pulled + ") DESC, " + pulled + " COLLATE BINARY DESC LIMIT 1"
                ).fetchone()
                mirrors.append({
                    "table": table, "row_count": count,
                    "newest_pulled_at": newest[0] if newest else None,
                })
                continue
            primary_key = [
                row["name"] for row in sorted(columns, key=lambda row: row["pk"])
                if row["pk"] > 0
            ]
            # Remaining fields break ties for nullable keys and keyless tables.
            order = primary_key + sorted(set(fields) - set(primary_key))
            selected = ", ".join(quote_identifier(name) for name in fields)
            ordering = ", ".join(quote_identifier(name) + " COLLATE BINARY" for name in order)
            plans.append((table, "SELECT " + selected + " FROM " + quoted + " ORDER BY " + ordering))

        output_dir.mkdir(parents=True, exist_ok=True)
        files = {}
        row_count = 0
        for table, query in plans:
            records = (
                {name: json_value(row[name]) for name in row.keys()}
                for row in connection.execute(query)
            )
            expected = output_dir / (table + ".jsonl")
            count = rewrite(expected, records)
            files[table] = str(expected)
            row_count += count
        expected = output_dir / "_mirrors.jsonl"
        rewrite(expected, mirrors)
        files["_mirrors"] = str(expected)
        return {
            "database": str(database), "output_dir": str(output_dir),
            "table_count": len(plans), "row_count": row_count,
            "mirror_count": len(mirrors), "files": files, "alternate_files": [],
        }
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="verb", required=True)
    run = commands.add_parser("run", help="Export a read-only database snapshot to JSONL.")
    run.add_argument("database", type=Path, help="Workspace SQLite file; opened read-only.")
    run.add_argument("--output-dir", type=Path, help="Default: <database directory>/state/.")
    args = parser.parse_args()
    try:
        result = export_state(args.database, args.output_dir)
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        print("Export failed: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
