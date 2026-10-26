"""Planted privacy lifecycle checks. Only synthetic material; no source-value output."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import base64
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import reader_check as rc

FORM_PROOF = []


class Round6PrivacyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()  # reader_check reports resolved paths; macOS /var is a symlink
        self.src = self.base/'src'; self.src.mkdir()
        self.out = self.base/'out'; self.trial = self.base/'trial'
        self.db = self.base/'data/store.db'; self.db.parent.mkdir()
        with sqlite3.connect(self.db) as connection:
            connection.execute('CREATE TABLE people (id INTEGER)')
        self.plan = {'thing': {'kind': 'table', 'name': 'people', 'database': str(self.db)},
                     'work_lead': 'fixture-lead',
                     'roots': [{'path': str(self.src), 'program': 'plant', 'database': str(self.db)}],
                     'readers': [{'program': 'plant', 'workspace': str(self.src), 'offline': True,
                                  'commands': [[sys.executable, '-c', 'import sys; sys.exit(0)', '{copy}']]}]}

    def run_check(self, **kwargs):
        try:
            return rc.check(self.plan, self.out, self.trial, True, **kwargs)
        except TypeError:
            self.fail('explicit lead keep option is unavailable')

    def outputs(self):
        return b'\n'.join(p.read_bytes() for p in self.out.rglob('*') if p.is_file())

    def test_searched_content_leaves_no_copy_or_output(self):
        marker = 'planted_sensitive_' + 'value_42'
        (self.src/'module.py').write_text('value = "'+marker+'"\n')
        _, verdict = self.run_check()
        self.assertEqual(verdict.get('private_scratch_copy_paths'), [])
        self.assertFalse(self.trial.exists())
        self.assertFalse(marker.encode() in self.outputs())
        self.assertTrue((self.src/'module.py').exists())

    def test_private_named_reader_is_marked_and_confirmed_by_path(self):
        source = self.src/'auth.py'
        source.write_text('db.execute("SELECT * FROM people")\n')
        self.plan['confirmations'] = [{'path': str(source), 'line': 0, 'decision': 'reader',
                                      'by': 'fixture-lead', 'at': '2026-10-06T12:00:00+00:00',
                                      'reason': 'Synthetic lead path confirmation.'}]
        code, verdict = self.run_check(keep_copies=True, keep_copies_by='fixture-lead')
        self.assertEqual(code, 1)
        row = next(r for r in verdict['blocking_readers'] if r['path']==str(source) and r['line']==1)
        self.assertEqual(row['test'], 'found; not dry-tested: private-named file')
        self.assertEqual(row['confirmation_by'], 'fixture-lead')
        self.assertTrue(verdict['confirmations'][0]['accepted'])
        self.assertFalse(list(self.trial.rglob('auth.py')))
        self.assertTrue(source.exists())

    def test_private_named_reader_mark_does_not_depend_on_keep_option(self):
        source = self.src/'token_reader.py'
        source.write_text('db.execute("SELECT * FROM people")\n')
        code, verdict = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict['blocking_readers'][0]['test'], 'found; not dry-tested: private-named file')
        self.assertFalse(self.trial.exists())

    def test_private_named_unrelated_cannot_clear_proven_reader(self):
        source = self.src/'auth.py'
        source.write_text('db.execute("SELECT * FROM people")\n')
        self.plan['confirmations'] = [{'path': str(source), 'line': 0, 'decision': 'unrelated',
                                      'by': 'fixture-lead', 'at': '2026-10-06T12:00:00+00:00',
                                      'reason': 'Synthetic attempted override.'}]
        code, verdict = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(verdict['confirmations'])
        self.assertFalse(verdict['confirmations'][0]['accepted'])

    def test_private_named_confirmation_rejects_non_lead(self):
        source = self.src/'auth.py'
        source.write_text('db.execute("SELECT * FROM people")\n')
        self.plan['confirmations'] = [{'path': str(source), 'line': 0, 'decision': 'reader',
                                      'by': 'runner', 'at': '2026-10-06T12:00:00+00:00',
                                      'reason': 'Synthetic non-lead confirmation.'}]
        _, verdict = self.run_check()
        self.assertTrue(verdict['confirmations'])
        self.assertFalse(verdict['confirmations'][0]['accepted'])

    def test_cleanup_after_partial_copy_error(self):
        def fail(plan, scratch):
            (scratch/'partial.py').write_text('synthetic')
            raise RuntimeError('suppressed synthetic detail')
        with patch.object(rc, 'run_tests', fail):
            code, verdict = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(verdict['test_setup_failed'])
        self.assertEqual(verdict.get('private_scratch_copy_paths'), [])
        self.assertFalse(self.trial.exists())

    def test_cleanup_after_keyboard_interrupt(self):
        def interrupt(plan, scratch):
            (scratch/'partial.py').write_text('synthetic')
            raise KeyboardInterrupt()
        with patch.object(rc, 'run_tests', interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_check()
        self.assertFalse(self.trial.exists())

    def test_cleanup_after_system_exit(self):
        def interrupt(plan, scratch):
            (scratch/'partial.py').write_text('synthetic')
            raise SystemExit(9)
        with patch.object(rc, 'run_tests', interrupt), self.assertRaises(SystemExit):
            self.run_check()
        self.assertFalse(self.trial.exists())

    def test_cleanup_precedes_report_write_error(self):
        (self.src/'module.py').write_text('value = 42\n')
        original = Path.write_text
        def fail(path, *args, **kwargs):
            if path.name=='verdict.json': raise OSError('synthetic failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail), self.assertRaises(OSError):
            self.run_check()
        self.assertFalse(self.trial.exists())

    def test_existing_scratch_is_not_deleted_or_claimed(self):
        self.trial.mkdir(); unrelated = self.trial/'caller.txt'; unrelated.write_text('synthetic')
        code, verdict = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(unrelated.exists())
        self.assertEqual(verdict.get('private_scratch_copy_paths'), [])
        self.assertEqual(verdict['private_scratch_copies'], [])

    def test_explicit_lead_keep_lists_each_copy_and_mode_700(self):
        (self.src/'module.py').write_text('value = 42\n'); (self.src/'nested').mkdir(mode=0o755)
        (self.src/'nested'/'probe.py').write_text('value = 7\n')
        _, verdict = self.run_check(keep_copies=True, keep_copies_by='fixture-lead')
        paths = {str(p) for p in self.trial.rglob('*') if p.is_file()}
        self.assertTrue(paths)
        self.assertEqual(set(verdict['private_scratch_copy_paths']), paths)
        self.assertEqual(set(verdict['private_scratch_copies']), paths)
        for path in [self.trial, *self.trial.rglob('*')]:
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_keep_requires_explicit_named_lead(self):
        for by in (None, '', 'runner'):
            with self.subTest(by=by), self.assertRaises(rc.InvalidPlan):
                self.run_check(keep_copies=True, keep_copies_by=by)
        self.assertFalse(self.trial.exists())

    def test_keep_on_setup_error_lists_partial_paths(self):
        def fail(plan, scratch):
            (scratch/'partial.py').write_text('synthetic')
            raise RuntimeError('synthetic')
        with patch.object(rc, 'run_tests', fail):
            _, verdict = self.run_check(keep_copies=True, keep_copies_by='fixture-lead')
        self.assertEqual(verdict['private_scratch_copy_paths'], [str(self.trial/'partial.py')])

    def test_explicit_keep_on_interrupt_saves_path_list(self):
        for exception in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exception.__name__):
                self.trial = self.base/exception.__name__
                def interrupt(plan, scratch):
                    (scratch/'partial.py').write_text('synthetic')
                    raise exception()
                with patch.object(rc, 'run_tests', interrupt):
                    code, verdict = self.run_check(keep_copies=True, keep_copies_by='fixture-lead')
                self.assertEqual(code, 1)
                self.assertEqual(verdict['private_scratch_copy_paths'], [str(self.trial/'partial.py')])
                self.assertTrue((self.out/'verdict.json').exists())

    def test_cleanup_failure_refuses_and_lists_remaining_paths(self):
        (self.src/'module.py').write_text('value = 42\n')
        with patch.object(rc.shutil, 'rmtree', side_effect=OSError('synthetic')):
            code, verdict = self.run_check()
        self.assertEqual(code, 1)
        self.assertTrue(verdict.get('scratch_cleanup_failed'))
        self.assertEqual(set(verdict['private_scratch_copy_paths']),
                         {str(p) for p in self.trial.rglob('*') if p.is_file()})

    def test_scratch_inside_repository_is_refused(self):
        repository = self.base/'repo'; (repository/'.git').mkdir(parents=True)
        self.trial = repository/'trial'
        with self.assertRaises(rc.InvalidPlan): self.run_check()
        self.assertFalse(self.trial.exists())

    def test_output_inside_scratch_is_refused(self):
        self.out = self.trial/'out'
        with self.assertRaises(rc.InvalidPlan): self.run_check()
        self.assertFalse(self.trial.exists())

    def test_readme_states_best_effort_and_no_retention_guarantee(self):
        text = (Path(rc.__file__).parent/'README-reader-check.md').read_text()
        self.assertIn('Key detection is a best effort.', text)
        self.assertIn('The guarantee is that no file content is shown or kept after the run, unless the lead explicitly keeps copies.', text)
        self.assertIn('--keep-copies', text)

    def test_sha256_exception_is_unchanged(self):
        digest = bytes(range(32)).hex()
        for value in (digest, digest.upper()):
            source = self.src/'module.py'; source.write_text('private_key = bytes.fromhex("'+value+'")\n')
            self.assertTrue(rc.source_first_look(source))

    def test_cli_keep_option_records_each_path(self):
        (self.src/'module.py').write_text('value = 42\n')
        planfile = self.base/'plan.json'; planfile.write_text(json.dumps(self.plan))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = rc.main(['--plan', str(planfile), '--out', str(self.out), '--scratch', str(self.trial),
                                '--run-tests', '--keep-copies', '--keep-copies-by', 'fixture-lead'])
            except SystemExit:
                self.fail('CLI keep option is unavailable')
        self.assertEqual(code, 0)
        verdict = json.loads((self.out/'verdict.json').read_text())
        self.assertEqual(set(verdict['private_scratch_copy_paths']),
                         {str(p) for p in self.trial.rglob('*') if p.is_file()})

    def signal_cleanup(self, sig):
        # The child pauses only after creating a partial copy. No real reader runs.
        planfile = self.base/'plan.json'; planfile.write_text(json.dumps(self.plan))
        ready = self.base/'ready'
        script = ('import sys,time; from pathlib import Path; import reader_check as r; '
                  'ready=Path(sys.argv[1]); '
                  'exec("def probe(plan,scratch):\\n (scratch/\'partial.py\').write_text(\'synthetic\')\\n ready.touch()\\n time.sleep(30)"); '
                  'r.run_tests=probe; sys.exit(r.main(sys.argv[2:]))')
        env = {**os.environ, 'PYTHONPATH': str(Path(rc.__file__).parent), 'PYTHONDONTWRITEBYTECODE': '1'}
        proc = subprocess.Popen([sys.executable, '-c', script, str(ready), '--plan', str(planfile),
                                 '--out', str(self.out), '--scratch', str(self.trial), '--run-tests'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            deadline = time.monotonic()+5
            while not ready.exists() and proc.poll() is None and time.monotonic()<deadline: time.sleep(0.01)
            self.assertTrue(ready.exists())
            proc.send_signal(sig)
            stdout, stderr = proc.communicate(timeout=5)
            self.assertFalse(self.trial.exists())
            self.assertFalse(stderr)
            self.assertIn(b'"verdict": "refused"', stdout)
            self.assertNotEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None: proc.kill(); proc.communicate()

    def test_sigint_removes_partial_copies(self): self.signal_cleanup(signal.SIGINT)
    def test_sigterm_removes_partial_copies(self): self.signal_cleanup(signal.SIGTERM)


def planted_forms():
    der = bytes.fromhex('302e020100300506032b657004220420')+bytes(range(32))
    encoded = base64.b64encode(der).decode()
    parts = [encoded[n:n+16] for n in range(0, len(encoded), 16)]
    prefix = ''.join('value_%d = %d\n'%(n, n) for n in range(200))
    escaped = ''.join('\\x%02x'%n for n in der)
    raw_hex = bytes(range(32)).hex()
    return [
        ('split_runtime_join', '.py', 'material = "".join('+repr(parts)+')\n', parts),
        ('split_runtime_concat', '.py', 'material = '+' + '.join(repr(p) for p in parts)+'\n', parts),
        ('triple_quoted_base64', '.py', prefix+'material = """\n'+'\n'.join(parts)+'\n"""\n', parts),
        ('hex_raw32_assignment', '.py', 'private_key = bytes.fromhex("'+raw_hex+'")\n', [raw_hex]),
        ('hex_escaped_bytes', '.py', 'material = b"'+escaped+'"\n', [escaped]),
        ('sql_split', '.sql', 'SELECT '+' || '.join("'"+p+"'" for p in parts)+' AS material;\n', parts),
        ('shell_split', '.sh', 'material='+''.join("'"+p+"'" for p in parts)+'\n', parts),
        ('javascript_split', '.js', 'const material = '+json.dumps(parts)+'.join("");\n', parts)]


def make_form_test(label, extension, body, markers):
    def test(self):
        # Both neutral names and private names carry the exact same planted form.
        for name in ('module', 'auth'):
            with self.subTest(name=name):
                source = self.src/(name+extension)
                source.write_text(body)
                self.addCleanup(source.unlink, missing_ok=True)
                self.out = self.base/('out-'+name)
                self.trial = self.base/('trial-'+name)
                self.assertTrue(rc.source_first_look(self.src/(name+extension)))
                planfile = self.base/'plan.json'; planfile.write_text(json.dumps(self.plan))
                stdout = io.StringIO(); stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = rc.main(['--plan', str(planfile), '--out', str(self.out),
                                    '--scratch', str(self.trial), '--run-tests'])
                self.assertEqual(code, 0)
                verdict = json.loads((self.out/'verdict.json').read_text())
                outputs = self.outputs()+stdout.getvalue().encode()+stderr.getvalue().encode()
                FORM_PROOF.append({'form': label, 'name_kind': 'neutral' if name=='module' else 'private-named',
                                   'files_searched': json.loads((self.out/'scan.json').read_text())['files_read'],
                                   'source_copy_count_after_run': len(list(self.trial.rglob(name+extension))),
                                   'all_copy_count_after_run': len([p for p in self.trial.rglob('*') if p.is_file()]),
                                   'scratch_exists_after_run': self.trial.exists(),
                                   'material_in_reports_stdout_or_stderr': any(m.encode() in outputs for m in markers)})
                source.unlink()
                self.assertTrue(verdict['tests'])
                self.assertEqual(verdict.get('private_scratch_copy_paths'), [])
                self.assertFalse(self.trial.exists())
                for marker in markers: self.assertFalse(marker.encode() in outputs)
                self.assertFalse(stderr.getvalue())
    return test


for label, extension, body, markers in planted_forms():
    setattr(Round6PrivacyTests, 'test_no_retained_copy_or_output_'+label, make_form_test(label, extension, body, markers))


if __name__ == '__main__': unittest.main()
