"""Planted dependencies and offline rename tests; all data are synthetic."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

import reader_check as check


class ReaderCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base/'source'; self.source.mkdir()
        self.live = self.base/'live'; self.live.mkdir()
        self.database = self.live/'service-example.db'
        with sqlite3.connect(self.database) as conn:
            conn.execute('CREATE TABLE people (id INTEGER PRIMARY KEY)')
        self.out = self.base/'output'; self.scratch = self.base/'trial'
        self.plan = {'work_lead': 'test lead', 'thing': {'kind': 'table', 'name': 'people', 'database': str(self.database)},
                     'roots': [{'path': str(self.source), 'program': 'sample', 'database': str(self.database)}]}

    def write(self, name, text):
        p = self.source/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        return p

    def run_check(self, execute=False):
        return check.check(self.plan, self.out, self.scratch, execute)

    def test_script_sql_is_a_confirmed_reader(self):
        self.write('reader.py', 'conn.execute("SELECT * FROM people")\n')
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(any(r['access']=='read' and r['sure']=='yes' for r in result['blocking_readers']))

    def test_concatenated_name_and_f_string_are_found(self):
        self.write('reader.py', 'table = "peo" + "ple"\nconn.execute(f"SELECT * FROM {table}")\n')
        _, result = self.run_check()
        self.assertEqual([(r['line'], r['sure']) for r in result['blocking_readers']], [(2, 'yes')])

    def test_multiline_sql_points_to_the_table_line(self):
        self.write('reader.py', 'conn.execute("""\nSELECT *\nFROM people\n""")\n')
        _, result=self.run_check()
        self.assertTrue(any(r['line']==3 and r['sure']=='yes' for r in result['blocking_readers']))

    def test_list_f_string_reader_is_found(self):
        self.write('reader.py', 'tables = ["people"]\nfor table in tables:\n    conn.execute(f"DELETE FROM {table}")\n')
        _, result = self.run_check()
        self.assertTrue(any(r['line']==3 and r['access']=='write' for r in result['blocking_readers']))

    def test_skill_and_launchagent_are_visible_without_values(self):
        skill = self.write('SKILL.md', 'Before using people, run the service.\n')
        self.write('job.plist', '<plist><dict><key>ProgramArguments</key><array><string>/bin/worker</string><string>people</string><string>PRIVATE_CANARY</string></array></dict></plist>')
        self.plan['roots'][0]['role'] = 'skill'
        _, result = self.run_check()
        self.assertEqual({Path(r['path']).name for r in result['blocking_readers']}, {'SKILL.md', 'job.plist'})
        self.assertNotIn('PRIVATE_CANARY', (self.out/'readers.csv').read_text()+(self.out/'verdict.json').read_text())

    def test_common_name_requires_hash_bound_confirmation(self):
        p = self.write('other.py', 'people = []\n')
        code, result = self.run_check()
        self.assertEqual(code, 1); self.assertEqual(result['blocking_readers'][0]['sure'], 'needs a look')
        self.plan['confirmations'] = [{'path': str(p), 'line': 1, 'decision': 'unrelated',
                                      'by': 'test lead', 'at': '2026-10-06T21:00:00+00:00',
                                      'reason': 'local list, no database connection', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}]
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(result['verdict'], 'search found no reader; not proven by a dry test')
        with (self.out/'readers.csv').open() as handle:
            self.assertEqual(list(csv.DictReader(handle))[0]['sure'], 'no')

    def test_stale_confirmation_refuses(self):
        p = self.write('other.py', 'people = []\n')
        self.plan['confirmations'] = [{'path': str(p), 'line': 1, 'decision': 'unrelated', 'reason': 'list', 'sha256': 'stale'}]
        code, result = self.run_check()
        self.assertEqual(code, 1); self.assertTrue(result['scan_gaps'])

    def test_sql_without_database_context_needs_a_look(self):
        self.plan['roots'][0].pop('database')
        self.write('reader.py', 'conn.execute("SELECT * FROM people")\n')
        _, result = self.run_check()
        self.assertEqual(result['blocking_readers'][0]['sure'], 'needs a look')

    def test_database_only_and_orm_references_are_not_missed(self):
        self.plan['thing']['name']='people_accounts'
        self.write('reader.py', 'from service_example import feedback\nPeopleAccount.query.all()\n')
        _, result=self.run_check()
        self.assertEqual({r['line'] for r in result['blocking_readers']}, {1, 2})
        self.assertTrue(all(r['sure']=='needs a look' for r in result['blocking_readers']))

    def test_hidden_source_is_searched_but_secrets_and_dependencies_are_excluded(self):
        self.write('.hidden/reader.py', 'conn.execute("SELECT * FROM people")\n')
        self.write('.env', 'PRIVATE_CANARY=people\n')
        self.write('node_modules/lib.js', 'SELECT * FROM people')
        _, result = self.run_check()
        readers = [r for r in result['blocking_readers'] if r['access']!='unsearched']
        self.assertEqual(len(readers), 1)
        self.assertIn('.hidden', readers[0]['path'])
        self.assertEqual(len(result['unconfirmed_skipped']), 1)

    def test_broken_symlink_is_a_scan_gap(self):
        (self.source/'missing.py').symlink_to(self.source/'absent.py')
        code, result = self.run_check()
        self.assertEqual(code, 1); self.assertTrue(result['scan_gaps'])

    def test_symlink_cycle_does_not_hang(self):
        (self.source/'cycle').symlink_to(self.source, target_is_directory=True)
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(result['verdict'], 'search found no reader; not proven by a dry test')

    def test_settings_emit_identifier_locations_only(self):
        self.write('settings.json', '{"private": "PRIVATE_CANARY", "table": "people"}')
        _, result = self.run_check()
        self.assertEqual(result['blocking_readers'][0]['sure'], 'needs a look')
        self.assertNotIn('PRIVATE_CANARY', json.dumps(result))

    def test_local_settings_and_backups_do_not_enter_test_copy(self):
        for name in ['settings.local.json', 'settings.json.bak', 'config.toml.bak', '.claude.json']:
            self.write(name, '{"private":"PRIVATE_CANARY"}')
        target=self.base/'copied'
        check.copy_workspace(self.source,target)
        self.assertEqual(list(target.iterdir()), [])

    def test_unsafe_output_location_is_refused(self):
        with self.assertRaises(check.InvalidPlan):
            check.check(self.plan, self.source/'output', self.scratch)

    def test_missing_root_does_not_claim_no_readers(self):
        self.plan['roots'] = [str(self.base/'missing')]
        code, result = self.run_check()
        self.assertEqual(code, 1); self.assertTrue(result['scan_gaps'])

    def test_cli_error_does_not_print_plan_values(self):
        plan = self.base/'plan.json'; plan.write_text('{"PRIVATE_CANARY": true}')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check.main(['--plan', str(plan), '--out', str(self.out)])
        self.assertEqual(code, 2); self.assertNotIn('PRIVATE_CANARY', out.getvalue())

    def add_test(self, code, env=None):
        self.write('probe.py', code)
        self.plan['readers'] = [{'program': 'sample', 'workspace': str(self.source), 'offline': True,
                                'commands': [[sys.executable, 'probe.py', '{copy}']], 'env': env or {}}]

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('sandbox-exec'), 'requires macOS sandbox')
    def test_table_rename_breaks_test_and_leaves_source_unchanged(self):
        self.add_test('import sqlite3,sys\nprint("PRIVATE_CANARY")\nconn=sqlite3.connect(sys.argv[1])\nconn.execute("SELECT * FROM people")\n')
        original = self.database.read_bytes()
        code, result = self.run_check(True)
        self.assertEqual(code, 1)
        self.assertEqual([t['exit_code']==0 for t in result['tests']], [True, False])
        self.assertEqual(original, self.database.read_bytes())
        self.assertNotIn('PRIVATE_CANARY', json.dumps(result))

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('sandbox-exec'), 'requires macOS sandbox')
    def test_startup_recreation_refuses_even_when_tests_pass(self):
        self.add_test('import sqlite3,sys\nwith sqlite3.connect(sys.argv[1]) as c: c.execute("CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY)")\n')
        code, result = self.run_check(True)
        self.assertEqual(code, 1)
        self.assertTrue(all(t['exit_code']==0 for t in result['tests']))
        self.assertTrue(result['tests'][-1]['old_table_recreated'])

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('sandbox-exec'), 'requires macOS sandbox')
    def test_sandbox_refuses_external_write(self):
        outside = self.base/'outside.txt'
        self.add_test('import os,pathlib\npathlib.Path(os.environ["DEST"]).write_text("synthetic")\n', {'DEST': str(outside)})
        code, result = self.run_check(True)
        self.assertEqual(code, 1); self.assertFalse(outside.exists())
        self.assertTrue(all(t['exit_code'] for t in result['tests']))

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('sandbox-exec'), 'requires macOS sandbox')
    def test_sandbox_denies_network_with_permission_error(self):
        self.add_test('import socket\ntry: socket.create_connection(("127.0.0.1", 9), timeout=1)\nexcept OSError as error: assert error.errno == 1\nelse: raise AssertionError("network was not denied")\n')
        _, result = self.run_check(True)
        self.assertTrue(all(t['exit_code']==0 for t in result['tests']))

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('sandbox-exec'), 'requires macOS sandbox')
    def test_file_folder_and_program_rename_only_copied_target(self):
        for kind in ['file', 'folder', 'program']:
            with self.subTest(kind=kind):
                target = self.source/kind
                if kind=='folder': target.mkdir()
                else: target.write_text('synthetic')
                self.plan['thing'] = {'kind': kind, 'name': kind, 'path': str(target)}
                self.add_test('import pathlib,sys\np=pathlib.Path(sys.argv[1])\nassert p.name.endswith("__moved") is False\n')
                self.scratch = self.base/('trial-'+kind)
                code, result = self.run_check(True)
                self.assertEqual(code, 1)
                self.assertEqual([t['exit_code']==0 for t in result['tests']], [True, False])
                self.assertTrue(target.exists())

    def test_configured_tests_not_run_refuses_clearance(self):
        self.add_test('print("synthetic")\n')
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn('configured reader tests were not run', result['reasons'])


if __name__=='__main__':
    unittest.main()
