#!/usr/bin/env python3
"""List accepted proposal approvals whose saved words equal the proposal reason.

This is a review list, not proof of what the person said. It changes no rows.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3


def list_legacy_approval_words(database: Path) -> list[dict]:
    uri = database.expanduser().resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            "SELECT a.id, p.id AS proposal, a.person_words FROM approvals AS a "
            "JOIN proposals AS p ON a.version=p.id "
            "AND a.subject_type=p.table_name AND a.subject_id=p.row_id "
            "WHERE p.state='accepted' AND a.call='approve' AND a.person_words=p.why "
            "ORDER BY a.id"
        )]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="existing database; opened read-only")
    args = parser.parse_args()
    try:
        rows = list_legacy_approval_words(args.db)
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, "Cannot list legacy approval words: " + str(error) + "\n")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
