#!/usr/bin/env python3
"""Export every SQLite table without changing the source database."""

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
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from core import Q, schema_hash


def encode(value):
    return {'$blob': base64.b64encode(value).decode('ascii')} if isinstance(value, bytes) else value


def decode(value):
    if isinstance(value, dict):
        if set(value) != {'$blob'} or not isinstance(value['$blob'], str):
            raise ValueError('Unsupported SQLite value')
        return base64.b64decode(value['$blob'], validate=True)
    if value is not None and not isinstance(value, (str, int, float)):
        raise ValueError('Unsupported SQLite value')
    return value


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(body):
    return hashlib.sha256(body).hexdigest()


def readonly(path):
    path = Path(path).resolve(strict=True)
    db = _fox_person.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('BEGIN')
    return db


def snapshot(db):
    result = {}
    for table, sql in db.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' ORDER BY name"):
        if not sql or sql.upper().startswith('CREATE VIRTUAL TABLE'):
            raise ValueError('Unsupported table: ' + table)
        if table in ('manifest',) or any(c in table for c in ('/', '\\', '\x00')):
            raise ValueError('Unsafe table filename: ' + table)
        columns = [dict(r) for r in db.execute('PRAGMA table_xinfo(' + Q(table) + ')')]
        names = [r['name'] for r in columns if r['hidden'] != 1]
        query = 'SELECT ' + ','.join(Q(n) for n in names) + ' FROM ' + Q(table)
        lines = sorted(packed({n: encode(r[n]) for n in names}) + b'\n' for r in db.execute(query))
        body = b''.join(lines)
        result[table] = (body, {'file': table + '.jsonl', 'columns': columns, 'rows': len(lines), 'sha256': sha(body)})
    manifest = {
        'format': 'foxrun-state-jsonl/v1', 'schema_sha256': schema_hash(db),
        'tables': {n: value[1] for n, value in result.items()},
        'schema': [dict(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name')],
        'pragmas': {n: db.execute('PRAGMA ' + n).fetchone()[0] for n in ('application_id', 'user_version', 'encoding')},
    }
    return result, manifest


def write_same(path, body):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refuse symlink: ' + str(path))
    if path.exists() and path.read_bytes() == body:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def inside(root, value):
    path = Path(value)
    path = path if path.is_absolute() else root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError('Path must be inside target root: ' + str(path))
    return path


def export(database, output):
    db = readonly(database)
    try:
        tables, manifest = snapshot(db)
    finally:
        db.close()
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Refuse symlink output')
    output.mkdir(parents=True, exist_ok=True)
    obsolete = set(p.name for p in output.glob('*.jsonl')) - {n + '.jsonl' for n in tables}
    if obsolete:
        raise ValueError('Archive stale exports before replacing the table set: ' + ', '.join(sorted(obsolete)))
    for name, (body, _) in tables.items():
        write_same(output / (name + '.jsonl'), body)
    write_same(output / 'manifest.json', packed(manifest) + b'\n')
    return manifest


def verify(database, output):
    db = readonly(database)
    try:
        tables, expected = snapshot(db)
    finally:
        db.close()
    manifest = json.loads((output / 'manifest.json').read_bytes())
    if manifest != expected:
        raise ValueError('Export manifest differs from the database')
    if {p.name for p in output.glob('*.jsonl')} != {n + '.jsonl' for n in tables}:
        raise ValueError('Export table set differs')
    for name, (body, _) in tables.items():
        if (output / (name + '.jsonl')).read_bytes() != body:
            raise ValueError('Export rows differ: ' + name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--database', default='home/.local/share/foxrun/data.db')
    parser.add_argument('--exports', default='exports')
    parser.add_argument('--check', choices=('coverage', 'hashes', 'repeat', 'git', 'all'))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    database, output = inside(root, args.database), inside(root, args.exports)
    if args.check:
        groups = ('coverage', 'hashes', 'repeat', 'git') if args.check == 'all' else (args.check,)
        failures = []
        for group in groups:
            try:
                if group in ('coverage', 'hashes'):
                    manifest = verify(database, output)
                    detail = str(len(manifest['tables'])) + ' tables; exact rows and schema'
                elif group == 'repeat':
                    verify(database, output)
                    files = [output / 'manifest.json', *sorted(output.glob('*.jsonl'))]
                    before = {p.name: (sha(p.read_bytes()), p.stat().st_mtime_ns) for p in files}
                    export(database, output)
                    after = {p.name: (sha(p.read_bytes()), p.stat().st_mtime_ns) for p in files}
                    if before != after:
                        raise ValueError('Second export changed bytes or file times')
                    detail = 'second export keeps every byte and file time'
                else:
                    prefix = ['git', '-C', str(output)]
                    if subprocess.check_output(prefix + ['rev-parse', '--show-toplevel'], text=True).strip() != str(output):
                        raise ValueError('Exports need their own repository')
                    if subprocess.check_output(prefix + ['remote'], text=True).strip():
                        raise ValueError('Exports repository has a remote')
                    detail = 'local Git repository; no remote'
                print('PASS schema ' + group + ' ' + detail)
            except (ValueError, OSError, sqlite3.Error, subprocess.CalledProcessError) as error:
                failures.append(group)
                print('FAIL schema ' + group + ' ' + str(error))
        return bool(failures)
    manifest = export(database, output)
    if not (output / '.git').exists():
        subprocess.run(['git', 'init', '-q', '-b', 'night-run', str(output)], check=True)
    if subprocess.check_output(['git', '-C', str(output), 'remote'], text=True).strip():
        raise ValueError('Refuse repository with a remote')
    print('PASS schema export ' + str(len(manifest['tables'])) + ' tables; ' + str(sum(t['rows'] for t in manifest['tables'].values)) + ' rows')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error) as error:
        print('FAIL schema export ' + str(error))
        raise SystemExit(1)
