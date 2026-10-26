#!/usr/bin/env python3
"""List active decisions that mention a replacement but have no replaces value."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote


WORD = re.compile(r"\b(replaces|amends|supersedes|corrects)\b", re.IGNORECASE)


def lint(database: Path) -> list[dict[str, str]]:
    if not database.is_file():
        raise ValueError("database must already exist: " + str(database))
    uri = "file:" + quote(str(database.resolve()), safe="/:@") + "?mode=ro"
    with _fox_person.connect(uri, uri=True) as db:
        rows = db.execute(
            "SELECT id,status,statement FROM decisions "
            "WHERE status IN ('ruled','soft') AND (replaces IS NULL OR trim(replaces)='') ORDER BY id"
        )
        return [dict(id=decision_id, status=status, word=match.group(), statement=statement)
                for decision_id, status, statement in rows
                if (match := WORD.search(statement or ""))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True, help="workspace root, for command parity")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if not args.receipt_root.is_dir():
            raise ValueError("receipt root must already exist: " + str(args.receipt_root))
        found = lint(args.db)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(2, "lint-replaces failed: " + str(error) + "\n")
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    else:
        for row in found:
            print(f"{row['id']} [{row['status']}] {row['word']}: {row['statement']}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
