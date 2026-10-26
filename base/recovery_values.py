"""Strict SQLite value decoding for private recovery bundles."""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path


class RestoreError(RuntimeError):
    """The requested restore cannot continue without losing certainty."""


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RestoreError("duplicate JSON key: " + str(key))
        result[key] = value
    return result


def strict_json(text: str, label: str):
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                RestoreError(label + ": non-finite JSON value " + value)
            ),
        )
    except RestoreError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise RestoreError(label + ": invalid JSON: " + str(error)) from error


def _decode_value(value, label: str):
    if isinstance(value, dict):
        if set(value) != {"$blob"} or not isinstance(value["$blob"], str):
            raise RestoreError(label + ": unsupported tagged JSON value")
        try:
            decoded = base64.b64decode(value["$blob"], validate=True)
        except (ValueError, TypeError) as error:
            raise RestoreError(label + ": invalid base64 BLOB") from error
        if base64.b64encode(decoded).decode("ascii") != value["$blob"]:
            raise RestoreError(label + ": non-canonical base64 BLOB")
        return decoded
    if isinstance(value, (list, bool)):
        raise RestoreError(label + ": unsupported JSON value type")
    if isinstance(value, float) and not math.isfinite(value):
        raise RestoreError(label + ": non-finite number")
    if value is not None and not isinstance(value, (str, int, float)):
        raise RestoreError(label + ": unsupported JSON value type")
    return value


def _read_jsonl(path: Path, table: str) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RestoreError("cannot read " + str(path) + ": " + str(error)) from error
    if raw and not raw.endswith("\n"):
        raise RestoreError(str(path) + ": JSONL must end with a newline")
    records = []
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise RestoreError(f"{path}:{number}: blank JSONL line")
        record = strict_json(line, f"{path}:{number}")
        if not isinstance(record, dict):
            raise RestoreError(f"{path}:{number}: row must be one JSON object")
        records.append(
            {
                key: _decode_value(value, f"{path}:{number}:{key}")
                for key, value in record.items()
            }
        )
    return records
