#!/usr/bin/env python3
"""Load a reviewed map through commands/base_capabilities. Equal rows do not change."""

from __future__ import annotations
import argparse
from contextlib import closing
import csv
import json
from pathlib import Path
import sqlite3
import subprocess
from core import connect


def mapped_rows(path):
    result = []
    with Path(path).open(newline='') as source:
        for row in csv.DictReader(source):
            if row['card_path'] == 'none':
                continue
            result.append(dict(name=row['name'], kind=row['kind'], set=row['set'] or None,
                               workspace=row['workspace'], status=row['state'],
                               runtimes=json.dumps(row['who_can_use'].split('; ')) if row['who_can_use'] else None,
                               card_path=row['card_path']))
    if len({r['name'] for r in result}) != len(result) or len({r['card_path'] for r in result}) != len(result):
        raise ValueError('duplicate name or card_path in map')
    return result


def load(database, mapping, actor, session):
    database = Path(database)
    if database.is_symlink() or not database.is_file():
        raise ValueError('database is missing or unsafe')
    rows = mapped_rows(mapping)
    counts = dict(inserted=0, updated=0, unchanged=0)
    command = (Path(__file__).resolve().parent / 'commands/base_capabilities')
    for row in rows:
        with closing(connect(database, readonly=True)) as db:
            found = db.execute('SELECT id FROM base_capabilities WHERE name=?', (row['name'],)).fetchone()
        args = [str(command), '--db', str(database), '--actor', actor,
                '--workspace', row['workspace'], '--session', session]
        args += ['update', '--id', str(found[0])] if found else ['insert']
        args += ['--json', json.dumps(row)]
        completed = subprocess.run(args, capture_output=True, text=True)
        if completed.returncode:
            raise ValueError('table command failed for ' + row['name'] + ': ' + completed.stderr.strip())
        response = json.loads(completed.stdout)
        key = ('updated' if found else 'inserted') if response['changed'] else 'unchanged'
        counts[key] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--map', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    print(json.dumps(load(args.db, args.map, args.actor, args.session), sort_keys=True))


if __name__ == '__main__':
    main()
