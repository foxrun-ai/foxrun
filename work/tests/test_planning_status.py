"""WMV2: Backlog and To do preserve ownership and release current claims."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from night_work_fixtures import WriterCase

class PlanningStatusTests(WriterCase):
    def test_backlog_and_todo_release_claim_keep_owner_and_flag(self):
        self.sql("UPDATE tasks SET status='in-progress',owner='worker',claimed_by='worker',claimed_at='2026-10-05',flag=1 WHERE id='T1'")
        self.assert_ok(self.call('backlog','T1','--by','chief-of-staff','--note','Later'))
        self.assertEqual([('backlog','worker',None,None,1)],self.sql("SELECT status,owner,claimed_by,claimed_at,flag FROM tasks WHERE id='T1'"))
        self.assertEqual([('claimed_at',),('claimed_by',),('status',)],self.sql('SELECT field FROM activity ORDER BY field'))
        self.assertEqual(1,len(self.sql('SELECT * FROM comments')))
        self.assert_ok(self.call('todo','T1','--by','chief-of-staff','--note','Next'))
        self.assertEqual([('todo','worker',None,None,1)],self.sql("SELECT status,owner,claimed_by,claimed_at,flag FROM tasks WHERE id='T1'"))
        self.assertEqual(2,len(self.sql('SELECT * FROM comments')))
        self.assertEqual([('in-progress','backlog'),('backlog','todo')],self.sql("SELECT old_value,new_value FROM activity WHERE field='status' ORDER BY id"))

    def test_repeat_status_does_not_write(self):
        for verb in ('todo','backlog'):
            self.assert_ok(self.call(verb,'T1','--by','sol'))
            before = self.db.read_bytes()
            self.assertIn('duplicate',self.call(verb,'T1','--by','sol')[1])
            self.assertEqual(before,self.db.read_bytes())

    def test_final_tasks_and_invalid_calls_do_not_write(self):
        for status in ('done','canceled','superseded'):
            self.sql('UPDATE tasks SET status=? WHERE id=?',(status,'T1'))
            for verb in ('backlog','todo'):
                self.assert_refused_without_write(verb,'T1','--by','sol')
        for args in [('backlog','missing','--by','sol'),('backlog','T1'),
                     ('todo','T1','--by','sol','--status','done')]:
            self.assert_refused_without_write(*args)
