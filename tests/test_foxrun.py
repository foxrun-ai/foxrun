#!/usr/bin/env python3
"""Launcher acceptance cases; every writable home is below FOXRUN_TEST_ROOT."""
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = '/usr/bin/python3'
FOLDERS = (
    'config', 'raw', 'runs', 'archive', 'backups/jsonl',
    'tools/cli', 'tools/mcp', 'tools/service', 'tools/external-app',
    'tools/schedule', 'tools/plugin', 'agents/generated', 'agents/tools',
    'profile', 'evals', 'wiki',
)

# Python children load this before the command. SQLite creates are guarded too.
WRITE_GUARD = r'''
import os
import fcntl
from pathlib import Path
import sqlite3
import sys
from urllib.parse import unquote, urlsplit
ROOT = Path(os.environ['FOXRUN_WRITE_ROOT']).resolve()
def allowed(value, dir_fd=None):
    if isinstance(value, int) or value is None:
        return
    target = Path(os.fsdecode(value))
    if dir_fd is not None and dir_fd != -1 and not target.is_absolute():
        if sys.platform == 'darwin':
            base = os.fsdecode(fcntl.fcntl(dir_fd, 50, b'\0' * 1024).split(b'\0', 1)[0])
        else:
            base = os.readlink('/proc/self/fd/' + str(dir_fd))
        target = Path(base) / target
    target = target.resolve()
    if str(target) == '/dev/null':  # 8a4199f: the start hook sends the logger's output to /dev/null
        return
    if target != ROOT and ROOT not in target.parents:
        raise RuntimeError('WRITE OUTSIDE TEMP HOME: ' + str(target))
def audit(event, args):
    if event == 'open':
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            allowed(args[0])
    elif event in ('os.remove', 'os.rmdir'):
        allowed(args[0], args[1])
    elif event in ('os.mkdir', 'os.chmod'):
        allowed(args[0], args[2])
    elif event in ('os.chown', 'os.utime'):
        allowed(args[0], args[3])
    elif event == 'os.truncate':
        allowed(args[0])
    elif event in ('os.rename', 'os.link'):
        allowed(args[0]); allowed(args[1])
    elif event == 'os.symlink':
        allowed(args[1])
    elif event == 'sqlite3.connect':
        value = str(args[0])
        if value == ':memory:' or 'mode=ro' in value:
            return
        allowed(unquote(urlsplit(value).path) if value.startswith('file:') else value)
sys.addaudithook(audit)
# Python 3.9 does not emit the sqlite3.connect audit event.
original_connect = sqlite3.connect
def connect(database, *args, **kwargs):
    value = str(database)
    if value != ':memory:' and not (kwargs.get('uri') and 'mode=ro' in value):
        allowed(unquote(urlsplit(value).path) if value.startswith('file:') else value)
    return original_connect(database, *args, **kwargs)
sqlite3.connect = connect
sqlite3.dbapi2.connect = connect
'''


# Every new task carries the six fields (ruling g-every-task-carries-the-six-fields-a-spec-is-a-parent-task).
SIX = ('--problem', 'The shop needs a first task', '--job-when', 'When the day starts', '--job-want', 'I want one task',
       '--job-so', 'So I can see the writer work', '--body', 'Writes one task row', '--acceptance', 'The task is shown',
       '--context', 'Launcher fixture', '--where', 'STATE.md')


class LauncherTests(unittest.TestCase):
    def setUp(self):
        parent = Path(os.environ.get('FOXRUN_TEST_ROOT', tempfile.gettempdir())).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix='launcher-home-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'system'
        self.portfolio = self.root / 'portfolio'
        self.workspace = self.portfolio / 'cedar-shop'
        for folder in FOLDERS:
            (self.home / folder).mkdir(parents=True, exist_ok=True)
        for folder in ('atlas', 'inbox', 'cedar-shop'):
            (self.portfolio / folder).mkdir(parents=True)
        (self.root / 'empty-home').mkdir()
        audit = self.root / 'audit'
        audit.mkdir()
        (audit / 'sitecustomize.py').write_text(WRITE_GUARD, encoding='utf-8')
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith('FOXRUN_'):
                self.env.pop(key)
        self.env.update(HOME=str(self.root / 'empty-home'), FOXRUN_HOME=str(self.home),
                        FOXRUN_PORTFOLIO=str(self.portfolio), FOXRUN_STATE=str(self.home / 'runs'),
                        FOXRUN_WRITE_ROOT=str(self.root), PYTHONPATH=str(audit),
                        PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(self.root), PATH='/usr/bin:/bin')
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery', 'default_workspace': 'cedar-shop'}))
        for name in ('catalog.yaml', 'modules.yaml', 'tools.yaml'):
            (self.home / 'config' / name).write_text('format: 1\n')
        # Doctor validates the real model policy, including its tiers.
        shutil.copyfile(ROOT / 'config/models.yaml', self.home / 'config/models.yaml')
        (self.home / 'VERSION').write_text('0.1.0\n')
        (self.home / 'AGENTS.md').write_text('# System rules\n')
        for file in ('AGENTS.md', 'RESOLVER.md'):
            (self.workspace / file).write_text('# Workspace rules\n')
        (self.workspace / 'STATE.md').write_text('# Cedar Shop state\nNo previous runs.\n')
        # Copy only command dependencies. Tests exercise actual installed paths.
        for folder in ('base', 'work', 'memory', 'hooks', 'events', 'decisions'):
            # Recheck 2 (T742): an installed ROOT also holds the person's two lists in base/;
            # the temp home starts without them (fbf6a7c), and tests that need them write them.
            shutil.copytree(ROOT / folder, self.home / folder, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', 'product-manifest.tsv', 'made-at-install.tsv'))
        shutil.copy2(ROOT / 'foxrun.py', self.home / 'foxrun.py')
        self.run_command(PYTHON, str(self.home / 'base/build_database.py'), str(self.home / 'data.db'),
                         '--modules', 'work', '--by', 'test')

    def run_command(self, *command, expected=0, env=None, input=None):
        result = subprocess.run(command, cwd=self.root, env=env or self.env, input=input,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, expected, result.stdout)
        return result.stdout

    def launcher(self, *args, expected=0, env=None):
        return self.run_command(PYTHON, str(self.home / 'foxrun.py'), *args, expected=expected, env=env)

    def table(self, name, header, entries):
        # The two lists live in base/ since fbf6a7c (10.14): PRODUCT_LIST and MADE_LIST in foxrun.py.
        with (self.home / 'base' / name).open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(header)
            writer.writerows(entries)

    def manifests(self):
        body = (self.home / 'foxrun.py').read_bytes()
        self.table('product-manifest.tsv', ('path', 'bytes', 'sha256'),
                   [('foxrun.py', len(body), hashlib.sha256(body).hexdigest())])
        self.table('made-at-install.tsv', ('path', 'kind'),
                   [('config/person.json', 'file'), ('raw', 'folder'),
                    ('portfolio/cedar-shop/STATE.md', 'file')])

    def fresh_dream(self):
        """A passing dream run from just now, so health passes and the checks under test decide the exit."""
        moment = datetime.now().astimezone().replace(microsecond=0).isoformat()
        run = self.home / 'runs/fixture-dream'
        run.mkdir(parents=True)
        (run / 'manifest.json').write_text(json.dumps({'job': 'dream', 'word': 'run', 'started_at': moment,
                                                       'finished_at': moment, 'result': 'pass'}))

    def snapshot(self):
        return {str(p.relative_to(self.root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_start_person_workspace_tasks_and_state(self):
        # create needs the six fields: ruling g-every-task-carries-the-six-fields-a-spec-is-a-parent-task.
        output = self.run_command(PYTHON, str(self.home / 'work/work.py'), '--db', str(self.home / 'data.db'),
                                 '--receipt-root', str(self.workspace), 'create', '--title', 'Check stock', '--by', 'avery', *SIX)
        self.assertEqual('T1\n', output)
        before = self.snapshot()
        output = self.launcher('start', '--workspace', 'cedar-shop')
        self.assertIn('Person: avery', output)
        self.assertIn('Workspace: cedar-shop', output)
        self.assertIn('T1: Check stock [todo]', output)
        # Since fbf6a7c start renders STATE.md from rows and keeps a start page in runs/; data.db is read only.
        self.assertIn('# State: cedar-shop', output)
        self.assertIn('Read first', output)
        self.assertEqual(before['system/data.db'], self.snapshot()['system/data.db'])
        self.assertIn('# State: cedar-shop', (self.workspace / 'STATE.md').read_text())

    def test_start_fresh_home_no_tasks(self):
        output = self.launcher('start')
        self.assertIn('Workspace: cedar-shop', output)
        self.assertIn('  none', output)

    def test_start_infers_installer_workspace(self):
        (self.home / 'config/person.json').write_text('{"name":"avery"}')
        self.assertIn('Workspace: cedar-shop', self.launcher('start'))

    def test_start_missing_database_fails_without_making_one(self):
        # fbf6a7c: start reads data.db read only and doctor requires it; with no data.db start fails, makes none.
        (self.workspace / 'STATE.md').unlink()
        (self.home / 'data.db').unlink()
        self.assertIn('FAIL start:', self.launcher('start', expected=1))
        self.assertFalse((self.home / 'data.db').exists())
        self.assertIn('FAIL data.db:', self.launcher('doctor', expected=1))

    def test_start_over_budget_prints_the_page_with_a_warning_line(self):
        # 2026-10-24, B-20261023-start-page-201-lines-blank-handoff-line: the 200-line budget is soft. A long handoff makes the page run over; start still prints.
        code = ('import sys; sys.path.insert(0, sys.argv[1]); import foxrun; from memory import start_context; '
                'start_context.handoff_part = lambda *a: "\\n".join("handoff line %d" % n for n in range(230)); '
                'raise SystemExit(foxrun.main(["start", "--workspace", "cedar-shop"]))')
        output = self.run_command(PYTHON, '-c', code, str(self.home))
        lines = output.splitlines()
        self.assertIn('Person: avery', output)
        self.assertIn('handoff line 229', output)
        self.assertGreater(len(lines), 201)
        self.assertEqual(lines[-1], 'Warning: start page is {} lines, over the 200-line budget.'.format(len(lines) - 1))

    def test_start_refuses_workspace_traversal(self):
        self.assertIn('workspace must be one folder name', self.launcher('start', '--workspace', '../outside', expected=1))

    def test_doctor_generated_seats_follow_personal_copy_and_removal(self):
        self.manifests()
        shipped = self.home / 'agents/architect.md'
        shipped.write_text('# Shipped fixture\n')
        personal = self.home / 'profile/agents/architect.md'
        personal.parent.mkdir(parents=True)
        for runtime, suffix in (('claude', '.md'), ('codex', '.toml')):
            folder = self.home / 'agents/generated' / runtime
            folder.mkdir(parents=True)
            file = folder / ('architect' + suffix)
            def build(source):
                text = 'Read ' + str(source) + ' fully before anything else.\n'
                file.write_text('developer_instructions = ' + json.dumps(text) + '\n'
                                if runtime == 'codex' else text)
            with self.subTest(runtime=runtime):
                build(shipped)
                self.assertIn('PASS generated runtime seat paths', self.launcher('doctor'))
                personal.write_text('# Personal fixture\n')
                stale = file.read_bytes(), file.stat().st_mtime_ns
                output = self.launcher('doctor', expected=1)
                self.assertIn('FAIL generated runtime seat paths', output)
                self.assertIn(str(personal), output)
                self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), stale)
                build(personal)
                self.assertIn('Doctor: 0 failed', self.launcher('doctor'))
                personal.unlink()
                self.assertIn('FAIL generated runtime seat paths', self.launcher('doctor', expected=1))
                build(shipped)
                self.assertIn('Doctor: 0 failed', self.launcher('doctor'))
                file.unlink()

    def test_doctor_generated_workspace_seat_uses_workspace_context(self):
        self.manifests()
        team = self.workspace / 'team'
        team.mkdir()
        seat = team / 'lead-cedar-shop.md'
        seat.write_text('# Workspace fixture\n')
        for runtime, suffix in (('claude', '.md'), ('codex', '.toml')):
            folder = self.home / 'agents/generated' / runtime
            folder.mkdir(parents=True)
            file = folder / ('lead-cedar-shop' + suffix)
            for source, expected in ((seat, 0), (self.home / 'agents' / seat.name, 1)):
                with self.subTest(runtime=runtime, source=source):
                    text = ('Read ' + str(source) + ' fully before anything else.\n'
                            'Read the client contract at ' + str(self.workspace / 'AGENTS.md') + '.\n')
                    file.write_text('developer_instructions = ' + json.dumps(text) + '\n'
                                    if runtime == 'codex' else text)
                    output = self.launcher('doctor', expected=expected)
                    self.assertIn(('PASS' if expected == 0 else 'FAIL') + ' generated runtime seat paths', output)
            file.unlink()

    def test_doctor_rejects_old_home_and_wrong_seat_paths(self):
        self.manifests()
        (self.home / 'agents/architect.md').write_text('# Fixture\n')
        for runtime, suffix in (('claude', '.md'), ('codex', '.toml')):
            folder = self.home / 'agents/generated' / runtime
            folder.mkdir(parents=True)
            file = folder / ('architect' + suffix)
            for source in (self.root / '.foxrun-next/agents/architect.md',
                           self.home / 'agents/chief-of-staff.md'):
                with self.subTest(runtime=runtime, source=source):
                    text = 'Read ' + str(source) + ' fully before anything else.\n'
                    file.write_text('developer_instructions = ' + json.dumps(text) + '\n'
                                    if runtime == 'codex' else text)
                    self.assertIn('FAIL generated runtime seat paths', self.launcher('doctor', expected=1))
            file.unlink()

    def test_doctor_rejects_runtime_without_one_seat_read(self):
        self.manifests()
        (self.home / 'agents/architect.md').write_text('# Fixture\n')
        folder = self.home / 'agents/generated/codex'
        folder.mkdir(parents=True)
        file = folder / 'architect.toml'
        for text in ('name = "architect"\n', 'developer_instructions = 4\n',
                     'developer_instructions = "No seat read"\n'):
            with self.subTest(text=text):
                file.write_text(text)
                self.assertIn('FAIL generated runtime seat paths', self.launcher('doctor', expected=1))

    def test_doctor_good_home_is_read_only(self):
        # fbf6a7c: an installed home always holds both lists, so a good home has them.
        self.manifests()
        before = self.snapshot()
        self.assertIn('Doctor: 0 failed', self.launcher('doctor'))
        self.assertEqual(before, self.snapshot())

    def test_doctor_home_without_lists_fails_read_only(self):
        # fbf6a7c: "An installed home always holds both lists." A home without them fails doctor.
        before = self.snapshot()
        output = self.launcher('doctor', expected=1)
        self.assertIn('FAIL required list base/product-manifest.tsv: missing file', output)
        self.assertIn('FAIL required list base/made-at-install.tsv: missing file', output)
        self.assertEqual(before, self.snapshot())

    def test_doctor_good_manifests(self):
        self.manifests()
        self.assertIn('PASS shipped foxrun.py', self.launcher('doctor'))

    def test_doctor_missing_config_and_folder_without_manifests(self):
        (self.home / 'config/tools.yaml').unlink()
        (self.home / 'wiki').rmdir()
        output = self.launcher('doctor', expected=1)
        self.assertIn('FAIL config/tools.yaml:', output)
        self.assertIn('FAIL folder wiki:', output)

    def test_start_refuses_config_symlink(self):
        file = self.home / 'config/person.json'
        saved = self.home / 'raw/person.json'
        file.rename(saved)
        file.symlink_to(saved)
        self.assertIn('symbolic link', self.launcher('start', expected=1))

    def test_doctor_changed_shipped_hash_same_size(self):
        self.manifests()
        script = self.home / 'foxrun.py'
        script.write_text(script.read_text().replace('Read the installed', 'Read The installed', 1))
        output = self.launcher('doctor', expected=1)
        self.assertIn('FAIL shipped foxrun.py: sha256 differs', output)

    def test_doctor_changed_shipped_size(self):
        self.manifests()
        with (self.home / 'foxrun.py').open('a') as stream:
            stream.write('\n# changed\n')
        self.assertIn('FAIL shipped foxrun.py: bytes differ', self.launcher('doctor', expected=1))

    def test_doctor_missing_shipped_file(self):
        self.manifests()
        body = (self.home / 'VERSION').read_bytes()
        self.table('product-manifest.tsv', ('path', 'bytes', 'sha256'),
                   [('VERSION', len(body), hashlib.sha256(body).hexdigest())])
        (self.home / 'VERSION').unlink()
        self.assertIn('FAIL shipped VERSION: missing file', self.launcher('doctor', expected=1))

    def test_doctor_broken_person_json(self):
        (self.home / 'config/person.json').write_text('{broken')
        self.assertIn('FAIL config/person.json:', self.launcher('doctor', expected=1))

    def test_doctor_invalid_person_shapes(self):
        for body in ('[]', '{}', '{"name":42}', '{"name":" "}'):
            with self.subTest(body=body):
                (self.home / 'config/person.json').write_text(body)
                self.assertIn('FAIL config/person.json:', self.launcher('doctor', expected=1))

    def test_doctor_missing_made_file(self):
        self.manifests()
        (self.workspace / 'STATE.md').unlink()
        self.assertIn('FAIL made portfolio/cedar-shop/STATE.md: missing file', self.launcher('doctor', expected=1))

    def test_doctor_manifest_paths_cannot_escape(self):
        self.table('product-manifest.tsv', ('path', 'bytes', 'sha256'), [('..//outside', 0, '0' * 64)])
        self.assertIn('unsafe path', self.launcher('doctor', expected=1))

    def test_doctor_symlink_refused(self):
        self.manifests()
        (self.home / 'raw').rmdir()
        (self.home / 'raw').symlink_to(self.workspace, target_is_directory=True)
        self.assertIn('FAIL made raw: symbolic link', self.launcher('doctor', expected=1))

    def test_doctor_malformed_manifests_and_bad_database(self):
        self.table('product-manifest.tsv', ('path', 'bytes', 'sha256'), [('wrong-columns',)])
        (self.home / 'data.db').write_bytes(b'not sqlite')
        output = self.launcher('doctor', expected=1)
        self.assertIn('FAIL base/product-manifest.tsv:', output)  # the list label carries base/ since fbf6a7c
        self.assertIn('FAIL data.db:', output)

    def test_version_from_installed_home(self):
        self.assertEqual('0.1.0\n', self.launcher('version'))

    def test_direct_installed_command_finds_its_home(self):
        env = dict(self.env)
        env.pop('FOXRUN_HOME')
        self.assertIn('Person: avery', self.launcher('start', env=env))

    def hook_input(self, hook):
        # 8a4199f (T302, standing seats): start hooks read native hook JSON with a session id.
        return json.dumps({'session_id': 'fixture-session', 'cwd': str(self.workspace),
                           'hook_event_name': 'SessionStart', 'source': 'compact' if hook == 'after-compact' else 'startup'})

    def test_each_hook_calls_start(self):
        # Native start hooks need the same holding task that the installer creates.
        self.run_command(PYTHON, str(self.home / 'events/session_run.py'), 'setup',
                         '--db', str(self.home / 'data.db'), '--create')
        for runtime in ('claude', 'codex'):
            for hook in ('session-start', 'after-compact', 'before-compact'):
                with self.subTest(runtime=runtime, hook=hook):
                    before = self.snapshot()
                    if hook == 'before-compact':
                        output = self.run_command(str(self.home / 'hooks' / runtime / hook), input='')
                        self.assertIn('No handoff yet in ', output)
                        self.assertEqual(before, self.snapshot())
                    else:
                        output = self.run_command(str(self.home / 'hooks' / runtime / hook), input=self.hook_input(hook))
                        # 7137c04 (T744): session-start then runs the session logger, which may add a stderr line.
                        context = json.loads(output.splitlines()[0])['hookSpecificOutput']['additionalContext']
                        self.assertIn('Person: avery', context)
                        self.assertIn('Workspace: cedar-shop', context)

    def test_hooks_default_to_empty_home_foxrun(self):
        self.run_command(PYTHON, str(self.home / 'events/session_run.py'), 'setup',
                         '--db', str(self.home / 'data.db'), '--create')
        default = self.root / 'empty-home/.foxrun'
        self.home.rename(default)
        self.home = default
        env = dict(self.env)
        env.pop('FOXRUN_HOME')
        for runtime in ('claude', 'codex'):
            # 8a4199f: the hook reads native hook JSON with a session id.
            self.assertIn('Person: avery', self.run_command(str(default / 'hooks' / runtime / 'session-start'), env=env,
                                                            input=self.hook_input('session-start')))

    def test_legacy_hooks_preserve_event_calls(self):
        stub = self.home / 'events/session_run.py'
        stub.parent.mkdir(exist_ok=True)
        # 8a4199f: the start script restores the seat first and keeps the logger's output off the hook output,
        # so the stub records its call in a file.
        calls = self.root / 'event-calls.txt'
        stub.write_text('import sys\nopen({!r}, "a").write("EVENT " + " ".join(sys.argv[1:]) + "\\n")\n'.format(str(calls)))
        for runtime in ('claude', 'codex'):
            for event in ('start', 'end'):
                self.run_command(str(self.home / 'hooks' / runtime / (runtime + '_session_' + event + '.sh')),
                                 input=self.hook_input('session-start'))
                self.assertIn('EVENT hook-{} --runtime {}'.format(event, runtime), calls.read_text())

    def test_state_show_no_writes(self):
        # The STATE.md renderer is built (b52bd2f, 10.13: words build and show); show reads and writes nothing.
        before = self.snapshot()
        self.assertIn('# State: cedar-shop', self.run_command(PYTHON, str(self.home / 'memory/state.py'), 'show', '--workspace', 'cedar-shop'))
        self.assertEqual(before, self.snapshot())

    def test_memory_checks_missing_inputs(self):
        self.fresh_dream()
        output = self.run_command(PYTHON, str(self.home / 'memory/check.py'))
        self.assertIn('SKIP links:', output)
        self.assertIn('SKIP handoff:', output)
        self.assertIn('Memory checks: 0 failed', output)

    def test_memory_links_existing_code_reports_failure(self):
        self.fresh_dream()
        pages = self.workspace / 'outputs/workspace-pages'
        pages.mkdir(parents=True)
        (pages / 'wiki.json').write_text(json.dumps({'pages': ['wiki/page.md'], 'answers': []}))
        wiki = self.workspace / 'wiki'
        wiki.mkdir()
        (wiki / 'page.md').write_text('[bad](missing.md)\n')
        output = self.run_command(PYTHON, str(self.home / 'memory/check.py'), expected=1)
        self.assertIn('FAIL links', output)
        self.assertIn('Memory checks: 1 failed', output)

    def test_memory_links_run_on_wiki_pages_without_a_manifest(self):
        self.fresh_dream()
        wiki = self.workspace / 'wiki/concepts'
        wiki.mkdir(parents=True)
        (wiki / 'page.md').write_text('[bad](missing.md)\n')
        output = self.run_command(PYTHON, str(self.home / 'memory/check.py'), expected=1)
        self.assertNotIn('SKIP links:', output)
        self.assertIn('FAIL links', output)

    def test_memory_handoff_finds_newest_handoff_with_a_transcript(self):
        self.fresh_dream()
        session = '0123456789abc-fixture'
        handoffs = self.workspace / 'history/handoffs'
        handoffs.mkdir(parents=True)
        (handoffs / '2026-10-18-001-old.md').write_text('---\ntype: handoff\nsession: ' + session + '\n---\n# Old\n')
        (handoffs / '2026-10-19-001-gone.md').write_text('---\ntype: handoff\nsession: fedcba9876543-gone\n---\n# Gone\n')
        (handoffs / '2026-10-19-001-gone.md.coverage.md').write_text('# Coverage\n')
        transcripts = self.root / 'empty-home/.claude/projects/fixture'
        transcripts.mkdir(parents=True)
        (transcripts / (session + '.jsonl')).write_text('')
        output = self.run_command(PYTHON, str(self.home / 'memory/check.py'))
        self.assertNotIn('SKIP handoff:', output)
        self.assertIn('handoff check: ' + str((handoffs / '2026-10-18-001-old.md').resolve()), output)
        self.assertIn('coverage ids=100% files=100% gaps=0', output)
        self.assertTrue((handoffs / '2026-10-18-001-old.md.coverage.md').is_file())

    def test_handoff_existing_check_runs_inside_home(self):
        transcript = self.home / 'raw/session.jsonl'
        transcript.write_text('')
        handoff = self.workspace / 'history/handoffs/handoff.md'
        handoff.parent.mkdir(parents=True)
        handoff.write_text('# Handoff\nNo work.\n')
        env = dict(self.env, FOXRUN_TRANSCRIPT=str(transcript), FOXRUN_HANDOFF=str(handoff))
        output = self.run_command(str(self.home / 'hooks/claude/before-compact'), env=env,
                                  input=json.dumps({'cwd': str(self.workspace), 'transcript_path': str(transcript), 'session_id': 'fixture'}))
        self.assertIn('coverage ids=100% files=100% gaps=0', output)
        self.assertTrue((self.home / 'runs/handoff-check/extract.md').is_file())
        self.assertTrue(handoff.with_name('handoff.md.coverage.md').is_file())

    def test_memory_refuses_input_outside_install(self):
        output = self.run_command(PYTHON, str(self.home / 'memory/check.py'), '--handoff-only',
                                  '--transcript', str(self.root / 'outside.jsonl'), '--handoff', str(self.workspace / 'STATE.md'), expected=1)
        self.assertIn('path is outside the install', output)

    def test_write_harness_blocks_file_and_database_escape(self):
        for statement in ('open({!r}, "w").write("bad")', 'import sqlite3; sqlite3.connect({!r})'):
            outside = ROOT.parent / 'write-harness-escape'
            output = self.run_command(PYTHON, '-c', statement.format(str(outside)), expected=1)
            self.assertIn('WRITE OUTSIDE TEMP HOME:', output)
            self.assertFalse(outside.exists())


class ProcessLookupTests(unittest.TestCase):
    def test_unavailable_process_inspection_does_not_bind_a_seat(self):
        from unittest import mock
        from work import standing
        for error in (PermissionError('process inspection denied'), FileNotFoundError('ps unavailable'),
                      subprocess.TimeoutExpired('/bin/ps', 3)):
            with self.subTest(error=type(error).__name__):
                runner = mock.Mock(side_effect=error)
                self.assertIsNone(standing.ancestry_launch('codex', runner=runner, pid=42))
                runner.assert_called_once()

    def test_nearest_native_process_still_owns_the_launch(self):
        from unittest import mock
        from work import standing
        token = 'a' * 32
        runner = mock.Mock(return_value=subprocess.CompletedProcess(
            [], 0, '1 codex FOXRUN_STANDING=' + token))
        self.assertEqual(standing.ancestry_launch('codex', runner=runner, pid=42), token)
        runner.assert_called_once()

    def test_ambiguous_launch_tokens_still_fail(self):
        from unittest import mock
        from work import standing
        runner = mock.Mock(return_value=subprocess.CompletedProcess(
            [], 0, '1 codex FOXRUN_STANDING=' + 'a' * 32 + ' FOXRUN_STANDING=' + 'b' * 32))
        with self.assertRaisesRegex(ValueError, 'ambiguous standing launch tokens'):
            standing.ancestry_launch('codex', runner=runner, pid=42)


if __name__ == '__main__':
    unittest.main()
