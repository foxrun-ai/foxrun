"""WMV3: task decision steps live in task_links, with exact history."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from night_work_fixtures import WriterCase

class TaskDecisionLinkTests(WriterCase):
    def link(self, step='2b', decision='order', task='T1'):
        return self.call('task-decision-link',task,'--decision',decision,'--step',step,'--by','chief-of-staff')

    def test_step_link_change_repeat_and_query(self):
        self.assert_ok(self.link())
        self.assertEqual([('T1','decision','order','step:2b',1)],self.sql('SELECT task,system,external_id,relation,active FROM task_links'))
        self.assertEqual([('2b',)],self.sql("SELECT substr(relation,6) FROM task_links"))
        self.assert_ok(self.link('3'))
        self.assertEqual([('step:3',)],self.sql('SELECT relation FROM task_links'))
        self.assertEqual([(None,'step:2b'),('step:2b','step:3')],self.sql("SELECT old_value,new_value FROM activity WHERE field='link' ORDER BY id"))
        self.assertEqual(2,len(self.sql('SELECT * FROM comments')))
        before = self.db.read_bytes()
        self.assertIn('duplicate',self.link('3')[1])
        self.assertEqual(before,self.db.read_bytes())

    def test_unknown_ids_bad_steps_and_missing_actor_do_not_write(self):
        for step in ('0','-1','02','2B','2.5','two','2bb'):
            self.assert_refused_without_write('task-decision-link','T1','--decision','order','--step',step,'--by','sol')
        for task,decision in [('missing','order'),('T1','missing')]:
            self.assert_refused_without_write('task-decision-link',task,'--decision',decision,'--step','3','--by','sol')
        self.assert_refused_without_write('task-decision-link','T1','--decision','order','--step','3')

    def test_inactive_link_becomes_active_and_keeps_scope_and_path(self):
        self.sql("INSERT INTO task_links(task,system,external_id,relation,active,scope,path) VALUES ('T1','decision','order','step:2b',0,'work','docs/decision.md')")
        self.assert_ok(self.link())
        self.assertEqual([(1,'work','docs/decision.md')],self.sql('SELECT active,scope,path FROM task_links'))
        self.assertEqual([('active','0','1')],self.sql('SELECT field,old_value,new_value FROM activity'))
        self.assertEqual(1,len(self.sql('SELECT * FROM comments')))
