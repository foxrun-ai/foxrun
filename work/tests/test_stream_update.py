"""T715: stream-update changes a stream's title or rank with one change row per field."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing
from base import person as _fox_person
from night_work_fixtures import WriterCase


class StreamUpdateTests(WriterCase):
    def setUp(self):
        super().setUp()
        with closing(_fox_person.connect(self.db)) as db:
            db.execute("INSERT INTO programs (id,name) VALUES ('PG1','Cedar Shop program')")
            db.execute("INSERT INTO themes (id,program,name,ord) VALUES ('TH1','PG1','Theme',1)")
            db.execute("INSERT INTO functions (id,name) VALUES ('ops','Operations')")
            db.execute("INSERT INTO projects (id,title,status,function,program,theme,ord,order_column,needs,span,alongside) "
                       "VALUES ('WS01','Old rules','todo','ops','PG1','TH1',17,17,'[]',1,0)")
            db.commit()

    def test_title_and_rank_each_write_one_change_row(self):
        self.assert_ok(self.call('stream-update', 'WS01', '--title', 'Agents', '--ord', '6',
                                 '--note', 'approved order', '--by', 'architect'))
        self.assertEqual([('Agents', 6, 17)], self.sql("SELECT title,ord,order_column FROM projects WHERE id='WS01'"))
        self.assertEqual(
            [('project', 'WS01', 'title', 'Old rules', 'Agents', 'architect', 'approved order', 'updated'),
             ('project', 'WS01', 'ord', '17', '6', 'architect', 'approved order', 'updated')],
            self.sql('SELECT subject_type,subject_id,field,old_value,new_value,actor,note,verb FROM activity ORDER BY id'))

    def test_only_changed_fields_and_repeat_writes_nothing(self):
        self.assert_ok(self.call('stream-update', 'WS01', '--title', 'Old rules', '--ord', '3', '--by', 'architect'))
        self.assertEqual([('ord', '17', '3')], self.sql('SELECT field,old_value,new_value FROM activity'))
        before = self.db.read_bytes()
        result = self.call('stream-update', 'WS01', '--ord', '3', '--by', 'architect')
        self.assertEqual((0, 'ok stream-update WS01 duplicate\n'), result[:2])
        self.assertEqual(before, self.db.read_bytes())

    def test_refusals_do_not_write(self):
        for args in [('stream-update', 'WS01', '--ord', '2'),
                     ('stream-update', 'WS01', '--by', 'architect'),
                     ('stream-update', 'WS01', '--ord', '0', '--by', 'architect'),
                     ('stream-update', 'WS99', '--ord', '2', '--by', 'architect'),
                     ('stream-update', 'WS01', '--order', '2', '--by', 'architect'),
                     ('stream-update', 'WS01', '--ord', '2', '--status', 'done', '--by', 'architect'),
                     ('stream-update', 'WS01', 'extra', '--ord', '2', '--by', 'architect'),
                     ('stream-update', '--ord', '2', '--by', 'architect')]:
            self.assert_refused_without_write(*args)


if __name__ == '__main__':
    import unittest
    unittest.main()
