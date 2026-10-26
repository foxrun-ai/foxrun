#!/usr/bin/env python3
"""Launcher acceptance cases; every writable home is below FOXRUN_TEST_ROOT."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
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
    # T742: the hook's silent event logger writes only to /dev/null as an output sink.
    if target == Path('/dev/null'):
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
        for name in ('catalog.yaml', 'models.yaml', 'modules.yaml', 'tools.yaml'):
            (self.home / 'config' / name).write_text((ROOT / 'config/models.yaml').read_text() if name == 'models.yaml' else 'format: 1\n')
        (self.home / 'VERSION').write_text('0.1.0\n')
        (self.home / 'AGENTS.md').write_text('# System rules\n')
        for file in ('AGENTS.md', 'RESOLVER.md'):
            (self.workspace / file).write_text('# Workspace rules\n')
        (self.workspace / 'STATE.md').write_text('# Cedar Shop state\nNo previous runs.\n')
        # Copy only command dependencies. Tests exercise actual installed paths.
        for folder in ('base', 'work', 'memory', 'hooks', 'events', 'decisions'):
            shutil.copytree(ROOT / folder, self.home / folder, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'foxrun.py', self.home / 'foxrun.py')
        # base/ of an installed home holds the two real lists. A test home starts with none.
        for name in ('product-manifest.tsv', 'made-at-install.tsv'):
            if (self.home / 'base' / name).exists():
                (self.home / 'base' / name).unlink()
        self.run_command(PYTHON, str(self.home / 'base/build_database.py'), str(self.home / 'data.db'),
                         '--modules', 'work', '--by', 'test')
        # fbf6a7c: memory/check.py now checks dream health; this home has a fresh passing dream.
        dream = self.home / 'runs/fixture-dream/manifest.json'
        dream.parent.mkdir(parents=True)
        moment = datetime.now(timezone.utc).isoformat()
        dream.write_text(json.dumps({'job': 'dream', 'word': 'run', 'started_at': moment,
                                     'finished_at': moment, 'result': 'pass'}) + '\n')

    def run_command(self, *command, expected=0, env=None, input=None):
        result = subprocess.run(command, cwd=self.root, env=env or self.env, input=input,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, expected, result.stdout)
        return result.stdout

    def launcher(self, *args, expected=0, env=None):
        return self.run_command(PYTHON, str(self.home / 'foxrun.py'), *args, expected=expected, env=env)

    def table(self, name, header, entries):
        # The two lists sit in base/. The launcher reads them only there.
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

    def snapshot(self):
        return {str(p.relative_to(self.root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_start_person_workspace_tasks_and_state(self):
        output = self.run_command(PYTHON, str(self.home / 'work/work.py'), '--db', str(self.home / 'data.db'),
                                 '--receipt-root', str(self.workspace), 'create', '--title', 'Check stock', '--by', 'avery',
                                 # g-every-task-carries-the-six-fields-a-spec-is-a-parent-task (404941a).
                                 '--problem', 'Stock needs a check', '--job-when', 'When stock arrives',
                                 '--job-want', 'I want a stock task', '--job-so', 'So I can check it',
                                 '--body', 'Check stock', '--acceptance', 'The task appears',
                                 '--context', 'Fixture stock', '--where', str(self.workspace / 'STATE.md'))
        self.assertEqual('T1\n', output)
        before_db = hashlib.sha256((self.home / 'data.db').read_bytes()).hexdigest()
        output = self.launcher('start', '--workspace', 'cedar-shop')
        self.assertIn('Person: avery', output)
        self.assertIn('Workspace: cedar-shop', output)
        self.assertIn('Check stock [todo]', output)
        # fbf6a7c: start rebuilds STATE.md and saves a run page.
        self.assertIn('# State: cedar-shop', output)
        # fbf6a7c: the start page links workspace contracts relative to its page.
        self.assertIn('[`RESOLVER.md`](RESOLVER.md)', output)
        self.assertEqual(before_db, hashlib.sha256((self.home / 'data.db').read_bytes()).hexdigest())

    def test_start_fresh_home_no_tasks(self):
        output = self.launcher('start')
        self.assertIn('Workspace: cedar-shop', output)
        self.assertIn('  none', output)

    def test_start_infers_installer_workspace(self):
        (self.home / 'config/person.json').write_text('{"name":"avery"}')
        self.assertIn('Workspace: cedar-shop', self.launcher('start'))

    def test_start_missing_state_and_database_reports_unbuilt(self):
        (self.workspace / 'STATE.md').unlink()
        (self.home / 'data.db').unlink()
        # fbf6a7c: the row-built start page requires a tracker and reports its absence.
        output = self.launcher('start', expected=1)
        self.assertIn('FAIL start: unable to open database file', output)

    def test_start_refuses_workspace_traversal(self):
        self.assertIn('workspace must be one folder name', self.launcher('start', '--workspace', '../outside', expected=1))

    def test_doctor_home_without_lists_fails_and_is_read_only(self):
        before = self.snapshot()
        output = self.launcher('doctor', expected=1)
        self.assertIn('FAIL required list base/product-manifest.tsv: missing file', output)
        self.assertIn('FAIL required list base/made-at-install.tsv: missing file', output)
        self.assertIn('Doctor: 2 failed', output)
        self.assertEqual(before, self.snapshot())

    def test_doctor_good_home_with_lists_is_read_only(self):
        self.manifests()
        before = self.snapshot()
        self.assertIn('Doctor: 0 failed', self.launcher('doctor'))
        self.assertEqual(before, self.snapshot())

    def test_doctor_workspace_skill_sources_are_checked(self):
        self.manifests()
        source = self.workspace / 'skills/creator-drafting/SKILL.md'
        source.parent.mkdir(parents=True)
        from base.agent_catalog import model_policy
        policy = model_policy(self.home)
        source.write_text(policy['allowed'][0])
        output = self.launcher('doctor', expected=1)
        self.assertIn(str(source), output)
        self.assertIn('FAIL model policy and literals:', output)
        source.write_text('tier: work')
        self.assertIn('Doctor: 0 failed', self.launcher('doctor'))

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
        self.assertIn('FAIL base/product-manifest.tsv:', output)
        self.assertIn('FAIL data.db:', output)

    def test_version_from_installed_home(self):
        self.assertEqual('0.1.0\n', self.launcher('version'))

    def test_direct_installed_command_finds_its_home(self):
        env = dict(self.env)
        env.pop('FOXRUN_HOME')
        self.assertIn('Person: avery', self.launcher('start', env=env))

    def hook_input(self, event='SessionStart'):
        return json.dumps({'session_id': 'fixture-session', 'cwd': str(self.workspace),
                           'hook_event_name': event, 'source': 'startup'})

    def test_each_hook_calls_start(self):
        self.run_command(PYTHON, str(self.home / 'events/session_run.py'), 'setup',
                         '--db', str(self.home / 'data.db'), '--create')
        for runtime in ('claude', 'codex'):
            for hook in ('session-start', 'after-compact', 'before-compact'):
                with self.subTest(runtime=runtime, hook=hook):
                    # fbf6a7c: native hooks pass a JSON object; start writes fresh state in the fixture.
                    payload = self.hook_input()
                    output = self.run_command(str(self.home / 'hooks' / runtime / hook), input=payload)
                    if hook == 'before-compact':
                        self.assertIn('No handoff yet in ', output)
                    elif hook == 'after-compact':
                        # The current hook returns a structured boot page after compaction.
                        self.assertIn('Boot Order', json.loads(output)['hookSpecificOutput']['additionalContext'])
                    else:
                        self.assertIn('Person: avery', output)
                        self.assertIn('Workspace: cedar-shop', output)
                    if hook == 'session-start':
                        self.assertTrue((self.home / 'STATE.md').is_file())

    def test_hooks_default_to_empty_home_foxrun(self):
        self.run_command(PYTHON, str(self.home / 'events/session_run.py'), 'setup',
                         '--db', str(self.home / 'data.db'), '--create')
        default = self.root / 'empty-home/.foxrun'
        self.home.rename(default)
        self.home = default
        env = dict(self.env)
        env.pop('FOXRUN_HOME')
        for runtime in ('claude', 'codex'):
            payload = self.hook_input()
            self.assertIn('Person: avery', self.run_command(str(default / 'hooks' / runtime / 'session-start'), env=env, input=payload))

    def test_legacy_hooks_preserve_event_calls(self):
        stub = self.home / 'events/session_run.py'
        stub.parent.mkdir(exist_ok=True)
        # 8a4199f: hooks keep stdout for context; capture the event call in this temp home.
        log = self.home / 'runs/event-calls.log'
        stub.write_text('from pathlib import Path\nimport sys\n'
                        'Path(__file__).resolve().parents[1].joinpath("runs/event-calls.log")'
                        '.open("a").write("EVENT " + " ".join(sys.argv[1:]) + "\\n")\n')
        for runtime in ('claude', 'codex'):
            for event in ('start', 'end'):
                payload = self.hook_input('SessionStart' if event == 'start' else 'SessionEnd')
                output = self.run_command(str(self.home / 'hooks' / runtime / (runtime + '_session_' + event + '.sh')), input=payload)
                self.assertTrue(log.is_file(), output)
                self.assertIn('EVENT hook-{} --runtime {}'.format(event, runtime), log.read_text())

    def test_state_show_prints_the_readout_and_writes_nothing(self):
        before = self.snapshot()
        output = self.run_command(PYTHON, str(self.home / 'memory/state.py'), 'show', '--workspace', 'cedar-shop')
        self.assertIn('# State: system', output)
        self.assertIn('# State: cedar-shop', output)
        self.assertEqual(before, self.snapshot())

    def test_memory_checks_missing_inputs(self):
        output = self.run_command(PYTHON, str(self.home / 'memory/check.py'))
        self.assertIn('SKIP links:', output)
        self.assertIn('SKIP handoff:', output)
        self.assertIn('Memory checks: 0 failed', output)

    def test_memory_links_existing_code_reports_failure(self):
        pages = self.workspace / 'outputs/workspace-pages'
        pages.mkdir(parents=True)
        (pages / 'wiki.json').write_text(json.dumps({'pages': ['wiki/page.md'], 'answers': []}))
        wiki = self.workspace / 'wiki'
        wiki.mkdir()
        (wiki / 'page.md').write_text('[bad](missing.md)\n')
        output = self.run_command(PYTHON, str(self.home / 'memory/check.py'), expected=1)
        self.assertIn('FAIL links', output)
        self.assertIn('Memory checks: 1 failed', output)

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


if __name__ == '__main__':
    unittest.main()


class ModelPolicyDoctorTests(unittest.TestCase):
    def setUp(self):
        self.portfolio_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.portfolio_temp.cleanup)
        self.portfolio = Path(self.portfolio_temp.name)
        patched = patch('base.paths.portfolio', return_value=self.portfolio)
        patched.start()
        self.addCleanup(patched.stop)

    def test_policy_maps_roles_and_rejects_unallowed_or_ambiguous_values(self):
        import copy
        from base.agent_catalog import model_policy, resolve_model
        original = model_policy(ROOT)
        self.assertEqual(resolve_model('code', 'codex', ROOT), original['tiers']['cheap']['codex']['model'])
        self.assertNotEqual(resolve_model('work', 'codex', ROOT), resolve_model('code', 'codex', ROOT))
        with self.assertRaises(ValueError):
            resolve_model('code', 'hermes', ROOT)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config').mkdir()
            for mutation in ('banned', 'unknown', 'effort', 'overlap', 'missing-runtime'):
                changed = copy.deepcopy(original)
                if mutation == 'banned': changed['tiers']['code']['codex']['model'] = original['banned'][0]
                if mutation == 'unknown': changed['tiers']['code']['codex']['model'] = 'unlisted-model'
                if mutation == 'effort': changed['tiers']['code']['codex']['effort'] = 'high'
                if mutation == 'overlap': changed['banned'].append(original['allowed'][0])
                if mutation == 'missing-runtime': changed['tiers']['work'].pop('hermes')
                (root / 'config/models.yaml').write_text(json.dumps(changed))
                with self.subTest(mutation=mutation), self.assertRaises(ValueError): model_policy(root)

    def test_literal_check_covers_code_config_squads_workflows_skills_and_held_seats(self):
        from base.agent_catalog import model_policy, model_id_hits, check_models
        policy = model_policy(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config').mkdir()
            (root / 'config/models.yaml').write_text(json.dumps(policy))
            known, banned = policy['allowed'][0], policy['banned'][0]
            spots = ['base/call.py', 'config/other.yaml', 'config/squads/team.yaml',
                     'skillwright/workflows/example.yaml', 'skills/example/SKILL.md',
                     'skills/example/models.yaml', 'agents/chief.md', 'AGENTS.md', 'CLAUDE.md', 'soul.md']
            for spot in spots:
                target = root / spot
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(known + '\n' + banned + '\n' + known + '-unlisted\n')
            for part in ['history', 'raw', 'archive', 'runs']:
                target = root / part / 'evidence.txt'
                target.parent.mkdir()
                target.write_text(known)
            hits = model_id_hits(root, policy)
            self.assertEqual(len(hits), len(spots) * 3)
            self.assertEqual({str(Path(h['path']).relative_to(root)) for h in hits}, set(spots))
            with self.assertRaisesRegex(ValueError, 'model IDs outside'): check_models(root)
            for spot in spots: (root / spot).write_text('tier: code\n')
            self.assertEqual(check_models(root), policy)
            extra = root / 'extra'
            (extra / 'config').mkdir(parents=True)
            (extra / 'config/models.yaml').write_text(known)
            with self.assertRaisesRegex(ValueError, 'model IDs outside'): check_models(root, [extra])


    def test_model_scope_skips_only_declared_imports_and_evidence(self):
        from base.agent_catalog import model_policy, model_id_hits
        policy = model_policy(ROOT)
        model = policy['allowed'][0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def put(rel, text=model):
                file = root / rel
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(text)
            for folder in ('backups', 'archive', 'history', 'raw', 'run', 'runs'):
                put(folder + '/literal.txt')
            for name in ('vault-.agents-skills-gstack', 'vault-.claude-skills-gstack', 'hermes-docs'):
                put('skills/' + name + '/SKILL.md')
            put('skills/browse/references/gstack-runtime/engine.py')
            put('skills/frontmatter/SKILL.md', '---\nname: frontmatter\nimported: true\n---\n' + model)
            put('skills/vendored/SKILL.md', '---\nmetadata:\n  source: vendored upstream\n---\n' + model)
            put('skills/block-scalar/SKILL.md', '---\nname: block-scalar\ndescription: |\n  Outside payload.\nimported: true\n---\n' + model)
            put('skills/local-manifest/SKILL.md')
            put('skills/local-manifest/manifest.json', json.dumps({'vendored': True}))
            put('skills/global-manifest/SKILL.md')
            put('config/manifest.json', json.dumps({'skills': [{'name': 'global-manifest', 'source': 'imported'}]}))
            owned = ['skills/own/SKILL.md', 'skills/browse/own.py', 'base/own.py',
                     'skills/mention/SKILL.md', 'docs/SCHEMA.md', 'skills/own-block/SKILL.md',
                     'skills/prose/SKILL.md']
            for rel in owned:
                put(rel, 'Instructions mention a vendored copy.\n' + model)
            put('skills/prose/SKILL.md', 'Imported from outside.\n' + model)
            put('skills/own-block/SKILL.md', '---\nname: own-block\ndescription: |\n  Instructions mention a vendored copy.\n---\n' + model)
            notes = []
            hits = model_id_hits(root, policy, source_roots=(), exemptions=notes)
            self.assertEqual({str(Path(h['path']).relative_to(root)) for h in hits}, set(owned))
            self.assertTrue(any('imported' in n['reason'] for n in notes))
            # An import marker on one skill does not exempt its siblings.
            (root / 'skills/frontmatter/SKILL.md').write_text(model)
            self.assertIn(str(root / 'skills/frontmatter/SKILL.md'),
                          {h['path'] for h in model_id_hits(root, policy, source_roots=())})

    def test_model_scope_default_sources_are_the_install_own_folders(self):
        from base.agent_catalog import model_policy, model_id_hits
        policy = model_policy(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            home, portfolio = Path(temp) / 'home', self.portfolio
            registry = home / 'config/models.yaml'
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(policy))
            (home / 'skills/example').mkdir(parents=True)
            (home / 'skills/example/SKILL.md').write_text(policy['allowed'][0])
            # Another person's product folder never counts as a release source.
            other = portfolio / 'foxrun-hq/src/skillwright/skills/example'
            other.mkdir(parents=True)
            (other / 'SKILL.md').write_text('tier: code')
            self.assertEqual(len(model_id_hits(home, policy, registry)), 1)
            own = portfolio / 'skillwright/skills/example'
            own.mkdir(parents=True)
            (own / 'SKILL.md').write_text('tier: code')
            self.assertEqual(model_id_hits(home, policy, registry), [])

    def test_model_scope_pending_release_requires_clean_preferred_source(self):
        from base.agent_catalog import model_policy, model_id_hits
        policy = model_policy(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home, sources, product = base / 'home', base / 'person/skills', base / 'product/skills'
            registry = home / 'config/models.yaml'
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(policy))
            for root in (home / 'skills', home / 'skillwright/skills', sources, product):
                (root / 'example').mkdir(parents=True)
                (root / 'example/SKILL.md').write_text(policy['allowed'][0])
            source = sources / 'example/SKILL.md'
            product_source = product / 'example/SKILL.md'
            product_source.write_text('tier: code')
            def scan():
                notes = []
                hits = model_id_hits(home, policy, registry, [sources, product], notes)
                return hits, notes
            self.assertEqual(len(scan()[0]), 2)  # A clean lower-priority copy cannot mask dirty personal source.
            source.write_text('tier: code')
            hits, notes = scan()
            self.assertEqual(hits, [])
            self.assertEqual(len([n for n in notes if 'pending full release' in n['reason']]), 2)
            source.write_text(policy['banned'][0])
            self.assertEqual(len(scan()[0]), 2)  # The exemption ends as soon as source regresses.
            source.unlink()
            product_source.unlink()
            self.assertEqual(len(scan()[0]), 2)  # A missing source cannot qualify.
            source.write_text('tier: code')
            for shelf in (home / 'skills', home / 'skillwright/skills'):
                (shelf / 'example/SKILL.md').write_text(source.read_text())
            self.assertEqual(scan(), ([], []))  # Full release clears the temporary exemptions.

    def test_model_scope_generated_page_exemption_has_exact_owner(self):
        from base.agent_catalog import MODEL_SCAN_EXEMPTIONS, model_policy, model_id_hits
        policy = model_policy(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            for rel in MODEL_SCAN_EXEMPTIONS['generated']:
                file = home / rel
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(policy['allowed'][0])
            notes = []
            self.assertEqual(model_id_hits(home, policy, source_roots=(), exemptions=notes), [])
            self.assertEqual(len(notes), len(MODEL_SCAN_EXEMPTIONS['generated']))
            self.assertTrue(any('object_type=runs, field=model' in n['reason'] for n in notes))
            (home / 'SCHEMA.md').rename(home / 'own.md')
            self.assertEqual(len(model_id_hits(home, policy, source_roots=())), 1)

    def test_model_scope_home_data_exemptions_do_not_hide_nested_source(self):
        from base.agent_catalog import model_policy, model_id_hits
        policy = model_policy(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = self.portfolio / 'cedar-shop'
            workspace.mkdir()
            (workspace / 'AGENTS.md').write_text('# Workspace')
            nested = []
            for root in (home, self.portfolio, workspace):
                for folder in ('state', 'run', 'runs'):
                    evidence = root / folder / 'evidence.txt'
                    evidence.parent.mkdir(parents=True)
                    evidence.write_text(policy['allowed'][0])
                    source = root / 'base/templates' / folder / 'source.py'
                    source.parent.mkdir(parents=True)
                    source.write_text(policy['allowed'][0])
                    nested.append(str(source))
            registry = home / 'config/models.yaml'
            hits = []
            for root in (home, self.portfolio):
                hits.extend(model_id_hits(root, policy, registry, source_roots=()))
            self.assertEqual({h['path'] for h in hits}, set(nested))

    def test_doctor_checks_workspace_skill_source_beside_generated_inventory(self):
        from base.agent_catalog import MODEL_SCAN_EXEMPTIONS, model_policy, check_models
        policy = model_policy(ROOT)
        # No workspace's generated inventory page is exempt by name.
        self.assertFalse([rel for rel in MODEL_SCAN_EXEMPTIONS['generated'] if rel.startswith('workspaces/')])
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            registry = home / 'config/models.yaml'
            registry.parent.mkdir()
            registry.write_text(json.dumps(policy))
            page = home / 'workspaces/cedar-shop/SKILLS.md'
            page.parent.mkdir(parents=True)
            page.write_text(policy['allowed'][0])
            workspace = self.portfolio / 'cedar-shop'
            source = workspace / 'skills/drafting/SKILL.md'
            source.parent.mkdir(parents=True)
            (workspace / 'AGENTS.md').write_text('# Workspace')
            source.write_text(policy['allowed'][0])
            with self.assertRaisesRegex(ValueError, 'drafting/SKILL.md'):
                check_models(home)
            source.write_text('tier: work')
            with self.assertRaisesRegex(ValueError, 'cedar-shop/SKILLS.md'):
                check_models(home)
            page.write_text('tier: work')
            self.assertEqual(check_models(home), policy)
