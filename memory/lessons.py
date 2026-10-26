#!/usr/bin/env python3
"""Lessons every agent reads (T260): apply the table, list active lessons, and build the start-page part.

Writers are work.py lesson-add and lesson-update. This file never writes a lesson row.
  apply --db <data.db>     add the lessons table, the active_lessons view, and their dictionary rows
  list --db <data.db>      print active lessons; --workspace and --seat narrow the list; --json for rows
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / 'lessons.sql'
SEED = HERE.parent / 'base/dictionary-seed.sql'
SEED_START = '-- T260: lessons'
SEED_END = '-- T260 end.'
START_LINES = 12  # the most lessons the start page lists; the command shows the rest


def has_lessons(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lessons'").fetchone() is not None


def statements(script: str) -> list[str]:
    """Split a script into whole statements; comment lines are dropped, so a ';' inside one is safe."""
    found, pending = [], ''
    for line in script.splitlines(keepends=True):
        if line.lstrip().startswith('--'):
            continue
        pending += line
        if sqlite3.complete_statement(pending):
            found.append(pending.strip())
            pending = ''
    if pending.strip():
        raise ValueError('incomplete SQL statement at the end of ' + str(SCHEMA))
    return found


def seed_block() -> list[str]:
    """The T260 statements of base/dictionary-seed.sql, one per line, without comments."""
    text = SEED.read_text(encoding='utf-8')
    start = text.index(SEED_START)
    block = text[start:text.index(SEED_END, start)]
    return [line for line in block.splitlines() if line.strip() and not line.startswith('--')]


def apply(database: Path, dictionary: bool = True) -> dict:
    """Create the table and the view when missing, then the dictionary rows. A second run changes nothing."""
    # The Foxrun connection registers the functions that an installed tracker's checks call (T595).
    sys.path.insert(0, str(HERE.parent))
    from base import person
    with closing(person.connect(database, timeout=20, isolation_level=None)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            before = db.total_changes
            existed = has_lessons(db)
            for statement in statements(SCHEMA.read_text(encoding='utf-8')):
                db.execute(statement)
            if dictionary and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='object_types'").fetchone():
                for statement in seed_block():
                    db.execute(statement)
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('quick_check failed; rolled back')
            changes = db.total_changes - before
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
    return {'table_existed': existed, 'changes': changes}


def active(db: sqlite3.Connection, workspace: str | None = None, seat: str | None = None) -> list[dict]:
    """Active lessons for every workspace plus the named one, and for every agent plus the named seat."""
    if not has_lessons(db):
        return []
    query = 'SELECT * FROM active_lessons'
    where, values = [], []
    if workspace:
        where.append("workspace IN ('all', ?)")
        values.append(workspace)
    if seat:
        where.append("applies_to IN ('all', ?)")
        values.append(seat)
    else:
        where.append("applies_to = 'all'")
    query += ' WHERE ' + ' AND '.join(where)
    cursor = db.execute(query, values)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def command(database: Path, workspace: str | None, seat: str | None) -> str:
    seat_clause = "applies_to IN ('all','" + seat + "')" if seat else "applies_to='all'"
    place = " AND workspace IN ('all','" + workspace + "')" if workspace else ''
    return ('sqlite3 -readonly ' + str(database) + ' "SELECT id,text FROM active_lessons WHERE '
            + seat_clause + place + ';"')


def start_part(database: Path, workspace: str, seat: str | None) -> str:
    """The Lessons part of the start page: a count, the newest lessons, and the command for all."""
    try:
        with closing(sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True)) as db:
            if not has_lessons(db):
                return ''
            rows = active(db, workspace, seat)
    except sqlite3.Error:
        return ''
    who = 'every agent' + (' and ' + seat if seat else '')
    lines = ['## Lessons', str(len(rows)) + ' active lessons for ' + who + ' in ' + workspace
             + '. Read them before you answer ' + _person() + '.']
    for row in rows[:START_LINES]:
        text = row['text'] if len(row['text']) <= 150 else row['text'][:149].rstrip() + '…'
        lines.append('  ' + row['id'] + ': ' + text)
    if len(rows) > START_LINES:
        lines.append('  ' + str(len(rows) - START_LINES) + ' more; use the command below.')
    lines.append('Command: ' + command(database, workspace, seat))
    return '\n'.join(lines)


def _person() -> str:
    try:
        sys.path.insert(0, str(HERE.parent))
        from base import person
        return person.display_name()
    except Exception:
        return 'the person'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='operation', required=True)
    one = sub.add_parser('apply')
    one.add_argument('--db', type=Path, required=True)
    one.add_argument('--no-dictionary', action='store_true', help='add the table and view only')
    two = sub.add_parser('list')
    two.add_argument('--db', type=Path, required=True)
    two.add_argument('--workspace')
    two.add_argument('--seat')
    two.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.operation == 'apply':
        print(json.dumps(apply(args.db, not args.no_dictionary), sort_keys=True))
        return 0
    with closing(sqlite3.connect('file:' + str(args.db) + '?mode=ro', uri=True)) as db:
        rows = active(db, args.workspace, args.seat)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(row['id'] + ' · ' + row['workspace'] + ' · ' + row['applies_to'] + ' · ' + row['text'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
