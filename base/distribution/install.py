#!/usr/bin/env python3
"""Create a core data.db and a made-up workspace. Existing changed data is preserved."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def logical_hash(db):
    result = []
    for name, sql in db.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        rows = [tuple(row) for row in db.execute('SELECT * FROM "' + name + '" ORDER BY 1')]
        result.append([name, sql, rows])
    return sha(json.dumps(result, sort_keys=True, separators=(',', ':')).encode())

def install(home, version):
    here = (Path(__file__).resolve().parent)
    spec = importlib.util.spec_from_file_location('sample', (Path(__file__).resolve().parent / 'sample_workspace.py'))
    sample = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sample)
    fixture = json.loads(((Path(__file__).resolve().parent / 'sample/rows.json')).read_text())
    target = home / 'Workspaces' / fixture['workspace']
    core = Path(__file__).resolve().parent.parent
    db_path = home / '.local/share/foxrun/data.db'
    receipt_path = db_path.parent / 'install-receipt.json'
    if sqlite3.sqlite_version_info < (3, 37):
        raise ValueError('SQLite 3.37 or later is required.')
    for path in [home, target, db_path, receipt_path]:
        if any(parent.is_symlink() for parent in [path, *path.parents]):
            raise ValueError('Install target crosses a symlink.')
    db = sample.build_database(core, fixture)
    try:
        outputs = sample.pages(db, fixture)
        receipt = {'version': version, 'workspace': fixture['workspace'], 'database_sha256': logical_hash(db),
                   'files': {name: sha(raw) for name, raw in sorted(outputs.items())}}
        changed = [name for name, raw in outputs.items() if (target / name).exists() and (target / name).read_bytes() != raw]
        if changed:
            raise ValueError('Existing workspace differs; nothing changed: ' + ', '.join(changed))
        if db_path.exists():
            if not receipt_path.is_file() or json.loads(receipt_path.read_text()) != receipt:
                raise ValueError('Existing install receipt differs; nothing changed.')
            current = _fox_person.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                if logical_hash(current) != receipt['database_sha256']:
                    raise ValueError('Existing database differs; nothing changed.')
            finally:
                current.close()
            if any(not (target / name).is_file() for name in outputs):
                raise ValueError('Existing workspace is incomplete; nothing changed.')
            print('PASS Workspace Install: existing sample and database match; nothing changed')
            return
        if receipt_path.exists() or target.exists():
            raise ValueError('Install target already has workspace files or a receipt; nothing changed.')
        db_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(prefix='install-', suffix='.db', dir=db_path.parent, delete=False)
        temporary.close()
        temp_path = Path(temporary.name)
        destination = _fox_person.connect(temp_path)
        try:
            db.backup(destination)
        finally:
            destination.close()
        try:
            # An exclusive link prevents overwriting a concurrent install.
            import os
            os.link(temp_path, db_path)
        finally:
            temp_path.unlink(missing_ok=True)
        sample.generate(core, target)
        receipt_path.write_bytes(sample.encoded(receipt))
        print('PASS Workspace Install: core data.db and made-up Cedar Shop created')
    finally:
        db.close()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home', type=Path, required=True)
    p.add_argument('--version', required=True)
    args = p.parse_args()
    try:
        install(args.home.absolute(), args.version)
    except (OSError, ValueError, sqlite3.Error) as error:
        print('FAIL Workspace Install: ' + str(error), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
