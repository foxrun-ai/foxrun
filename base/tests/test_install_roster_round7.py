"""Fresh installs persist their roster for subsequent command connections."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing, redirect_stderr
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from base import person, install_workspace
from base.distribution import sample_workspace, install

ROOT = Path(__file__).resolve().parents[2]


def manifest_plan(root, database=None, actor=None, addons=(), modules_root=ROOT):
    target, live = root / 'target', root / 'live'
    target.mkdir(exist_ok=True); live.mkdir(exist_ok=True)
    values = {}
    for module in install_workspace.BASE_MODULES:
        manifest, _ = install_workspace.load_manifest(ROOT, module)
        for entry in manifest['files']:
            for key in install_workspace.PLACEHOLDER.findall((ROOT / module / entry['from']).read_text()):
                values[key] = 'fixture-' + key
    values.pop('approved_tags', None); values.pop('timestamp', None)
    values.update(workspace='cedar-shop', workspace_purpose='Made-up garden tools')
    return install_workspace.plan_install(modules_root=modules_root, target=target, live_vault=live,
        workspace_type='personal', raw_modules=','.join(sorted(install_workspace.BASE_MODULES | set(addons))),
        values=values, target_workspace='cedar-shop', install_timestamp='2026-01-01T00:00:00Z',
        approved_tags=[], database=database, actor=actor)


def database_files(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob('*')
                  if p.suffix in ('.db', '.sqlite', '.sqlite3') or p.name.endswith(('-wal', '-shm')))


class InstallRoster(unittest.TestCase):
    def test_sample_reopened_roster(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME': folder, 'FOXRUN_PERSON': 'avery'}):
            path = Path(folder) / 'data.db'
            fixture = json.loads((ROOT / 'base/distribution/sample/rows.json').read_text())
            sample_workspace.build_database(ROOT / 'base', fixture, path).close()
            with closing(person.connect(path)) as db:
                self.assertEqual(db.execute("SELECT foxrun_workspace_allowed('cedar-shop')").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT foxrun_workspace_allowed('unknown-workspace')").fetchone()[0], 0)

    def test_distribution_work_create_known_and_unknown(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME': folder, 'FOXRUN_PERSON': 'avery'}):
            root = Path(folder).resolve()
            install.install(root, 'round7-test')
            db = root / '.local/share/foxrun/data.db'
            # b52bd2f: add-only refuses dictionary UPDATEs; this fixture needs only work tables.
            with closing(person.connect(db)) as con:
                con.executescript((ROOT / 'work/blueprint.sql').read_text())
            (root / 'portfolio/cedar-shop').mkdir(parents=True)
            (root / 'portfolio/cedar-shop/STATE.md').write_text('Fixture state.\n')
            env = dict(os.environ, HOME=folder, FOXRUN_HOME=folder, FOXRUN_PERSON='avery', FOXRUN_PORTFOLIO=str(root / 'portfolio'))
            args = ['/usr/bin/python3', '-B', str(ROOT / 'work/work.py'), '--db', str(db),
                    '--receipt-root', str(root), 'create', '--title', 'Check the garden trowel',
                    '--by', 'avery', '--session', 'fixture-session',
                    # g-every-task-carries-the-six-fields-a-spec-is-a-parent-task (404941a).
                    '--problem', 'The trowel needs a check', '--job-when', 'When work starts',
                    '--job-want', 'I want one task', '--job-so', 'So I can check the trowel',
                    '--body', 'Check the garden trowel', '--acceptance', 'The task exists',
                    '--context', 'Fixture garden', '--where', str(root / 'portfolio/cedar-shop/STATE.md'),
                    '--workspace']
            accepted = subprocess.run(args + ['cedar-shop'], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            with closing(person.connect(db)) as con:
                columns = {row[1] for row in con.execute('PRAGMA table_info("runs")')}
                table = 'work_tasks' if 'actor' in columns else 'tasks'
                self.assertEqual(con.execute('SELECT count(*) FROM "' + table + '" WHERE title=?',
                    ('Check the garden trowel',)).fetchone()[0], 1)
                if table == 'work_tasks':
                    self.assertEqual(con.execute("SELECT count(*) FROM work_changes WHERE subject_type='task' AND action='created'").fetchone()[0], 1)
                    self.assertEqual(con.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
            before = db.read_bytes()
            refused = subprocess.run(args + ['unknown-workspace'], cwd=root, env=env, text=True, capture_output=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(db.read_bytes(), before)

    def test_manifest_installer_with_an_addon_builds_no_workspace_database(self):
        # T714: one database, the system data.db. An add-on turned on adds no database to a workspace.
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME': folder, 'FOXRUN_PERSON': 'avery'}), \
                patch.object(install_workspace.pack_policy, 'ships', lambda manifest: True):
            root = Path(folder).resolve()
            # The product ships no add-on; a local one sits in modules/<name> beside the core folders.
            tree = root / 'tree'
            for part in install_workspace.BASE_MODULES:
                shutil.copytree(ROOT / part, tree / part, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
            addon = tree / 'modules/sample-addon'
            addon.mkdir(parents=True)
            (addon / 'install.json').write_text('{"files": [], "blueprint": true}\n')
            (addon / 'blueprint.sql').write_text('CREATE TABLE IF NOT EXISTS sample_rows (id TEXT PRIMARY KEY);\n')
            plan = manifest_plan(root, addons=('sample-addon',), modules_root=tree)
            self.assertIn('sample-addon', plan['modules'])
            self.assertIsNone(plan['database'])
            install_workspace.apply_plan(plan)
            self.assertTrue((root / 'target/AGENTS.md').is_file())
            self.assertEqual(database_files(root / 'target'), [])

    @unittest.skipUnless((ROOT / 'modules/commerce/blueprint.sql').is_file() and (ROOT / 'install.py').is_file(),
                         'needs the product tree with the commerce add-on source')
    def test_install_with_an_addon_puts_its_tables_in_the_system_database(self):
        # T714: turn on the commerce add-on in a copy of the product; install.py's build path takes it to data.db.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            core, home, portfolio, user = root / 'core', root / 'system', root / 'portfolio', root / 'user'
            user.mkdir()
            # Only the product tree has install.py (see the skip); an installed home is never copied.
            shutil.copytree(ROOT, core, ignore=shutil.ignore_patterns('__pycache__', '*.db', '*.sqlite', '*-wal', '*-shm'))
            pack = core / 'modules/commerce/install.json'
            data = json.loads(pack.read_text())
            data.pop('ships')
            pack.write_text(json.dumps(data, indent=2) + '\n')
            manifest = core / 'product-manifest.tsv'
            with manifest.open(newline='') as stream:
                rows = {row['path']: row for row in csv.DictReader(stream, delimiter='\t')}
            for path in sorted((core / 'modules/commerce').rglob('*')):
                if path.is_file():
                    raw = path.read_bytes()
                    name = path.relative_to(core).as_posix()
                    rows[name] = {'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            with manifest.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=('path', 'bytes', 'sha256'), delimiter='\t', lineterminator='\n')
                writer.writeheader()
                writer.writerows(rows[name] for name in sorted(rows))
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('FOXRUN_') and key not in ('PYTHONPATH', 'PYTHONHOME')}
            env.update(HOME=str(user), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run(['/usr/bin/python3', '-B', str(core / 'install.py'), '--yes',
                                     '--workspace', 'cedar-shop', '--home', str(home), '--portfolio', str(portfolio)],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((home / 'modules/commerce/install.json').is_file())
            self.assertEqual(database_files(portfolio), [])
            self.assertEqual(database_files(home), ['data.db'])
            with closing(sqlite3.connect(str(home / 'data.db'))) as db:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                modules = {row[0] for row in db.execute('SELECT name FROM base_modules')}
            self.assertIn('commerce', modules)
            self.assertTrue(any(name.startswith('commerce_') for name in tables), sorted(tables))

    def test_manifest_installer_refuses_every_database_step(self):
        # T714: a relative workspace file, the system data.db, or another workspace's data.db: all refused, nothing written.
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME': folder, 'FOXRUN_PERSON': 'avery'}):
            root = Path(folder).resolve()
            other = root / 'other-workspace'
            other.mkdir()
            (other / 'data.db').write_bytes(b'existing tracker')
            for database in ('data.db', 'db/cedar-shop.sqlite', str(root / 'data.db'), str(other / 'data.db')):
                with self.subTest(database=database):
                    with self.assertRaisesRegex(install_workspace.InstallError, 'no database of its own'):
                        manifest_plan(root, database=database, actor='installer', addons=())
                    self.assertEqual(list((root / 'target').iterdir()), [])
                    self.assertFalse((root / 'data.db').exists())
            self.assertEqual((other / 'data.db').read_bytes(), b'existing tracker')
            plan = manifest_plan(root)
            edited = dict(plan, database={'destination': 'data.db', 'action': 'build-new-database'})
            edited['plan_sha256'] = install_workspace.plan_hash(edited)
            with self.assertRaisesRegex(install_workspace.InstallError, 'plan has a database step'):
                install_workspace.apply_plan(edited)
            self.assertEqual(list((root / 'target').iterdir()), [])
            (root / 'values.json').write_text('{}')
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                cli = install_workspace.main(['--modules-root', str(ROOT), '--workspace-type', 'personal',
                    '--modules', 'base,work,people,memory', '--target-workspace', 'cedar-shop',
                    '--install-timestamp', '2026-01-01T00:00:00Z', '--approved-tags', '[]',
                    '--target', str(root / 'target'), '--live-vault-root', str(root / 'live'),
                    '--values-json', str(root / 'values.json'), '--plan-out', str(root / 'plan.json'),
                    '--database', 'data.db', '--by', 'installer'])
            self.assertEqual(cli, 2)
            self.assertIn('no database of its own', stderr.getvalue())
            self.assertFalse((root / 'plan.json').exists())
            self.assertEqual(database_files(root), ['other-workspace/data.db'])


if __name__ == '__main__':
    unittest.main()
