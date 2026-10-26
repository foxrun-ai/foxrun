#!/usr/bin/env python3
"""Tests for memory/state.py. Each test makes a small home with only the files it needs.

Run from the system home: python3 -m unittest memory.tests.test_state
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else 'python3'
NEEDED = ('memory/state.py', 'memory/runs.py', 'base/paths.py', 'base/person.py', 'base/tracker.py', 'base/agent_catalog.py', 'base/simple_yaml.py')
TABLES = '''
CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, project TEXT, tags TEXT, owner TEXT,
  parent TEXT, check_by TEXT, created_on TEXT);
CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT);
CREATE TABLE activity (id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT, field TEXT, new_value TEXT, at TEXT);
CREATE TABLE bugs (id TEXT PRIMARY KEY, title TEXT, status TEXT);
CREATE TABLE decisions (id TEXT PRIMARY KEY, name TEXT, status TEXT, decided_on TEXT);
CREATE TABLE runs (id TEXT PRIMARY KEY, "by" TEXT, started_at TEXT, ended_at TEXT, subject_type TEXT, subject_id TEXT);
CREATE TABLE programs (id TEXT PRIMARY KEY, name TEXT, status TEXT);
CREATE TABLE functions (id TEXT PRIMARY KEY, name TEXT);
CREATE VIEW open_tasks AS SELECT id,title,status,project FROM tasks
  WHERE status NOT IN ('done','canceled','superseded') AND parent IS NULL;
CREATE VIEW needs_me AS SELECT id,title FROM tasks
  WHERE status NOT IN ('done','canceled','superseded') AND lower(coalesce(owner,''))='avery';
CREATE VIEW close_now AS SELECT id,title FROM tasks WHERE status='in-review';
CREATE VIEW open_decisions AS SELECT id,name FROM decisions WHERE status IN ('open','soft');
'''
def steady(text):
    """A page without the two lines that change at every build."""
    return '\n'.join(line for line in text.splitlines() if not line.startswith(('timestamp: ', 'MADE ')))


FORBIDDEN = ('No work has started yet.', 'No records yet.', 'Install complete.', 'TODO', 'TBD')


def day(offset):
    return (datetime.now().astimezone() - timedelta(days=offset)).strftime('%Y-%m-%dT%H:%M:%S-04:00')


class StateTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('FOXRUN_TEST_ROOT') or None
        self.temp = tempfile.TemporaryDirectory(prefix='state-home-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.home, self.portfolio = root / 'system', root / 'portfolio'
        for name in NEEDED:
            (self.home / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, self.home / name)
        for folder in ('config', 'runs', 'agents'):
            (self.home / folder).mkdir()
        (self.home / 'config/person.json').write_text(json.dumps(
            {'name': 'avery', 'default_workspace': 'cedar-shop', 'workspaces': ['cedar-shop', 'oak-studio']}))
        (self.home / 'config/gates.md').write_text('# Gates\n')
        (self.home / 'config/models.yaml').write_text((ROOT / 'config/models.yaml').read_text())
        for name in ('AGENTS.md', 'RESOLVER.md'):
            (self.home / name).write_text('# ' + name + '\n')
        (self.home / 'agents/chief-of-staff.md').write_text('# Chief of Staff\n')
        (self.home / 'profile').mkdir()
        (self.home / 'profile/AGENTS.md').write_text('# Global Contract\n')
        for name in ('cedar-shop', 'oak-studio', 'atlas'):
            (self.portfolio / name / 'team').mkdir(parents=True)
            for page in ('AGENTS.md', 'RESOLVER.md'):
                (self.portfolio / name / page).write_text('# ' + page + '\n')
        (self.portfolio / 'cedar-shop/team/lead-cedar-shop.md').write_text('# Lead\n')
        self.system_db = self.home / 'data.db'
        self.make(self.system_db)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('FOXRUN_')}
        self.env.update(FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio), PYTHONDONTWRITEBYTECODE='1')

    def make(self, database, rows=True):
        with sqlite3.connect(str(database)) as db:
            db.executescript(TABLES)
            if not rows:
                return
            db.executemany('INSERT INTO projects VALUES (?,?)', [('WS01', 'Creators'), ('WS02', 'Stock')])
            db.executemany('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)', [
                ('T1', 'Check stock', 'in-progress', 'WS02', None, 'avery', None, None, day(1)),
                ('T2', 'Write the brief', 'in-review', 'WS01', None, None, None, None, day(2)),
                ('T3', 'Call the creator', 'todo', 'WS01', None, None, None, None, day(30)),
                ('T4', 'Old plan', 'backlog', 'WS01', None, None, None, None, day(40)),
                ('T5', 'Wait for the label', 'blocked', 'WS02', None, None, None, None, day(3)),
                ('T6', 'Closed thing', 'done', 'WS01', None, None, None, None, day(3)),
                ('T7', 'A child task', 'todo', 'WS01', None, None, 'T3', None, day(1)),
                ('T8', 'Oak task', 'todo', None, 'workspace:oak-studio', None, None, None, day(1)),
            ])
            db.executemany('INSERT INTO activity (subject_type,subject_id,field,new_value,at) VALUES (?,?,?,?,?)', [
                ('task', 'T2', 'status', 'in-review', day(1)), ('task', 'T6', 'status', 'done', day(20))])
            db.executemany('INSERT INTO bugs VALUES (?,?,?)', [('B1', 'Broken link', 'open'), ('B2', 'Fixed', 'fixed')])
            db.executemany('INSERT INTO decisions VALUES (?,?,?,?)', [
                ('g-new', 'Ship on Friday', 'ruled', day(2)[:10]), ('g-old', 'Old rule', 'ruled', day(60)[:10])])
            db.executemany('INSERT INTO runs VALUES (?,?,?,?,?,?)', [('R1', 'worker', day(1), day(1), 'task', 'T1'), ('R2', 'worker', day(50), day(50), 'task', 'T1')])
            db.execute("INSERT INTO programs VALUES ('PG1','Cedar Shop','todo')")
            db.executemany('INSERT INTO functions VALUES (?,?)', [('amazon', 'Amazon'), ('ugc', 'UGC')])

    def state(self, *args, expected=0):
        result = subprocess.run([PYTHON, '-B', str(self.home / 'memory/state.py')] + list(args), cwd=str(self.home),
                                env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, expected, result.stdout)
        return result.stdout

    def files(self):
        root = Path(self.temp.name)
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def count(self, page, label):
        return re.search(r'^' + re.escape(label) + r'\s+(\S.*)$', page, re.M).group(1)

    def check_frame(self, page, scope):
        lines = page.splitlines()
        self.assertEqual(lines[0:3], ['---', 'type: state', 'workspace: ' + scope])
        self.assertRegex(lines[3], r'^timestamp: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        self.assertEqual(lines[4:6], ['---', '# State: ' + scope])
        self.assertTrue(lines[7].startswith('An agent reads this page at the start. A script makes it from the rows in [`data.db`]('))
        headings = [line for line in lines if line.startswith('## ')]
        self.assertEqual([re.sub(r'\d{4}-\d\d-\d\d', '<date>', h) for h in headings],
                         ['## Always', '## Open', '## New since <date>', '## Ask the rows'])
        for label in ('OPEN TASKS', 'BLOCKED', 'WAITING FOR AVERY', 'OPEN BUGS', 'NEWEST CHANGE', 'MADE',
                      'NEW TASKS', 'MOVED TO IN REVIEW', 'DECISIONS', 'RUNS'):
            self.count(page, label)
        self.assertLessEqual(len(lines), 90)
        for text in FORBIDDEN:
            self.assertNotIn(text, page)
        for line in lines:
            if line.startswith('|'):
                self.assertLessEqual(line.count('|') - 1, 4, line)
        # every relative link opens a thing that exists
        folder = self.home if scope == 'system' else self.portfolio / scope
        for target in re.findall(r'\]\(([^)#]+)\)', page):
            self.assertTrue((folder / target).exists(), target)

    def test_build_writes_the_workspace_page_from_rows(self):
        self.assertIn('built ', self.state('build', '--workspace', 'cedar-shop'))
        page = (self.portfolio / 'cedar-shop/STATE.md').read_text()
        self.check_frame(page, 'cedar-shop')
        self.assertIn('The global contract [`AGENTS.md`](../../system/profile/AGENTS.md)', page)
        self.assertNotIn('](../../system/AGENTS.md)', page)
        self.assertEqual(self.count(page, 'OPEN TASKS'), '5')
        self.assertEqual(self.count(page, 'BLOCKED'), '1')
        self.assertEqual(self.count(page, 'WAITING FOR AVERY'), '1')
        self.assertEqual(self.count(page, 'OPEN BUGS'), '1')
        self.assertEqual(self.count(page, 'NEW TASKS'), '4')  # T1 T2 T5 T6; T7 has a parent
        self.assertEqual(self.count(page, 'MOVED TO IN REVIEW'), '1')
        self.assertEqual(self.count(page, 'DECISIONS'), '1')
        self.assertEqual(self.count(page, 'RUNS'), '1')
        self.assertIn('| WS01 Creators | — | 1 | 2 |', page)
        self.assertIn('| WS02 Stock | 1 | — | — |', page)
        self.assertIn('| T2 | Write the brief | WS01 |', page)
        self.assertIn('| Ship on Friday | ', page)
        self.assertNotIn('Old rule', page)
        self.assertNotIn('Oak task', page)
        self.assertIn('[`lead-cedar-shop`](team/lead-cedar-shop.md)', page)
        self.assertIn('| Program | PG1 Cedar Shop |', page)
        self.assertIn('| Functions | amazon · ugc |', page)
        self.assertIn('| What is in review? | `close_now` |', page)
        self.assertNotIn('v_low_stock', page)
        self.assertIn('--workspace cedar-shop \\', page)
        # the sum of the three columns plus BLOCKED equals OPEN TASKS
        cells = [row.strip('|').split('|')[1:] for row in page.splitlines() if row.startswith('| WS0')]
        total = sum(int(c) for row in cells for c in (x.strip() for x in row) if c.isdigit())
        self.assertEqual(total + 1, 5)

    def test_workspace_notes_gates_take_priority_over_legacy_paths(self):
        folder = self.portfolio / 'cedar-shop'
        for name in ('notes', 'docs'):
            (folder / name).mkdir()
            (folder / name / 'gates.md').write_text('# Gates\n')
        page = self.state('show', '--workspace', 'cedar-shop')
        self.assertIn('See [`notes/gates.md`](notes/gates.md).', page)
        workspace_page = page.split('# State: cedar-shop', 1)[1]
        self.assertNotIn('The gates page is not on disk.', workspace_page)

    def test_workspace_gates_keep_legacy_fallbacks(self):
        folder = self.portfolio / 'cedar-shop'
        (folder / 'docs').mkdir()
        (folder / 'docs/gates.md').write_text('# Gates\n')
        page = self.state('show', '--workspace', 'cedar-shop')
        self.assertIn('See [`docs/gates.md`](docs/gates.md).', page)
        (folder / 'docs/gates.md').unlink()
        page = self.state('show', '--workspace', 'cedar-shop')
        self.assertIn('See [`../../system/config/gates.md`](../../system/config/gates.md).', page)

    def test_system_gates_find_installed_workspace_notes_when_no_system_page_exists(self):
        (self.home / 'config/gates.md').unlink()
        folder = self.portfolio / 'cedar-shop/notes'
        folder.mkdir()
        (folder / 'gates.md').write_text('# Gates\n')
        page = self.state('show', '--workspace', 'cedar-shop')
        self.assertIn('See [`../portfolio/cedar-shop/notes/gates.md`](../portfolio/cedar-shop/notes/gates.md).', page)
        self.assertNotIn('The gates page is not on disk.', page)

    def test_approval_label_uses_the_configured_person(self):
        page = self.state('show', '--workspace', 'cedar-shop')
        self.assertIn("| Avery's yes first |", page)
        config = self.home / 'config/person.json'
        values = json.loads(config.read_text())
        values['name'] = 'robin'
        config.write_text(json.dumps(values))
        self.assertIn("| Robin's yes first |", self.state('show', '--workspace', 'cedar-shop'))

    def test_approval_label_is_neutral_without_a_person_name(self):
        config = self.home / 'config/person.json'
        values = json.loads(config.read_text())
        for name in (None, 'person'):
            with self.subTest(name=name):
                values['name'] = name
                config.write_text(json.dumps(values))
                page = self.state('show', '--workspace', 'cedar-shop')
                self.assertIn('| Your yes first |', page)
                self.assertNotIn('His yes first', page)

    def test_a_workspace_with_its_own_database_reads_that_database(self):
        own = self.portfolio / 'oak-studio/data.db'
        self.make(own, rows=False)
        with sqlite3.connect(str(own)) as db:
            db.execute("INSERT INTO tasks VALUES ('T1','Sand the table','in-progress',NULL,NULL,NULL,NULL,NULL,?)", (day(1),))
        self.state('build', '--workspace', 'oak-studio')
        page = (self.portfolio / 'oak-studio/STATE.md').read_text()
        self.check_frame(page, 'oak-studio')
        self.assertEqual(self.count(page, 'OPEN TASKS'), '1')
        self.assertIn('[`data.db`](data.db)', page)
        self.assertIn('| No stream | 1 | — | — |', page)
        self.assertIn('`lead-oak-studio` (not on disk)', page)

    def test_a_workspace_with_no_lead_seat_names_who_works_there(self):
        (self.home / 'agents/keeper.md').write_text('# Keeper\n')
        (self.portfolio / 'oak-studio/team/oak-helper.md').write_text('# Helper\n')
        (self.portfolio / 'oak-studio/config').mkdir()
        (self.portfolio / 'oak-studio/config/team.yaml').write_text(
            '# who works here\nworks_here: [keeper, oak-helper, hermes:oak, ghost]  # T711\n')
        self.state('build', '--workspace', 'oak-studio')
        page = (self.portfolio / 'oak-studio/STATE.md').read_text()
        self.check_frame(page, 'oak-studio')
        self.assertIn('| Works here | [`keeper`](../../system/agents/keeper.md) · [`oak-helper`](team/oak-helper.md)'
                      ' · `oak` (Hermes profile) · `ghost` (not on disk) |', page)
        self.assertNotIn('lead-oak-studio', page)
        # A lead seat wins over the list.
        (self.portfolio / 'oak-studio/team/lead-oak-studio.md').write_text('# Lead\n')
        self.state('build', '--workspace', 'oak-studio')
        page = (self.portfolio / 'oak-studio/STATE.md').read_text()
        self.assertIn('| Lead | [`lead-oak-studio`](team/lead-oak-studio.md) |', page)
        self.assertNotIn('Works here', page)

    def test_a_shared_database_gives_a_tagged_task_to_its_workspace(self):
        self.state('build', '--workspace', 'oak-studio')
        page = (self.portfolio / 'oak-studio/STATE.md').read_text()
        self.assertEqual(self.count(page, 'OPEN TASKS'), '1')
        self.assertEqual(self.count(page, 'OPEN BUGS'), '0')

    def test_no_task_is_a_real_page(self):
        own = self.portfolio / 'oak-studio/data.db'
        self.make(own, rows=False)
        self.state('build', '--workspace', 'oak-studio')
        page = (self.portfolio / 'oak-studio/STATE.md').read_text()
        self.check_frame(page, 'oak-studio')
        self.assertEqual(self.count(page, 'OPEN TASKS'), '0')
        self.assertIn('No task is open.', page)

    def test_build_all_writes_the_system_page_by_workspace(self):
        output = self.state('build', '--all')
        # The system page, Atlas, and the two workspaces (g-atlas-is-a-standard-workspace-with-its-wiki-at-the-top).
        self.assertEqual(output.count('built '), 4)
        self.assertTrue((self.portfolio / 'atlas/STATE.md').is_file())
        self.check_frame((self.portfolio / 'atlas/STATE.md').read_text(), 'atlas')
        page = (self.home / 'STATE.md').read_text()
        self.check_frame(page, 'system')
        self.assertIn('The global contract [`AGENTS.md`](profile/AGENTS.md)', page)
        self.assertEqual(self.count(page, 'OPEN TASKS'), '6')
        self.assertIn('| Workspace | In progress | In review | Not started |', page)
        self.assertIn('| cedar-shop | 1 | 1 | 2 |', page)
        self.assertIn('| oak-studio | — | — | 1 |', page)
        self.assertIn('[`chief-of-staff`](agents/chief-of-staff.md)', page)
        # Atlas has no open task here, so the table Open has no row for it.
        self.assertNotIn('| atlas |', page)
        self.assertEqual([p.name for p in self.home.iterdir() if p.name.startswith('.STATE')], [])

    def test_check_passes_after_a_build_and_fails_after_a_row_changes(self):
        self.state('build', '--all')
        before = self.files()
        self.assertEqual(self.state('build', '--all', '--check').count('PASS '), 4)
        self.assertEqual(before, self.files())
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute("UPDATE tasks SET status='done' WHERE id='T1'")
        output = self.state('build', '--all', '--check', expected=1)
        self.assertIn('the page does not match its rows', output)
        (self.portfolio / 'oak-studio/STATE.md').unlink()
        self.assertIn('the page is missing', self.state('build', '--workspace', 'oak-studio', '--check', expected=1))

    # T801: one line with the last nightly result and the last state push to GitHub.
    def receipt(self, stamp, exit_code, dry_run=False, place='nightly'):
        # T755: receipts live in runs/nightly/; place='' writes one at the top of runs/, as before the move.
        folder = self.home / 'runs' / place / (stamp + '-nightly')
        folder.mkdir(parents=True)
        (folder / 'receipt.json').write_text(json.dumps({'owner': 'keeper', 'at': stamp, 'exit': exit_code,
                                                         'dry_run': dry_run, 'steps': {}}))

    def nightly_lines(self, page):
        fence = page.split('```')[1]
        return [line for line in fence.splitlines() if line.startswith('NIGHTLY ')]

    def test_nightly_line_without_a_run_or_a_state_repo(self):
        self.state('build', '--workspace', 'cedar-shop')
        page = (self.portfolio / 'cedar-shop/STATE.md').read_text()
        self.assertEqual(len(self.nightly_lines(page)), 1)
        self.assertEqual(self.count(page, 'NIGHTLY'), 'no run yet · GitHub backup none')

    def test_nightly_line_reads_the_newest_real_receipt_and_the_last_push(self):
        self.receipt('20261020T070000000000Z', 0, place='')
        self.receipt('20261021T070000000000Z', 1)
        self.receipt('20261022T070000000000Z', 0, dry_run=True)
        remote, state = Path(self.temp.name) / 'remote.git', self.home / 'state'
        git = ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false']
        subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(state)], check=True)
        (state / 'tasks.jsonl').write_text('{}\n')
        for step in (['add', '-A'], ['commit', '-q', '-m', 'export'], ['remote', 'add', 'origin', str(remote)]):
            subprocess.run(git + ['-C', str(state)] + step, check=True)
        before = datetime.now().astimezone()
        subprocess.run(git + ['-C', str(state), 'push', '-q', '-u', 'origin', 'main'], check=True,
                       capture_output=True)
        after = datetime.now().astimezone()
        self.state('build', '--system')
        page = (self.home / 'STATE.md').read_text()
        self.assertEqual(len(self.nightly_lines(page)), 1)
        ran = datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')
        pushed = {moment.strftime('%Y-%m-%d %H:%M') for moment in (before, after)}
        value = self.count(page, 'NIGHTLY').split(' · OLDER THAN 36 HOURS')[0]
        self.assertTrue(value.startswith('failed ' + ran + ' · GitHub backup '), value)
        self.assertIn(value.rsplit(' ', 2)[-2] + ' ' + value.rsplit(' ', 1)[-1], pushed)

    def test_a_nightly_older_than_36_hours_is_flagged_with_tidy(self):
        # T755: the start page flags a nightly older than 36 hours and names /tidy.
        old = datetime.now(timezone.utc) - timedelta(hours=40)
        self.receipt(old.strftime('%Y%m%dT%H%M%S%fZ'), 0)
        self.state('build', '--system')
        flagged = self.count((self.home / 'STATE.md').read_text(), 'NIGHTLY')
        self.assertTrue(flagged.endswith(' · OLDER THAN 36 HOURS: run /tidy'), flagged)
        fresh = datetime.now(timezone.utc) - timedelta(hours=2)
        self.receipt(fresh.strftime('%Y%m%dT%H%M%S%fZ'), 0)
        self.state('build', '--system')
        self.assertNotIn('OLDER THAN', self.count((self.home / 'STATE.md').read_text(), 'NIGHTLY'))

    def test_a_new_nightly_receipt_does_not_fail_the_page_check(self):
        self.state('build', '--workspace', 'cedar-shop')
        self.receipt('20261021T070000000000Z', 0)
        self.assertIn('PASS', self.state('build', '--workspace', 'cedar-shop', '--check'))

    def test_build_all_makes_no_page_for_a_folder_with_no_contract(self):
        # T693: ~/foxrun/apps and a preview folder have no AGENTS.md; build --all made STATE.md for them.
        (self.portfolio / 'apps/tool').mkdir(parents=True)
        output = self.state('build', '--all')
        self.assertEqual(output.count('built '), 4)
        self.assertFalse((self.portfolio / 'apps/STATE.md').exists())
        self.assertEqual(self.state('build', '--all', '--check').count('PASS '), 4)

    def test_a_default_workspace_renamed_behind_a_link_keeps_the_untagged_tasks(self):
        # T693: person.json says foxrun-dev; foxrun-dev is a link to foxrun-hq since T634. Untagged tasks were nobody's.
        self.state('build', '--workspace', 'cedar-shop')
        before = self.count((self.portfolio / 'cedar-shop/STATE.md').read_text(), 'OPEN TASKS')
        self.assertNotEqual(before, '0')
        (self.portfolio / 'cedar-shop').rename(self.portfolio / 'cedar-hq')
        (self.portfolio / 'cedar-shop').symlink_to('cedar-hq', target_is_directory=True)
        self.state('build', '--all')
        page = (self.portfolio / 'cedar-hq/STATE.md').read_text()
        self.assertEqual(self.count(page, 'OPEN TASKS'), before)
        self.assertEqual(self.count((self.home / 'STATE.md').read_text(), 'OPEN TASKS'), '6')
        self.assertIn('| cedar-hq | 1 | 1 | 2 |', (self.home / 'STATE.md').read_text())

    def test_build_refuses_a_symbolic_link_and_an_unknown_workspace(self):
        (self.home / 'STATE.md').symlink_to(self.home / 'AGENTS.md')
        self.assertIn('must not be a symbolic link', self.state('build', expected=1))
        self.assertEqual((self.home / 'AGENTS.md').read_text(), '# AGENTS.md\n')
        self.assertIn('unknown workspace: nowhere', self.state('build', '--workspace', 'nowhere', expected=1))

    def test_ask_the_rows_names_the_rulings_command_when_decisions_exist(self):
        page = self.state('show', '--workspace', 'cedar-shop')
        self.assertEqual(page.count('| What did avery rule about X? | `python3 ' + str(self.home / 'foxrun.py') +
                                    ' rulings <words>` |'), 2)
        self.make(self.portfolio / 'oak-studio/data.db')
        oak = self.state('show', '--workspace', 'oak-studio').split('# State: oak-studio', 1)[1]
        self.assertIn(' rulings <words> --workspace oak-studio` |', oak)
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute('DROP TABLE decisions')
        self.assertNotIn('rulings <words>', self.state('show', '--workspace', 'cedar-shop').split('# State: cedar-shop', 1)[0])

    def seat_part(self, seat, workspace='cedar-shop'):
        for name in ('memory/start_context.py', 'base/simple_yaml.py'):
            shutil.copyfile(ROOT / name, self.home / name)
        code = ('import sys; sys.path.insert(0, sys.argv[1]); from memory.start_context import seat_part; '
                'print(seat_part(sys.argv[2], sys.argv[3]))')
        result = subprocess.run([PYTHON, '-B', '-c', code, str(self.home), workspace, seat], env=self.env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def test_seat_part_holds_the_summary_and_judgment_and_stays_short(self):
        front = '---\n{"id": "architect", "display_name": "Architect", "summary": "Keeps the model."}\n---\n'
        body = ('# Architect\n\n## Identity\n\nNot in the part.\n\n## Judgment\n\n- Answer only from the sources.\n'
                + ''.join('- Rule ' + str(n) + '.\n' for n in range(60)) + '\n### How you write state\n\nNot in the part.\n'
                '\n### Boot reads\n\n1. Read the decisions.\n')
        (self.home / 'agents/architect.md').write_text(front + body)
        part = self.seat_part('architect')
        lines = part.rstrip('\n').splitlines()
        self.assertEqual(lines[:4], ['## Seat: Architect (architect)', 'File: ' + str(self.home / 'agents/architect.md'),
                                     'Summary: Keeps the model.', 'Judgment:'])
        self.assertEqual(lines[4], '- Answer only from the sources.')
        self.assertLessEqual(len(lines), 40)
        self.assertIn('more lines under Judgment in the file above.)', part)
        self.assertEqual(lines[-1], 'Boot reads: under Boot reads in the file above. Run them before work.')
        self.assertNotIn('Not in the part.', part)

    def test_long_state_section_is_cut_with_a_pointer_instead_of_raising(self):
        for name in ('memory/start_context.py', 'base/simple_yaml.py'):
            shutil.copyfile(ROOT / name, self.home / name)
        text = '# State\n\n## Always\n\n' + ''.join('- Rule ' + str(n) + '.\n' for n in range(40)) + \
               '\n## Ask the rows\n\n| Question | Command |\n|---|---|\n| What? | `x` |\n'
        code = ('import sys; sys.path.insert(0, sys.argv[1]); from memory.start_context import compact_state; '
                'text = open(sys.argv[2]).read()\n'
                'try:\n    compact_state(text, 10)\nexcept ValueError:\n    print("RAISED")\n'
                'print(compact_state(text, 10, "/home/STATE.md"))')
        source = self.home / 'long-state.md'
        source.write_text(text)
        result = subprocess.run([PYTHON, '-B', '-c', code, str(self.home), str(source)], env=self.env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        lines = result.stdout.rstrip('\n').splitlines()
        self.assertEqual(lines[0], 'RAISED')
        part = lines[1:]
        self.assertLessEqual(len(part), 10)
        self.assertEqual(part[0], '# State')
        self.assertEqual(part[-1], 'Cut to fit the start budget. Read the full file: /home/STATE.md')

    def test_seat_part_prefers_the_workspace_team_file_and_says_when_none(self):
        (self.home / 'agents/lead-cedar-shop.md').write_text('# System copy\n\n## Judgment\n\n- System rule.\n')
        (self.portfolio / 'cedar-shop/team/lead-cedar-shop.md').write_text('# Lead\n\n## Judgment\n\n- Team rule.\n')
        part = self.seat_part('lead-cedar-shop')
        self.assertIn('- Team rule.', part)
        self.assertNotIn('System rule', part)
        self.assertEqual(self.seat_part('worker').strip(),
                         'Seat worker: no seat file (agents/worker.md, cedar-shop/team/worker.md).')
        self.assertIn('Judgment: the file has no Judgment section.', self.seat_part('chief-of-staff'))
        self.assertEqual(self.seat_part('').strip(), 'No seat named.')

    def test_show_prints_both_pages_and_writes_nothing(self):
        before = self.files()
        output = self.state('show', '--workspace', 'cedar-shop')
        self.assertIn('# State: system', output)
        self.assertIn('# State: cedar-shop', output)
        self.assertEqual(before, self.files())

    def test_show_for_a_seat_marks_the_session_and_keeps_a_copy_in_the_run(self):
        run = self.home / 'runs/2026-10-13-start'
        output = self.state('show', '--workspace', 'cedar-shop', '--seat', 'lead-cedar-shop', '--mark', '--run-dir', str(run))
        self.assertIn('## For lead-cedar-shop in cedar-shop', output)
        self.assertIn('The rows hold no session of this seat here.', output)
        self.assertEqual((run / 'start-page.md').read_text(), output)
        markers = json.loads((self.home / 'runs/state-markers.json').read_text())
        self.assertEqual(list(markers), ['lead-cedar-shop|cedar-shop'])
        output = self.state('show', '--workspace', 'cedar-shop', '--seat', 'lead-cedar-shop')
        self.assertIn('This part shows the time since your last session here:', output)
        self.assertRegex(output.split('## For lead-cedar-shop')[1], r'NEW TASKS\s+0\n')
        self.assertRegex(output.split('## For lead-cedar-shop')[1], r'RUNS\s+0\n')

    def stamp(self, minutes):
        return (datetime.now().astimezone() + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()

    def seat_counts(self, *extra):
        part = self.state('show', '--workspace', 'cedar-shop', '--seat', 'chief-of-staff', *extra).split('## For chief-of-staff')[1]
        return part, {label: int(self.count(part, label)) for label in ('NEW TASKS', 'MOVED TO IN REVIEW', 'DECISIONS', 'RUNS')}

    def test_seat_part_does_not_count_same_day_rows_from_before_the_session(self):
        # The reader's probe: a run 10 minutes before the mark was counted as new after the mark.
        with sqlite3.connect(str(self.system_db)) as db:
            for table in ('activity', 'runs', 'decisions', 'tasks'):
                db.execute('DELETE FROM ' + table)
            db.execute("INSERT INTO runs VALUES ('old-today','worker',?,?,'task','T1')", (self.stamp(-10), self.stamp(-9)))
            db.execute("INSERT INTO activity (subject_type,subject_id,field,new_value,at) VALUES ('task','T1','status','in-review',?)", (self.stamp(-8),))
            db.execute("INSERT INTO tasks VALUES ('T1','Before','in-review',NULL,NULL,NULL,NULL,NULL,?)", (self.stamp(-8),))
        self.seat_counts('--mark')
        part, counts = self.seat_counts()
        self.assertEqual(counts, {'NEW TASKS': 0, 'MOVED TO IN REVIEW': 0, 'DECISIONS': 0, 'RUNS': 0})
        self.assertIn('(the marked session)', part)
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute("INSERT INTO runs VALUES ('new-today','worker',?,NULL,'task','T2')", (self.stamp(5),))
            db.execute("INSERT INTO activity (subject_type,subject_id,field,new_value,at) VALUES ('task','T2','status','in-review',?)", (self.stamp(5),))
            db.execute("INSERT INTO tasks VALUES ('T2','After','in-review',NULL,NULL,NULL,NULL,NULL,?)", (self.stamp(5),))
        part, counts = self.seat_counts()
        self.assertEqual(counts, {'NEW TASKS': 1, 'MOVED TO IN REVIEW': 1, 'DECISIONS': 0, 'RUNS': 1})

    def test_seat_part_reads_the_session_end_from_the_run_rows(self):
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute('DELETE FROM runs')
            db.execute("INSERT INTO runs VALUES ('R8','worker',?,?,'task','T1')", (self.stamp(-50), self.stamp(-40)))
            db.execute("INSERT INTO runs VALUES ('R9','chief-of-staff',?,?,'task','T1')", (self.stamp(-30), self.stamp(-20)))
            db.execute("INSERT INTO runs VALUES ('R10','worker',?,?,'task','T1')", (self.stamp(-10), self.stamp(-5)))
        part, counts = self.seat_counts()
        self.assertIn('(the run row R9)', part)
        self.assertEqual(counts['RUNS'], 1)
        self.assertNotIn('system/runs/state-markers.json', self.files())

    def test_seat_part_says_when_a_row_has_a_date_and_no_time(self):
        ended = self.stamp(-20)
        today = ended[:10]
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute('DELETE FROM runs')
            db.execute("INSERT INTO runs VALUES ('R9','chief-of-staff',?,?,'task','T1')", (self.stamp(-30), ended))
            db.execute("INSERT INTO decisions VALUES ('g-today','Ruled today','ruled',?)", (today,))
        part, counts = self.seat_counts()
        self.assertEqual(counts['DECISIONS'], 0)
        self.assertIn('1 row has the date ' + today + ' and no time. It is not counted', part)

    def test_a_workspace_with_no_agents_page_gets_no_broken_link(self):
        # The reader's finding: sample-project has no AGENTS.md and no RESOLVER.md today.
        for name in ('AGENTS.md', 'RESOLVER.md'):
            (self.portfolio / 'oak-studio' / name).unlink()
        self.state('build', '--workspace', 'oak-studio')
        page = (self.portfolio / 'oak-studio/STATE.md').read_text()
        self.check_frame(page, 'oak-studio')
        self.assertIn('then `AGENTS.md` (not on disk), then `RESOLVER.md` (not on disk)', page)
        self.assertNotIn('](AGENTS.md)', page)
        self.assertNotIn('](RESOLVER.md)', page)

    def test_show_refuses_a_run_folder_outside_the_runs_folder(self):
        output = self.state('show', '--run-dir', str(self.portfolio / 'cedar-shop'), expected=1)
        self.assertIn('--run-dir must be a folder inside', output)
        self.assertFalse((self.portfolio / 'cedar-shop/start-page.md').exists())
        self.assertIn('--mark needs --seat', self.state('show', '--mark', expected=1))


    # ------------------------------------------------------------ two workspaces: no row of the other one is counted

    def two_workspaces(self):
        """Rows of oak-studio in the shared database, each newer than every row of cedar-shop."""
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute("UPDATE tasks SET status='in-review', owner='avery', project='WS01', created_on=? WHERE id='T8'", (self.stamp(-30),))
            db.execute("INSERT INTO activity (subject_type,subject_id,field,new_value,at) VALUES ('task','T8','status','in-review',?)", (self.stamp(-20),))
            db.execute("INSERT INTO runs VALUES ('oak-run','worker',?,?,'task','T8')", (self.stamp(-25), self.stamp(-15)))
            db.execute("ALTER TABLE decisions ADD COLUMN tags TEXT")
            db.execute("INSERT INTO decisions VALUES ('g-oak','Oak rule','ruled',?,'workspace:oak-studio')", (day(0)[:10],))

    def page(self, workspace):
        self.state('build', '--workspace', workspace)
        return (self.portfolio / workspace / 'STATE.md').read_text()

    def test_scope_a_shared_database_counts_no_row_of_the_other_workspace(self):
        before = self.page('cedar-shop')
        self.two_workspaces()
        cedar, oak = self.page('cedar-shop'), self.page('oak-studio')
        # cedar-shop: every count and every list is what it was before the oak rows came
        self.assertEqual(steady(before), steady(cedar))
        for text in ('Oak task', 'Oak rule', 'T8'):
            self.assertNotIn(text, cedar)
        # oak-studio: exactly its own rows
        for label, value in (('OPEN TASKS', '1'), ('WAITING FOR AVERY', '1'), ('OPEN BUGS', '0'), ('NEW TASKS', '1'),
                             ('MOVED TO IN REVIEW', '1'), ('DECISIONS', '1'), ('RUNS', '1')):
            self.assertEqual(self.count(oak, label), value, label)
        self.assertIn('| T8 | Oak task | WS01 |', oak)
        self.assertIn('| Oak rule | ', oak)
        for text in ('Check stock', 'Write the brief', 'Ship on Friday', 'T1 ', 'T2 '):
            self.assertNotIn(text, oak)
        self.assertEqual(self.count(oak, 'NEWEST CHANGE'), self.stamp(-20)[:16].replace('T', ' '))
        self.assertNotEqual(self.count(cedar, 'NEWEST CHANGE'), self.count(oak, 'NEWEST CHANGE'))

    def test_scope_a_task_with_no_workspace_counts_for_the_default_workspace_only(self):
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute("INSERT INTO tasks VALUES ('T9','No workspace on it','todo',NULL,NULL,NULL,NULL,NULL,?)", (self.stamp(-5),))
            db.execute("INSERT INTO runs VALUES ('R-free','worker',?,?,NULL,NULL)", (self.stamp(-5), self.stamp(-4)))
        cedar, oak = self.page('cedar-shop'), self.page('oak-studio')
        self.assertEqual((self.count(cedar, 'OPEN TASKS'), self.count(oak, 'OPEN TASKS')), ('6', '1'))
        self.assertEqual((self.count(cedar, 'RUNS'), self.count(oak, 'RUNS')), ('2', '0'))

    def test_the_system_page_lists_decisions_of_one_day_in_one_order(self):
        # T693: decisions of the same day came out in set order, so --check failed on a page just built.
        with sqlite3.connect(str(self.system_db)) as db:
            db.executemany('INSERT INTO decisions VALUES (?,?,?,?)',
                           [('g-%d' % n, 'Rule number %d' % n, 'ruled', day(1)[:10]) for n in range(8)])
        pages = set()
        for seed in ('1', '2', '3'):
            self.env['PYTHONHASHSEED'] = seed
            self.state('build', '--system')
            pages.add('\n'.join(line for line in (self.home / 'STATE.md').read_text().splitlines()
                                if not line.startswith(('timestamp: ', 'MADE '))))
        self.assertEqual(len(pages), 1)

    def test_scope_the_system_page_counts_each_row_once(self):
        self.two_workspaces()
        self.state('build', '--system')
        page = (self.home / 'STATE.md').read_text()
        for label, value in (('OPEN TASKS', '6'), ('RUNS', '2'), ('DECISIONS', '2'), ('MOVED TO IN REVIEW', '2'), ('OPEN BUGS', '1')):
            self.assertEqual(self.count(page, label), value, label)

    def test_scope_a_workspace_with_its_own_database_and_the_shared_one_do_not_mix(self):
        # The other table shape: oak-studio has its own data.db. Rows tagged oak-studio in the shared one are not its rows.
        self.two_workspaces()
        own = self.portfolio / 'oak-studio/data.db'
        self.make(own, rows=False)
        with sqlite3.connect(str(own)) as db:
            db.execute("INSERT INTO tasks VALUES ('T1','Sand the table','in-progress',NULL,NULL,NULL,NULL,NULL,?)", (self.stamp(-50),))
            db.execute("INSERT INTO runs VALUES ('own-run','worker',?,?,NULL,NULL)", (self.stamp(-50), self.stamp(-45)))
        cedar, oak = self.page('cedar-shop'), self.page('oak-studio')
        self.assertEqual((self.count(oak, 'OPEN TASKS'), self.count(oak, 'RUNS'), self.count(oak, 'DECISIONS')), ('1', '1', '0'))
        for text in ('Oak task', 'Oak rule', 'Check stock', 'Ship on Friday'):
            self.assertNotIn(text, oak)
        for text in ('Oak task', 'Oak rule', 'Sand the table'):
            self.assertNotIn(text, cedar)
        self.assertEqual(self.count(cedar, 'OPEN TASKS'), '5')
        part = self.state('show', '--workspace', 'oak-studio', '--seat', 'worker').split('## For worker')[1]
        self.assertIn('(the run row own-run)', part)

    def test_scope_the_session_boundary_is_never_a_run_of_another_workspace(self):
        # The third reader's probe 3: a newer oak-studio run of the same seat became the cedar-shop boundary.
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute('DELETE FROM runs')
            db.execute("UPDATE tasks SET created_on=?", (self.stamp(-600),))
            db.execute("UPDATE tasks SET created_on=? WHERE id='T1'", (self.stamp(-120),))
            db.execute("INSERT INTO runs VALUES ('cedar-run','worker',?,?,'task','T2')", (self.stamp(-240), self.stamp(-180)))
            db.execute("INSERT INTO runs VALUES ('oak-run','worker',?,?,'task','T8')", (self.stamp(-60), self.stamp(-30)))
            db.execute("INSERT INTO runs VALUES ('loose-run','worker',?,?,NULL,NULL)", (self.stamp(-20), self.stamp(-10)))
        part = self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker').split('## For worker in cedar-shop')[1]
        self.assertIn('(the run row cedar-run)', part)
        self.assertEqual(int(self.count(part, 'NEW TASKS')), 1)
        part = self.state('show', '--workspace', 'oak-studio', '--seat', 'worker').split('## For worker in oak-studio')[1]
        self.assertIn('(the run row oak-run)', part)
        # a mark for one workspace is not the boundary of the other
        self.state('show', '--workspace', 'oak-studio', '--seat', 'worker', '--mark')
        part = self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker').split('## For worker in cedar-shop')[1]
        self.assertIn('(the run row cedar-run)', part)
        self.assertEqual(int(self.count(part, 'NEW TASKS')), 1)

    def test_scope_a_run_that_names_no_task_is_no_boundary_and_the_marker_is_used(self):
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute('DELETE FROM runs')
            db.execute("INSERT INTO runs VALUES ('loose-run','worker',?,?,NULL,NULL)", (self.stamp(-20), self.stamp(-10)))
        part = self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker').split('## For worker')[1]
        self.assertIn('The rows hold no session of this seat here.', part)
        (self.home / 'runs/state-markers.json').write_text(json.dumps({'worker|cedar-shop': self.stamp(-60)}))
        part = self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker').split('## For worker')[1]
        self.assertIn('(the marked session)', part)

    def test_times_with_and_without_an_offset_are_compared_with_the_full_boundary(self):
        def local(minutes, form):
            moment = datetime.now().astimezone() + timedelta(minutes=minutes)
            if form == 'naive':
                return moment.strftime('%Y-%m-%d %H:%M:%S')
            if form == 'utc':
                return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            return moment.replace(microsecond=0).isoformat()
        with sqlite3.connect(str(self.system_db)) as db:
            db.execute('DELETE FROM runs')
            rows = [('old-naive', -90, 'naive'), ('old-utc', -90, 'utc'), ('old-offset', -90, 'offset'),
                    ('new-naive', -30, 'naive'), ('new-utc', -30, 'utc'), ('new-offset', -30, 'offset')]
            db.executemany("INSERT INTO runs VALUES (?,'worker',?,NULL,'task','T1')", [(name, local(minutes, form)) for name, minutes, form in rows])
        (self.home / 'runs/state-markers.json').write_text(json.dumps({'chief-of-staff|cedar-shop': self.stamp(-60)}))
        part, counts = self.seat_counts()
        self.assertEqual(counts['RUNS'], 3)

    def test_two_writers_of_the_session_markers_do_not_lose_a_mark(self):
        lock = self.home / 'runs/.state-markers.json.lock'
        lock.write_text('held by another state.py\n')
        output = self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker', '--mark', expected=1)
        self.assertIn('The session was not marked', output)
        self.assertFalse((self.home / 'runs/state-markers.json').exists())
        self.assertTrue(lock.exists())
        self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker')
        lock.unlink()
        self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker', '--mark')
        self.state('show', '--workspace', 'oak-studio', '--seat', 'worker', '--mark')
        self.assertEqual(sorted(json.loads((self.home / 'runs/state-markers.json').read_text())), ['worker|cedar-shop', 'worker|oak-studio'])
        self.assertFalse(lock.exists())

    def test_marking_never_writes_through_a_planted_temporary_link(self):
        # T750 F07: the old fixed name .state-markers.json.tmp followed a link planted there.
        victim = self.home / 'victim.txt'
        victim.write_text('ORIGINAL\n')
        planted = self.home / 'runs/.state-markers.json.tmp'
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.symlink_to(victim)
        self.state('show', '--workspace', 'cedar-shop', '--seat', 'worker', '--mark')
        self.assertEqual(victim.read_text(), 'ORIGINAL\n')
        self.assertTrue(planted.is_symlink())
        self.assertEqual(sorted(json.loads((self.home / 'runs/state-markers.json').read_text())), ['worker|cedar-shop'])
        self.assertEqual([p.name for p in (self.home / 'runs').glob('.state-markers.json.*.tmp')], [])

if __name__ == '__main__':
    unittest.main()
