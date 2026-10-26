#!/usr/bin/env python3
"""Verify workspace database selection without exposing owner rows."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--tree', type=Path, default=Path(__file__).resolve().parents[2])
options, unittest_args = parser.parse_known_args()
TREE = options.tree.resolve()


class WorkspaceDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Launch fix rel (fbf6a7c): start reads the full tracker shape (project, parent, created_on ...).
        # A hand-made three-column table no longer starts, so every fixture copies one real build.
        cls.built = tempfile.TemporaryDirectory(prefix='.workspace-db-build-')
        cls.template = Path(cls.built.name) / 'data.db'
        subprocess.run(['/usr/bin/python3', '-B', str(TREE / 'base/build_database.py'), str(cls.template),
                        '--modules', 'work', '--by', 'test'], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.built.cleanup()

    def setUp(self):
        parent = Path(os.environ.get('FOXRUN_TEST_ROOT', str(Path(__file__).resolve().parent)))
        self.temp = tempfile.TemporaryDirectory(prefix='.workspace-db-test-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home, self.portfolio = self.root / 'system', self.root / 'portfolio'
        (self.home / 'config').mkdir(parents=True)
        (self.home / 'config/person.json').write_text(json.dumps({'name':'Avery','default_workspace':'alpha'}))
        shutil.copyfile(TREE / 'config/models.yaml', self.home / 'config/models.yaml')
        for workspace in ('alpha','beta'):
            folder = self.portfolio / workspace
            folder.mkdir(parents=True)
            (folder / 'STATE.md').write_text('Fixture state.\n')
        self.db(self.home / 'data.db', 'SYSTEM')
        self.env = {k:v for k,v in os.environ.items() if not k.startswith('FOXRUN_') and k not in ('PYTHONPATH','PYTHONHOME')}
        self.env.update(HOME=str(self.root),TMPDIR=str(self.root),PYTHONDONTWRITEBYTECODE='1',
                        FOXRUN_HOME=str(self.home),FOXRUN_PORTFOLIO=str(self.portfolio),FOXRUN_PERSON='Avery')
        if os.environ.get('PYTHONPATH'):
            self.env['PYTHONPATH'] = os.environ['PYTHONPATH']

    def db(self, path, identifier):
        shutil.copyfile(self.template, path)
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO tasks(id,title,status) VALUES(?,?,?)',(identifier,'Fixture task','todo'))

    def start(self, workspace, expected=0):
        result = subprocess.run(['/usr/bin/python3','-B',str(TREE / 'foxrun.py'),'start','--workspace',workspace],
                                env=self.env,cwd=self.root,text=True,capture_output=True)
        self.assertEqual(expected, result.returncode)
        return result.stdout

    def test_system_fallback(self):
        self.assertIn('  SYSTEM:', self.start('alpha'))

    def test_workspace_database_wins(self):
        self.db(self.portfolio / 'alpha/data.db','ALPHA')
        output = self.start('alpha')
        self.assertIn('  ALPHA:',output)
        self.assertNotIn('  SYSTEM:',output)

    def test_two_workspaces_are_separate(self):
        self.db(self.portfolio / 'alpha/data.db','ALPHA')
        self.db(self.portfolio / 'beta/data.db','BETA')
        for name, present, absent in (('alpha','ALPHA','BETA'),('beta','BETA','ALPHA')):
            output = self.start(name)
            self.assertIn('  ' + present + ':',output)
            self.assertNotIn('  ' + absent + ':',output)

    def test_read_does_not_change_database(self):
        path = self.portfolio / 'beta/data.db'
        self.db(path,'BETA')
        before = hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns
        self.start('beta')
        self.assertEqual(before,(hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns))

    def test_workspace_database_symlink_is_refused(self):
        (self.portfolio / 'beta/data.db').symlink_to(self.home / 'data.db')
        self.start('beta',1)

    def test_invalid_workspace_database_is_not_silently_replaced(self):
        (self.portfolio / 'beta/data.db').write_bytes(b'not a database')
        self.start('beta',1)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0],*unittest_args])
