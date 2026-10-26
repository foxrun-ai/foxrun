"""The nightly entry routes lint findings to the Keeper; only a crashed step or a failed push fails (T293)."""
import importlib.util
import json
import io
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'cron/nightly.py'
spec = importlib.util.spec_from_file_location('launch_nightly', SOURCE)
nightly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nightly)


class NightlyLintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('base/lint.py', 'memory/dream.py', 'memory/check.py'):
            p = self.root / name
            p.parent.mkdir(exist_ok=True)
            p.write_text('# installed command copy\n')
        self.calls = []

    def runner(self, command, **kwargs):
        self.calls.append(command)
        return subprocess.CompletedProcess(command, 0, '[]', '')

    def test_lint_runs_first_and_routes_to_keeper(self):
        self.assertEqual(nightly.sequence(self.root, runner=self.runner, portfolio=self.root / 'portfolio'), 0)
        self.assertEqual([Path(c[2]).name for c in self.calls], ['lint.py', 'dream.py', 'check.py'])
        receipt = json.loads(next((self.root / 'runs/nightly').glob('*-lint/receipt.json')).read_text())
        self.assertEqual(receipt['owner'], 'keeper')
        self.assertEqual(receipt['exit'], 0)
        self.assertIn('--workspaces', self.calls[0])

    def test_lint_findings_still_run_memory_and_do_not_fail(self):
        # Findings are reported, not failures (T293).
        def run(command, **kwargs):
            result = self.runner(command, **kwargs)
            if Path(command[2]).name == 'lint.py':
                result.returncode = 1
                result.stdout = '[{"level":"error"}]'
            return result
        self.assertEqual(nightly.sequence(self.root, runner=run), 0)
        self.assertEqual(len(self.calls), 3)

    def test_invalid_report_fails_closed(self):
        def run(command, **kwargs):
            result = self.runner(command, **kwargs)
            result.stdout = 'unstructured output'
            return result
        self.assertEqual(nightly.sequence(self.root, runner=run), 1)
        report = json.loads(next((self.root / 'runs/nightly').glob('*/findings.json')).read_text())
        self.assertEqual(report[0]['rule_id'], 'CONFIG')

    def test_memory_failure_does_not_erase_lint_report(self):
        def run(command, **kwargs):
            result = self.runner(command, **kwargs)
            if Path(command[2]).name == 'dream.py':
                result.returncode = 3
            return result
        self.assertEqual(nightly.sequence(self.root, runner=run), 1)
        self.assertTrue(list((self.root / 'runs/nightly').glob('*/receipt.json')))
        self.assertEqual(len(self.calls), 3)

    def test_memory_check_runs_after_dream_failure(self):
        def run(command, **kwargs):
            result = self.runner(command, **kwargs)
            if Path(command[2]).name == 'dream.py':
                result.returncode = 3
            if Path(command[2]).name == 'check.py':
                result.returncode = 4
            return result
        self.assertEqual(nightly.sequence(self.root, runner=run), 1)
        self.assertEqual([Path(c[2]).name for c in self.calls], ['lint.py', 'dream.py', 'check.py'])

    def test_dry_run_preserves_readonly_memory_check(self):
        with patch.object(nightly, 'sequence', return_value=0) as sequence, patch.object(nightly.os,'nice') as nice, patch.object(nightly.subprocess,'run'):
            self.assertEqual(nightly.main(['--dry-run', '--workspace', 'alpha', '--workspaces', str(self.root)]), 0)
        nice.assert_called_once_with(10)
        args, kwargs = sequence.call_args
        self.assertEqual(args[1], ['--dry-run'])
        self.assertEqual(args[2], ['--readonly', '--workspace', 'alpha'])
        self.assertEqual(kwargs['portfolio'], self.root)
        self.assertTrue(kwargs['dry_run'])

    def test_normal_run_lowers_priority_before_sequential_checks(self):
        events=[]
        with patch.object(nightly.os,'nice',side_effect=lambda value:events.append(('nice',value))), \
             patch.object(nightly.sys,'platform','darwin'), \
             patch.object(nightly.subprocess,'run',side_effect=lambda command,**kwargs:events.append(('taskpolicy',command,kwargs))), \
             patch.object(nightly,'sequence',side_effect=lambda *args,**kwargs:events.append(('sequence',)) or 0):
            self.assertEqual(nightly.main([]),0)
        self.assertEqual(events,[('nice',10),('taskpolicy',['/usr/sbin/taskpolicy','-b','-p',str(nightly.os.getpid())],{'check':True}),('sequence',)])

    def test_background_policy_failure_stops_before_heavy_checks(self):
        with patch.object(nightly.os,'nice'), patch.object(nightly.sys,'platform','darwin'), \
             patch.object(nightly.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'taskpolicy')), \
             patch.object(nightly,'sequence') as sequence:
            self.assertEqual(nightly.main([]),1)
        sequence.assert_not_called()

    def test_workspaces_view_rebuilds_after_check(self):
        (self.root / 'base/make_workspaces_view.py').write_text('# installed command copy\n')
        portfolio = self.root / 'portfolio'
        self.assertEqual(nightly.sequence(self.root, runner=self.runner, portfolio=portfolio), 0)
        self.assertEqual([Path(c[2]).name for c in self.calls], ['lint.py', 'dream.py', 'check.py', 'make_workspaces_view.py'])
        view = self.calls[-1]
        self.assertEqual(view[view.index('--output-root') + 1], str(self.root / 'workspaces'))
        self.assertEqual(view[view.index('--workspace-root') + 1], str(portfolio))

    def test_dry_run_builds_workspaces_view_in_a_temp_folder(self):
        (self.root / 'base/make_workspaces_view.py').write_text('# installed command copy\n')
        self.assertEqual(nightly.sequence(self.root, runner=self.runner, portfolio=self.root, dry_run=True), 0)
        view = self.calls[-1]
        self.assertNotEqual(view[view.index('--output-root') + 1], str(self.root / 'workspaces'))

    def test_workspaces_view_failure_fails_the_night(self):
        (self.root / 'base/make_workspaces_view.py').write_text('# installed command copy\n')
        def run(command, **kwargs):
            result = self.runner(command, **kwargs)
            if Path(command[2]).name == 'make_workspaces_view.py':
                result.returncode = 5
            return result
        self.assertEqual(nightly.sequence(self.root, runner=run, portfolio=self.root), 1)


class StatePushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.remote = base / 'home', base / 'remote.git'
        self.state = self.root / 'state'
        self.state.mkdir(parents=True)
        self.git('init', '-q', '--bare', '-b', 'main', str(self.remote), cwd=base)
        self.git('init', '-q', '-b', 'main')
        for key, value in (('user.name', 'Test'), ('user.email', 'test@example.invalid'), ('commit.gpgsign', 'false')):
            self.git('config', key, value)
        (self.state / 'tasks.jsonl').write_text('{"id":"T1"}\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'first')
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-q', '-u', 'origin', 'main')

    def git(self, *arguments, cwd=None):
        return subprocess.run(['git'] + list(arguments), cwd=str(cwd or self.state), check=True,
                              capture_output=True, text=True).stdout.strip()

    def remote_head(self):
        return self.git('--git-dir', str(self.remote), 'log', '-1', '--format=%s', 'main', cwd=self.root)

    def test_commits_and_pushes_a_new_export(self):
        (self.state / 'tasks.jsonl').write_text('{"id":"T1"}\n{"id":"T2"}\n')
        self.assertEqual(nightly.push_state(self.root), 0)
        self.assertTrue(self.remote_head().startswith('state: nightly export '))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_dry_run_commits_and_pushes_nothing(self):
        (self.state / 'tasks.jsonl').write_text('{"id":"T9"}\n')
        self.assertEqual(nightly.push_state(self.root, dry_run=True), 0)
        self.assertEqual(self.remote_head(), 'first')
        self.assertNotEqual(self.git('status', '--porcelain'), '')

    def test_pulls_before_push(self):
        other = Path(self.temp.name) / 'other'
        self.git('clone', '-q', str(self.remote), str(other), cwd=self.root)
        for key, value in (('user.name', 'Test'), ('user.email', 'test@example.invalid'), ('commit.gpgsign', 'false')):
            self.git('config', key, value, cwd=other)
        (other / 'inbox.jsonl').write_text('{"proposal":1}\n')
        self.git('add', '-A', cwd=other)
        self.git('commit', '-q', '-m', 'from elsewhere', cwd=other)
        self.git('push', '-q', cwd=other)
        (self.state / 'tasks.jsonl').write_text('{"id":"T3"}\n')
        self.assertEqual(nightly.push_state(self.root), 0)
        self.assertTrue((self.state / 'inbox.jsonl').is_file())
        self.assertTrue(self.remote_head().startswith('state: nightly export '))

    def test_secret_value_refuses_push_and_keeps_commit_local(self):
        # Built at run time so this file holds no secret-looking text.
        planted = {'github-token': 'gh' + 'p_' + 'A1b2' * 9,
                   'telegram-bot-token': '1234567890' + ':' + 'AAH' + 'x9_' * 10 + 'k1',
                   'url-userinfo': 'https://bot' + ':' + 'hunter2' + '@example.invalid/x',
                   'stripe-key': 'rk' + '_live_' + 'Z9' * 8}
        for reason, value in planted.items():
            with self.subTest(reason=reason):
                (self.state / 'tasks.jsonl').write_text('{"id":"T4","note":"%s"}\n' % value)
                stream = io.StringIO()
                with patch.object(nightly.sys, 'stdout', stream):
                    self.assertEqual(nightly.push_state(self.root), 1)
                    self.assertEqual(nightly.push_state(self.root), 1)
                self.assertIn('REFUSED; secret-looking value (%s) in tasks.jsonl' % reason, stream.getvalue())
                self.assertNotIn(value, stream.getvalue())
                self.assertEqual(self.remote_head(), 'first')
                self.assertTrue(self.git('log', '-1', '--format=%s').startswith('state: nightly export '))
                self.git('reset', '-q', '--hard', 'origin/main')

    def failing(self, verb):
        """subprocess.run, except the git verb given fails with no output, as a broken scan would."""
        def run(command, **kwargs):
            if verb in command:
                return subprocess.CompletedProcess(command, 128, b'' if 'input' in kwargs else '', 'fatal: simulated')
            return subprocess.run(command, **kwargs)
        return run

    def test_scan_that_cannot_read_the_outgoing_changes_refuses_the_push(self):
        # T750 F04: an empty answer from a failed git command is never a clean scan.
        token = 'gh' + 'p_' + 'A1b2' * 9
        for verb in ('rev-list', 'cat-file'):
            with self.subTest(verb=verb):
                (self.state / 'tasks.jsonl').write_text('{"id":"T5","note":"%s"}\n' % token)
                stream = io.StringIO()
                with patch.object(nightly.sys, 'stdout', stream):
                    self.assertEqual(nightly.push_state(self.root, runner=self.failing(verb)), 1)
                self.assertIn('REFUSED; secret scan could not', stream.getvalue())
                self.assertEqual(self.remote_head(), 'first')
                self.git('reset', '-q', '--hard', 'origin/main')

    def test_secret_in_a_binary_blob_refuses_the_push(self):
        # T750 F04: the scan reads whole outgoing blobs, not only text diff lines.
        token = 'gh' + 'p_' + 'A1b2' * 9
        (self.state / 'export.bin').write_bytes(b'\x00\x01\xffbinary ' + token.encode() + b'\x00')
        stream = io.StringIO()
        with patch.object(nightly.sys, 'stdout', stream):
            self.assertEqual(nightly.push_state(self.root), 1)
        self.assertIn('REFUSED; secret-looking value (github-token) in export.bin', stream.getvalue())
        self.assertNotIn(token, stream.getvalue())
        self.assertEqual(self.remote_head(), 'first')

    def test_clean_binary_blob_still_pushes(self):
        (self.state / 'export.bin').write_bytes(bytes(range(256)) * 4)
        self.assertEqual(nightly.push_state(self.root), 0)
        self.assertTrue(self.remote_head().startswith('state: nightly export '))

    def test_skips_when_state_is_not_a_repo(self):
        plain = Path(self.temp.name) / 'plain'
        (plain / 'state').mkdir(parents=True)
        self.assertEqual(nightly.push_state(plain), 0)

    def test_schedule_preserves_current_clock_settings_and_portfolio(self):
        config = self.root / 'config'
        config.mkdir()
        for settings, key, expected in [({'hour': 4, 'minute': 15}, 'StartCalendarInterval', {'Hour': 4, 'Minute': 15}),
                                        ({'interval_seconds': 120}, 'StartInterval', 120)]:
            with self.subTest(settings=settings):
                (config / 'dream.json').write_text(json.dumps(settings))
                stream = io.BytesIO()
                with patch.object(nightly, 'ROOT', self.root), patch.object(nightly.sys, 'stdout') as stdout:
                    stdout.buffer = stream
                    self.assertEqual(nightly.main(['--schedule', '--workspaces', str(self.root / 'portfolio')]), 0)
                value = plistlib.loads(stream.getvalue())
                self.assertEqual(value[key], expected)
                self.assertEqual(value['ProgramArguments'][-2:], ['--workspaces', str(self.root / 'portfolio')])
                self.assertFalse((self.root / 'runs').exists())


if __name__ == '__main__':
    unittest.main()
