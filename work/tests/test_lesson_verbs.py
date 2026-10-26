#!/usr/bin/env python3
"""T260: work.py lesson-add and lesson-update write the lessons table every agent reads."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import closing
import importlib.util
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import work
from test_work import blueprint_sql

spec = importlib.util.spec_from_file_location('lesson_verbs_lessons', _fox_root / 'memory/lessons.py')
lessons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lessons)


class LessonVerbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lesson-verbs-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.receipts = self.root / 'receipts'
        self.receipts.mkdir()
        self.db = self.root / 'data.db'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(blueprint_sql())
            db.commit()
        (Path(os.environ['FOXRUN_PORTFOLIO']) / 'cedar-shop').mkdir(exist_ok=True)

    def call(self, *arguments: str):
        out, err = io.StringIO(), io.StringIO()
        code = work.run(['--db', str(self.db), '--receipt-root', str(self.receipts), *arguments],
                        stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def rows(self, sql, values=()):
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, values)]

    def add(self, rule='Every task id carries its title.', source='file:/memory/a.md', *more):
        return self.call('lesson-add', '--rule', rule, '--source', source, '--by', 'keeper', *more)

    def test_refuses_until_the_table_is_applied(self):
        code, _, err = self.add()
        self.assertEqual(2, code)
        self.assertIn('lessons table is not installed', err)
        lessons.apply(self.db)
        self.assertEqual((0, 'ok lesson-add L1\n', ''), self.add())

    def test_add_writes_every_field_and_one_change_row(self):
        lessons.apply(self.db)
        code, out, err = self.add('Answer the question he asked first.', 'comment:7535',
                                  '--person-words', 'answer what I asked', '--lesson-workspace', 'cedar-shop',
                                  '--applies-to', 'chief-of-staff')
        self.assertEqual((0, 'ok lesson-add L1\n', ''), (code, out, err))
        row = self.rows('SELECT * FROM lessons')[0]
        self.assertEqual({'id': 'L1', 'text': 'Answer the question he asked first.',
                          'person_words': 'answer what I asked', 'source': 'comment:7535',
                          'workspace': 'cedar-shop', 'applies_to': 'chief-of-staff', 'status': 'active',
                          'replaces': None}, {key: row[key] for key in row if key != 'created_on'})
        self.assertEqual(work.now()[:10], row['created_on'])
        self.assertEqual([('create', 'keeper', 'source=comment:7535')], [
            (r['field'], r['actor'], r['note']) for r in
            self.rows("SELECT field,actor,note FROM activity WHERE subject_type='lesson' AND subject_id='L1'")])

    def test_defaults_ids_and_duplicates(self):
        lessons.apply(self.db)
        self.add()
        self.assertEqual((0, 'ok lesson-add L1 duplicate\n', ''), self.add('every task id carries its title. ', 'x'))
        self.assertEqual((0, 'ok lesson-add L2\n', ''), self.add('Group replies for the phone.'))
        self.assertEqual([('L1', 'all', 'all'), ('L2', 'all', 'all')],
                         [(r['id'], r['workspace'], r['applies_to']) for r in self.rows('SELECT * FROM lessons')])

    def test_replaces_marks_the_old_lesson(self):
        lessons.apply(self.db)
        self.add()
        code, out, _ = self.add('Every id, in every reply, carries its title.', 'comment:9', '--replaces', 'L1')
        self.assertEqual((0, 'ok lesson-add L2\n'), (code, out))
        self.assertEqual({'L1': 'replaced', 'L2': 'active'},
                         {r['id']: r['status'] for r in self.rows('SELECT id,status FROM lessons')})
        self.assertEqual(['L2'], [r['id'] for r in self.rows('SELECT id FROM active_lessons')])
        self.assertEqual(1, len(self.rows("SELECT 1 FROM activity WHERE subject_id='L1' AND field='status' "
                                          "AND new_value='replaced' AND note='replaced by L2'")))

    def test_update_changes_fields_once(self):
        lessons.apply(self.db)
        self.add()
        self.assertEqual((0, 'ok lesson-update L1\n', ''),
                         self.call('lesson-update', 'L1', '--applies-to', 'architect', '--rule', 'Ids carry titles.',
                                   '--by', 'keeper'))
        self.assertEqual((0, 'ok lesson-update L1 duplicate\n', ''),
                         self.call('lesson-update', 'L1', '--applies-to', 'architect', '--by', 'keeper'))
        self.assertEqual(('Ids carry titles.', 'architect'),
                         tuple(self.rows('SELECT text,applies_to FROM lessons')[0].values()))
        self.assertEqual({'applies_to', 'text'}, {r['field'] for r in self.rows(
            "SELECT field FROM activity WHERE subject_id='L1' AND field<>'create'")})
        self.assertEqual((0, 'ok lesson-update L1\n', ''),
                         self.call('lesson-update', 'L1', '--status', 'replaced', '--by', 'keeper'))
        self.assertEqual([], self.rows('SELECT * FROM active_lessons'))

    def test_refusals(self):
        lessons.apply(self.db)
        self.add()
        cases = [
            (('lesson-add', '--rule', 'x', '--by', 'keeper'), 'needs --rule'),
            (('lesson-add', '--source', 'x', '--by', 'keeper'), 'needs --rule'),
            (('lesson-add', '--rule', 'x', '--source', 's'), '--by is required'),
            (('lesson-add', 'L5', '--rule', 'x', '--source', 's', '--by', 'keeper'), 'no positional id'),
            (('lesson-add', '--rule', 'x', '--source', 's', '--status', 'active', '--by', 'keeper'), '--status belongs'),
            (('lesson-add', '--rule', 'two\nlines', '--source', 's', '--by', 'keeper'), 'one non-empty line'),
            (('lesson-add', '--rule', 'x', '--source', 's', '--lesson-workspace', 'nowhere', '--by', 'keeper'),
             'no such workspace'),
            (('lesson-add', '--rule', 'x', '--source', 's', '--applies-to', 'Chief Of Staff', '--by', 'keeper'),
             'must be all or a lowercase seat id'),
            (('lesson-add', '--rule', 'x', '--source', 's', '--replaces', 'L9', '--by', 'keeper'),
             'no such lesson to replace'),
            (('lesson-update', 'L1', '--by', 'keeper'), 'needs a field to change'),
            (('lesson-update', 'L9', '--rule', 'y', '--by', 'keeper'), 'no such lesson'),
            (('lesson-update', 'T1', '--rule', 'y', '--by', 'keeper'), 'a lesson id is L and a number'),
            (('lesson-update', 'L1', '--status', 'open', '--by', 'keeper'), '--status must be one of'),
            (('lesson-update', 'L1', '--replaces', 'L1', '--by', 'keeper'), 'cannot replace itself'),
            (('comment', 'T1', 'hello', '--rule', 'x', '--by', 'keeper'), '--rule belong to lesson-add'),
        ]
        for argv, message in cases:
            with self.subTest(argv=argv):
                code, _, err = self.call(*argv)
                self.assertEqual(2, code)
                self.assertIn(message, err)
        self.assertEqual(1, len(self.rows('SELECT * FROM lessons')))


class ScriptRefusalTests(unittest.TestCase):
    def test_a_decisions_refusal_from_the_script_exits_2_without_a_traceback(self):
        import subprocess
        with tempfile.TemporaryDirectory(prefix='work-script-') as folder:
            folder = str(Path(folder).resolve())
            db = Path(folder) / 'data.db'
            with closing(sqlite3.connect(db)) as connection:
                connection.executescript(blueprint_sql())
            result = subprocess.run([sys.executable, '-B', str(_fox_root / 'work/work.py'), '--db', str(db),
                                     '--receipt-root', folder, 'decision-add', '--id', 'probe', '--name', 'probe',
                                     '--status', 'bogus', '--by', 'keeper'], capture_output=True, text=True)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn('work failed: --status must be one of', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
