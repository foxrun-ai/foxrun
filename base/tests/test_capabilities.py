"""Synthetic regression checks for T9 migration, guards, and command loading."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import csv
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

import core
import load_capabilities
import regenerate

HERE = Path(__file__).resolve().parent.parent
CTX = dict(writer='agent', actor='test', session='T9-test', workspace='system-workspace')


class CapabilityDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'data.db'
        core.build(self.db, (Path(__file__).resolve().parent / '../blueprint'))

    def row(self, **changes):
        value = dict(name='sample', kind='cli', set='base', workspace='system-workspace',
                     status='live', runtimes='["machine"]', card_path='code/agent-team/docs/tools/sample.md')
        value.update(changes)
        return value

    def write(self, row):
        return core.execute(self.db, (Path(__file__).resolve().parent / '../blueprint'), 'base_capabilities', 'insert', row, None, CTX)

    def test_eight_columns_and_dictionary_sentences(self):
        db = core.connect(self.db, readonly=True)
        self.addCleanup(db.close)
        self.assertEqual(['id','name','kind','set','workspace','status','runtimes','card_path'],
                         [r['name'] for r in db.execute('PRAGMA table_info(base_capabilities)')])
        fields = db.execute("SELECT f.field,f.description FROM base_fields f JOIN base_object_types o ON o.id=f.object_type WHERE o.location='base_capabilities' ORDER BY f.sort_order").fetchall()
        self.assertEqual(8, len(fields))
        self.assertEqual('The hidden number that other tables join on.', fields[0]['description'])

    def test_guards_refuse_invalid_facts(self):
        for change in [dict(kind='connector'),dict(status='enabled'),dict(set=None),
                       dict(set='wrong'),dict(runtimes=None),dict(runtimes='[]'),
                       dict(runtimes='{}'),dict(runtimes='["bad"]'),dict(runtimes='[null]'),
                       dict(runtimes='[1]'),dict(workspace='wrong')]:
            with self.subTest(change=change), self.assertRaises(sqlite3.DatabaseError):
                self.write(self.row(**change))
        self.write(self.row(status='dead', set=None, runtimes=None))

    def test_unique_keys_and_raw_writes(self):
        self.write(self.row())
        with self.assertRaises(sqlite3.IntegrityError):self.write(self.row(card_path='other'))
        with self.assertRaises(sqlite3.IntegrityError):self.write(self.row(name='another'))
        with closing(sqlite3.connect(self.db)) as db:
            with self.assertRaises(sqlite3.DatabaseError):db.execute("UPDATE base_capabilities SET status='parked'")

    def test_event_on_change_and_none_on_equal_update(self):
        identity = self.write(self.row())['id']
        def events():
            with closing(sqlite3.connect(self.db)) as db:
                return db.execute("SELECT count(*) FROM work_changes WHERE subject_type='capability'").fetchone()[0]
        self.assertEqual(1, events())
        self.assertFalse(core.execute(self.db,(Path(__file__).resolve().parent / '../blueprint'),'base_capabilities','update',self.row(),identity,CTX)['changed'])
        self.assertEqual(1, events())
        core.execute(self.db,(Path(__file__).resolve().parent / '../blueprint'),'base_capabilities','update',dict(status='parked'),identity,CTX)
        self.assertEqual(2, events())

    def test_load_twice_through_command(self):
        mapping = self.root / 'map.csv'
        with mapping.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['name','kind','set','workspace','state','who_can_use','card_path'])
            writer.writeheader()
            writer.writerow(dict(name='sample',kind='cli',set='base',workspace='system-workspace',state='live',who_can_use='codex; machine',card_path='code/agent-team/docs/tools/sample.md'))
            writer.writerow(dict(name='skip',card_path='none'))
        self.assertEqual(dict(inserted=1,updated=0,unchanged=0),load_capabilities.load(self.db,mapping,'test','T9-test'))
        self.assertEqual(dict(inserted=0,updated=0,unchanged=1),load_capabilities.load(self.db,mapping,'test','T9-test'))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual('["codex", "machine"]',db.execute('SELECT runtimes FROM base_capabilities').fetchone()[0])
            self.assertEqual(1,db.execute("SELECT count(*) FROM work_changes WHERE subject_type='capability'").fetchone()[0])



if __name__=='__main__':
    regenerate.generate_commands(HERE,core.load((Path(__file__).resolve().parent / '../blueprint'))[0])
    unittest.main()
