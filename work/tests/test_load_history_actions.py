"""Synthetic import tests: exact history, missing parents, unknown fields, and repeat safety."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest


class HistoryLoadTests(unittest.TestCase):
    def test_event_doubles_stay_excluded_after_the_parent_arrives(self):
        from load_history_actions import load
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'system-workspace.sqlite', root / 'data.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE activity (id INTEGER PRIMARY KEY,subject_type,subject_id,field,old_value,new_value,actor,source,at,note,verb)')
                for i, (field, value) in enumerate((('comment','9'), ('approval','approve'), ('receipt','proof.md'), ('link','task:T1')), 1):
                    db.execute('INSERT INTO activity VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                               (i,'task','missing',field,None,value,'sol','work cli','2026-10-01',None,'created'))
                db.commit()
            with closing(sqlite3.connect(target)) as db:
                db.execute('CREATE TABLE work_changes (seq,workspace,subject_type,subject_id,field,old_value,new_value,action,actor,source,occurred_at,recorded_at,summary,refs)')
                db.execute('CREATE TABLE _foxrun_sequence (id,value)')
                db.execute('INSERT INTO _foxrun_sequence VALUES (1,0)')
                db.commit()
            def connect(path, context=None):
                db = sqlite3.connect(path)
                db.row_factory = sqlite3.Row
                return db
            core = types.SimpleNamespace(connect=connect)
            first = load(source,target,'system-workspace',root/'before1.db',core)
            self.assertEqual((first['doubles'], first['waiting'], first['new_rows']), (4,0,0))
            with closing(sqlite3.connect(target)) as db:
                db.execute('CREATE TABLE work_tasks (id,number,workspace,status)')
                db.execute("INSERT INTO work_tasks VALUES (1,'missing','system-workspace','todo')")
                db.commit()
            second = load(source,target,'system-workspace',root/'before2.db',core)
            self.assertEqual((second['doubles'], second['waiting'], second['new_rows']), (4,0,0))

    def test_import_is_exact_and_repeat_adds_nothing(self):
        from load_history_actions import load
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'system-workspace.sqlite', root / 'data.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE activity (id INTEGER PRIMARY KEY, subject_type,subject_id,field,old_value,new_value,actor,source,at,note,verb)')
                db.execute('CREATE TABLE functions (id,organization)')
                db.execute("INSERT INTO functions VALUES ('comms','foxrun')")
                rows = [
                    (1,'task','T1','comment',None,'77','sol','work cli','2026-10-01','Exact note',None),
                    (2,'task','T1','mystery',None,'?', 'sol','work cli','2026-10-01',None,None),
                    (3,'task','T2','title','Old','New','sol','work cli','2026-10-01',None,None),
                    (4,'task','T1','status','todo','in-progress','sol','work cli','2026-10-01','claimed',None),
                    (5,'function','comms','create',None,'Comms','sol','work cli','2026-10-01',None,None),
                ]
                db.executemany('INSERT INTO activity VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
                db.commit()
            with closing(sqlite3.connect(target)) as db:
                db.execute('CREATE TABLE work_tasks (id INTEGER PRIMARY KEY,number,workspace,status)')
                db.execute("INSERT INTO work_tasks VALUES (8,'T1','system-workspace','in-progress')")
                db.execute('CREATE TABLE work_functions (id INTEGER PRIMARY KEY,number,workspace)')
                db.execute("INSERT INTO work_functions VALUES (9,'comms','foxrun')")
                db.execute('CREATE TABLE work_changes (seq INTEGER PRIMARY KEY,workspace,subject_type,subject_id,field,old_value,new_value,action,actor,source,occurred_at,recorded_at,summary,refs)')
                db.execute('CREATE TABLE _foxrun_sequence (id INTEGER PRIMARY KEY,value)')
                db.execute('INSERT INTO _foxrun_sequence VALUES (1,0)')
                db.execute('CREATE TRIGGER advance AFTER INSERT ON work_changes BEGIN UPDATE _foxrun_sequence SET value=NEW.seq WHERE id=1; END')
                db.commit()
            def connect(path, context=None, readonly=False):
                db = sqlite3.connect(path)
                db.row_factory = sqlite3.Row
                return db
            core = types.SimpleNamespace(connect=connect)
            before = source.read_bytes()
            first = load(source, target, 'system-workspace', root/'backup1.db', core)
            self.assertEqual((first['blank_lines'], first['loaded'], first['held'], first['waiting'], first['doubles']), (5,2,1,1,1))
            self.assertEqual(first['held_by_field'], {'mystery':1})
            self.assertEqual(first['new_rows'], 2)
            second = load(source, target, 'system-workspace', root/'backup2.db', core)
            self.assertEqual(second['new_rows'], 0)
            self.assertEqual(source.read_bytes(), before)
            with closing(sqlite3.connect(target)) as db:
                self.assertEqual(db.execute('SELECT subject_id,field,old_value,new_value,action,actor,source,occurred_at,summary FROM work_changes ORDER BY seq').fetchall(),
                                 [(8,'status','todo','in-progress','claimed','sol','work cli','2026-10-01','claimed'),
                                  (9,'create',None,'Comms','created','sol','work cli','2026-10-01',None)])
                self.assertEqual(db.execute("SELECT workspace FROM work_changes WHERE subject_type='function'").fetchall(), [('foxrun',)])
                refs = json.loads(db.execute('SELECT refs FROM work_changes ORDER BY seq LIMIT 1').fetchone()[0])
                self.assertEqual(refs[0]['source_key'], '[4]')
                self.assertEqual(refs[0]['source_database'], 'system-workspace.sqlite')
                self.assertEqual(refs[0]['original_verb'], None)
            # A later source state that contradicts its unchanged parent stays held.
            with closing(sqlite3.connect(source)) as db:
                db.execute("INSERT INTO activity VALUES (6,'task','T1','status','in-progress','done','sol','work cli','2026-10-01',NULL,NULL)")
                db.commit()
            third = load(source, target, 'system-workspace', root/'backup3.db', core)
            self.assertEqual(third['new_rows'], 0)
            self.assertEqual(third['held_by_field'], {'mystery':1,'status':1})
            with closing(sqlite3.connect(target)) as db:
                db.execute("UPDATE work_changes SET summary='tampered' WHERE seq=1")
                db.commit()
            with self.assertRaisesRegex(ValueError, 'Existing history differs'):
                load(source, target, 'system-workspace', root/'backup4.db', core)


if __name__ == '__main__':
    unittest.main()
