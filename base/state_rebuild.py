#!/usr/bin/env python3
"""Rebuild a separate database from blueprint v11 and complete JSONL exports."""

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
import tempfile

from core import Q, load, sql_schema, guard_sql, schema_hash
from views import view_sql
from state_jsonl import decode, inside, packed, readonly, sha, snapshot, verify, write_same


def blueprint_sql(blueprint):
    targets, columns = load(blueprint)
    return sql_schema(targets, columns), view_sql(targets, columns), guard_sql(targets, columns)


def expected_schema(blueprint):
    db = _fox_person.connect(':memory:')
    try:
        for sql in blueprint_sql(blueprint):
            db.executescript(sql)
        return schema_hash(db)
    finally:
        db.close()


def read_exports(output):
    manifest = json.loads((output / 'manifest.json').read_bytes())
    if manifest['format'] != 'foxrun-state-jsonl/v1':
        raise ValueError('Unsupported export format')
    expected_files = {name + '.jsonl' for name in manifest['tables']}
    if {p.name for p in output.glob('*.jsonl')} != expected_files:
        raise ValueError('Export table set differs')
    rows = {}
    for name, table in manifest['tables'].items():
        if table['file'] != name + '.jsonl' or any(c in name for c in ('/', '\\', '\x00')):
            raise ValueError('Unsafe export filename: ' + name)
        body = (output / table['file']).read_bytes()
        lines = body.splitlines(keepends=True)
        if sha(body) != table['sha256'] or len(lines) != table['rows'] or lines != sorted(lines):
            raise ValueError('Export checksum, count, or order differs: ' + name)
        rows[name] = []
        fields = {r['name'] for r in table['columns'] if r['hidden'] != 1}
        for line in lines:
            record = json.loads(line)
            if set(record) != fields or packed(record) + b'\n' != line:
                raise ValueError('Noncanonical export row: ' + name)
            rows[name].append({k: decode(v) for k, v in record.items()})
    return manifest, rows


def compare(path, manifest):
    db = readonly(path)
    try:
        _, actual = snapshot(db)
        if actual != manifest:
            raise ValueError('Rebuilt schema, rows, or metadata differ')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Rebuilt integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Rebuilt foreign keys differ')
    finally:
        db.close()


def rebuild(blueprint, exports, target):
    manifest, rows = read_exports(exports)
    desired = expected_schema(blueprint)
    if desired != manifest['schema_sha256']:
        raise ValueError('Blueprint schema differs from the export schema')
    target = Path(target)
    if target.exists():
        try:
            compare(target, manifest)
            return manifest
        except (ValueError, sqlite3.Error):
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.t66-', dir=target.parent) as folder:
        candidate = Path(folder) / 'candidate.db'
        db = _fox_person.connect(candidate)
        db.row_factory = sqlite3.Row
        try:
            schema, views, guards = blueprint_sql(blueprint)
            db.executescript(schema)
            db.executescript(views)
            actual_tables = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            if actual_tables != set(rows):
                raise ValueError('Blueprint table set differs from exports')
            db.execute('BEGIN')
            db.execute('PRAGMA defer_foreign_keys=ON')
            for name, records in rows.items():
                actual_columns = [dict(r) for r in db.execute('PRAGMA table_xinfo(' + Q(name) + ')')]
                if actual_columns != manifest['tables'][name]['columns']:
                    raise ValueError('Blueprint columns differ: ' + name)
                writable = [r['name'] for r in actual_columns if r['hidden'] == 0]
                sql = 'INSERT INTO ' + Q(name) + ' (' + ','.join(Q(n) for n in writable) + ') VALUES (' + ','.join('?' for _ in writable) + ')'
                db.executemany(sql, [tuple(r[n] for n in writable) for r in records])
            for name, value in manifest['pragmas'].items():
                if name not in ('application_id', 'user_version', 'encoding'):
                    raise ValueError('Unsupported database metadata')
                if name != 'encoding':
                    db.execute('PRAGMA ' + name + '=' + str(int(value)))
            db.commit()
            db.executescript(guards)
            db.commit()
        finally:
            db.close()
        compare(candidate, manifest)
        if target.exists():
            archive = target.parent / (target.name + '.archive') / (sha(target.read_bytes()) + '.db')
            archive.parent.mkdir(parents=True, exist_ok=True)
            if archive.exists():
                if archive.read_bytes() != target.read_bytes():
                    raise ValueError('Rebuild archive differs')
                raise ValueError('Rebuild archive already exists; preserve both files')
            target.rename(archive)
        candidate.rename(target)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--database', default='home/.local/share/foxrun/data.db')
    parser.add_argument('--exports', default='exports')
    parser.add_argument('--output', default='rebuild/data.rebuilt.db')
    parser.add_argument('--blueprint', default='code/foxrun-modules/base/blueprint')
    parser.add_argument('--without-original', action='store_true', help='Rebuild from blueprint and exports when the original database is unavailable.')
    parser.add_argument('--check', choices=('blueprint', 'hashes', 'integrity', 'repeat', 'source', 'all'))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    source, exports, target, blueprint = [inside(root, value) for value in (args.database, args.exports, args.output, args.blueprint)]
    if source == target:
        raise ValueError('The rebuild must use a separate file')
    receipt = target.parent / 'rebuild-hashes.json'
    if not args.check:
        before = None if args.without_original else sha(source.read_bytes())
        manifest = read_exports(exports)[0] if args.without_original else verify(source, exports)
        rebuild(blueprint, exports, target)
        if not args.without_original:
            verify(source, exports)
        if not args.without_original and sha(source.read_bytes()) != before:
            raise ValueError('The source database changed during rebuild')
        result = {'source': None if args.without_original else source.relative_to(root).as_posix(), 'rebuilt': target.relative_to(root).as_posix(),
                  'source_file_sha256': before, 'rebuilt_file_sha256': sha(target.read_bytes()),
                  'schema_sha256': manifest['schema_sha256'],
                  'tables': {n: {'rows': t['rows'], 'sha256': t['sha256']} for n, t in manifest['tables'].items()}}
        write_same(receipt, packed(result) + b'\n')
        print('PASS rebuild rebuild ' + str(len(manifest['tables'])) + ' tables; ' + manifest['schema_sha256'])
        return 0
    failures = []
    groups = ('blueprint', 'hashes', 'integrity', 'repeat', 'source') if args.check == 'all' else (args.check,)
    for group in groups:
        try:
            manifest = read_exports(exports)[0] if args.without_original else verify(source, exports)
            if group == 'blueprint':
                if expected_schema(blueprint) != manifest['schema_sha256']:
                    raise ValueError('Blueprint schema differs')
                compare(target, manifest)
                detail = 'blueprint v11 schema equals original and rebuild'
            elif group in ('hashes', 'integrity'):
                compare(target, manifest)
                detail = 'all table row hashes and counts match' if group == 'hashes' else 'integrity and foreign keys pass; guards retain schema'
            elif group == 'repeat':
                compare(target, manifest)
                before = (sha(target.read_bytes()), target.stat().st_mtime_ns)
                rebuild(blueprint, exports, target)
                if before != (sha(target.read_bytes()), target.stat().st_mtime_ns):
                    raise ValueError('Second rebuild changed bytes or file time')
                detail = 'second rebuild keeps every byte and file time'
            else:
                if args.without_original:
                    print('OUT-OF-SCOPE rebuild source original database is unavailable; compare the rebuilt database with the exports')
                    continue
                result = json.loads(receipt.read_bytes())
                if result['source_file_sha256'] != sha(source.read_bytes()):
                    raise ValueError('Source file differs from recorded hash')
                if result['rebuilt_file_sha256'] != sha(target.read_bytes()):
                    raise ValueError('Rebuilt file differs from recorded hash')
                detail = 'original database file remains unchanged'
            print('PASS rebuild ' + group + ' ' + detail)
        except (ValueError, OSError, sqlite3.Error) as error:
            failures.append(group)
            print('FAIL rebuild ' + group + ' ' + str(error))
    return bool(failures)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error) as error:
        print('FAIL rebuild rebuild ' + str(error))
        raise SystemExit(1)
