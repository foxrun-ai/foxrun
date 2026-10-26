#!/usr/bin/env python3
"""T661: a cross-area write reaches a lead and keeps its review trail."""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'work')]
from base.tests.support import setup
setup()
import work
from base import person, ownership
from memory import start_context, state
from events.log import show_events


class OwnershipAlarmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='T661-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.portfolio = self.root / 'portfolio'
        self.workspace = self.portfolio / 'sample'
        self.workspace.mkdir(parents=True)
        (self.portfolio / 'other').mkdir()
        (self.home / 'agents').mkdir(parents=True)
        (self.home / 'config').mkdir()
        (self.home / 'agents/toolsmith.md').write_text('---\nid: toolsmith\nowns: [tools]\n---\n')
        (self.home / 'agents/architect.md').write_text('---\nid: architect\nowns: [base]\n---\n')
        (self.home / 'config/person.json').write_text(json.dumps(dict(
            name='person', leads=['architect'], workspaces=['sample', 'other'], default_workspace='sample')))
        self.env = patch.dict(os.environ, dict(FOXRUN_HOME=str(self.home),
            FOXRUN_PORTFOLIO=str(self.portfolio), FOXRUN_PERSON='person',
            PYTHONDONTWRITEBYTECODE='1'), clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.database = self.home / 'data.db'
        with person.connect(self.database) as db:
            db.executescript((ROOT / 'work/blueprint.sql').read_text())
            for number in range(1, 10):
                db.execute('INSERT INTO tasks(id,title,status,tags) VALUES (?,?,?,?)',
                           ('T' + str(number), 'Existing task ' + str(number), 'todo', 'workspace:sample'))
        self.target = self.home / 'tools/requested.py'

    def rows(self, query, values=()):
        with sqlite3.connect(self.database) as db:
            return db.execute(query, values).fetchall()

    def call(self, *args):
        out, error = io.StringIO(), io.StringIO()
        code = work.run(['--workspace', 'sample', '--receipt-root', str(self.workspace), *args],
                        stdout=out, stderr=error)
        return code, out.getvalue(), error.getvalue()

    def check(self, *args, path=None, writer='builder'):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'base/ownership.py'),
                               '--home', str(self.home), 'write-check', str(path or self.target),
                               '--workspace', 'sample', '--by', writer, *args], capture_output=True, text=True)

    def alarm(self):
        result = self.check()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('ownership-alarm T10', result.stdout)
        return 'T10'

    def clear(self, alarm='T10', reason='Reviewed this exact write', actor='reviewer'):
        return self.call('ownership-clear', alarm, '--reason', reason, '--by', actor)

    def snapshot(self):
        return self.rows('SELECT * FROM tasks'), self.rows('SELECT * FROM activity')

    def test_alarm_is_a_tracker_task_for_the_area_owner(self):
        schema = self.rows('SELECT name,sql FROM sqlite_master ORDER BY name')
        alarm = self.alarm()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.rows('SELECT status,owner,created_by FROM tasks WHERE id=?', (alarm,)),
                         [('blocked', 'toolsmith', 'builder')])
        for field in ('problem', 'job_when', 'job_want', 'job_so', 'body', 'acceptance', 'context'):
            self.assertTrue(self.rows('SELECT ' + field + ' FROM tasks WHERE id=?', (alarm,))[0][0])
        self.assertEqual(self.rows('SELECT name,sql FROM sqlite_master ORDER BY name'), schema)
        detail = json.loads(self.rows("SELECT note FROM activity WHERE field='ownership_alarm'")[0][0])
        self.assertEqual((detail['target'], detail['owner'], detail['writer'], detail['reason']),
                         (str(self.target), 'toolsmith', 'builder', 'writer is not the owner'))

    def test_refusal_names_the_owner_route(self):
        result = self.check()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('ROUTE: hand this write to toolsmith: start a background worker as the toolsmith seat', result.stdout)

    def test_one_clear_command_records_the_reason_and_second_person(self):
        self.alarm()
        self.assertEqual(self.clear()[0], 0)
        self.assertEqual(self.rows("SELECT status FROM tasks WHERE id='T10'"), [('done',)])
        self.assertEqual(self.rows("SELECT old_value,new_value,actor,note,verb FROM activity WHERE subject_id='T10' ORDER BY id")[-1],
                         ('open', 'cleared', 'reviewer', 'Reviewed this exact write', 'accepted'))

    def test_clear_without_nonblank_reason_writes_nothing(self):
        self.alarm()
        for flags in ([], ['--reason', ''], ['--reason', '  '], ['--reason', '\n']):
            before = self.snapshot()
            code, _, error = self.call('ownership-clear', 'T10', '--by', 'reviewer', *flags)
            self.assertEqual(code, 2)
            self.assertIn('--reason', error)
            self.assertEqual(self.snapshot(), before)

    def test_writer_cannot_clear_its_own_alarm(self):
        self.alarm()
        before = self.snapshot()
        self.assertIn('second person', self.clear(actor='BUILDER')[2])
        self.assertEqual(self.snapshot(), before)

    def test_existing_event_reader_shows_block_and_clear_trail(self):
        self.alarm()
        self.assertEqual(self.clear(reason='Checked the requested repair')[0], 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            show_events(self.database, 'task', 'T10')
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(events), 2)
        self.assertEqual({event['event_table'] for event in events}, {'activity'})
        self.assertEqual({event['actor'] for event in events}, {'builder', 'reviewer'})
        self.assertIn('Checked the requested repair', out.getvalue())
        self.assertIn(str(self.target), out.getvalue())
        self.assertIn('writer is not the owner', out.getvalue())

    def test_cleared_alarm_allows_only_the_same_writer_path_and_owner(self):
        self.alarm()
        self.assertEqual(self.clear()[0], 0)
        before = self.snapshot()
        result = self.check('--alarm', 'T10')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ALLOW: cleared alarm T10', result.stdout)
        for path, writer in ((self.home / 'tools/different.py', 'builder'), (self.target, 'stranger')):
            result = self.check('--alarm', 'T10', path=path, writer=writer)
            self.assertEqual(result.returncode, 2)
            self.assertIn('does not match', result.stderr)
        self.assertEqual(self.snapshot(), before)
        (self.home / 'agents/toolsmith.md').write_text('---\nid: changed-owner\nowns: [tools]\n---\n')
        self.assertEqual(self.check('--alarm', 'T10').returncode, 2)

    def test_clearing_does_not_create_a_permanent_blanket_allow(self):
        self.alarm()
        self.assertEqual(self.clear()[0], 0)
        result = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertIn('ownership-alarm T11', result.stdout)
        self.assertEqual(self.clear()[0], 2)

    def test_repeated_requests_keep_one_open_task_and_each_attempt_event(self):
        self.alarm()
        self.alarm()
        self.assertEqual(self.rows("SELECT count(*) FROM tasks WHERE status='blocked'"), [(1,)])
        self.assertEqual(self.rows("SELECT old_value,new_value FROM activity WHERE subject_id='T10' ORDER BY id"),
                         [(None, 'open'), ('open', 'open')])

    def test_owner_and_configured_lead_see_alarm_in_existing_start_section(self):
        self.alarm()
        tasks = start_context.selected_tasks('sample')
        for seat in ('toolsmith', 'architect'):
            text, _ = start_context.function_part('sample', None, seat, state.now(), tasks, {})
            self.assertIn('Open tasks:\n  T10: Ownership alarm:', text)
            self.assertEqual(text.count('## '), 1)
        self.assertEqual(self.clear()[0], 0)
        text, _ = start_context.function_part('sample', None, 'architect', state.now(),
                                             start_context.selected_tasks('sample'), {})
        self.assertNotIn('T10:', text)

    def test_function_start_still_selects_the_alarm(self):
        with person.connect(self.database) as db:
            db.execute("INSERT INTO functions(id,name,organization) VALUES ('build','Build','sample')")
        self.alarm()
        tasks = start_context.selected_tasks('sample', 'build')
        self.assertEqual([row['id'] for row in tasks], ['T10'])
        text, _ = start_context.function_part('sample', 'build', 'architect', state.now(), tasks, {})
        self.assertIn('T10: Ownership alarm:', text)
        query = text.split('Command: ', 1)[1].split('"', 1)[1].rsplit('"', 1)[0]
        self.assertEqual([row[0] for row in self.rows(query)], ['T10'])

    def test_workspace_tracker_takes_precedence_over_system_tracker(self):
        local = self.workspace / 'data.db'
        with person.connect(local) as db:
            db.executescript((ROOT / 'work/blueprint.sql').read_text())
        before = self.snapshot()
        result = self.check()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('ownership-alarm T1', result.stdout)
        self.assertEqual(self.snapshot(), before)
        with sqlite3.connect(local) as db:
            self.assertEqual(db.execute('SELECT id,status,owner FROM tasks').fetchall(),
                             [('T1', 'blocked', 'toolsmith')])
        self.assertEqual(self.clear(alarm='T1')[0], 0)

    def test_custom_home_supplies_default_workspace_and_tracker(self):
        # The CLI must honor --home even if the calling process has another home.
        with patch.dict(os.environ, FOXRUN_HOME=str(ROOT)):
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'base/ownership.py'),
                '--home', str(self.home), 'write-check', str(self.target), '--by', 'builder'],
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('ownership-alarm T10', result.stdout)

    def test_unknown_owner_escalates_to_configured_lead(self):
        result = self.check(path=self.home / 'unowned/new.py')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.rows("SELECT owner FROM tasks WHERE id='T10'"), [('architect',)])
        self.assertIn('no owner for unowned/new.py', self.rows("SELECT note FROM tasks WHERE id='T10'")[0][0])

    def test_generic_task_commands_cannot_hide_or_clear_an_alarm(self):
        self.alarm()
        before = self.snapshot()
        for args in (('cancel', 'T10', '--reason', 'skip'), ('todo', 'T10'),
                     ('task-update', 'T10', '--owner', 'builder')):
            code, _, error = self.call(*args, '--by', 'reviewer')
            self.assertEqual(code, 2)
            self.assertIn('ownership-clear', error)
            self.assertEqual(self.snapshot(), before)

    def test_event_failure_rolls_back_new_alarm_and_clearing(self):
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TRIGGER refuse_alarm BEFORE INSERT ON activity WHEN NEW.field='ownership_alarm' "
                       "BEGIN SELECT RAISE(ABORT,'event refused'); END")
        before = self.snapshot()
        self.assertEqual(self.check().returncode, 2)
        self.assertEqual(self.snapshot(), before)
        with sqlite3.connect(self.database) as db:
            db.execute('DROP TRIGGER refuse_alarm')
        self.alarm()
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TRIGGER refuse_clear BEFORE INSERT ON activity WHEN NEW.new_value='cleared' "
                       "BEGIN SELECT RAISE(ABORT,'event refused'); END")
        before = self.snapshot()
        self.assertEqual(self.clear()[0], 2)
        self.assertEqual(self.snapshot(), before)

    def test_missing_database_keeps_write_blocked_without_creating_it(self):
        missing = self.root / 'missing.db'
        result = self.check('--db', str(missing))
        self.assertEqual(result.returncode, 2)
        self.assertIn('tracker check failed', result.stderr)
        self.assertFalse(missing.exists())

    def test_owner_write_needs_no_tracker_or_alarm(self):
        before = self.snapshot()
        self.assertEqual(self.check(writer='toolsmith').returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_worker_write_inside_its_run_folder_files_no_alarm(self):
        # B-20261024-run-folder-writes-raise-ownership-alarms
        (self.home / 'agents/chief.md').write_text('---\nid: chief-of-staff\nowns: [runs, skillwright]\n---\n')
        before = self.snapshot()
        run = self.home / 'runs/2026-10-24/T859-architect-writing-suite-research'
        for path in (run / 'result.md', run / 'heavy/every-writing.md'):
            result = self.check(path=path, writer='worker')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('ALLOW: worker -> runs/2026-10-24/T859-architect-writing-suite-research/', result.stdout)
            self.assertIn('inside a run folder', result.stdout)
        self.assertEqual(self.snapshot(), before)
        for path in (self.home / 'runs/README.md', self.home / 'runs/2026-10-24/sessions.jsonl',
                     self.home / 'runs/2026-10-24/legacy/old/note.md',
                     self.home / 'skillwright/skill-releases/20261023T082744337965Z-19a21023a925/copywriting'):
            result = self.check(path=path, writer='worker')
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('ALARM: worker -> ', result.stdout)
            self.assertIn('ownership-alarm T', result.stdout)

    def test_pending_alarm_and_other_workspace_cannot_authorize_write(self):
        self.alarm()
        self.assertEqual(self.check('--alarm', 'T10').returncode, 2)
        self.assertEqual(self.clear()[0], 0)
        result = self.call('ownership-check', 'T10', '--write-path', str(self.target), '--by', 'builder',
                           '--workspace', 'other')
        self.assertEqual(result[0], 2)
        self.assertIn('another workspace', result[2])


if __name__ == '__main__':
    unittest.main()
