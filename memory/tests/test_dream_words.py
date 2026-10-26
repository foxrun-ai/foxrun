#!/usr/bin/env python3
"""Tests for the three words of memory/dream.py: run, code, report.

Each test makes a small home with only the files it needs. The two check commands and
work.py are small stand-ins written by the test; the real ones need their whole folders.
Run from the system home: python3 -m unittest memory.tests.test_dream_words
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else 'python3'
NEEDED = ('memory/runs.py', 'memory/dream.py', 'memory/handoff_check.py', 'memory/state.py', 'memory/kept.py', 'memory/health.py',
          'memory/model_proposals.py', 'base/simple_yaml.py',
          'base/paths.py', 'base/person.py', 'base/tracker.py', 'base/backup.py',
          'base/page_indexes.py', 'base/templates/index.md')
# Stand-ins for the two checkers. Like the real ones, each prints a JSON list with --json and exits 1 with a finding.
PASSING_CHECK = 'print("[]")\n'
ONE_FINDING = ('import json, sys\nprint(json.dumps([{"category": "collision", "file": "a.sql", "line": 3, '
               '"subject": "orders", "detail": "two tables collide"}]))\nsys.exit(1)\n')
TWO_FINDINGS = ('import json, sys\nprint(json.dumps([{"category": "collision", "file": "a.sql", "line": 3, "subject": "alpha", '
                '"detail": "FIRST: missing table alpha"}, {"category": "collision", "file": "b.sql", "line": 9, "subject": "beta", '
                '"detail": "SECOND: missing table beta"}]))\nsys.exit(1)\n')
TWO_REPLACES = ('import json, sys\nprint(json.dumps([{"id": "g-one", "status": "ruled", "word": "replaces", "statement": "It replaces g-zero."}, '
                '{"id": "g-two", "status": "soft", "word": "supersedes", "statement": "It supersedes g-one."}]))\nsys.exit(1)\n')
BROKEN_CHECK = 'import sys\nprint("Traceback: the checker broke")\nsys.exit(1)\n'
# A stand-in for work.py: it writes the bug row the real command writes, and keeps the words it got.
WORK = '''import json, sqlite3, sys
a = sys.argv[1:]
value = lambda flag: a[a.index(flag) + 1]
open(value('--db') + '.calls', 'a').write(json.dumps(a) + '\\n')
if 'bug-open' in a:
    with sqlite3.connect(value('--db')) as db:
        db.execute('INSERT INTO bugs VALUES (?,?,?)', (value('--id'), value('--title'), 'open'))
'''
TABLES = '''
CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, project TEXT, tags TEXT, parent TEXT, created_on TEXT);
CREATE TABLE activity (id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT, field TEXT, old_value TEXT, new_value TEXT, at TEXT);
CREATE TABLE comments (id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT, at TEXT, body TEXT);
CREATE TABLE runs (id TEXT PRIMARY KEY, subject_id TEXT, "by" TEXT, result TEXT, started_at TEXT, ended_at TEXT);
CREATE TABLE decisions (id TEXT PRIMARY KEY, name TEXT, status TEXT, decided_on TEXT);
CREATE TABLE bugs (id TEXT PRIMARY KEY, title TEXT, status TEXT);
'''


def at(days, hour=12):
    moment = (datetime.now().astimezone() - timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return moment.isoformat()


def day(days):
    return (datetime.now().astimezone() - timedelta(days=days)).strftime('%Y-%m-%d')


class DreamWordTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('FOXRUN_TEST_ROOT') or None
        self.temp = tempfile.TemporaryDirectory(prefix='dream-home-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.home, self.portfolio = root / 'system', root / 'portfolio'
        for name in NEEDED:
            (self.home / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, self.home / name)
        for folder in ('config', 'runs', 'backups/jsonl', 'agents', 'decisions', 'work'):
            (self.home / folder).mkdir(parents=True)
        (self.home / 'base/check_blueprints.py').write_text(PASSING_CHECK)
        (self.home / 'decisions/lint_replaces.py').write_text(PASSING_CHECK)
        (self.home / 'work/work.py').write_text(WORK)
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery', 'default_workspace': 'cedar-shop'}))
        for folder in (self.home, self.portfolio / 'cedar-shop', self.portfolio / 'oak-studio'):
            folder.mkdir(parents=True, exist_ok=True)
            for name in ('AGENTS.md', 'RESOLVER.md'):
                (folder / name).write_text('# ' + name + '\n')
        self.db = self.home / 'data.db'
        with sqlite3.connect(str(self.db)) as db:
            db.executescript(TABLES)
            db.execute("INSERT INTO tasks VALUES ('T1','Check stock','in-progress',NULL,NULL,NULL,?)", (at(1),))
            db.execute("INSERT INTO tasks VALUES ('T2','Old task','todo',NULL,NULL,NULL,?)", (at(20),))
            db.executemany("INSERT INTO activity (subject_type,subject_id,field,old_value,new_value,at) VALUES ('task',?,?,?,?,?)", [
                ('T1', 'status', 'todo', 'in-progress', at(1)), ('T2', 'status', None, 'todo', at(20)), ('T2', 'title', 'x', 'Old task', at(5))])
            db.executemany("INSERT INTO comments (subject_type,subject_id,at,body) VALUES ('task',?,?,?)", [
                ('T1', at(1), 'started'), ('T1', at(1, 15), 'half done'), ('T2', at(3), 'later')])
            db.executemany('INSERT INTO runs VALUES (?,?,?,?,?,?)', [
                ('R1', 'T1', 'worker', 'pass', at(1), at(1, 13)), ('R2', 'T2', 'worker', 'fail', at(10), at(10, 13))])
            db.execute("INSERT INTO decisions VALUES ('g-1','Ship on Friday','ruled',?)", (day(1),))
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('FOXRUN_')}
        self.env.update(FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio),
                        FOXRUN_STATE=str(self.home / 'runs'), HOME=str(root), PYTHONDONTWRITEBYTECODE='1')

    def dream(self, *args, expected=0):
        result = subprocess.run([PYTHON, '-B', str(self.home / 'memory/dream.py')] + list(args), cwd=str(self.home),
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result.stdout, result.stderr

    def folders(self):
        # T755: dream folders live in runs/nightly/.
        return sorted((p for p in (self.home / 'runs/nightly').iterdir() if '-dream' in p.name), key=lambda p: (len(p.name), p.name))

    def files(self):
        root = Path(self.temp.name)
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def calls(self):
        file = Path(str(self.db) + '.calls')
        return [json.loads(line) for line in file.read_text().splitlines()] if file.is_file() else []

    # ------------------------------------------------------------ the words

    def test_code_runs_the_four_steps_and_leaves_one_run_folder(self):
        out, _ = self.dream('code')
        for name in ('kept', 'state', 'index', 'daily', 'backup', 'checks'):
            self.assertIn('code ' + name + ': pass', out)
        self.assertNotIn('model half', out)
        (folder,) = self.folders()
        self.assertEqual(json.loads((folder / 'manifest.json').read_text())['code_steps'], ['kept', 'state', 'index', 'daily', 'backup', 'checks'])
        steps = [json.loads(line) for line in (folder / 'steps.jsonl').read_text().splitlines()]
        self.assertEqual([(s['step'], s['result']) for s in steps],
                         [('kept', 'pass'), ('state', 'pass'), ('index', 'pass'), ('daily', 'pass'), ('backup', 'pass'), ('checks', 'pass')])
        report = (folder / 'report.md').read_text()
        self.assertIn('WORD         code', report)
        self.assertIn('CODE HALF    6 of 6 steps passed', report)
        self.assertIn('MODEL HALF   not asked', report)
        self.assertIn('FAILURES     0', report)
        self.assertIn('## Not a step yet', report)
        self.assertIn('- draft wiki pages: ', report)
        self.assertIn('# State: system', (self.home / 'STATE.md').read_text())
        self.assertIn('# State: cedar-shop', (self.portfolio / 'cedar-shop/STATE.md').read_text())
        self.assertIn('# Index: cedar-shop', (self.portfolio / 'cedar-shop/index.md').read_text())
        self.assertIn('# Index: portfolio', (self.portfolio / 'index.md').read_text())
        self.assertIn('Check stock', (self.home / 'state/tasks.jsonl').read_text())
        self.assertTrue((self.home / 'state/_mirrors.jsonl').is_file())
        self.assertFalse((self.home / 'backups/jsonl/tasks.jsonl').exists())
        self.assertEqual(self.calls(), [])

    def test_run_without_a_model_runner_runs_the_code_half_and_says_so(self):
        out, err = self.dream('run')
        self.assertIn('code state: pass', out)
        self.assertIn('model half: skipped', out)
        # fd24669 (10.14 launch fix s2b) dropped the 'Jev is optional' stderr line; a missing runner records skipped and passes quietly
        self.assertEqual('', err)
        report = (self.folders()[0] / 'report.md').read_text()
        # report words per dream.py docstring since fd24669: 'skipped: no model'
        self.assertIn('MODEL HALF   skipped-no-model', report)
        self.assertIn('skipped: no model', report)

    def test_no_word_means_run(self):
        out, err = self.dream('--dry-run')
        self.assertIn('model half: skipped', out)
        # fd24669 (10.14 launch fix s2b) dropped the 'Jev is optional' stderr line; a missing runner records skipped and passes quietly
        self.assertEqual('', err)

    def test_dry_run_runs_no_step_and_writes_nothing(self):
        before = self.files()
        out, _ = self.dream('run', '--dry-run')
        for name in ('state', 'index', 'daily', 'backup', 'checks'):
            self.assertIn('code ' + name + ': not run (dry run)', out)
        self.assertEqual(before, self.files())

    def test_with_no_home_set_the_job_works_on_its_own_home(self):
        del self.env['FOXRUN_HOME']
        self.dream('code')
        self.assertTrue((self.folders()[0] / 'report.md').is_file())
        self.assertFalse((Path(self.temp.name).resolve() / '.foxrun').exists())

    # ------------------------------------------------------------ the report: the reader's probe and its kin

    def test_code_after_run_does_not_touch_the_night_report(self):
        # Probe: run, then code on the same day. The night report and its manifest were overwritten.
        self.dream('run')
        (night,) = self.folders()
        before = {p.name: p.read_bytes() for p in night.iterdir()}
        self.dream('code')
        self.assertEqual(before, {p.name: p.read_bytes() for p in night.iterdir()})
        self.assertEqual([p.name for p in self.folders()], [night.name, night.name + '-2'])
        second = self.folders()[1]
        self.assertEqual(len((night / 'steps.jsonl').read_text().splitlines()), 6)
        self.assertEqual(len((second / 'steps.jsonl').read_text().splitlines()), 6)
        self.assertIn('MODEL HALF   skipped', (night / 'report.md').read_text())
        self.assertIn('MODEL HALF   not asked', (second / 'report.md').read_text())

    def test_report_shows_the_last_whole_night_not_a_later_code_call(self):
        _, err = self.dream('report', expected=1)
        self.assertIn('No dream report yet.', err)
        self.dream('code')
        out, _ = self.dream('report')
        self.assertIn('WORD         code', out)
        self.dream('run')
        self.dream('code')
        before = self.files()
        out, _ = self.dream('report')
        self.assertEqual(out, (self.folders()[1] / 'report.md').read_text())
        self.assertIn('WORD         run', out)
        self.assertEqual(before, self.files())

    def test_each_run_on_one_day_has_its_own_folder_and_report_shows_the_newest(self):
        for _ in range(3):
            self.dream('run')
        names = [p.name for p in self.folders()]
        self.assertEqual(names, [names[0], names[0] + '-2', names[0] + '-3'])
        out, _ = self.dream('report')
        self.assertEqual(out, (self.folders()[2] / 'report.md').read_text())

    # ------------------------------------------------------------ the steps

    def test_daily_writes_the_page_of_the_last_full_day_with_week_and_month_counts(self):
        out, _ = self.dream('code')
        self.assertIn('1 written (cedar-shop), 0 kept, 1 with no event row', out)
        page = (self.portfolio / 'cedar-shop/history/daily' / (day(1) + '.md')).read_text()
        self.assertEqual(page.splitlines()[0:3], ['---', 'type: daily', 'workspace: cedar-shop'])
        self.assertIn('# Day: ' + day(1), page)
        self.assertIn('| Count | This day | 7 days | 30 days |', page)
        self.assertIn('| Task changes | 1 | 2 | 3 |', page)
        self.assertIn('| Comments | 2 | 3 | 3 |', page)
        self.assertIn('| Runs | 1 | 1 | 2 |', page)
        self.assertIn('| New tasks | 1 | 1 | 2 |', page)
        self.assertIn('| Decisions | 1 | 1 | 1 |', page)
        self.assertIn('| T1 | Check stock | todo | in-progress |', page)
        self.assertIn('| R1 | T1 | worker | pass |', page)
        self.assertIn('| Ship on Friday | ruled |', page)
        self.assertFalse((self.portfolio / 'oak-studio/history/daily').exists())

    def test_a_day_page_is_frozen(self):
        self.dream('code')
        file = self.portfolio / 'cedar-shop/history/daily' / (day(1) + '.md')
        before = file.read_bytes()
        with sqlite3.connect(str(self.db)) as db:
            db.execute("INSERT INTO comments (subject_type,subject_id,at,body) VALUES ('task','T1',?,'late row')", (at(1, 18),))
        out, _ = self.dream('code')
        self.assertIn('0 written (none), 1 kept', out)
        self.assertEqual(before, file.read_bytes())

    def test_a_day_page_never_writes_through_a_planted_temporary_link(self):
        # T750 F07: the old fixed name .<day>.md.tmp followed a link planted there.
        folder = self.portfolio / 'cedar-shop/history/daily'
        folder.mkdir(parents=True)
        victim = Path(self.temp.name) / 'victim.txt'
        victim.write_text('ORIGINAL\n')
        planted = folder / ('.' + day(1) + '.md.tmp')
        planted.symlink_to(victim)
        out, _ = self.dream('code')
        self.assertIn('1 written (cedar-shop)', out)
        self.assertEqual(victim.read_text(), 'ORIGINAL\n')
        self.assertTrue(planted.is_symlink())
        page = folder / (day(1) + '.md')
        self.assertIn('# Day: ' + day(1), page.read_text())
        self.assertEqual(page.stat().st_mode & 0o777, 0o644)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([page.name, planted.name]))

    def test_saved_state_never_writes_through_a_planted_temporary_link(self):
        import importlib.util
        import sys
        victim = Path(self.temp.name) / 'victim.txt'
        victim.write_text('ORIGINAL\n')
        folder = Path(self.temp.name) / 'session-nightly'
        folder.mkdir()
        (folder / 'state.json.tmp').symlink_to(victim)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update(self.env)
        sys.path[:0] = [str(self.home), str(self.home / 'memory')]
        self.addCleanup(lambda: [sys.path.remove(p) for p in (str(self.home), str(self.home / 'memory'))])
        loaded = set(sys.modules)
        self.addCleanup(lambda: [sys.modules.pop(name) for name in set(sys.modules) - loaded])
        spec = importlib.util.spec_from_file_location('dream_under_test', self.home / 'memory/dream.py')
        dream = importlib.util.module_from_spec(spec)
        sys.modules['dream_under_test'] = dream
        spec.loader.exec_module(dream)
        dream.save_state(folder / 'state.json', {'flagged': {}})
        self.assertEqual(victim.read_text(), 'ORIGINAL\n')
        self.assertEqual(json.loads((folder / 'state.json').read_text()), {'flagged': {}})
        self.assertEqual((folder / 'state.json').stat().st_mode & 0o777, 0o600)

    def test_backup_also_writes_a_workspace_that_has_its_own_database(self):
        with sqlite3.connect(str(self.portfolio / 'oak-studio/data.db')) as db:
            db.executescript(TABLES)
            db.execute("INSERT INTO tasks VALUES ('T1','Sand the table','todo',NULL,NULL,NULL,?)", (at(40),))
        out, _ = self.dream('code')
        self.assertIn('2 databases written', out)
        self.assertIn('Sand the table', (self.home / 'backups/jsonl/oak-studio/tasks.jsonl').read_text())
        self.assertIn('Check stock', (self.home / 'state/tasks.jsonl').read_text())
        self.assertNotIn('Sand the table', (self.home / 'state/tasks.jsonl').read_text())

    def bug_calls(self):
        return [call for call in self.calls() if 'bug-open' in call]

    def test_checks_zero_findings_file_no_bug_row(self):
        out, _ = self.dream('code')
        self.assertIn('code checks: pass (3 checks, 0 findings, 0 new bug rows, 0 filed before)', out)
        self.assertEqual(self.calls(), [])
        with sqlite3.connect(str(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM bugs').fetchone()[0], 0)

    def test_checks_one_finding_is_one_bug_row_and_is_not_filed_twice(self):
        (self.home / 'base/check_blueprints.py').write_text(ONE_FINDING)
        out, _ = self.dream('code')
        self.assertIn('1 findings, 1 new bug rows, 0 filed before', out)
        (call,) = self.bug_calls()
        self.assertEqual(call[call.index('--description') + 1], 'collision: a.sql:3: orders: two tables collide')
        self.assertTrue(call[call.index('--id') + 1].startswith('B-dream-blueprints-'))
        out, _ = self.dream('code')
        self.assertIn('1 findings, 0 new bug rows, 1 filed before', out)
        self.assertEqual(len(self.bug_calls()), 1)

    def test_checks_two_findings_of_one_checker_are_two_bug_rows(self):
        # The second reader's probe: two findings made one bug row, with only the second finding.
        (self.home / 'base/check_blueprints.py').write_text(TWO_FINDINGS)
        out, _ = self.dream('code')
        self.assertIn('2 findings, 2 new bug rows', out)
        first, second = self.bug_calls()
        texts = [call[call.index('--description') + 1] for call in (first, second)]
        self.assertEqual(texts, ['collision: a.sql:3: alpha: FIRST: missing table alpha',
                                 'collision: b.sql:9: beta: SECOND: missing table beta'])
        self.assertNotEqual(first[first.index('--id') + 1], second[second.index('--id') + 1])
        with sqlite3.connect(str(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM bugs').fetchone()[0], 2)

    def test_checks_findings_of_two_checkers_are_all_kept(self):
        (self.home / 'base/check_blueprints.py').write_text(TWO_FINDINGS)
        (self.home / 'decisions/lint_replaces.py').write_text(TWO_REPLACES)
        out, _ = self.dream('code')
        self.assertIn('4 findings, 4 new bug rows', out)
        texts = [call[call.index('--description') + 1] for call in self.bug_calls()]
        self.assertIn('g-one [ruled] replaces: It replaces g-zero.', texts)
        self.assertIn('g-two [soft] supersedes: It supersedes g-one.', texts)
        self.assertEqual(len(set(call[call.index('--id') + 1] for call in self.bug_calls())), 4)

    def test_checks_a_checker_that_breaks_is_not_read_as_a_finding(self):
        (self.home / 'base/check_blueprints.py').write_text(BROKEN_CHECK)
        (self.home / 'decisions/lint_replaces.py').write_text(ONE_FINDING)
        out, _ = self.dream('code', expected=1)
        self.assertIn('code checks: fail', out)
        self.assertIn('Could not: blueprints: it did not print a JSON list of findings', out)
        self.assertIn('1 findings, 1 new bug rows', out)
        self.assertEqual(len(self.bug_calls()), 1)

    def test_a_status_with_no_activity_row_is_a_finding(self):
        with sqlite3.connect(str(self.db)) as db:
            db.execute("UPDATE tasks SET status='done' WHERE id='T1'")
        out, _ = self.dream('code')
        self.assertIn('direct-write-system (task T1 in the system database has a status with no activity row)', out)
        self.assertEqual(len(self.calls()), 1)

    def test_a_check_that_cannot_run_fails_the_step_and_is_in_the_report(self):
        (self.home / 'decisions/lint_replaces.py').unlink()
        out, _ = self.dream('code', expected=1)
        self.assertIn('code checks: fail', out)
        self.assertIn('Could not: replaces: the command is not installed: decisions/lint_replaces.py', out)
        self.assertIn('FAILURES     1', (self.folders()[0] / 'report.md').read_text())

    def test_a_failed_step_is_in_the_report_and_the_next_step_still_runs(self):
        (self.home / 'base/backup.py').unlink()
        out, _ = self.dream('code', expected=1)
        self.assertIn('code backup: fail (the command is not installed: base/backup.py)', out)
        self.assertIn('code checks: pass', out)
        report = (self.folders()[0] / 'report.md').read_text()
        self.assertIn('CODE HALF    5 of 6 steps passed', report)
        self.assertIn('- backup: the command is not installed: base/backup.py', report)


    # ------------------------------------------------------------ two workspaces, two callers, and a dry run of each word

    def test_day_pages_of_two_workspaces_in_one_database_do_not_mix(self):
        with sqlite3.connect(str(self.db)) as db:
            db.execute("ALTER TABLE decisions ADD COLUMN tags TEXT")
            db.execute("ALTER TABLE runs ADD COLUMN subject_type TEXT")
            db.execute("UPDATE runs SET subject_type='task'")
            db.execute("INSERT INTO tasks VALUES ('T7','Sand the table','todo',NULL,'workspace:oak-studio',NULL,?)", (at(1),))
            db.execute("INSERT INTO activity (subject_type,subject_id,field,old_value,new_value,at) VALUES ('task','T7','status','backlog','todo',?)", (at(1),))
            db.execute("INSERT INTO comments (subject_type,subject_id,at,body) VALUES ('task','T7',?,'oak note')", (at(1),))
            db.execute("INSERT INTO runs VALUES ('R7','T7','worker','pass',?,?,'task')", (at(1), at(1, 13)))
            db.execute("INSERT INTO decisions VALUES ('g-oak','Oak rule','ruled',?,'workspace:oak-studio')", (day(1),))
        out, _ = self.dream('code')
        self.assertIn('2 written (cedar-shop, oak-studio)', out)
        cedar = (self.portfolio / 'cedar-shop/history/daily' / (day(1) + '.md')).read_text()
        oak = (self.portfolio / 'oak-studio/history/daily' / (day(1) + '.md')).read_text()
        for line in ('| Task changes | 1 | 2 | 3 |', '| Comments | 2 | 3 | 3 |', '| Runs | 1 | 1 | 2 |', '| New tasks | 1 | 1 | 2 |', '| Decisions | 1 | 1 | 1 |'):
            self.assertIn(line, cedar)
        for text in ('| T7 |', 'Sand the table', '| R7 |', 'Oak rule'):
            self.assertNotIn(text, cedar)
        for line in ('| Task changes | 1 | 1 | 1 |', '| Comments | 1 | 1 | 1 |', '| Runs | 1 | 1 | 1 |', '| New tasks | 1 | 1 | 1 |', '| Decisions | 1 | 1 | 1 |',
                     '| T7 | Sand the table | backlog | todo |', '| R7 | T7 | worker | pass |', '| Oak rule | ruled |'):
            self.assertIn(line, oak)
        for text in ('| T1 |', 'Check stock', '| R1 |', 'Ship on Friday'):
            self.assertNotIn(text, oak)

    def test_a_second_memory_job_in_one_home_fails_at_once_and_changes_nothing(self):
        lock = self.home / 'runs/.dream.lock'
        lock.write_text(json.dumps({'pid': os.getpid(), 'at': '2026-10-13T02:30:00-04:00'}) + '\n')
        before = self.files()
        for word in ('code', 'run'):
            _, err = self.dream(word, expected=3)
            self.assertIn('another memory job runs in this home now', err)
            self.assertIn('Nothing was changed', err)
        self.assertEqual(before, self.files())
        gone = subprocess.Popen([PYTHON, '-c', 'pass'])
        gone.wait()
        lock.write_text(json.dumps({'pid': gone.pid, 'at': '2026-10-13T02:30:00-04:00'}) + '\n')
        before = self.files()
        _, err = self.dream('code', expected=3)
        self.assertIn('the memory job has a stale lock: process ' + str(gone.pid), err)
        self.assertIn('the lock was not removed', err)
        self.assertEqual(before, self.files())
        # the words that only read still work, and leave the lock alone
        self.dream('code', '--dry-run')
        self.dream('report', expected=1)
        self.assertEqual(before, self.files())
        lock.unlink()
        self.dream('code')
        self.assertFalse(lock.exists())

    def test_dry_run_of_every_word_writes_nothing(self):
        self.dream('code')
        before = self.files()
        for words in (('code', '--dry-run'), ('run', '--dry-run'), ('--dry-run',), ('report', '--dry-run'), ('run', '--dry-run', '--rerun')):
            self.dream(*words)
        self.assertEqual(before, self.files())

if __name__ == '__main__':
    unittest.main()
