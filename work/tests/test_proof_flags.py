"""T290: current proof flags and one-release aliases have identical writes."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

import work

class ProofFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / 'tracker.sqlite'
        (self.root / 'proof.md').write_text('Checked output')
        (self.root / 'second.md').write_text('Second output')
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript((Path(work.__file__).parent / 'blueprint.sql').read_text())
            db.executemany("INSERT INTO tasks(id,title) VALUES (?,?)", [('T1','One'),('T2','Two')])
            db.commit()

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = work.run(['--db', str(self.db), '--receipt-root', str(self.root), *args], stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def rows(self, sql):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute(sql).fetchall()

    def test_current_and_old_done_flags(self):
        for task, flags in [('T1', ['--proof','proof.md','--note','Checked']),
                            ('T2', ['--receipt','proof.md','--proof','Checked'])]:
            self.assertEqual(0, self.call('done', task, '--by', 'sol', *flags)[0])
        self.assertEqual([('T1','in-review'),('T2','in-review')], self.rows('SELECT id,status FROM tasks ORDER BY id'))
        self.assertEqual([('Proof: Checked',),('Proof: Checked',)], self.rows('SELECT body FROM comments ORDER BY id'))
        self.assertEqual(2, len(self.rows('SELECT * FROM attachments')))

    def test_repeat_paths_and_mixed_alias_are_checked_and_idempotent(self):
        args = ('done','T1','--by','sol','--proof','proof.md','--receipt','second.md','--note','Checked')
        self.assertEqual(0, self.call(*args)[0])
        before = self.db.read_bytes()
        self.assertIn('duplicate', self.call(*args)[1])
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(2, len(self.rows('SELECT * FROM attachments')))

    def test_invalid_flags_write_nothing(self):
        before = self.db.read_bytes()
        for flags in (['--proof','proof.md'], ['--proof','missing.md','--note','Checked'],
                      ['--proof','proof.md','--proof','proof.md','--note','Checked'],
                      ['--receipt','proof.md','--proof','one','--proof','two']):
            self.assertEqual(2, self.call('done','T1','--by','sol',*flags)[0])
            self.assertEqual(before, self.db.read_bytes())

    def test_done_refuses_any_open_task_run_without_writes(self):
        runs = []
        for actor in ('sol', 'opus'):
            code, output, error = self.call('run-start', 'T1', '--by', actor,
                                           '--model', 'test-model', '--runtime', 'codex')
            self.assertEqual((code, error), (0, ''))
            runs.append(output.strip())
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE runs SET ended_at='' WHERE id=?", (runs[1],))
            db.commit()
        args = ('done', 'T1', '--by', 'sol', '--proof', 'proof.md', '--note', 'Checked')
        before = self.db.read_bytes()
        code, output, error = self.call(*args)
        self.assertEqual((code, output), (2, ''))
        self.assertIn('task T1 has open runs:', error)
        self.assertIn('run-end before done', error)
        for run in runs:
            self.assertIn(run, error)
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(0, self.call('run-end', runs[0], '--result', 'pass', '--proof', 'proof.md')[0])
        before = self.db.read_bytes()
        self.assertEqual(2, self.call(*args)[0])
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(0, self.call('run-end', runs[1], '--result', 'fail', '--proof', 'proof.md')[0])
        self.assertEqual(0, self.call(*args)[0])
        self.assertEqual([('in-review',)], self.rows("SELECT status FROM tasks WHERE id='T1'"))

    def test_done_ignores_other_tasks_and_other_run_subjects(self):
        self.assertEqual(0, self.call('run-start', 'T2', '--by', 'opus',
                                     '--model', 'test-model', '--runtime', 'claude')[0])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('INSERT INTO runs(id,subject_type,subject_id,"by",model,runtime,started_at) '
                       "VALUES ('R-project','project','T1','opus','test-model','claude','2026-10-17')")
            db.commit()
        self.assertEqual(0, self.call('done', 'T1', '--by', 'sol',
                                     '--proof', 'proof.md', '--note', 'Checked')[0])
        self.assertEqual(2, len(self.rows('SELECT id FROM runs WHERE ended_at IS NULL')))

    def test_run_end_current_and_alias(self):
        for task, flag in [('T1','--proof'),('T2','--evidence')]:
            result = self.call('run-start',task,'--by','sol','--model','inherit','--runtime','codex')
            self.assertEqual(0, result[0])
            run_id = result[1].strip().split()[-1]
            self.assertEqual(0, self.call('run-end',run_id,'--result','built',flag,'proof.md')[0])
        self.assertEqual([('built','proof.md'),('built','proof.md')], self.rows('SELECT result,evidence FROM runs ORDER BY id'))

if __name__ == '__main__':
    unittest.main()
