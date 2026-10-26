#!/usr/bin/env python3
"""Installer acceptance: fresh HOME for every test, no live runtime or network."""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[2]
TREE = Path(os.environ.get('FOXRUN_PRODUCT_TREE', str(HERE))).resolve()
RUN = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TREE))
PYTHON = '/usr/bin/python3'
try:
    import install
except ModuleNotFoundError as error:
    if error.name != 'install':
        raise
    install = None

from base.tests.privacy_support import account_name
import pwd
OWNER = re.compile('|'.join(re.escape(value) for value in (account_name(), pwd.getpwuid(os.getuid()).pw_name)), re.I)


@unittest.skipIf(install is None, 'Set FOXRUN_PRODUCT_TREE to the product checkout for installer checks.')
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

    def command(self, *extra, input=None, home=None, portfolio=None, runtime_home=True):
        # A test with no --runtime-home seeds HOME itself and checks it.
        if runtime_home:
            self.assertEqual(list(self.user.iterdir()), [], 'HOME must start empty')
        trial = ['--runtime-home', str(self.root / 'trial-runtime')] if runtime_home else []
        return subprocess.run([PYTHON,'-B',str(TREE / 'install.py'),
                               '--home',str(home if home is not None else self.home),
                               '--portfolio',str(portfolio if portfolio is not None else self.portfolio),
                               # T351 (6214220): install turns on the real nightly launchd job; a test never does.
                               '--no-schedule',
                               *trial,
                               *extra], cwd=str(TREE),env=self.env,input=input,text=True,capture_output=True)

    def run_tool(self, path, *args, env=None):
        return subprocess.run([PYTHON,'-B',str(path),*args],cwd=str(self.root),
                              env=env or self.env,text=True,capture_output=True)

    def runtime_files(self, runtime):
        expected = set()
        skills = ('chief', 'architect', 'keeper', 'toolsmith', 'skillwright', 'scout', 'adviser')
        prefixes = ['agents/skills'] + [name + '/skills' if len(runtime) > 1 else 'skills' for name in runtime]
        for prefix in prefixes:
            for skill in skills:
                expected.add(prefix + '/' + skill + '/SKILL.md')
                replay = 'read-seat-boot' if skill in ('chief', 'architect') else 'read-purpose'
                expected.add(prefix + '/' + skill + '/replays/' + replay + '.json')
            for name in install.PRODUCT_SKILLS:
                source = TREE / 'skillwright/skills' / name
                expected.update(prefix + '/' + name + '/' + p.relative_to(source).as_posix()
                                for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        expected.update((name + '/' if len(runtime) > 1 else '') +
                        ('CLAUDE.md' if name == 'claude' else 'AGENTS.md') for name in runtime)
        return expected

    def assert_install(self, result, person='person', workspace='my-workspace', home_files=frozenset()):
        self.assertEqual(result.returncode,0,result.stdout + result.stderr)
        self.assertIn('Install time:', result.stdout)
        self.assertIn('Next command: python3 ' + str(self.home / 'foxrun.py') + ' start',result.stdout)
        self.assertIn('fresh template',result.stdout)
        config = json.loads((self.home / 'config/person.json').read_text())
        self.assertEqual(config['name'],person)
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
        self.assertFalse((self.home / 'agents/generated/hermes').exists())
        self.assertFalse(any(p.name=='not-shipped' for p in self.home.rglob('*')))
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
                # The source record names the product folder install ran from, a path on the person's own machine.
                if path == record:
                    text = text.replace(str(script.resolve().parent), '<source-tree>')
                if OWNER.search(text):
                    hits.append(str(path.relative_to(base)))
        self.assertEqual(hits,[])
        # With --runtime-home, install writes nothing into HOME. With none, it writes exactly home_files there.
        self.assertEqual({p.relative_to(self.user).as_posix() for p in self.user.rglob('*') if p.is_file()},
                         set(home_files), 'HOME must hold exactly the files this install writes there')
        runtime = ('claude', 'codex') if config['runtime'] == 'both' else (config['runtime'],)
        if result.args.count('--runtime-home') == 1:
            trial = Path(result.args[result.args.index('--runtime-home') + 1])
            self.assertEqual({p.relative_to(trial).as_posix() for p in trial.rglob('*') if p.is_file()},
                             self.runtime_files(runtime))

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

    def test_default_install_writes_its_runtime_files_into_home(self):
        # No --runtime-home and no --hookup: install writes the runtime contracts and the skill
        # shelves into HOME, and nothing else there. The person's own contract text survives.
        for key in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME'):
            self.env.pop(key, None)
        contract = self.user / '.claude/CLAUDE.md'
        contract.parent.mkdir()
        mine = b'# My own rules (labeled fake)\r\nKeep this line.\r\n'
        contract.write_bytes(mine)
        result = self.command('--yes', runtime_home=False)
        self.assertNotIn('--runtime-home', result.args)
        expected = {'.' + name for name in self.runtime_files(('claude', 'codex'))}
        self.assertTrue({'.claude/CLAUDE.md', '.codex/AGENTS.md'} <= expected)
        self.assertTrue(any(name.startswith('.agents/skills/') for name in expected))
        self.assert_install(result, home_files=expected)
        raw = contract.read_bytes()
        self.assertTrue(raw.startswith(mine), raw[:200])
        self.assertEqual(raw.count(b'<!-- foxrun:begin -->'), 1)
        self.assertFalse((self.user / '.claude/settings.json').exists() or (self.user / '.codex/hooks.json').exists())

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
        expected={'claude/settings.json','codex/hooks.json'}
        # T741 (5e3bf09): the installer also trusts its Codex hooks in codex/config.toml.
        self.assertEqual({p.relative_to(runtime).as_posix() for p in runtime.rglob('*') if p.is_file()},
                         expected | {'codex/config.toml'} | self.runtime_files(('claude', 'codex')))
        for name in expected:
            hooks=json.loads((runtime/name).read_text())['hooks']
            # T744 (7137c04): a SessionEnd hook closes the run that session-start logs.
            self.assertEqual(set(hooks),{'SessionStart','PreCompact','SessionEnd'})
            # The current runtime contract loads rules; startup and compact run their own hook.
            self.assertEqual([entry['matcher'] for entry in hooks['SessionStart']], ['startup|resume', 'compact'])
            self.assertNotIn('start-rules', json.dumps(hooks))
            for entry, script in zip(hooks['SessionStart'], ('session-start', 'after-compact')):
                self.assertEqual([hook['type'] for hook in entry['hooks']], ['command'])
                self.assertTrue(entry['hooks'][0]['command'].endswith('/' + name.split('/')[0] + '/' + script))

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

if __name__=='__main__':
    unittest.main()
