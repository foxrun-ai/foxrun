#!/usr/bin/env python3
"""Write the same work history event through the existing work command."""
from __future__ import annotations
import sqlite3


def record_activity(db: sqlite3.Connection, subject_type: str, subject_id: str, field: str, old, new,
                    actor: str, at: str, note: str | None = None, *, verb: str) -> None:
    from work import ACTIONS, SOURCE, WorkError
    if verb not in ACTIONS:
        raise WorkError("history action must be one of the 33 reviewed words")
    if "verb" in {row[1] for row in db.execute('PRAGMA table_info("activity")')}:
        db.execute(
            "INSERT INTO activity (subject_type,subject_id,field,old_value,new_value,actor,source,at,note,verb) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (subject_type, subject_id, field, old, new, actor, SOURCE, at, note, verb),
        )
        return
    db.execute(
        "INSERT INTO activity (subject_type,subject_id,field,old_value,new_value,actor,source,at,note) VALUES (?,?,?,?,?,?,?,?,?)",
        (subject_type, subject_id, field, old, new, actor, SOURCE, at, note),
    )


import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import closing
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'work'))


def show_events(database, subject_type=None, subject_id=None, limit=100):
    """Read existing event tables. Never create a missing database."""
    database = Path(database).expanduser()
    if database.is_symlink() or not database.is_file():
        raise ValueError('database must be an existing regular file')
    if limit < 1 or limit > 10000:
        raise ValueError('limit must be between 1 and 10000')
    events = []
    uri = 'file:' + quote(str(database.resolve()), safe='/:@') + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, clock in [('activity', 'at'), ('comments', 'at'),
                             ('attachments', 'at'), ('runs', 'started_at')]:
            if table not in tables:
                continue
            columns = {r[1] for r in db.execute('PRAGMA table_info("' + table + '")')}
            if not {'id', 'subject_type', 'subject_id', clock} <= columns:
                raise ValueError('unsupported event schema: ' + table)
            conditions, values = [], []
            for field, value in [('subject_type', subject_type), ('subject_id', subject_id)]:
                if value is not None:
                    conditions.append(field + '=?')
                    values.append(value)
            sql = 'SELECT * FROM "' + table + '"'
            if conditions:
                sql += ' WHERE ' + ' AND '.join(conditions)
            sql += ' ORDER BY "' + clock + '" DESC,id DESC LIMIT ?'
            for row in db.execute(sql, values + [limit]):
                event = dict(row)
                event['event_table'] = table
                events.append((str(event.get(clock) or ''), table, str(event['id']), event))
    events.sort(key=lambda event: event[:3], reverse=True)
    for _, _, _, event in events[:limit]:
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Show existing events or add an event through work.py.')
    commands = parser.add_subparsers(dest='command', required=True)
    show = commands.add_parser('show')
    show.add_argument('--db', type=Path)
    show.add_argument('--workspace')
    show.add_argument('--subject-type')
    show.add_argument('--subject-id')
    show.add_argument('--limit', type=int, default=100)
    add = commands.add_parser('add', help='Use the existing work command flags and approval rules.')
    add.add_argument('event', choices=['comment', 'run-start', 'run-note', 'run-end', 'done'])
    add.add_argument('work_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == 'add':
            command = [sys.executable, '-B', str(ROOT / 'work/work.py'), args.event]
            return subprocess.run(command + args.work_args).returncode
        from base import paths
        database = args.db
        if database is None and args.workspace:
            from base.tracker import tracker
            database = tracker(args.workspace)
        return show_events(database or paths.database(), args.subject_type,
                           args.subject_id, args.limit)
    except (OSError, ValueError, sqlite3.Error) as error:
        print('FAIL events: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
