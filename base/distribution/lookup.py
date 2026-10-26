#!/usr/bin/env python3
"""Read object type and field definitions from core data.db. No writes or guesses."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
import json
from pathlib import Path
import sqlite3

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('name')
    p.add_argument('--db', type=Path, required=True)
    args = p.parse_args()
    db = _fox_person.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        objects = [dict(r) for r in db.execute('SELECT o.*,m.name AS module_name FROM base_object_types o JOIN base_modules m ON m.id=o.module WHERE o.name=? OR o.location=?', (args.name, args.name))]
        for row in objects:
            row['fields'] = [dict(r) for r in db.execute('SELECT * FROM base_fields WHERE object_type=? ORDER BY sort_order,id', (row['id'],))]
        print(json.dumps({'result': 'matched' if objects else 'unknown', 'definitions': objects}, sort_keys=True, indent=2))
        return 0 if objects else 1
    finally:
        db.close()

if __name__ == '__main__':
    raise SystemExit(main())
