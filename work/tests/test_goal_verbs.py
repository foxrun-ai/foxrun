"""WMV4: create goals and assign existing tasks with comments and activity."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from night_work_fixtures import WriterCase

class GoalVerbTests(WriterCase):
    def create(self, *args):
        return self.call('goal-create','--title','Synthetic goal','--horizon','quarter','--by','sol',*args)

    def test_create_goal_with_fields_and_assign_then_repeat(self):
        self.sql("INSERT INTO functions(id,name) VALUES ('work','Work')")
        self.assert_ok(self.create('--id','G-wm','--period','2026-Q4','--function','work','--owner','person','--tags','WORK,foundation','--status','at-risk'))
        self.assertEqual([('G-wm','Synthetic goal','quarter','2026-Q4','work','person','work,foundation','at-risk')],self.sql('SELECT id,title,horizon,period,function,owner,tags,status FROM goals'))
        self.assertEqual([('goal','G-wm','create','sol')],self.sql('SELECT subject_type,subject_id,field,actor FROM activity'))
        self.assert_ok(self.call('task-goal','T1','--goal','G-wm','--by','chief-of-staff'))
        self.assertEqual([('G-wm',)],self.sql("SELECT goal FROM tasks WHERE id='T1'"))
        self.assertEqual([(None,'G-wm')],self.sql("SELECT old_value,new_value FROM activity WHERE field='goal'"))
        self.assertEqual(2,len(self.sql('SELECT * FROM comments')))
        before = self.db.read_bytes()
        self.assertIn('duplicate',self.call('task-goal','T1','--goal','G-wm','--by','chief-of-staff')[1])
        self.assertEqual(before,self.db.read_bytes())

    def test_goal_numbers_ignore_named_ids_and_use_highest_number(self):
        for goal_id in ('G-standard','G2','G10'):
            self.assert_ok(self.create('--id',goal_id))
        result = self.create()
        self.assert_ok(result)
        self.assertEqual('G11',result[1].strip().split()[-1])

    def test_duplicate_invalid_goal_and_unknown_assignment_do_not_write(self):
        self.assert_ok(self.create('--id','G-wm'))
        for args in [('goal-create','--title','Duplicate','--horizon','quarter','--id','G-wm','--by','sol'),
                     ('goal-create','--title','Bad','--horizon','week','--by','sol'),
                     ('goal-create','--title','Bad','--horizon','quarter','--status','todo','--by','sol'),
                     ('goal-create','--title','Bad','--horizon','quarter','--function','missing','--by','sol'),
                     ('goal-create','--title','Missing horizon','--by','sol'),
                     ('goal-create','--title','Missing actor','--horizon','quarter'),
                     ('task-goal','T1','--goal','missing','--by','sol'),
                     ('task-goal','missing','--goal','G-wm','--by','sol'),
                     ('task-goal','T1','--goal','G-wm')]:
            self.assert_refused_without_write(*args)

    def test_change_goal_records_old_and_new(self):
        for goal_id in ('G-one','G-two'):
            self.assert_ok(self.create('--id',goal_id))
            self.assert_ok(self.call('task-goal','T1','--goal',goal_id,'--by','sol'))
        self.assertEqual([(None,'G-one'),('G-one','G-two')],self.sql("SELECT old_value,new_value FROM activity WHERE field='goal' ORDER BY id"))
