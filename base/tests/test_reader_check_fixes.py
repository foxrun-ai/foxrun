"""Review-round planted cases. All input values are synthetic."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import reader_check as rc


class FixTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()  # reader_check reports resolved paths; macOS /var is a symlink
        self.src = self.base/'src'; self.src.mkdir()
        self.db = self.base/'live'/'service-example.db'; self.db.parent.mkdir()
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE people (id INTEGER PRIMARY KEY)')
        self.out = self.base/'out'; self.scratch = self.base/'trial'
        self.plan = {'thing': {'kind': 'table', 'name': 'people', 'database': str(self.db)},
                     'roots': [{'path': str(self.src), 'program': 'sample', 'database': str(self.db)}],
                     'work_lead': 'test lead'}

    def write(self, name, text):
        p = self.src/name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def run_check(self, tests=False):
        return rc.check(self.plan, self.out, self.scratch, tests)

    def confirmation(self, p, line=1, **changes):
        c = {'path': str(p), 'line': line, 'decision': 'unrelated', 'reason': 'synthetic lead review',
             'by': 'test lead', 'at': '2026-10-06T21:00:00+00:00'}
        if line:
            c['sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
        return {**c, **changes}

    def test_skipped_places_refuse_without_opening_private_content(self):
        names = ['auth.json', 'token.json', 'agent-secret-read', '.env', '.envrc', '.env.example',
                 'logs/r.py', 'sessions/r.py', 'raw/r.py', 'build/r.py', 'dist/r.py',
                 'target/r.py', 'vendor/r.py', 'coverage/r.py', 'tool.bin']
        for name in names:
            with self.subTest(place=name):
                root = self.base/name.replace('/', '-'); root.mkdir()
                p = root/name; p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'\0SELECT * FROM people' if name=='tool.bin' else b'SELECT * FROM people')
                self.plan['roots'] = [{'path': str(root), 'program': 'sample'}]
                real_read = Path.read_bytes
                real_open = Path.open
                def guarded_read(path):
                    if path == p and name != 'tool.bin':
                        raise AssertionError('private content opened')
                    return real_read(path)
                def guarded_open(path, *args, **kwargs):
                    if path == p and name != 'tool.bin':
                        raise AssertionError('private content opened')
                    return real_open(path, *args, **kwargs)
                with patch.object(Path, 'read_bytes', guarded_read), patch.object(Path, 'open', guarded_open):
                    code, v = self.run_check()
                self.assertEqual(code, 1)
                self.assertTrue(v['unconfirmed_skipped'])

    def test_whole_words_keep_tokenizer_authors_and_secretary_searchable(self):
        for name in ['tokenizer.py', 'authors/r.py', 'author_feed.py', 'secretary.py']:
            self.write(name, 'conn.execute("SELECT * FROM people")\n')
        _, v = self.run_check()
        self.assertEqual(len(v['blocking_readers']), 4)

    def test_each_skipped_place_needs_a_lead_confirmation(self):
        p = self.write('.env', 'never read this')
        q = self.write('auth.json', 'never read this either')
        self.plan['confirmations'] = [self.confirmation(p, line=0)]
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual([s['path'] for s in v['unconfirmed_skipped']], [str(q)])
        self.plan['confirmations'].append(self.confirmation(q, line=0))
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertFalse(v['unconfirmed_skipped'])

    def test_dynamic_sql_join_needs_a_look(self):
        self.write('r.py', 't = "".join(["peo", "ple"])\nconn.execute(f"SELECT * FROM {t}")\n')
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(any(r['line']==2 and r['sure']=='needs a look' for r in v['blocking_readers']))

    def test_dynamic_sql_format_needs_a_look(self):
        self.write('r.py', 'conn.execute("SELECT * FROM {}{}".format("peo", "ple"))\n')
        self.assert_dynamic()

    def test_dynamic_sql_percent_needs_a_look(self):
        self.write('r.py', 'T = "peo%s" % "ple"\nconn.execute("SELECT * FROM %s" % T)\n')
        self.assert_dynamic()

    def test_dynamic_sql_dict_needs_a_look(self):
        self.write('r.py', 'T = {"p": "peo" + "ple"}\nconn.execute("SELECT * FROM " + T["p"])\n')
        self.assert_dynamic()

    def test_dynamic_sql_attribute_needs_a_look(self):
        self.write('r.py', 'class M:\n    table = "peo" "ple"\n    def all(self, c):\n        return c.execute(f"SELECT * FROM {self.table}")\n')
        self.assert_dynamic()

    def test_dynamic_sql_js_join_needs_a_look(self):
        self.write('r.js', 'const t = ["peo","ple"].join("");\ndb.prepare(`SELECT * FROM ${t}`).all();\n')
        self.assert_dynamic()

    def test_dynamic_sql_partial_known_branch_needs_a_look(self):
        self.write('r.py', 't = "other" if flag else runtime_name\nconn.execute(f"SELECT * FROM {t}")\n')
        self.assert_dynamic()

    def test_dynamic_sql_js_concat_and_variable_need_a_look(self):
        self.write('r.js', 'const t = ["peo", "ple"].join("");\nconst sql = "SELECT * FROM " + t;\ndb.prepare(sql);\n')
        self.assert_dynamic()

    def assert_dynamic(self):
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(any(r['sure']=='needs a look' for r in v['blocking_readers']))

    def test_unrelated_cannot_clear_proven_sql(self):
        p = self.write('r.py', 'conn.execute("SELECT * FROM people")\n')
        self.plan['confirmations'] = [self.confirmation(p)]
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['blocking_readers'][0]['sure'], 'yes')
        self.assertTrue(v['scan_gaps'])

    def test_output_cannot_enter_thing_or_overwrite_checked_file(self):
        folder = self.base/'thing'; folder.mkdir()
        target = folder/'verdict.json'; target.write_text('synthetic original')
        for kind, path in [('folder', folder), ('file', target), ('program', target)]:
            with self.subTest(kind=kind):
                self.plan['thing'] = {'kind': kind, 'name': path.name, 'path': str(path)}
                with self.assertRaises(rc.InvalidPlan):
                    rc.check(self.plan, folder, self.scratch)
                self.assertEqual(target.read_text(), 'synthetic original')

    def test_output_protects_vault_and_code(self):
        home = self.base/'home'; home.mkdir()
        with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {'FOXRUN_PORTFOLIO': str(home/'foxrun')}):
            for name in ['foxrun', 'Code']:
                with self.subTest(place=name), self.assertRaises(rc.InvalidPlan):
                    rc.check(self.plan, home/name/'out', self.scratch)

    def test_output_protects_checked_symlink_destination(self):
        linked = self.base/'linked'; linked.mkdir()
        (self.src/'link').symlink_to(linked, target_is_directory=True)
        with self.assertRaises(rc.InvalidPlan):
            rc.check(self.plan, linked/'out', self.scratch)

    def test_output_refuses_report_file_link_into_checked_source(self):
        p = self.write('keep.py', 'synthetic original')
        self.out.mkdir()
        (self.out/'verdict.json').symlink_to(p)
        with self.assertRaises(rc.InvalidPlan):
            self.run_check()
        self.assertEqual(p.read_text(), 'synthetic original')

    def test_settings_without_rg_is_confirmable_and_hides_values(self):
        p = self.write('config.yaml', 'value: SYNTHETIC_PRIVATE_CANARY\ntables: [people, peoples]\n')
        with patch.object(shutil, 'which', return_value=None):
            code, v = self.run_check()
            self.assertEqual(code, 1)
            self.assertFalse(v['scan_gaps'])
            self.assertEqual(v['blocking_readers'][0]['line'], 2)
            self.plan['confirmations'] = [self.confirmation(p, line=2)]
            code, v = self.run_check()
            self.assertEqual(code, 1)
            self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', ''.join(p.read_text() for p in self.out.iterdir()))

    def test_confirmation_requires_by_and_at(self):
        p = self.write('r.py', 'people = []\n')
        for missing in ['by', 'at']:
            with self.subTest(missing=missing):
                c = self.confirmation(p); c.pop(missing)
                self.plan['confirmations'] = [c]
                code, v = self.run_check()
                self.assertEqual(code, 1)
                self.assertTrue(v['scan_gaps'])

    def test_confirmation_records_by_at_reason_in_csv_and_verdict(self):
        p = self.write('r.py', 'people = []\n')
        c = self.confirmation(p); self.plan['confirmations'] = [c]
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        saved_verdict = json.loads((self.out/'verdict.json').read_text())
        self.assertIn('confirmations', saved_verdict)
        saved = saved_verdict['confirmations'][0]
        with (self.out/'readers.csv').open() as handle:
            row = list(csv.DictReader(handle))[0]
        for key in ['by', 'at', 'reason']:
            self.assertEqual(saved[key], c[key])
            self.assertEqual(row['confirmation_'+key], c[key])

    def test_confirmation_only_named_work_lead_and_valid_time(self):
        p = self.write('r.py', 'people = []\n')
        for changes in [{'by': 'scanner agent'}, {'at': 'yesterday'}]:
            with self.subTest(change=changes):
                self.plan['confirmations'] = [self.confirmation(p, **changes)]
                code, v = self.run_check()
                self.assertEqual(code, 1)
                self.assertTrue(v['scan_gaps'])

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('sandbox-exec'), 'requires macOS sandbox')
    def test_external_file_folder_program_copies_and_writes_report(self):
        for kind in ['file', 'folder', 'program']:
            with self.subTest(kind=kind):
                target = self.base/kind
                if kind=='folder': target.mkdir(); (target/'keep').write_text('synthetic')
                else: target.write_text('synthetic')
                self.plan['thing'] = {'kind': kind, 'name': target.name, 'path': str(target)}
                self.write('probe.py', 'import pathlib,sys\nassert pathlib.Path(sys.argv[1]).exists()\nassert pathlib.Path(sys.argv[2]).exists()\n')
                self.plan['readers'] = [{'program': 'sample', 'workspace': str(self.src), 'offline': True,
                                        'commands': [[sys.executable, 'probe.py', '{copy}', '{original}']]}]
                self.scratch = self.base/('trial-'+kind)
                try:
                    code, v = self.run_check(True)
                except Exception:
                    self.fail('external target setup did not save a verdict')
                self.assertEqual(code, 1)
                self.assertTrue((self.out/'verdict.json').exists())
                self.assertEqual([t['exit_code']==0 for t in v['tests']], [True, False])
                self.assertTrue(target.exists())

    def test_program_module_import_without_alias(self):
        self.plan['thing'] = {'kind': 'program', 'name': 'small-talk'}
        self.write('r.py', 'from small_talk import feedback\n')
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['blocking_readers'][0]['line'], 1)

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('sandbox-exec'), 'requires macOS sandbox')
    def test_private_scratch_copy_paths_are_listed(self):
        self.write('probe.py', 'import sys\n')
        self.plan['readers'] = [{'program': 'sample', 'workspace': str(self.src), 'offline': True,
                                'commands': [[sys.executable, 'probe.py', '{copy}']]}]
        _, v = rc.check(self.plan, self.out, self.scratch, True,
                        keep_copies=True, keep_copies_by=self.plan['work_lead'])
        db_copies = {str(p) for p in self.scratch.rglob('*.db')}
        self.assertEqual(len(db_copies), 3)
        self.assertIn('private_scratch_copies', v)
        self.assertTrue(db_copies.issubset(set(v['private_scratch_copies'])))

    def test_test_setup_failure_still_writes_refusal_and_copy_paths(self):
        self.plan['readers'] = [{'program': 'sample', 'workspace': str(self.src), 'offline': True, 'commands': []}]
        try:
            code, v = self.run_check(True)
        except Exception:
            self.fail('test setup error did not save a verdict')
        self.assertNotEqual(code, 0)
        self.assertTrue((self.out/'verdict.json').exists())
        self.assertEqual(v['verdict'], 'refused')


class Round2Tests(unittest.TestCase):
    setUp = FixTests.setUp
    write = FixTests.write
    run_check = FixTests.run_check
    confirmation = FixTests.confirmation

    def test_dependency_trees_and_data_are_listed_without_confirmation(self):
        import subprocess
        subprocess.run(['git', 'init', '-q', str(self.src)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        for name in ['node_modules/p/i.js', '.venv/lib/a.py', '__pycache__/a.pyc',
                     'logo.png', 'uv.lock', 'store.db', 'file.map']:
            self.write(name, 'synthetic ignored input')
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertFalse(v['unconfirmed_skipped'])
        scan = json.loads((self.out/'scan.json').read_text())
        self.assertEqual(len(scan['skipped']), 8)
        self.assertTrue(all(s['requires_confirmation'] is False for s in scan['skipped']))
        self.assertFalse(v['blocking_readers'])

    def test_private_data_name_keeps_confirmation_priority(self):
        self.write('auth.png', 'never open this')
        _, v = self.run_check()
        scan = json.loads((self.out/'scan.json').read_text())
        self.assertIn('requires_confirmation', scan['skipped'][0])
        self.assertTrue(scan['skipped'][0]['requires_confirmation'])
        self.assertEqual(len(v['unconfirmed_skipped']), 1)

    def test_six_non_sql_javascript_lines_have_no_row(self):
        lines = ['const s = parts.join(", ") + tail;', 'import x from "./a" + b;',
                 'console.log(`update ${n} of ${m}`);', 'const next = items.join("") + 1;',
                 'el.textContent = `from ${a} to ${b}`;', 'if (i + 1 < n) remove.delete(key);']
        for i, line in enumerate(lines):
            with self.subTest(case=i):
                self.write('u.js', line+'\n')
                code, v = self.run_check()
                self.assertEqual(code, 1)
                self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
                self.assertFalse(v['blocking_readers'])

    def test_sql_verb_after_built_part_does_not_make_a_row(self):
        self.write('u.js', 'console.log(`${value} update FROM`);\n')
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertFalse(v['blocking_readers'])

    def test_python_executor_task_has_no_sql_row(self):
        self.write('u.py', 'executor.execute(task)\n')
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertFalse(v['blocking_readers'])

    def test_verdict_starts_with_cleared_unsearched_count_and_lead(self):
        p = self.write('auth.json', 'never opened')
        q = self.write('logs/r.py', 'never opened either')
        ordinary = self.write('o.py', 'people = []\n')
        self.plan['confirmations'] = [self.confirmation(p, 0), self.confirmation(q.parent, 0), self.confirmation(ordinary)]
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertEqual(list(v)[:3], ['verdict', 'unsearched_places_cleared', 'confirmed_by'])
        self.assertEqual(v['unsearched_places_cleared'], 2)
        self.assertEqual(v['confirmed_by'], ['test lead'])
        saved = json.loads((self.out/'verdict.json').read_text())
        self.assertEqual(saved['unsearched_places_cleared'], 2)

    def test_printed_line_names_cleared_unsearched_count_and_lead(self):
        import contextlib
        import io
        p = self.write('auth.json', 'never opened')
        self.plan['confirmations'] = [self.confirmation(p, 0)]
        plan = self.base/'plan.json'; plan.write_text(json.dumps(self.plan))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = rc.main(['--plan', str(plan), '--out', str(self.out), '--scratch', str(self.scratch)])
        self.assertEqual(code, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        printed = json.loads(output.getvalue())
        self.assertEqual(printed['verdict'], 'search found no reader; not proven by a dry test')
        self.assertIn('unsearched_places_cleared', printed)
        self.assertEqual(printed['unsearched_places_cleared'], 1)
        self.assertEqual(printed['confirmed_by'], ['test lead'])

    def test_listed_only_confirmation_does_not_count_as_unsearched_clearance(self):
        self.write('.git/config', 'synthetic')
        self.plan['confirmations'] = [self.confirmation(self.src/'.git', 0)]
        _, v = self.run_check()
        self.assertIn('unsearched_places_cleared', v)
        self.assertEqual(v['unsearched_places_cleared'], 0)
        self.assertEqual(v['confirmed_by'], [])

    def test_output_protects_bin_foxrun_state_and_launchagents(self):
        home = self.base/'home'; home.mkdir()
        with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {'FOXRUN_HOME': str(home/'.foxrun'), 'FOXRUN_STATE': str(home/'.local/state/foxrun')}):
            for relative in ['bin', '.foxrun', '.local/state/foxrun', 'Library/LaunchAgents']:
                with self.subTest(place=relative), self.assertRaises(rc.InvalidPlan):
                    rc.check(self.plan, home/relative/'out', self.scratch)

    def test_private_parent_root_is_plainly_unsearched_and_counted_after_confirmation(self):
        root = self.base/'secrets'/'src'; root.mkdir(parents=True)
        (root/'r.py').write_text('conn.execute("SELECT * FROM people")\n')
        self.plan['roots'] = [{'path': str(root), 'program': 'sample'}]
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn('unsearched_roots', v)
        self.assertEqual(v['unsearched_roots'][0]['path'], str(root))
        self.assertIn('under a protected private folder', v['unsearched_roots'][0]['reason'])
        self.assertIn('not searched', v['unsearched_roots'][0]['reason'])
        self.plan['confirmations'] = [self.confirmation(root, 0)]
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertEqual(v['unsearched_places_cleared'], 1)
        self.assertEqual(v['confirmed_by'], ['test lead'])
        self.assertIn('not searched', v['unsearched_roots'][0]['reason'])


class Round3Tests(unittest.TestCase):
    setUp = FixTests.setUp
    write = FixTests.write
    run_check = FixTests.run_check

    def source_reader(self, name, body):
        p = self.write(name, body)
        code, v = self.run_check()
        rows = [r for r in v['blocking_readers'] if r['path']==str(p) and r['line']==1]
        self.assertEqual(code, 1)
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]['access'], 'unsearched')
        self.assertNotIn(body.strip(), json.dumps(v))

    def test_private_named_go_reader_has_location_only(self):
        self.source_reader('auth.go', 'db.Query("SELECT * FROM people")\n')

    def test_private_named_python_reader_has_location_only(self):
        self.source_reader('token_utils.py', 'store.execute("SELECT * FROM people")\n')

    def test_oauth_folder_source_reader_has_location_only(self):
        self.source_reader('oauth/client.ts', 'db.prepare("SELECT * FROM people");\n')

    def test_config_and_settings_source_extensions_remain_code(self):
        self.write('oauth/config.go', 'db.Query("SELECT * FROM people")\n')
        p = self.write('oauth/settings.py', 't = "".join(["peo", "ple"])\nstore.execute(f"SELECT * FROM {t}")\n')
        _, v = self.run_check()
        self.assertIn('private_named_source_files_searched', v)
        self.assertEqual(v['private_named_source_files_searched'], 2)
        self.assertTrue(any(r['path']==str(p) and r['line']==2 and r['sure']=='needs a look' for r in v['blocking_readers']))

    def closed_case(self, name):
        import builtins
        import io
        p = self.write(name, 'SELECT * FROM people\n')
        opened = set(); real_builtin = builtins.open; real_io = io.open
        def record(real):
            def wrapper(file, *args, **kwargs):
                if isinstance(file, (str, bytes, Path)):
                    opened.add(str(Path(file).absolute()))
                return real(file, *args, **kwargs)
            return wrapper
        with patch.object(builtins, 'open', record(real_builtin)), patch.object(io, 'open', record(real_io)):
            code, v = self.run_check()
        self.assertNotIn(str(p), opened)
        self.assertEqual(code, 1)
        self.assertTrue(any(s['path']==str(p) or rc.inside(p, Path(s['path'])) for s in v['unconfirmed_skipped']))
        self.assertIn('private_named_files_closed', v)
        self.assertGreaterEqual(v['private_named_files_closed'], 1)

    def test_auth_json_stays_closed_with_open_audit(self): self.closed_case('auth.json')
    def test_env_local_stays_closed_with_open_audit(self): self.closed_case('.env.local')
    def test_token_txt_stays_closed_with_open_audit(self): self.closed_case('token.txt')
    def test_secrets_keys_source_stays_closed_with_open_audit(self): self.closed_case('secrets/keys.py')
    def test_credentials_yaml_stays_closed_with_open_audit(self): self.closed_case('credentials.yaml')
    def test_id_rsa_stays_closed_with_open_audit(self): self.closed_case('id_rsa')
    def test_server_key_stays_closed_with_open_audit(self): self.closed_case('server.key')

    def test_all_key_formats_and_protected_folders_stay_closed(self):
        for name in ['.pem', '.key', 'server.key.py', 'server.pem', 'server.p12', 'server.pfx', 'server.keystore', 'server.jks',
                     'server.crt', 'server.cer', 'id_ecdsa', 'id_ed25519.pub', 'id_dsa',
                     '.ssh/client.py', '.gnupg/client.ts', '.aws/client.go',
                     '.credentials/client.rb', 'mcp/client.py', '.codex/client.py']:
            with self.subTest(path=name): self.closed_case(name)

    def test_gitignored_private_named_source_stays_closed(self):
        (self.src/'.git').mkdir()
        self.write('.gitignore', 'auth.go\nprivate/*.py\n')
        self.closed_case('auth.go')

    def test_nested_gitignore_source_stays_closed(self):
        (self.src/'.git').mkdir()
        self.write('oauth/.gitignore', '/client.ts\n')
        self.closed_case('oauth/client.ts')

    def test_private_source_link_to_non_source_file_stays_closed(self):
        p = self.base/'values.txt'; p.write_text('SELECT * FROM people\n')
        (self.src/'auth.go').symlink_to(p)
        opened = []; real_open = Path.open
        def record(path, *args, **kwargs):
            opened.append(path); return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', record): _, v = self.run_check()
        self.assertNotIn(self.src/'auth.go', opened)
        self.assertNotIn(p, opened)
        self.assertIn('private_named_files_closed', v)
        self.assertEqual(v['private_named_files_closed'], 1)

    def test_private_source_canary_never_enters_outputs_or_stdout(self):
        import contextlib
        import io
        canary = 'PLANTED_ONLY_PRIVATE_VALUE_3'
        source = self.write('auth.go', 'db.Query("SELECT * FROM people") // '+canary+'\n')
        plan = self.base/'plan.json'; plan.write_text(json.dumps(self.plan))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = rc.main(['--plan', str(plan), '--out', str(self.out)])
        self.assertEqual(code, 1)
        payloads = [p.read_text() for p in self.out.iterdir() if p.is_file()]+[output.getvalue()]
        self.assertTrue(all(canary not in s for s in payloads))
        rows = json.loads((self.out/'verdict.json').read_text())['blocking_readers']
        self.assertTrue(any(r['path']==str(source) and r['line']==1 for r in rows))
        self.assertIn('private_named_source_files_searched', output.getvalue())

    def test_python_parser_warnings_never_expose_source_fragments(self):
        import contextlib
        import io
        import warnings
        self.write('auth.py', 'pattern = "PLANTED_VALUE\\q"\nstore.execute("SELECT * FROM people")\n')
        output = io.StringIO()
        # Permit this planted file in the old policy to test parser output itself.
        with patch.object(rc, 'private_path', return_value=False), contextlib.redirect_stderr(output), warnings.catch_warnings():
            warnings.simplefilter('always')
            _, v = self.run_check()
        self.assertEqual(output.getvalue(), '')
        self.assertIn('private_named_source_files_searched', v)

    def test_private_named_source_never_enters_a_workspace_copy(self):
        self.write('auth.go', 'SELECT * FROM people\n')
        self.write('oauth/client.ts', 'SELECT * FROM people\n')
        self.write('safe.py', 'x = 1\n')
        target = self.base/'copy'
        rc.copy_workspace(self.src, target)
        self.assertFalse((target/'auth.go').exists())
        self.assertFalse((target/'oauth/client.ts').exists())
        self.assertTrue((target/'safe.py').exists())
        # It was deliberately excluded even before the new source scan policy.
        _, v = self.run_check()
        self.assertIn('private_named_source_files_searched', v)
        self.assertEqual(v['private_named_source_files_searched'], 2)

    def test_private_counts_and_path_confirmation_are_explicit(self):
        self.write('auth.go', 'SELECT * FROM people\n')
        self.write('oauth/client.ts', 'SELECT * FROM people\n')
        self.write('auth.json', 'SELECT * FROM people\n')
        self.write('secrets/keys.py', 'SELECT * FROM people\n')
        _, v = self.run_check()
        self.assertIn('private_named_source_files_searched', v)
        self.assertEqual(v['private_named_source_files_searched'], 2)
        self.assertEqual(v['private_named_files_closed'], 2)
        self.assertIn('lead', v['private_named_closed_rule'])
        self.assertIn('path', v['private_named_closed_rule'])
        saved = json.loads((self.out/'scan.json').read_text())
        self.assertEqual(saved['private_named_source_files_searched'], 2)
        self.assertEqual(saved['private_named_files_closed'], 2)


class Round3aTests(unittest.TestCase):
    setUp = FixTests.setUp
    write = FixTests.write
    run_check = FixTests.run_check

    def sql_case(self, suffix, body):
        self.plan['thing']['name'] = 'draft_versions'
        self.plan['roots'][0].pop('database')
        prefix = 'const t = ["draft", "versions"].join("_");\n' if suffix in {'.js', '.ts'} else 't = "_".join(["draft", "versions"])\n'
        self.write('r'+suffix, prefix+body)
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(any(r['sure']=='needs a look' and r['line']!=0 for r in v['blocking_readers']))

    def test_lower_sql_helper_template_is_a_reader(self):
        self.sql_case('.js', 'const q = `select * from ${t} where id = ?`;\nawait run(q, [id]);\n')

    def test_lower_sql_concat_is_a_reader(self):
        self.sql_case('.js', 'const sql = "select * from " + t;\ndb.all(sql, cb);\n')

    def test_lower_sql_tagged_template_is_a_reader(self):
        self.sql_case('.ts', 'const rows = await sql`select * from ${sql(t)}`;\n')

    def test_tx_execute_lower_sql_is_a_reader(self):
        self.sql_case('.py', 'tx.execute(f"select * from {t}")\n')

    def test_store_execute_bound_sql_is_a_reader(self):
        self.sql_case('.py', 'q = "SELECT * FROM " + t\nstore.execute(q)\n')

    def test_self_store_execute_bound_format_is_a_reader(self):
        self.sql_case('.py', 'class R:\n    def all(self):\n        text = "select * from {}".format(t)\n        return self.store.execute(text)\n')

    def test_sqlite_connect_execute_lower_sql_is_a_reader(self):
        self.sql_case('.py', 'import sqlite3\nsqlite3.connect(p).execute(f"delete from {t}")\n')

    def test_javascript_db_run_built_variable_is_a_reader(self):
        self.sql_case('.js', 'const sql = buildSelect(t);\ndb.run(sql);\n')

    def test_javascript_db_exec_built_variable_is_a_reader(self):
        self.sql_case('.js', 'const sql = buildSelect(t);\ndb.exec(sql);\n')

    def test_javascript_db_get_built_variable_is_a_reader(self):
        self.sql_case('.js', 'const sql = buildSelect(t);\ndb.get(sql);\n')

    def test_pandas_read_sql_built_name_is_a_reader(self):
        self.sql_case('.py', 'df = pd.read_sql(f"select * from {t}", handle)\n')

    def test_planted_apply_program_schema_line_156_is_a_reader(self):
        self.write('schema.py', '\n'*154+'t = "_".join(["draft", "versions"])\n'
                   +'store.execute(f"pragma table_info({t})")\n')
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(any(r['line']==156 and r['sure']=='needs a look' for r in v['blocking_readers']))

    def test_built_pragma_on_generic_receiver_is_a_reader(self):
        self.sql_case('.py', 'store.execute(f"pragma table_info({t})")\n')

    def test_unknown_execute_argument_preserves_possible_reader(self):
        self.sql_case('.py', 'store.execute(q)\n')

    def test_fragmented_update_preserves_possible_reader(self):
        self.sql_case('.py', 'text = "update " + t + " set value = ?"\nstore.execute(text, [value])\n')

    def test_non_sql_executor_and_pool_stay_without_rows(self):
        self.write('r.py', 'executor.execute(task)\npool.execute(job)\n')
        code, v = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(v['verdict'], 'search found no reader; not proven by a dry test')
        self.assertFalse(v['blocking_readers'])


if __name__ == '__main__':
    unittest.main()
