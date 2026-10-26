"""Verify regeneration leaves files and rows unchanged after its first successful run."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import hashlib
import sqlite3
from pathlib import Path
from core import connect,schema_hash
from dictionary_v11 import snapshot
from regenerate import regenerate

def state(root,database):
    # macOS /var and /private/var name the same temporary home; compare resolved paths.
    root=Path(root).resolve();database=(root/database).resolve()
    directories=(root/'code/foxrun-modules/base',root/'vault/system-workspace/docs/data-db',database.parent)
    files={}
    for directory in directories:
        for path in directory.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or path.name.endswith(('-shm','-wal')):continue
            files[str(path.relative_to(root))]=(hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns)
    db=connect(database,readonly=True);digest=schema_hash(db);db.close()
    return files,digest,snapshot(database)

def verify(root,database='home/dm2-build/data.db'):
    first=regenerate(root,database)
    before=state(root,database)
    second=regenerate(root,database)
    after=state(root,database)
    assert first==second==before[1]==after[1],'regeneration schema differs'
    assert before==after,'second regeneration changed a file, row, or file timestamp'
    print('PASS second regeneration changes no files or rows; schema '+first)
