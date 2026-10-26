#!/usr/bin/env python3
"""T260: the lessons table, the active_lessons view, their dictionary rows, and the start-page part.

Run from the system home: python3 -m unittest memory.tests.test_lessons
"""
from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

MEMORY = Path(__file__).resolve().parents[1]
ROOT = MEMORY.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('memory_lessons_module', MEMORY / 'lessons.py')
lessons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lessons)
spec = importlib.util.spec_from_file_location('lessons_apply_dictionary', ROOT / 'base/apply_dictionary.py')
apply_dictionary = importlib.util.module_from_spec(spec)
from unittest.mock import patch
with patch.dict('os.environ', {'FOXRUN_PERSON': 'sample-person'}):
    spec.loader.exec_module(apply_dictionary)

DICTIONARY = '''
CREATE TABLE object_types (name TEXT PRIMARY KEY NOT NULL, supertype TEXT, subtype TEXT, lens TEXT,
  container TEXT NOT NULL, module TEXT NOT NULL, database_type TEXT, storage_name TEXT NOT NULL,
  description TEXT NOT NULL, why TEXT, example TEXT, definition TEXT, source TEXT NOT NULL);
CREATE TABLE fields (object_type TEXT NOT NULL REFERENCES object_types(name) DEFERRABLE INITIALLY DEFERRED,
  field TEXT NOT NULL, ordinal INTEGER NOT NULL, required INTEGER NOT NULL DEFAULT 0, field_type TEXT NOT NULL,
  pick_values TEXT, pick_source TEXT, description TEXT NOT NULL, storage_type TEXT, sql_definition TEXT,
  source TEXT NOT NULL, PRIMARY KEY (object_type, field), UNIQUE (object_type, ordinal));
'''


class LessonsTable(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lessons-')
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'data.db'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(DICTIONARY)

    def rows(self, sql, values=()):
        with closing(sqlite3.connect(self.db)) as db:
            return list(db.execute(sql, values))

    def insert(self, **change):
        row = dict(id='L1', text='Every task id carries its title.', source='file:/memory/a.md',
                   created_on='2026-10-19')
        row.update(change)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO lessons (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')',
                       list(row.values()))
            db.commit()

    def test_apply_adds_table_view_and_dictionary_once(self):
        first = lessons.apply(self.db)
        self.assertEqual({'table_existed': False, 'changes': 17}, first)
        self.assertEqual({'table_existed': True, 'changes': 0}, lessons.apply(self.db))
        names = {row[0] for row in self.rows("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        self.assertTrue({'lessons', 'active_lessons'} <= names)
        self.assertEqual([('active_lessons', 'view', 'memory'), ('lessons', 'table', 'memory')],
                         self.rows("SELECT name,database_type,module FROM object_types ORDER BY name"))
        columns = [row[1] for row in self.rows('PRAGMA table_info(lessons)')]
        self.assertEqual(['id', 'text', 'person_words', 'source', 'workspace', 'applies_to', 'status',
                          'replaces', 'created_on'], columns)
        self.assertEqual(columns, [row[0] for row in self.rows(
            "SELECT field FROM fields WHERE object_type='lessons' ORDER BY ordinal")])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual([], apply_dictionary.dictionary_column_errors(db))

    def test_apply_keeps_existing_rows(self):
        lessons.apply(self.db)
        self.insert()
        lessons.apply(self.db)
        self.assertEqual([('L1', 'all', 'all', 'active')],
                         self.rows('SELECT id,workspace,applies_to,status FROM lessons'))

    def test_checks_refuse_bad_rows(self):
        lessons.apply(self.db)
        self.insert()
        bad = [dict(id='L2', text='two\nlines'), dict(id='L2', text=' '), dict(id='L2', source=''),
               dict(id='L2', text='other', status='open'), dict(id='X2', text='other'), dict(id='L0', text='other'),
               dict(id='L2x', text='other'), dict(id='L2', text='other', created_on='10.19'),
               dict(id='L2', text='other', replaces='L9'), dict(id='L1', text='other'),
               dict(id='L2')]  # the same source and text twice
        for row in bad:
            with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                self.insert(**row)

    def test_view_lists_active_newest_first(self):
        lessons.apply(self.db)
        self.insert()
        self.insert(id='L2', text='Answer the question he asked first.', created_on='2026-10-19')
        self.insert(id='L3', text='An old rule.', created_on='2026-09-01', status='replaced')
        self.insert(id='L10', text='Group replies for the phone.', created_on='2026-10-19')
        self.assertEqual(['L10', 'L2', 'L1'], [row[0] for row in self.rows('SELECT id FROM active_lessons')])

    def test_active_filters_workspace_and_seat(self):
        lessons.apply(self.db)
        self.insert()
        self.insert(id='L2', text='Shop rule.', workspace='cedar-shop')
        self.insert(id='L3', text='Chief rule.', applies_to='chief-of-staff')
        with closing(sqlite3.connect(self.db)) as db:
            ids = lambda workspace, seat: sorted(row['id'] for row in lessons.active(db, workspace, seat))
            self.assertEqual(['L1'], ids('system-workspace', None))
            self.assertEqual(['L1', 'L2'], ids('cedar-shop', None))
            self.assertEqual(['L1', 'L3'], ids('system-workspace', 'chief-of-staff'))
            self.assertEqual(['L1'], ids('system-workspace', 'architect'))

    def test_start_part_is_short_and_has_the_command(self):
        self.assertEqual('', lessons.start_part(self.db, 'system-workspace', None))
        lessons.apply(self.db)
        for number in range(1, 31):
            self.insert(id='L' + str(number), text='Rule number ' + str(number) + '. ' + 'x' * 200)
        text = lessons.start_part(self.db, 'system-workspace', 'architect')
        lines = text.splitlines()
        self.assertEqual('## Lessons', lines[0])
        self.assertIn('30 active lessons for every agent and architect in system-workspace.', lines[1])
        self.assertLessEqual(len(lines), lessons.START_LINES + 4)
        self.assertTrue(all(len(line) <= 160 for line in lines[2:-1]))
        self.assertIn('18 more; use the command below.', text)
        self.assertTrue(lines[-1].startswith('Command: sqlite3 -readonly '))
        command = lines[-1][len('Command: sqlite3 -readonly '):].split(' ', 1)[1].strip('"').rstrip(';')
        self.assertEqual(30, len(self.rows(command)))

    def test_seed_block_is_in_the_shipped_seed(self):
        block = lessons.seed_block()
        self.assertEqual(17, len(block))
        self.assertTrue(all(line.startswith('INSERT OR IGNORE INTO ') for line in block))


if __name__ == '__main__':
    unittest.main()
