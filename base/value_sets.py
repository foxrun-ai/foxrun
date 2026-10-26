#!/usr/bin/env python3
"""Seed the value sets the blueprint's guards read. Adds only what is missing.

The values come from blueprint/implementation-rules.json (value_set_guards).
Each value is one base_values row, written through the table command, so it leaves its change row.
The zero-state build holds no value rows; run this once on a database before a guarded field is written.

Usage: value_sets.py --db DATA.db --actor NAME --session SESSION [--workspace foxrun] [--check]
"""

from __future__ import annotations
import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
import argparse
from base import person as _fox_person
import json
from pathlib import Path
import sqlite3
import sys

from core import connect, execute


def wanted(blueprint):
    rules = json.loads((Path(blueprint) / 'implementation-rules.json').read_text())
    return [(g['set'], value, order, '; '.join(g['rulings']) + ' (' + g['answer'] + ')')
            for g in rules.get('value_set_guards', []) for order, value in enumerate(g['values'], 1)]


def missing(path, blueprint):
    db = connect(path, readonly=True)
    try:
        have = {(r[0], r[1]) for r in db.execute('SELECT "set",value FROM base_values WHERE active=1')}
    finally:
        db.close()
    return [row for row in wanted(blueprint) if (row[0], row[1]) not in have]


def seed(path, blueprint, context):
    """Insert each missing value. Return the count of rows written."""
    written = 0
    for name, value, order, source in missing(path, blueprint):
        execute(path, blueprint, 'base_values', 'insert',
                {'set': name, 'value': value, 'sort_order': order, 'source': source, 'active': 1}, None, context)
        written += 1
    return written


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', required=True)
    p.add_argument('--blueprint', default=str((Path(__file__).resolve().parent / 'blueprint')))
    p.add_argument('--actor')
    p.add_argument('--session')
    p.add_argument('--workspace', default=_fox_person.workspace('system'))
    p.add_argument('--check', action='store_true', help='Write nothing. Fail when a value is missing.')
    a = p.parse_args()
    try:
        if a.check:
            gaps = missing(a.db, a.blueprint)
            if gaps:
                print('FAIL value sets: ' + str(len(gaps)) + ' values missing: ' + ', '.join(g[0] + '=' + g[1] for g in gaps))
                return 1
            print('PASS value sets: ' + str(len(wanted(a.blueprint))) + ' values present')
            return 0
        if not a.actor or not a.session:
            raise ValueError('A write needs --actor and --session')
        context = {'writer': 'agent', 'actor': a.actor, 'session': a.session, 'workspace': a.workspace,
                   'reason': 'seed the value sets the guards read'}
        count = seed(a.db, a.blueprint, context)
        print('PASS value sets: ' + str(count) + ' values written; ' + str(len(wanted(a.blueprint))) + ' wanted')
        return 0
    except (ValueError, sqlite3.Error) as error:
        print('FAIL value sets: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
