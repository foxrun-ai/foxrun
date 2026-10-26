"""T882: update a committed older install, never a newly installed current tree."""
import csv
from contextlib import closing, contextmanager
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

TREE = Path(__file__).resolve().parents[1]
if not (TREE / 'install.py').is_file():
    raise unittest.SkipTest('update acceptance needs the source installer and git history')
sys.path.insert(0, str(TREE))
import install
import update

# The last committed install before the update command existed (T873).
OLDER = '7e836f09'


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob('*') if p.is_file()}


def refresh_row(tree, name):
    path = tree / 'product-manifest.tsv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    raw = (tree / name).read_bytes()
    row = update.file_row(name, raw)
    rows = [r for r in rows if r['path'] != name] + [row]
    path.write_bytes(update.table_bytes(sorted(rows, key=lambda r: r['path'])))


def drop_row(tree, name):
    path = tree / 'product-manifest.tsv'
    with path.open(newline='') as stream:
        rows = [r for r in csv.DictReader(stream, delimiter='\t') if r['path'] != name]
    path.write_bytes(update.table_bytes(rows))


def home_rows(home):
    with (home / 'base/product-manifest.tsv').open(newline='') as stream:
        return {row['path']: row for row in csv.DictReader(stream, delimiter='\t')}


def fake_accounts(folder, gid, passwd, group, directory=(), file_only=(), directory_users=()):
    """Write fake /etc/passwd and /etc/group files into folder, and return stand-ins for pwd and grp.
    Lines may use {uid} (this user), {other} (another account), {gid}, and {next} (gid + 1).
    directory adds group entries that only the system lookup sees, as LDAP does, and
    directory_users adds passwd entries that only the system lookup sees. file_only adds
    group lines that only the local file holds, so each check is proved alone. The system
    lookup names this user avery. All names are labeled fake."""
    import os, types
    from pathlib import Path
    names = dict(uid=os.getuid(), other=os.getuid() + 1, gid=gid, next=gid + 1)
    paths = (Path(folder) / 'passwd', Path(folder) / 'group')
    for path, lines in zip(paths, (passwd, group)):
        path.write_text(''.join(line.format(**names) + '\n' for line in lines))
    with paths[1].open('a') as stream:
        stream.write(''.join(line.format(**names) + '\n' for line in file_only))
    entries = []
    for line in [line.format(**names) for line in group] + [line.format(**names) for line in directory]:
        name, _password, number, members = line.split(':')
        if number.isdigit():
            entries.append(types.SimpleNamespace(gr_name=name, gr_gid=int(number),
                                                 gr_mem=[m for m in members.split(',') if m]))
    users = []
    for line in [line.format(**names) for line in list(passwd) + list(directory_users)]:
        name, _password, number, primary = line.split(':')[:4]
        users.append(types.SimpleNamespace(pw_name=name, pw_uid=int(number), pw_gid=int(primary)))
    def getpwuid(uid):
        if uid != names['uid']:
            raise KeyError(uid)
        return types.SimpleNamespace(pw_name='avery', pw_uid=uid, pw_gid=gid)
    return ([str(path) for path in paths], types.SimpleNamespace(getpwuid=getpwuid, getpwall=lambda: list(users)),
            types.SimpleNamespace(getgrall=lambda: list(entries)))


AVERY = 'avery:x:{uid}:{gid}:Avery (labeled fake):/home/avery:/bin/bash'
BLAKE = 'blake:x:{other}:{next}:Blake (labeled fake):/home/blake:/bin/bash'
# Each case: name, the fake_accounts arguments after gid, then whether the group is private.
GROUPS = (
    ('Ubuntu private group', dict(passwd=[AVERY, BLAKE], group=['avery:x:{gid}:', 'blake:x:{next}:']), True),
    ('private group that lists its user', dict(passwd=[AVERY], group=['avery:x:{gid}:avery']), True),
    ('shared group', dict(passwd=[AVERY, BLAKE], group=['developers:x:{gid}:avery,blake']), False),
    ('private name with another member', dict(passwd=[AVERY, BLAKE], group=['avery:x:{gid}:blake']), False),
    ('duplicate gid entry with another member',
     dict(passwd=[AVERY, BLAKE], group=['avery:x:{gid}:'], file_only=['builders:x:{gid}:blake']), False),
    ('duplicate gid entry from the directory',
     dict(passwd=[AVERY, BLAKE], group=['avery:x:{gid}:'], directory=['avery:x:{gid}:blake']), False),
    ('group not in the local group file',
     dict(passwd=[AVERY], group=['blake:x:{next}:'], directory=['avery:x:{gid}:']), False),
    ('user not in the local passwd file', dict(passwd=[BLAKE], group=['avery:x:{gid}:']), False),
    ('another account has it as primary group',
     dict(passwd=[AVERY, 'blake:x:{other}:{gid}::/home/blake:/bin/sh'], group=['avery:x:{gid}:']), False),
    ('another directory account has it as primary group',
     dict(passwd=[AVERY, BLAKE], group=['avery:x:{gid}:', 'blake:x:{next}:'],
          directory_users=['casey:x:{other}:{gid}::/home/casey:/bin/sh']), False),
    ('private name that is not the primary group',
     dict(passwd=['avery:x:{uid}:{next}::/home/avery:/bin/sh'], group=['avery:x:{gid}:']), False),
    ('NIS line in the group file', dict(passwd=[AVERY], group=['avery:x:{gid}:'], file_only=['+:x:{next}:']), False),
    # macOS gives every user the primary group staff, which other accounts share.
    ('macOS staff group', dict(passwd=[AVERY], group=['staff:x:{gid}:root']), False),
)
# A group other users share, so a group-writable path refuses on any host, Linux with private groups too.
SHARED = next(group for name, group, _private in GROUPS if name == 'shared group')


# A child that holds the update lock as a running update does, then waits to be ended.
HOLDER = """
import fcntl, os, sys, time
descriptor = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(descriptor, fcntl.LOCK_EX)
os.write(descriptor, (str(os.getpid()) + '\\n').encode())
print('held', flush=True)
time.sleep(60)
"""


class UpdateAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_temp = tempfile.TemporaryDirectory(prefix='older-product-')
        cls.old = Path(cls.old_temp.name).resolve()
        archive = subprocess.run(['git', 'archive', OLDER + ':src'], cwd=str(TREE.parent), capture_output=True, check=True)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as stream:
            stream.extractall(cls.old)
        # git archive writes 0775 folders. Python 3.14's tarfile clears group and other write bits; 3.9 keeps them.
        # Clear them here too, so both Pythons install the same older home that tar with umask 022 gives.
        for folder, folders, names in os.walk(str(cls.old)):
            for path in [folder] + [os.path.join(folder, name) for name in folders + names]:
                if not os.path.islink(path):
                    os.chmod(path, os.stat(path).st_mode & 0o7755)

    @classmethod
    def tearDownClass(cls):
        cls.old_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='update-accept-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.user = self.root / 'user'
        self.user.mkdir()
        self.home = self.user / '.foxrun'
        self.portfolio = self.user / 'foxrun'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('FOXRUN_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
        self.env.update(HOME=str(self.user), PYTHONDONTWRITEBYTECODE='1')
        result = self.command(self.old / 'install.py', '--home', self.home, '--portfolio', self.portfolio,
                              '--person', 'avery', '--workspace', 'cedar-shop', '--runtime', 'both',
                              '--yes', '--no-schedule')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        task = self.command(self.home / 'work/work.py', '--db', self.home / 'data.db',
                            '--receipt-root', self.portfolio / 'cedar-shop', 'create',
                            '--title', 'Keep this task through an update', '--by', 'avery',
                            '--problem', 'Keep existing work', '--job-when', 'When upgrading',
                            '--job-want', 'I want saved tasks', '--job-so', 'So I can continue work',
                            '--body', 'Keep this row', '--acceptance', 'Row bytes stay equal',
                            '--context', 'Update acceptance fixture', '--where', 'STATE.md')
        self.assertEqual(task.returncode, 0, task.stdout + task.stderr)
        for name in ('agents/soul.md', 'profile/AGENTS.md'):
            with (self.home / name).open('ab') as stream:
                stream.write(b'\r\nPersonal choice.\r\n')
        for name in ('config/models.local.yaml', 'config/custom.local.json', 'workspaces/cedar-shop/notes.local.md',
                     'tools/cli/personal.md', 'profile/VOICE.md'):
            target = self.home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'Personal bytes\x00\r\n')
        self.local = self.user / '.local'
        self.local.mkdir()
        (self.local / 'settings.local').write_bytes(b'Keep local data\x00\r\n')
        self.kept = {name: (self.home / name).read_bytes() for name in install.STARTERS}
        self.kept.update({p.relative_to(self.home).as_posix(): p.read_bytes() for p in self.home.rglob('*')
                          if p.is_file() and ('.local' in p.name or p.relative_to(self.home).parts[0] in ('profile', 'workspaces'))})
        self.kept['config/person.json'] = (self.home / 'config/person.json').read_bytes()
        self.kept['tools/cli/personal.md'] = (self.home / 'tools/cli/personal.md').read_bytes()
        self.portfolio_before = snapshot(self.portfolio)
        self.local_before = snapshot(self.local)
        self.tasks_before = self.tasks()

    def command(self, script, *args):
        return subprocess.run([sys.executable, '-B', str(script), *map(str, args)],
                              cwd=str(self.root), env=self.env, text=True, capture_output=True)

    def tasks(self):
        with closing(sqlite3.connect(str(self.home / 'data.db'))) as db:
            return repr(db.execute('SELECT * FROM tasks ORDER BY id').fetchall()).encode()

    def assert_personal(self):
        self.assertEqual(snapshot(self.portfolio), self.portfolio_before)
        self.assertEqual(snapshot(self.local), self.local_before)
        self.assertEqual(self.tasks(), self.tasks_before)
        for name, raw in self.kept.items():
            self.assertEqual((self.home / name).read_bytes(), raw, name)

    def record(self, source):
        record = self.home / update.SOURCE_RECORD
        record.write_bytes(update.source_record(source))
        record.chmod(0o644)  # as with umask 022, whatever this host's umask

    def recorded(self):
        return Path(json.loads((self.home / update.SOURCE_RECORD).read_text())['source'])

    def changed_source(self, source=None):
        source = source or self.root / 'source'
        source.mkdir()
        with (TREE / 'product-manifest.tsv').open(newline='') as stream:
            names = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
        for name in names | set(install.STARTERS) | {'product-manifest.tsv'}:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(TREE / name, target)
        # Only this user may write the copy, as with umask 022, so each test sets the bits it checks.
        for folder, _folders, files in os.walk(str(source)):
            for path in [folder] + [os.path.join(folder, name) for name in files]:
                os.chmod(path, os.stat(path).st_mode & 0o7755)
        return source

    def test_older_install_updates_and_reruns_with_identical_personal_bytes(self):
        self.assertFalse((self.home / 'update.py').exists())
        # Remove a migration-owned object to prove that the migration really runs.
        with closing(sqlite3.connect(str(self.home / 'data.db'))) as db:
            db.execute('DROP VIEW close_now')
        for attempt in range(2):
            result = self.command(TREE / 'foxrun.py', 'update')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
            self.assert_personal()
            self.assertEqual((self.home / 'update.py').read_bytes(), (TREE / 'update.py').read_bytes())
            with closing(sqlite3.connect(str(self.home / 'data.db'))) as db:
                self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE name='close_now'").fetchone(), ('close_now',))
        self.assertEqual(len(list((self.home / 'backups').glob('update-*'))), 2)
        self.assertEqual((self.home / 'skillwright/workflows/.product/review.yaml').read_bytes(),
                         (TREE / 'skillwright/workflows/review.yaml').read_bytes())

    def test_personal_workflow_and_local_manifest_rows_stay_personal(self):
        source = self.changed_source()
        workflow = self.home / 'skillwright/workflows/review.yaml'
        workflow.write_bytes(b'Personal review workflow\r\n')
        record = self.home / 'skillwright/workflows/.release-manifest.json'
        data = json.loads(record.read_text())
        data['workflows']['review'] = dict(owner='person', release_id='personal-choice')
        record.write_text(json.dumps(data))
        local = source / 'config/custom.local.json'
        local.write_bytes(b'Product must not replace local bytes')
        refresh_row(source, 'config/custom.local.json')
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(workflow.read_bytes(), b'Personal review workflow\r\n')
        self.assertEqual(json.loads(record.read_text())['workflows']['review'], data['workflows']['review'])
        self.assertEqual((self.home / 'skillwright/workflows/.product/review.yaml').read_bytes(),
                         (source / 'skillwright/workflows/review.yaml').read_bytes())
        self.assert_personal()

    def test_uv_command_runs_the_same_update(self):
        spec = importlib.util.spec_from_file_location('test_uv_command', str(TREE / 'packaging/foxrun_cli.py'))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch.object(cli, 'PRODUCT', TREE), mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(cli.main(['update', '--home', str(self.home)]), 0)
        self.assert_personal()
        self.assertEqual(self.recorded(), TREE)

    def test_uv_command_uses_its_bundled_product_over_the_recorded_source(self):
        other = self.changed_source()
        self.record(other)
        spec = importlib.util.spec_from_file_location('test_uv_bundle', str(TREE / 'packaging/foxrun_cli.py'))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch.object(cli, 'PRODUCT', TREE), mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(cli.main(['update', '--home', str(self.home)]), 0)
        self.assertEqual(self.recorded(), TREE)
        self.assert_personal()

    def test_installed_launcher_uses_explicit_current_source(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.command(self.home / 'foxrun.py', 'update', '--source', TREE)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assert_personal()

    def test_explicit_source_another_user_can_write_is_refused_before_its_code_runs(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        marker = self.root / 'planted-ran'
        plant = ('import pathlib; pathlib.Path(%r).write_text("ran (labeled fake)")\n' % str(marker)).encode()
        for name in ('update.py', 'install.py'):
            (source / name).write_bytes(plant + (source / name).read_bytes())
        spec = importlib.util.spec_from_file_location('test_uv_explicit', str(TREE / 'packaging/foxrun_cli.py'))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        before = snapshot(self.home)
        for path in (source / 'update.py', source / 'install.py', source / 'base', source / 'base/person.py'):
            with self.subTest(path=path.name):
                mode = path.stat().st_mode & 0o777
                path.chmod(mode | 0o002)
                try:
                    launched = self.command(self.home / 'foxrun.py', 'update', '--source', source)
                    with mock.patch.object(cli, 'PRODUCT', TREE), mock.patch.dict(os.environ, self.env, clear=True):
                        uv = cli.main(['update', '--source', str(source), '--home', str(self.home)])
                finally:
                    path.chmod(mode)
                self.assertEqual(launched.returncode, 1, launched.stdout + launched.stderr)
                self.assertEqual(uv, 1)
                self.assertIn('The source ' + str(source) + ' is not safe to run: '
                              + os.path.realpath(str(path)) + ' is world-writable', launched.stderr)
                self.assertFalse(marker.exists(), 'the source code ran before its check')
                self.assertEqual(snapshot(self.home), before)
        # A shared group refuses a group-writable explicit source; this user's private group passes it.
        update_py = source / 'update.py'
        update_py.chmod(0o664)
        driver = self.accounts_driver()
        result = self.command(driver, self.home, update_py.stat().st_gid, json.dumps(SHARED),
                              '--source', source, '--home', self.home)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(os.path.realpath(str(update_py)) + ' is group-writable (fix: chmod g-w ', result.stderr)
        self.assertFalse(marker.exists(), 'the source code ran before its check')
        self.assertEqual(snapshot(self.home), before)
        with self.accounts(update_py.stat().st_gid, **GROUPS[0][1]), \
                mock.patch.object(update.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(update.main(['--source', str(source), '--home', str(self.home)]), 0)
        real = os.path.realpath(str(source))
        self.assertEqual(run.call_args.args[0], [sys.executable, '-I', '-B', os.path.join(real, 'update.py'),
                                                 '--source', real, '--home', str(self.home)])
        self.assert_personal()

    def test_product_folder_another_user_can_write_refuses_its_own_update(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        before = snapshot(self.home)
        real = os.path.realpath(str(source))
        path = source / 'base/person.py'
        path.chmod(0o666)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('This product folder ' + real + ' is not safe to run: '
                      + os.path.realpath(str(path)) + ' is world-writable', result.stderr)
        path.chmod(0o664)
        result = self.command(self.accounts_driver(), source, path.stat().st_gid, json.dumps(SHARED), '--home', self.home)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('This product folder ' + real + ' is not safe to run: '
                      + os.path.realpath(str(path)) + ' is group-writable', result.stderr)
        self.assertNotIn('Update backup:', result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assert_personal()

    def test_private_group_refuses_another_directory_account_and_a_failed_lookup(self):
        gid = self.root.stat().st_gid
        clean = dict(passwd=[AVERY, BLAKE], group=['avery:x:{gid}:', 'blake:x:{next}:'])
        with self.accounts(gid, **clean):
            self.assertTrue(update.private_group(gid))
        # The local files look clean, but the system lookup knows another account with gid as its primary group.
        with self.accounts(gid, directory_users=['casey:x:{other}:{gid}::/home/casey:/bin/sh'], **clean):
            self.assertFalse(update.private_group(gid))
        for failing in ('getpwall', 'getpwuid'):
            with self.subTest(failing), self.accounts(gid, **clean), \
                    mock.patch.object(update.pwd, failing, side_effect=OSError('directory down (labeled fake)')):
                self.assertFalse(update.private_group(gid))

    def test_installed_launcher_without_source_uses_the_recorded_source(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        guide = source / 'GUIDE.md'
        guide.write_bytes(guide.read_bytes() + b'\nA newer source page.\n')
        refresh_row(source, 'GUIDE.md')
        self.record(source)
        self.assertFalse((self.home / 'install.py').exists())
        result = self.command(self.home / 'foxrun.py', 'update')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual((self.home / 'GUIDE.md').read_bytes(), guide.read_bytes())
        self.assertEqual(self.recorded(), source)
        # The installed update.py alone finds the same recorded source.
        again = self.command(self.home / 'update.py')
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assert_personal()

    def test_install_records_its_source_for_a_later_update(self):
        home, portfolio = self.root / 'fresh/.foxrun', self.root / 'fresh/foxrun'
        result = self.command(TREE / 'install.py', '--home', home, '--portfolio', portfolio,
                              '--person', 'avery', '--workspace', 'cedar-shop', '--runtime', 'both',
                              '--runtime-home', self.root / 'fresh/runtime', '--yes', '--no-schedule')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((home / update.SOURCE_RECORD).read_text()), {'version': 1, 'source': str(TREE)})
        refreshed = self.command(home / 'foxrun.py', 'update', '--home', home)
        self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)
        self.assertTrue(refreshed.stdout.rstrip().endswith('Doctor: 0 failed'))

    def test_no_source_refuses_with_each_route_command(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        guide = (TREE / 'INSTALL.md').read_text()
        commands = [line.strip() for line in update.ROUTES.splitlines() if line.startswith('  ')]
        self.assertEqual(len(commands), 5)
        for command in commands:
            self.assertIn('\n' + command + '\n', guide, command)
        for case in ('missing', 'gone', 'invalid'):
            with self.subTest(case=case):
                record = self.home / update.SOURCE_RECORD
                if case == 'missing':
                    record.unlink()
                elif case == 'gone':
                    self.record(self.root / 'deleted-clone')
                else:
                    record.write_text('not json')
                before = snapshot(self.home)
                result = self.command(self.home / 'foxrun.py', 'update')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('Update needs the product source.', result.stderr)
                if case == 'gone':
                    self.assertIn(str(self.root / 'deleted-clone') + ' is not a product folder now', result.stderr)
                for command in commands:
                    self.assertIn('  ' + command + '\n', result.stderr + '\n', command)
                self.assertIn('Plugin: run setup after a plugin upgrade', result.stderr)
                self.assertEqual(snapshot(self.home), before)
                self.assert_personal()

    def refused_unsafe(self, path, reason, group=None):
        """Update with no --source refuses the recorded source. With group, the installed update.py
        runs with fake account files, so a group-writable path refuses on a private-group host too."""
        before = snapshot(self.home)
        if group is None:
            result = self.command(self.home / 'foxrun.py', 'update')
        else:
            result = self.command(self.accounts_driver(), self.home, path.stat().st_gid, json.dumps(group),
                                  '--home', self.home)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('Update needs the product source.', result.stderr)
        self.assertIn(os.path.realpath(str(path)) + ' is ' + reason, result.stderr)
        for command in (line.strip() for line in update.ROUTES.splitlines() if line.startswith('  ')):
            self.assertIn('  ' + command + '\n', result.stderr + '\n', command)
        self.assertNotIn('Update backup:', result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assert_personal()

    def test_group_writable_recorded_source_is_refused(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        self.record(source)
        # Update copies hooks, commands with no extension, and SQL that run later, so each file counts.
        for path in (source, source / 'update.py', source / 'install.py', source / 'hooks/claude/session-start',
                     source / 'work/apply.sql', source / 'skillwright/skills/orchestrate/bin/brief-check',
                     source / 'GUIDE.md'):
            with self.subTest(path=path.name):
                mode = path.stat().st_mode & 0o777
                path.chmod(mode | 0o020)
                try:
                    self.refused_unsafe(path, 'group-writable', SHARED)
                finally:
                    path.chmod(mode)

    def test_world_writable_source_record_is_refused(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        record = self.home / update.SOURCE_RECORD
        record.chmod(0o646)
        self.refused_unsafe(record, 'world-writable')
        self.assertEqual(record.stat().st_mode & 0o777, 0o646)

    def test_recorded_source_owned_by_another_user_is_refused(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        self.record(source)
        # The record passes as this user; the source folder then shows another owner.
        with mock.patch.object(update, 'HERE', self.home), \
                mock.patch.object(update.os, 'getuid', side_effect=[os.getuid(), os.getuid() + 1]):
            with self.assertRaises(ValueError) as caught:
                update.find_source(self.home)
        message = str(caught.exception)
        self.assertIn(os.path.realpath(str(source)) + ' is not owned by the current user', message)
        self.assertIn('Update needs the product source.', message)
        self.assertIn('  git pull\n', message)
        self.assertIn('Plugin: run setup after a plugin upgrade', message)

    def test_writable_base_folder_in_recorded_source_is_refused(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        self.record(source)
        # update.py imports base/ from the source, so its folder and files count too.
        for path, bits, reason in ((source / 'base', 0o020, 'group-writable'),
                                   (source / 'base/person.py', 0o002, 'world-writable')):
            with self.subTest(path=path.name):
                mode = path.stat().st_mode & 0o777
                path.chmod(mode | bits)
                try:
                    self.refused_unsafe(path, reason, SHARED)
                finally:
                    path.chmod(mode)

    def test_writable_parent_without_sticky_bit_is_refused(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        shared = self.root / 'shared'
        shared.mkdir()
        source = self.changed_source(shared / 'source')
        self.record(source)
        shared.chmod(0o775)
        self.addCleanup(shared.chmod, 0o755)
        self.refused_unsafe(shared, 'group-writable without the sticky bit', SHARED)
        # The sticky bit stops another user from swapping the source folder.
        shared.chmod(0o1777)
        with mock.patch.object(update, 'HERE', self.home):
            self.assertEqual(update.find_source(self.home), source.resolve())

    @contextmanager
    def accounts(self, gid, **group):
        """Patch update with fake account files, pwd, and grp, and clear the cached answers."""
        folder = Path(tempfile.mkdtemp(dir=str(self.root)))
        (passwd, group_file), fake_pwd, fake_grp = fake_accounts(folder, gid, **group)
        update.private_group.cache_clear()
        try:
            with mock.patch.multiple(update, pwd=fake_pwd, grp=fake_grp, PASSWD_FILE=passwd, GROUP_FILE=group_file):
                yield
        finally:
            update.private_group.cache_clear()

    def test_private_group_writable_source_and_parent_run_and_a_shared_group_refuses(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        # git clone and install with umask 002 give 0775 folders and 0664 files, in a 0775 parent.
        clone = self.root / 'code'
        clone.mkdir()
        source = self.changed_source(clone / 'source')
        self.record(source)
        for folder, _folders, names in os.walk(str(clone)):
            for path in [folder] + [os.path.join(folder, name) for name in names]:
                os.chmod(path, os.stat(path).st_mode & 0o777 | 0o020)
        self.assertEqual(clone.stat().st_mode & 0o777, 0o775)
        self.assertEqual((source / 'update.py').stat().st_mode & 0o777, 0o664)
        gid = source.stat().st_gid
        for name, group, private in GROUPS:
            with self.subTest(name):
                with self.accounts(gid, **group), mock.patch.object(update, 'HERE', self.home):
                    if private:
                        self.assertEqual(update.find_source(self.home), source.resolve())
                    else:
                        with self.assertRaises(ValueError) as caught:
                            update.find_source(self.home)
                        real = os.path.realpath(str(source))
                        self.assertIn(real + ' is group-writable (fix: chmod g-w ' + real + ')', str(caught.exception))
        # A private group never excuses a world write bit, on a file or on a parent.
        cases = ((source / 'base/person.py', 0o666, 'world-writable'),
                 (clone, 0o777, 'world-writable without the sticky bit'))
        for path, mode, reason in cases:
            with self.subTest(reason):
                before = path.stat().st_mode & 0o777
                os.chmod(str(path), mode)
                try:
                    with self.accounts(gid, **GROUPS[0][1]), mock.patch.object(update, 'HERE', self.home):
                        with self.assertRaises(ValueError) as caught:
                            update.find_source(self.home)
                finally:
                    os.chmod(str(path), before)
                self.assertIn(os.path.realpath(str(path)) + ' is ' + reason, str(caught.exception))
        self.assert_personal()

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS gives each user the shared group staff')
    def test_macos_staff_group_is_not_private_so_group_writable_still_refuses(self):
        import grp
        import pwd
        update.private_group.cache_clear()
        self.addCleanup(update.private_group.cache_clear)
        user = pwd.getpwuid(os.getuid())
        gid = self.root.stat().st_gid
        self.assertNotEqual(grp.getgrgid(user.pw_gid).gr_name, user.pw_name)
        self.assertFalse(update.private_group(user.pw_gid))
        self.assertFalse(update.private_group(gid))
        folder = self.root / 'group-writable'
        folder.mkdir()
        folder.chmod(0o775)
        real = os.path.realpath(str(folder))
        self.assertEqual(update.writable_by_others(folder), real + ' is group-writable (fix: chmod g-w ' + real + ')')

    def test_recorded_source_runs_from_its_checked_real_path_in_isolated_mode(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        link = self.root / 'linked-source'
        link.symlink_to(source)
        self.record(link)
        # source_record resolves links, so write the linked string by hand.
        (self.home / update.SOURCE_RECORD).write_text(json.dumps({'version': 1, 'source': str(link)}))
        real = Path(os.path.realpath(str(source)))
        checked = []
        original = update.source_unsafe
        def spy(path):
            checked.append(Path(path))
            return original(path)
        with mock.patch.object(update, 'HERE', self.home), mock.patch.object(update, 'source_unsafe', spy), \
                mock.patch.object(update.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(update.main(['--home', str(self.home)]), 0)
        self.assertEqual(checked, [real])
        self.assertEqual(run.call_args.args[0], [sys.executable, '-I', '-B', str(real / 'update.py'),
                                                 '--source', str(real), '--home', str(self.home)])
        self.assertNotIn(str(link), ' '.join(run.call_args.args[0]))
        self.assert_personal()

    def test_user_owned_recorded_source_still_runs(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        source.chmod(0o755)
        self.record(source)
        record = self.home / update.SOURCE_RECORD
        for path in (record, source, source / 'update.py', source / 'install.py'):
            self.assertEqual(path.stat().st_uid, os.getuid(), path)
            self.assertFalse(path.stat().st_mode & 0o022, path)
        with mock.patch.object(update, 'HERE', self.home):
            self.assertEqual(update.find_source(self.home), source.resolve())
        result = self.command(self.home / 'foxrun.py', 'update')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual(self.recorded(), source.resolve())
        self.assert_personal()

    def test_failed_migration_changes_no_existing_bytes(self):
        source = self.changed_source()
        (source / 'work/apply.sql').write_text('BEGIN IMMEDIATE; CREATE TABLE trial(id); INVALID SQL; COMMIT;')
        refresh_row(source, 'work/apply.sql')
        before = snapshot(self.home)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        # The update must fail on the bad statement in the trial migration, for no other reason.
        self.assertIn('Update backup:', result.stdout)
        self.assertEqual(result.stderr, 'Update refused or failed: near "INVALID": syntax error\n')
        for name, raw in before.items():
            self.assertEqual((self.home / name).read_bytes(), raw, name)
        self.assert_personal()

    def test_failed_doctor_restores_old_product_and_database(self):
        source = self.changed_source()
        (source / 'foxrun.py').write_text('raise SystemExit(1)\n')
        refresh_row(source, 'foxrun.py')
        before = snapshot(self.home)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rolled back', result.stderr)
        for name, raw in before.items():
            self.assertEqual((self.home / name).read_bytes(), raw, name)
        self.assertFalse((self.home / 'update.py').exists())
        self.assert_personal()

    def test_failed_doctor_excludes_writers_until_rollback(self):
        for journal_mode in ('delete', 'wal'):
            with self.subTest(journal_mode=journal_mode):
                with closing(sqlite3.connect(str(self.home / 'data.db'))) as db:
                    db.execute('PRAGMA journal_mode=' + journal_mode)
                    db.execute('DROP VIEW close_now')
                source = self.changed_source()
                marker = self.root / 'doctor-ready'
                release = self.root / 'doctor-release'
                writer_ready = self.root / 'writer-ready'
                writer_done = self.root / 'writer-done'
                launcher = source / 'foxrun.py'
                wrapper = """
_original_doctor = doctor
def doctor(connection=None):
    import time
    assert connection.in_transaction
    assert connection.execute("SELECT name FROM sqlite_master WHERE name='close_now'").fetchone()
    result = _original_doctor(connection=connection)
    assert result == 0
    Path({marker!r}).touch()
    end = time.monotonic() + 20
    while not Path({release!r}).exists():
        if time.monotonic() >= end:
            raise ValueError('test release timed out')
        time.sleep(0.01)
    return 1
""".format(marker=str(marker), release=str(release))
                launcher.write_text(launcher.read_text() + wrapper)
                refresh_row(source, 'foxrun.py')
                updater = subprocess.Popen([sys.executable, '-B', str(source / 'update.py'), '--home', str(self.home)],
                                           cwd=self.root, env=self.env, text=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.addCleanup(lambda p=updater: p.kill() if p.poll() is None else None)
                def wait_for(path):
                    end = time.monotonic() + 20
                    while not path.exists():
                        if time.monotonic() >= end or updater.poll() is not None:
                            self.fail('update did not reach the concurrency checkpoint: ' + str(path))
                        time.sleep(0.01)
                wait_for(marker)
                writer_code = """
import sqlite3, sys
from pathlib import Path
with sqlite3.connect(sys.argv[1], timeout=20) as db:
    Path(sys.argv[2]).touch()
    db.execute('BEGIN IMMEDIATE')
    db.execute("UPDATE tasks SET title='Task saved by the waiting writer' WHERE title='Keep this task through an update'")
Path(sys.argv[3]).touch()
"""
                writer = subprocess.Popen([sys.executable, '-B', '-c', writer_code, str(self.home / 'data.db'),
                                           str(writer_ready), str(writer_done)], env=self.env, text=True,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.addCleanup(lambda p=writer: p.kill() if p.poll() is None else None)
                wait_for(writer_ready)
                time.sleep(0.2)
                self.assertIsNone(writer.poll(), 'writer must wait while Doctor holds the transaction')
                self.assertFalse(writer_done.exists())
                release.touch()
                output, errors = updater.communicate(timeout=30)
                self.assertNotEqual(updater.returncode, 0, output + errors)
                self.assertIn('rolled back', errors)
                out, err = writer.communicate(timeout=30)
                self.assertEqual(writer.returncode, 0, out + err)
                self.assertTrue(writer_done.exists())
                with closing(sqlite3.connect(str(self.home / 'data.db'))) as db:
                    self.assertEqual(db.execute("SELECT title FROM tasks WHERE title='Task saved by the waiting writer'").fetchall(),
                                     [('Task saved by the waiting writer',)])
                    self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='close_now'").fetchone())
                    # Restore only the synthetic fixture for the next journal mode.
                    db.execute("UPDATE tasks SET title='Keep this task through an update' WHERE title='Task saved by the waiting writer'")
                    db.execute('CREATE VIEW close_now AS SELECT * FROM tasks')
                    db.commit()
                self.assert_personal()
                shutil.rmtree(source)
                for path in (marker, release, writer_ready, writer_done):
                    path.unlink()

    def test_migration_cannot_commit_inside_the_update_transaction(self):
        source = self.changed_source()
        (source / 'work/apply.sql').write_text(
            'BEGIN IMMEDIATE; CREATE TABLE trial(id); COMMIT; BEGIN IMMEDIATE; COMMIT;')
        refresh_row(source, 'work/apply.sql')
        before = snapshot(self.home)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        for name, raw in before.items():
            self.assertEqual((self.home / name).read_bytes(), raw, name)
        self.assert_personal()

    def test_linked_destination_is_refused_before_changes(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'Outside file')
        (self.home / 'VERSION').unlink()
        (self.home / 'VERSION').symlink_to(outside)
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Linked update path', result.stderr)
        self.assertEqual(outside.read_bytes(), b'Outside file')
        self.assert_personal()

    def test_linked_database_sidecar_is_refused_before_opening_database(self):
        outside = self.root / 'outside-database-bytes'
        outside.write_bytes(b'Outside database bytes')
        sidecar = self.home / 'data.db-wal'
        sidecar.symlink_to(outside)
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Linked update path', result.stderr)
        self.assertEqual(outside.read_bytes(), b'Outside database bytes')
        sidecar.unlink()
        self.assert_personal()

    def test_update_keeps_every_file_install_personalizes(self):
        home, portfolio = self.root / 'fresh/.foxrun', self.root / 'fresh/foxrun'
        result = self.command(TREE / 'install.py', '--home', home, '--portfolio', portfolio,
                              '--person', 'avery', '--workspace', 'cedar-shop', '--runtime', 'both',
                              '--runtime-home', self.root / 'fresh/runtime', '--yes', '--no-schedule')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Every product row update copies must hold the source bytes after install. A row that install
        # rewrote for this person belongs in install.STARTERS, or update would reset it.
        with (TREE / 'product-manifest.tsv').open(newline='') as stream:
            names = [row['path'] for row in csv.DictReader(stream, delimiter='\t')]
        copied = [name for name in names if name not in install.BUILD_ONLY and not update.personal(name, set(install.STARTERS))]
        self.assertEqual([name for name in copied if (home / name).read_bytes() != (TREE / name).read_bytes()], [])
        reasons = home / 'config/lint/db-reasons.tsv'
        self.assertIn(b'cedar-shop\ttasks', reasons.read_bytes())
        with reasons.open('ab') as stream:
            stream.write(b'system\tcaptures\t\t\tempty-table\tPersonal reason (labeled fake)\n')
        kept = reasons.read_bytes()
        for attempt in range(2):
            refreshed = self.command(home / 'foxrun.py', 'update', '--home', home)
            self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)
            self.assertTrue(refreshed.stdout.rstrip().endswith('Doctor: 0 failed'))
            self.assertEqual(reasons.read_bytes(), kept)

    def test_retired_file_that_ships_again_is_updated(self):
        first = self.command(TREE / 'foxrun.py', 'update', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        guide = self.home / 'GUIDE.md'
        shipped = guide.read_bytes()
        # One release retires GUIDE.md: the file stays, and its row keeps the retired marker.
        retired = self.changed_source(self.root / 'retired')
        drop_row(retired, 'GUIDE.md')
        result = self.command(retired / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual(guide.read_bytes(), shipped)
        row = home_rows(self.home)['GUIDE.md']
        self.assertEqual(row['sha256'], update.RETIRED + update.file_row('GUIDE.md', shipped)['sha256'])
        again = self.command(retired / 'update.py', '--home', self.home)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(home_rows(self.home)['GUIDE.md'], row)
        # The next release ships GUIDE.md again with new bytes; update replaces the retired file.
        back = self.changed_source(self.root / 'back')
        (back / 'GUIDE.md').write_bytes(shipped + b'\nThe page ships again.\n')
        refresh_row(back, 'GUIDE.md')
        result = self.command(back / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual(guide.read_bytes(), (back / 'GUIDE.md').read_bytes())
        self.assertEqual(home_rows(self.home)['GUIDE.md'], {k: str(v) for k, v in update.file_row('GUIDE.md', guide.read_bytes()).items()})
        self.assert_personal()

    def test_four_updates_keep_the_last_three_backups_and_nothing_else(self):
        backups = self.home / 'backups'
        backups.mkdir(exist_ok=True)
        (backups / 'manual').mkdir()
        (backups / 'notes.txt').write_bytes(b'Personal backup note\n')
        made = []
        for attempt in range(4):
            result = self.command(TREE / 'update.py', '--home', self.home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
            made.append(Path(result.stdout.split('Update backup: ', 1)[1].split('\n', 1)[0]))
            self.assertTrue(made[-1].is_dir())
        self.assertEqual(sorted(backups.glob('update-*')), sorted(made[1:]))
        self.assertTrue((backups / 'manual').is_dir())
        self.assertEqual((backups / 'notes.txt').read_bytes(), b'Personal backup note\n')
        self.assert_personal()

    def test_hand_edited_product_file_is_kept_beside_the_new_one(self):
        first = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        # Unchanged product files make no copy, and the older install's files count as unchanged.
        self.assertEqual(list(self.home.rglob('*' + update.LOCAL_EDIT + '*')), [])
        self.assertNotIn('Move your change', first.stdout)
        guide = self.home / 'GUIDE.md'
        mine = guide.read_bytes() + b'\nMy own note (labeled fake).\n'
        guide.write_bytes(mine)
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual(guide.read_bytes(), (TREE / 'GUIDE.md').read_bytes())
        copies = list(self.home.rglob('*' + update.LOCAL_EDIT + '*'))
        self.assertEqual([copy.parent for copy in copies], [self.home])
        self.assertTrue(copies[0].name.startswith('GUIDE.md' + update.LOCAL_EDIT))
        self.assertEqual(copies[0].read_bytes(), mine)
        self.assertEqual(copies[0].stat().st_mode & 0o777, 0o600)
        self.assertIn('  ' + str(copies[0]) + '\nMove your change into a .local file.\n', result.stdout)
        # The next update finds the file unchanged again and makes no second copy.
        again = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(list(self.home.rglob('*' + update.LOCAL_EDIT + '*')), copies)
        self.assertNotIn('Move your change', again.stdout)
        self.assert_personal()

    def test_hand_edit_that_matches_the_new_release_is_still_kept(self):
        first = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.changed_source()
        mine = (source / 'GUIDE.md').read_bytes() + b'\nThe same note in the next release (labeled fake).\n'
        (source / 'GUIDE.md').write_bytes(mine)
        refresh_row(source, 'GUIDE.md')
        guide = self.home / 'GUIDE.md'
        guide.write_bytes(mine)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual(guide.read_bytes(), mine)
        copies = list(self.home.rglob('*' + update.LOCAL_EDIT + '*'))
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].name.startswith('GUIDE.md' + update.LOCAL_EDIT))
        self.assertEqual(copies[0].read_bytes(), mine)
        self.assertEqual(copies[0].stat().st_mode & 0o777, 0o600)
        self.assertIn('  ' + str(copies[0]) + '\nMove your change into a .local file.\n', result.stdout)
        self.assert_personal()

    def test_failed_doctor_restores_every_file_when_a_kept_copy_is_gone(self):
        first = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        guide = self.home / 'GUIDE.md'
        guide.write_bytes(guide.read_bytes() + b'\nMy own note (labeled fake).\n')
        source = self.changed_source()
        launcher = source / 'foxrun.py'
        # Doctor removes the kept copy, then fails, so the rollback meets a missing copy.
        launcher.write_text(launcher.read_text() + """
def doctor(connection=None):
    for copy in Path({home!r}).rglob('*' + {mark!r} + '*'):
        copy.unlink()
    return 1
""".format(home=str(self.home), mark=update.LOCAL_EDIT))
        refresh_row(source, 'foxrun.py')
        before = snapshot(self.home)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rolled back', result.stderr)
        for name, raw in before.items():
            self.assertEqual((self.home / name).read_bytes(), raw, name)
        self.assertEqual(list(self.home.rglob('*' + update.LOCAL_EDIT + '*')), [])
        self.assert_personal()

    def hold_lock(self):
        holder = subprocess.Popen([sys.executable, '-B', '-c', HOLDER, str(self.home / update.LOCK)],
                                  env=self.env, text=True, stdout=subprocess.PIPE)
        self.addCleanup(lambda: holder.kill() if holder.poll() is None else None)
        self.assertEqual(holder.stdout.readline(), 'held\n')
        return holder

    def test_killed_update_leaves_no_lock_that_blocks_the_next_one(self):
        holder = self.hold_lock()
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=20)
        self.assertEqual((self.home / update.LOCK).read_text(), str(holder.pid) + '\n')
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertFalse((self.home / update.LOCK).exists())
        self.assert_personal()

    def test_running_update_lock_is_refused_with_its_process(self):
        holder = self.hold_lock()
        before = snapshot(self.home)
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stderr, 'Update refused or failed: Another update is running (process ' + str(holder.pid) +
                         ') and holds ' + str(self.home / update.LOCK) + '. Wait for it to end, then run the update again.\n')
        self.assertEqual(snapshot(self.home), before)
        self.assert_personal()

    def test_new_product_path_with_the_release_bytes_is_adopted_silently(self):
        # The older install has no update.py; this home already holds the release's own bytes there.
        (self.home / 'update.py').write_bytes((TREE / 'update.py').read_bytes())
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual((self.home / 'update.py').read_bytes(), (TREE / 'update.py').read_bytes())
        self.assertEqual(home_rows(self.home)['update.py']['sha256'],
                         update.file_row('update.py', (TREE / 'update.py').read_bytes())['sha256'])
        self.assertEqual(list(self.home.rglob('*' + update.LOCAL_EDIT + '*')), [])
        self.assertNotIn('Move your change', result.stdout)
        self.assert_personal()

    def test_new_product_path_with_other_bytes_is_kept_and_named(self):
        (self.home / 'update.py').write_bytes(b'Personal command')
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertEqual((self.home / 'update.py').read_bytes(), (TREE / 'update.py').read_bytes())
        copies = list(self.home.rglob('*' + update.LOCAL_EDIT + '*'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].parent, self.home)
        self.assertTrue(copies[0].name.startswith('update.py' + update.LOCAL_EDIT))
        self.assertEqual(copies[0].read_bytes(), b'Personal command')
        self.assertEqual(copies[0].stat().st_mode & 0o777, 0o600)
        self.assertIn('  ' + str(copies[0]) + '\nMove your change into a .local file.\n', result.stdout)
        # The file is now in the home list, so the next update makes no second copy.
        again = self.command(TREE / 'update.py', '--home', self.home)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(list(self.home.rglob('*' + update.LOCAL_EDIT + '*')), copies)
        self.assertNotIn('Move your change', again.stdout)
        self.assert_personal()

    def test_release_record_survives_two_updates_unchanged(self):
        name = 'skillwright/manifests/shipped.yaml'
        self.assertIn(name, install.STARTERS)
        with (TREE / 'made-at-install.tsv').open(newline='') as stream:
            self.assertIn(name, {row['path'] for row in csv.DictReader(stream, delimiter='\t')})
        # Skillwright's release record writes the person's own list after install.
        record = self.home / name
        mine = record.read_bytes() + b'\n# Released by this person (labeled fake).\n'
        record.write_bytes(mine)
        self.kept[name] = mine
        for attempt in range(2):
            result = self.command(TREE / 'update.py', '--home', self.home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
            self.assertEqual(record.read_bytes(), mine)
            self.assertNotIn(name, home_rows(self.home))
            self.assertEqual(list(record.parent.glob('*' + update.LOCAL_EDIT + '*')), [])
        self.assert_personal()


    def ship_shelf(self):
        """Do what skill-ship's first release does: freeze skills/ as a release, then link to it."""
        tool, scoped = update.load_skillwright(TREE, self.home)
        shelf = self.home / 'skills'
        own = shelf / 'cedar-notes'
        own.mkdir()
        (own / 'SKILL.md').write_bytes(b'---\nname: cedar-notes\ndescription: Personal notes (labeled fake).\n---\nMine.\r\n')
        override = shelf / 'capability/SKILL.md'
        override.write_bytes(override.read_bytes() + b'\nMy own capability rule (labeled fake).\n')
        skills = {}
        for name in scoped.skill_names(shelf):
            digest, count = tool.digest_tree(shelf / name)
            owner = 'person' if name in ('cedar-notes', 'capability') else 'product'
            skills[name] = dict(source='skills_dojo', digest=digest, file_count=count, owner=owner)
        release_id = '20261024T120000000000Z-0123456789ab'
        record = dict(version=3, kind='scoped_release', release_id=release_id, dojo_commit='0123456789ab' * 3,
                      policy=dict(version=1, path='config/catalog.yaml', digest='0' * 64), skills=skills,
                      excluded={}, removed=[], digest=scoped.record_digest(skills), runtime_canaries='passed')
        with update.skill_env(self.home):
            release = tool.RELEASES / release_id
            release.mkdir(parents=True)
            for name in skills:
                shutil.copytree(str(shelf / name), str(release / name), symlinks=True)
            tool.write_json(release / scoped.RECORD, record)
            scoped.validate_record(tool, release)
            tool.make_read_only(release)
            parked = tool.STATE / 'shelf-before' / release_id
            parked.parent.mkdir(parents=True)
            os.rename(str(shelf), str(parked))
            tool.switch_link(release)
            tool.write_json(tool.DIST, record)
            tool.write_json(scoped.pin_path(), dict(gaps=[], release=release_id))
            tool.write_json(tool.STATE_FILE, dict(version=1, scoped=True, release_id=release_id,
                            current=dict(kind='release', path=str(release)), previous=None))
        self.addCleanup(self.writable, self.home / 'skillwright/skill-releases')
        # Skill-ship writes these two starters; each test checks them itself.
        for name in ('skillwright/manifests/shipped.yaml', 'agents/execution/skills.yaml'):
            self.kept.pop(name)
        return tool, scoped, release

    @staticmethod
    def writable(root):
        for folder, _folders, names in os.walk(str(root)):
            os.chmod(folder, 0o755)

    def only_owner_writes_skillwright(self):
        """Clear group and other write bits that install's umask gave the skillwright folders,
        so a shared fake group refuses only the folder a test makes writable."""
        for folder in ('skillwright', 'skillwright/skill-releases', 'skillwright/skill-state'):
            path = self.home / folder
            os.chmod(str(path), path.stat().st_mode & 0o7755)

    def skillwright_records(self):
        return {name: (self.home / name).read_bytes() for name in (
            'skillwright/manifests/shipped.yaml', 'agents/execution/skills.yaml',
            'skillwright/skill-state/release-state.json')}

    def test_skill_ship_release_link_updates_the_skills_the_skillwright_way(self):
        tool, scoped, old = self.ship_shelf()
        mine = {name: snapshot(old / name) for name in ('cedar-notes', 'capability')}
        old_bytes = snapshot(old)
        source = self.changed_source()
        for name in ('skills/flow/SKILL.md', 'skills/capability/SKILL.md'):
            with (source / name).open('ab') as stream:
                stream.write(b'\nA newer product line.\n')
            refresh_row(source, name)
        added = 'skills/flow/replays/read-new-rule.json'
        (source / added).write_bytes(b'{"labeled": "fake"}\n')
        refresh_row(source, added)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'))
        self.assertTrue((self.home / 'skills').is_symlink())
        new = Path(os.path.realpath(str(self.home / 'skills')))
        self.assertNotEqual(new, old)
        self.assertEqual(new.parent, old.parent)
        self.assertIn('previous release stays for rollback: ' + str(old), result.stdout)
        # The new product skill file is in the new release; the person's skills are byte-identical.
        self.assertEqual((new / 'flow/SKILL.md').read_bytes(), (source / 'skills/flow/SKILL.md').read_bytes())
        self.assertEqual((self.home / added).read_bytes(), (source / added).read_bytes())
        for name, files in mine.items():
            self.assertEqual(snapshot(new / name), files, name)
        self.assertNotIn(b'A newer product line.', (new / 'capability/SKILL.md').read_bytes())
        self.assertEqual(home_rows(self.home)['skills/capability/SKILL.md']['sha256'],
                         update.file_row('', (new / 'capability/SKILL.md').read_bytes())['sha256'])
        # The old release stays whole for rollback, and Skillwright's records name the new one.
        self.assertEqual(snapshot(old), old_bytes)
        with update.skill_env(self.home):
            record = scoped.validate_record(tool, new)
            state = tool.load_json(tool.STATE_FILE)
            self.assertEqual(tool.load_json(tool.DIST), record)
            self.assertEqual(tool.load_json(scoped.pin_path())['release'], record['release_id'])
            receipt = tool.load_json(tool.SHIPS / (record['release_id'] + '.json'))
            self.assertFalse((tool.STATE / 'scoped-transaction.json').exists())
        self.assertEqual(record['skills']['flow']['owner'], 'product')
        self.assertEqual(state['current']['path'], str(new))
        self.assertEqual(state['previous'], dict(kind='release', path=str(old)))
        self.assertEqual((receipt['result'], receipt['previous']['path']), ('shipped', str(old)))
        # A second update with the same product makes no new release.
        again = self.command(source / 'update.py', '--home', self.home)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), new)
        self.assertEqual(sorted(p.name for p in old.parent.iterdir()), sorted([old.name, new.name]))
        self.assert_personal()

    def test_failed_doctor_restores_the_previous_skill_release(self):
        tool, scoped, old = self.ship_shelf()
        records = self.skillwright_records()
        source = self.changed_source()
        with (source / 'skills/flow/SKILL.md').open('ab') as stream:
            stream.write(b'\nA newer product line.\n')
        refresh_row(source, 'skills/flow/SKILL.md')
        (source / 'foxrun.py').write_text('raise SystemExit(1)\n')
        refresh_row(source, 'foxrun.py')
        before = snapshot(self.home)
        result = self.command(source / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rolled back', result.stderr)
        self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), old)
        self.assertEqual(self.skillwright_records(), records)
        self.assertEqual([p.name for p in old.parent.iterdir()], [old.name])
        for name, raw in before.items():
            self.assertEqual((self.home / name).read_bytes(), raw, name)
        with update.skill_env(self.home):
            ships = [tool.load_json(path) for path in tool.SHIPS.glob('*-update.json')]
            self.assertFalse((tool.STATE / 'scoped-transaction.json').exists())
        self.assertEqual([(ship['result'], ship['rollback']) for ship in ships], [('failed', 'restored')])
        self.assert_personal()

    def test_open_skill_ship_transaction_refuses_before_any_change(self):
        tool, scoped, old = self.ship_shelf()
        with update.skill_env(self.home):
            tool.write_json(tool.STATE / 'scoped-transaction.json', dict(labeled='fake'))
        records = self.skillwright_records()
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Linked update path: ' + str(self.home / 'skills'), result.stderr)
        self.assertIn('skill-ship recover', result.stderr)
        self.assertNotIn('Update backup:', result.stdout)
        self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), old)
        self.assertEqual(self.skillwright_records(), records)

    def test_unknown_skills_link_still_refuses(self):
        outside = self.root / 'outside-skills'
        shutil.copytree(str(self.home / 'skills'), str(outside))
        shutil.rmtree(str(self.home / 'skills'))
        (self.home / 'skills').symlink_to(outside)
        outside_before = snapshot(outside)
        result = self.command(TREE / 'update.py', '--home', self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Linked update path: ' + str(self.home / 'skills'), result.stderr)
        self.assertNotIn('Update backup:', result.stdout)
        self.assertEqual(snapshot(outside), outside_before)
        self.assert_personal()

    def bumped_flow_source(self):
        source = self.changed_source()
        with (source / 'skills/flow/SKILL.md').open('ab') as stream:
            stream.write(b'\nA newer product line.\n')
        refresh_row(source, 'skills/flow/SKILL.md')
        return source

    def test_release_folders_another_user_can_write_are_refused_before_any_change(self):
        tool, scoped, old = self.ship_shelf()
        source = self.bumped_flow_source()
        records = self.skillwright_records()
        releases = self.home / 'skillwright/skill-releases'
        cases = ((releases, 0o777, 'world-writable'), (old, 0o575, 'group-writable'),
                 (self.home / 'skillwright/skill-state', 0o757, 'world-writable'))
        driver = self.accounts_driver()
        self.only_owner_writes_skillwright()
        for folder, mode, reason in cases:
            with self.subTest(folder.name):
                before = folder.stat().st_mode & 0o777
                os.chmod(str(folder), mode)
                try:
                    # A shared group, so the group-writable case refuses on a private-group host too.
                    result = self.command(driver, source, folder.stat().st_gid, json.dumps(SHARED), '--home', self.home)
                finally:
                    os.chmod(str(folder), before)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Linked update path: ' + str(self.home / 'skills'), result.stderr)
                self.assertIn(str(folder.resolve()) + ' is ' + reason, result.stderr)
                self.assertNotIn('Update backup:', result.stdout)
                self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), old)
                self.assertEqual(sorted(p.name for p in releases.iterdir()), [old.name])
                self.assertEqual(self.skillwright_records(), records)
        self.assert_personal()

    def test_release_swapped_after_its_check_is_never_shipped(self):
        # Another writer swaps bytes into the active release after the check and before the copy.
        tool, scoped, old = self.ship_shelf()
        source = self.bumped_flow_source()
        records = self.skillwright_records()
        driver = self.root / 'swap-driver.py'
        driver.write_text("""import os, shutil, sys
from pathlib import Path
source, home = sys.argv[1], sys.argv[2]
sys.path.insert(0, source)
import update
copy = shutil.copytree
def swapped(src, dst, *args, **options):
    # copytree calls itself for each subfolder; swap once, at the top of the skill.
    if Path(src).name == 'flow' and not Path(src, 'planted.sh').exists():
        os.chmod(src, 0o755)
        Path(src, 'planted.sh').write_text('echo planted (labeled fake)\\n')
        os.chmod(src, 0o555)
    return copy(src, dst, *args, **options)
update.shutil.copytree = swapped
raise SystemExit(update.main(['--source', source, '--home', home]))
""")
        result = self.command(driver, source, self.home)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('The active release changed after its check: flow', result.stderr)
        self.assertIn('rolled back', result.stderr)
        self.assertTrue((old / 'flow/planted.sh').is_file(), 'the driver ran')
        self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), old)
        self.assertEqual(sorted(p.name for p in old.parent.iterdir()), [old.name])
        self.assertEqual(self.skillwright_records(), records)
        with update.skill_env(self.home):
            self.assertEqual(list(tool.SHIPS.glob('*-update.json')), [])
            self.assertFalse((tool.STATE / 'scoped-transaction.json').exists())
        self.assert_personal()

    def test_writable_skillwright_parent_is_refused_before_any_change(self):
        tool, scoped, old = self.ship_shelf()
        source = self.bumped_flow_source()
        records = self.skillwright_records()
        parent = self.home / 'skillwright'
        releases = parent / 'skill-releases'
        driver = self.accounts_driver()
        self.only_owner_writes_skillwright()
        for mode, reason in ((0o777, 'world-writable'), (0o775, 'group-writable')):
            with self.subTest(reason):
                before = parent.stat().st_mode & 0o777
                os.chmod(str(parent), mode)
                try:
                    # A shared group, so the group-writable case refuses on a private-group host too.
                    result = self.command(driver, source, parent.stat().st_gid, json.dumps(SHARED), '--home', self.home)
                finally:
                    os.chmod(str(parent), before)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Linked update path: ' + str(self.home / 'skills'), result.stderr)
                self.assertIn(str(parent.resolve()) + ' is ' + reason, result.stderr)
                self.assertNotIn('Update backup:', result.stdout)
                self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), old)
                self.assertEqual(sorted(p.name for p in releases.iterdir()), [old.name])
                self.assertEqual(self.skillwright_records(), records)
        self.assert_personal()

    def accounts_driver(self):
        """Run the update.py in a folder with fake pwd, grp, and account files, so a test can give a
        path any group on any host. Arguments: the folder, the gid, the fake_accounts JSON, update's own."""
        driver = self.root / 'accounts-driver.py'
        driver.write_text(inspect.getsource(fake_accounts) + """
import json, sys, tempfile
tree, gid, group, args = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4:]
sys.path.insert(0, tree)
import update
(update.PASSWD_FILE, update.GROUP_FILE), update.pwd, update.grp = fake_accounts(tempfile.mkdtemp(), gid, **group)
raise SystemExit(update.main(args))
""")
        return driver

    def test_private_group_skillwright_folders_update_and_a_shared_group_refuses(self):
        tool, scoped, old = self.ship_shelf()
        source = self.bumped_flow_source()
        records = self.skillwright_records()
        parent = self.home / 'skillwright'
        releases = parent / 'skill-releases'
        driver = self.accounts_driver()
        gid = parent.stat().st_gid
        # A user with umask 002 has 0775 skillwright folders.
        folders = (parent, releases, parent / 'skill-state')
        before = {folder: folder.stat().st_mode & 0o777 for folder in folders}
        for folder in folders:
            os.chmod(str(folder), 0o775)
        self.addCleanup(lambda: [os.chmod(str(f), m) for f, m in before.items()])
        refused = [(name, group, 0o775, 'group-writable') for name, group, private in GROUPS if not private]
        refused.append(('private group, world-writable', GROUPS[0][1], 0o777, 'world-writable'))
        for name, group, mode, reason in refused:
            with self.subTest(name):
                os.chmod(str(parent), mode)
                try:
                    result = self.command(driver, source, gid, json.dumps(group), '--source', source, '--home', self.home)
                finally:
                    os.chmod(str(parent), 0o775)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(str(parent.resolve()) + ' is ' + reason, result.stderr)
                if reason == 'group-writable':
                    self.assertIn('(fix: chmod g-w ' + str(parent.resolve()) + ')', result.stderr)
                self.assertNotIn('Update backup:', result.stdout)
                self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), old)
                self.assertEqual(sorted(p.name for p in releases.iterdir()), [old.name])
                self.assertEqual(self.skillwright_records(), records)
        result = self.command(driver, source, gid, json.dumps(GROUPS[0][1]), '--source', source, '--home', self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'), result.stdout)
        new = Path(os.path.realpath(str(self.home / 'skills')))
        self.assertNotEqual(new, old)
        self.assertEqual(new.parent, releases.resolve())
        with update.skill_env(self.home):
            scoped.validate_record(tool, new)
        self.assert_personal()

    def owner_left_a_writable_file(self, tool, scoped, old):
        """The owner made one product file 0666 inside the frozen release. Its record stays valid."""
        self.writable(old)
        notes = old / 'flow/notes.md'
        notes.write_text('owner notes (labeled fake)\n')
        with update.skill_env(self.home):
            record = json.loads((old / scoped.RECORD).read_text())
            digest, count = tool.digest_tree(old / 'flow')
            record['skills']['flow'].update(digest=digest, file_count=count)
            record['digest'] = scoped.record_digest(record['skills'])
            os.chmod(str(old / scoped.RECORD), 0o644)
            tool.write_json(old / scoped.RECORD, record)
            tool.write_json(tool.DIST, record)
            tool.make_read_only(old)
            os.chmod(str(notes), 0o666)
            scoped.validate_record(tool, old)
        return notes

    def staging_window_driver(self, obey_modes):
        """At the first product file written into staging, another writer tries the copied notes.md."""
        driver = self.root / 'window-driver.py'
        driver.write_text("""import os, stat, sys
from pathlib import Path
source, home, obey = sys.argv[1], sys.argv[2], sys.argv[3] == 'obey'
sys.path.insert(0, source)
import update
write = Path.write_bytes
done = []
def spy(self, data):
    if '/.update-' in str(self) and not done:
        done.append(1)
        staging = next(p for p in Path(self).parents if p.name.startswith('.update-'))
        target = staging / 'flow/notes.md'
        folders = [staging] + [p for p in target.parents if staging in p.parents]
        # Another local user needs search on every folder and a write bit on the file.
        allowed = (all(f.stat().st_mode & stat.S_IXOTH for f in folders)
                   and target.stat().st_mode & (stat.S_IWOTH | stat.S_IWGRP))
        print('WINDOW root ' + oct(staging.stat().st_mode & 0o777) + ' file ' +
              oct(target.stat().st_mode & 0o777) + ' other user ' + ('can' if allowed else 'cannot') + ' write',
              flush=True)
        if allowed or not obey:
            with open(str(target), 'w') as stream:
                stream.write('swapped by another user (labeled fake)\\n')
    return write(self, data)
Path.write_bytes = spy
raise SystemExit(update.main(['--source', source, '--home', home]))
""")
        return driver

    def test_writable_file_in_the_active_release_cannot_be_swapped_into_the_new_release(self):
        tool, scoped, old = self.ship_shelf()
        self.owner_left_a_writable_file(tool, scoped, old)
        source = self.bumped_flow_source()
        result = self.command(self.staging_window_driver(obey_modes=True), source, self.home, 'obey')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The staging root is closed and the copy lost its write bits before any new file went in.
        self.assertIn('WINDOW root 0o700 file 0o644 other user cannot write', result.stdout)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'), result.stdout)
        new = Path(os.path.realpath(str(self.home / 'skills')))
        self.assertNotEqual(new, old)
        self.assertEqual((new / 'flow/notes.md').read_text(), 'owner notes (labeled fake)\n')
        self.assertEqual(new.stat().st_mode & 0o777, 0o555)
        self.assertEqual((new / 'flow/notes.md').stat().st_mode & 0o777, 0o444)
        with update.skill_env(self.home):
            scoped.validate_record(tool, new)
        self.assert_personal()

    def test_write_into_staging_before_the_new_digest_is_never_shipped(self):
        # A writer that ignores the modes changes a copied file after its check; the confirm after the overlay stops it.
        tool, scoped, old = self.ship_shelf()
        self.owner_left_a_writable_file(tool, scoped, old)
        source = self.bumped_flow_source()
        records = self.skillwright_records()
        result = self.command(self.staging_window_driver(obey_modes=False), source, self.home, 'force')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('WINDOW root 0o700', result.stdout)
        self.assertIn('The new release changed while update made it: flow', result.stderr)
        self.assertIn('rolled back', result.stderr)
        self.assertEqual(Path(os.path.realpath(str(self.home / 'skills'))), old)
        self.assertEqual(sorted(p.name for p in old.parent.iterdir()), [old.name])
        self.assertEqual((old / 'flow/notes.md').read_text(), 'owner notes (labeled fake)\n')
        self.assertEqual(self.skillwright_records(), records)
        with update.skill_env(self.home):
            self.assertEqual(list(tool.SHIPS.glob('*-update.json')), [])
            self.assertFalse((tool.STATE / 'scoped-transaction.json').exists())
        self.assert_personal()

    def test_stale_staging_folders_are_removed_under_the_lock(self):
        tool, scoped, old = self.ship_shelf()
        releases = self.home / 'skillwright/skill-releases'
        stale = releases / '.update-ab12cd_9'
        shutil.copytree(str(old / 'flow'), str(stale / 'flow'), symlinks=True)
        tool.make_read_only(stale)
        # Only update's own staging names are removed.
        kept = [releases / '.update-notmine', releases / 'my-notes']
        for folder in kept:
            folder.mkdir()
        (releases / '.update-zz99yy88').symlink_to(kept[1])
        driver = self.root / 'lock-driver.py'
        driver.write_text("""import sys
source, home = sys.argv[1], sys.argv[2]
sys.path.insert(0, source)
import update
remove = update.ReleaseShelf.remove_stale
def spy(shelf):
    # The lifecycle lock is held when the removal starts, so skill-ship cannot run beside it.
    with update.skill_env(shelf.home):
        try:
            with shelf.tool.lifecycle_lock():
                print('lifecycle lock free', flush=True)
        except RuntimeError:
            print('lifecycle lock held', flush=True)
    remove(shelf)
update.ReleaseShelf.remove_stale = spy
raise SystemExit(update.main(['--source', source, '--home', home]))
""")
        source = self.bumped_flow_source()
        result = self.command(driver, source, self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith('Doctor: 0 failed'), result.stdout)
        self.assertIn('lifecycle lock held', result.stdout)
        self.assertNotIn('lifecycle lock free', result.stdout)
        self.assertIn('Removed a staging folder a stopped update left: ' + str(stale), result.stdout)
        self.assertFalse(stale.exists())
        for folder in kept:
            self.assertTrue(folder.is_dir(), folder)
        self.assertTrue((releases / '.update-zz99yy88').is_symlink())
        new = Path(os.path.realpath(str(self.home / 'skills')))
        self.assertNotEqual(new, old)
        self.assertEqual(sorted(p.name for p in releases.iterdir()),
                         sorted(['.update-notmine', '.update-zz99yy88', 'my-notes', old.name, new.name]))
        self.assert_personal()

if __name__ == '__main__':
    unittest.main()
