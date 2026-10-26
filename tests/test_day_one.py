#!/usr/bin/env python3
"""First-run regressions with Cedar Shop fixtures and isolated homes."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TREE = Path(__file__).resolve().parents[1]

# Every new task carries the six fields (T718); Where is the workspace's STATE.md.
SIX = ('--problem', 'The shop needs a first task', '--job-when', 'When the day starts', '--job-want', 'I want one task',
       '--job-so', 'So I can see the writer work', '--body', 'Writes one task row', '--acceptance', 'The task is shown',
       '--context', 'Day one fixture', '--where', 'STATE.md')


class DayOneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR', str(TREE)))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'system'
        self.portfolio = self.root / 'portfolio'
        (self.home / 'config').mkdir(parents=True)
        for name in ('cedar-shop', 'maple-shop'):
            (self.portfolio / name).mkdir(parents=True)
            (self.portfolio / name / 'STATE.md').write_text('Cedar Shop fixture.\n')
        (self.home / 'config/person.json').write_text(json.dumps({'name':'Avery', 'default_workspace':'cedar-shop'}))
        shutil.copyfile(TREE / 'config/models.yaml', self.home / 'config/models.yaml')
        self.env = dict(HOME=str(self.root), TMPDIR=str(self.root), PATH='/usr/bin:/bin:/usr/sbin:/sbin',
                        FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio),
                        FOXRUN_STATE=str(self.home), FOXRUN_PERSON='Avery', PYTHONDONTWRITEBYTECODE='1')
        if os.environ.get('PYTHONPATH'):
            self.env['PYTHONPATH'] = os.environ['PYTHONPATH']

    def command(self, path, *args, expected=0, stdin=None):
        result = subprocess.run(['/usr/bin/python3', '-B', str(TREE / path), *map(str,args)],
                                env=self.env, cwd=self.root, input=stdin, capture_output=True, text=True)
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def database(self, path):
        self.command('base/build_database.py', path, '--modules', 'work', '--by', 'fixture')

    def task(self, name, title):
        return self.command('work/work.py', '--workspace', name, '--receipt-root', self.portfolio / name,
                            'create', '--title', title, '--by', 'avery', '--session', 'fixture', *SIX).strip()

    def test_scoped_create_show_uses_real_id(self):
        self.database(self.home / 'data.db')
        identifier = self.task('cedar-shop', 'Check Cedar Shop delivery')
        self.assertRegex(identifier, r'^T\d+$')
        output = self.command('work/work.py', '--db', self.home / 'data.db', '--receipt-root', self.portfolio / 'cedar-shop', 'show', identifier)
        self.assertIn('Check Cedar Shop delivery', output)
        with sqlite3.connect(self.home / 'data.db') as db:
            self.assertEqual(identifier, db.execute('SELECT id FROM tasks').fetchone()[0])

    def test_scoped_create_workspace_database_wins(self):
        self.database(self.home / 'data.db')
        local = self.portfolio / 'cedar-shop/data.db'
        self.database(local)
        identifier = self.task('cedar-shop', 'Check local delivery')
        self.command('work/work.py', '--workspace', 'cedar-shop', '--receipt-root', self.portfolio / 'cedar-shop', 'show', identifier)
        with sqlite3.connect(self.home / 'data.db') as db:
            self.assertEqual(0, db.execute('SELECT count(*) FROM tasks').fetchone()[0])

    def test_unknown_workspace_lists_existing_names(self):
        output = self.command('foxrun.py', 'start', '--workspace', 'unknown-shop', expected=2)
        self.assertEqual(1, len(output.splitlines()))
        self.assertIn('cedar-shop, maple-shop', output)

    def test_start_filters_shared_tracker_and_counts_others(self):
        self.database(self.home / 'data.db')
        cedar = self.task('cedar-shop', 'Cedar visible task')
        self.task('maple-shop', 'Maple hidden task')
        output = self.command('foxrun.py', 'start', '--workspace', 'cedar-shop')
        self.assertIn(cedar, output)
        self.assertIn('Cedar visible task', output)
        self.assertNotIn('Maple hidden task', output)
        # fbf6a7c: the start page no longer counts other workspaces' tasks; it shows only this workspace's rows.
        self.assertNotIn('not built yet', output)

    def hook(self, runtime, payload):
        (self.home / 'memory').mkdir(exist_ok=True)
        shutil.copyfile(TREE / 'memory/before_compact.py', self.home / 'memory/before_compact.py')
        shutil.copytree(TREE / 'base', self.home / 'base', dirs_exist_ok=True)
        result = subprocess.run(['/bin/sh', str(TREE / 'hooks' / runtime / 'before-compact')],
                                env=self.env, input=payload, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def test_compact_empty_stdin(self):
        for runtime in ('claude', 'codex'):
            output = self.hook(runtime, '')
            self.assertEqual(1, len(output.splitlines()))
            self.assertIn('No handoff yet in ', output)

    def test_compact_runtime_shapes_select_latest_handoff_and_never_block(self):
        folder = self.portfolio / 'maple-shop/history/handoffs'
        folder.mkdir(parents=True)
        old, latest = folder / 'old.md', folder / 'latest.md'
        old.write_text('old')
        latest.write_text('latest')
        os.utime(old, (1,1))
        transcript = self.root / 'transcript.jsonl'
        transcript.write_text('{}\n')
        (self.home / 'memory').mkdir(exist_ok=True)
        (self.home / 'memory/handoff_check.py').write_text("import sys\nprint('CHECK ' + ' '.join(sys.argv[1:]))\nsys.exit(1)\n")
        for runtime, payload in (('claude', dict(cwd=str(folder), transcript_path=str(transcript), session_id='fixture')),
                                 ('codex', dict(data=dict(cwd=str(folder), transcript_path=str(transcript), session_id='fixture')))):
            output = self.hook(runtime, json.dumps(payload))
            self.assertIn(str(latest), output)
            self.assertIn(str(transcript), output)
            self.assertNotIn(str(old), output)

    def test_owner_migration_does_not_ship(self):
        self.assertFalse((TREE / 'base/migrate_person_words.py').exists())
        old = 'OLD_WORDS'
        for path in TREE.rglob('*.py'):
            if '.git' in path.parts or 'tests' in path.parts or path.name.startswith('test'):
                continue
            self.assertNotIn(old, path.read_text(), str(path))

    def test_root_agents_names_only_installed_parts(self):
        text = (TREE / 'AGENTS.md').read_text()
        self.assertNotIn('`apps/`', text)
        self.assertNotIn('`small-talk/`', text)

    def test_hermes_cli_refuses_with_one_line(self):
        for args in (('probe', 'example-agent', '--runtimes', 'hermes'),
                     ('create', 'example-agent', '--hermes-mode', 'profile'),
                     ('create', 'example-agent', '--runtimes=hermes')):
            # The command lives at agents/tools/agent_new.py (src/agents/README.md); Hermes still refuses there.
            output = self.command('agents/tools/agent_new.py', *args, expected=2)
            self.assertEqual('Claude and Codex on day one.\n', output)

    # The installer is source-only: a live home has no install.py (T671 base study, recheck 2 T742).
    @unittest.skipUnless((TREE / 'install.py').exists(), 'install.py ships in the source tree only')
    def test_installer_has_no_unshipped_table_warning(self):
        text = (TREE / 'install.py').read_text()
        self.assertNotIn('Target table rows without a shipped blueprint:', text)
        self.assertNotIn('data.db/base/base_installed_modules', text)

    def test_installed_work_command_finds_custom_home_without_environment(self):
        self.database(self.home / 'data.db')
        config = json.loads((self.home / 'config/person.json').read_text())
        config['portfolio'] = str(self.portfolio)
        (self.home / 'config/person.json').write_text(json.dumps(config))
        for name in ('base', 'work', 'events', 'decisions'):
            shutil.copytree(TREE / name, self.home / name)
        env = {key:value for key,value in self.env.items() if not key.startswith('FOXRUN_')}
        result = subprocess.run(['/usr/bin/python3', '-B', str(self.home / 'work/work.py'),
                                 '--workspace', 'cedar-shop', '--receipt-root', str(self.portfolio / 'cedar-shop'),
                                 'create', '--title', 'Check Cedar Shop custom install', '--by', 'avery', *SIX],
                                env=env, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout.strip(), r'^T\d+$')

    def test_checker_name_ignores_case(self):
        spec = importlib.util.spec_from_file_location('day_one_work', TREE / 'work/work.py')
        work = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = work
        with mock.patch.dict(os.environ, self.env):
            spec.loader.exec_module(work)
        task = dict(id='T1', check_by='AVERY', owner='worker', claimed_by='worker')
        with mock.patch.object(work, 'has_t309', return_value=True), mock.patch.object(work._fox_person, 'name', return_value='avery'), mock.patch.object(work, 'assert_not_finisher'):
            work.assert_signer(None, task, 'Avery')
            with self.assertRaises(work.WorkError):
                work.assert_signer(None, task, 'chief-of-staff')

if __name__ == '__main__':
    unittest.main()
