"""WMV1: existing task ranks have a comment and field activity."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from night_work_fixtures import WriterCase

class TaskRankTests(WriterCase):
    def test_rank_change_and_repeat(self):
        self.assert_ok(self.call('task-rank','T1','--ord','3','--by','chief-of-staff'))
        self.assertEqual([(3,)],self.sql("SELECT ord FROM tasks WHERE id='T1'"))
        self.assertEqual([('ord','10','3','chief-of-staff')],self.sql('SELECT field,old_value,new_value,actor FROM activity'))
        self.assertEqual([('Changed ord: 10 -> 3',)],self.sql('SELECT body FROM comments'))
        before = self.db.read_bytes()
        self.assertIn('duplicate',self.call('task-rank','T1','--ord','3','--by','chief-of-staff')[1])
        self.assertEqual(before,self.db.read_bytes())

    def test_task_update_accepts_zero_rank(self):
        self.assert_ok(self.call('task-update','T1','--ord','0','--by','sol'))
        self.assertEqual([(0,)],self.sql("SELECT ord FROM tasks WHERE id='T1'"))

    def test_bad_rank_missing_actor_and_unknown_task_do_not_write(self):
        for args in [('task-rank','T1','--ord','-1','--by','sol'),
                     ('task-rank','T1','--by','sol'),
                     ('task-rank','T1','--ord','2'),
                     ('task-rank','missing','--ord','2','--by','sol'),
                     ('task-rank','T1','--ord','2','--title','Unexpected','--by','sol')]:
            self.assert_refused_without_write(*args)
