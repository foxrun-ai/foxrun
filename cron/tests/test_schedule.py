#!/usr/bin/env python3
"""The nightly job renders from its template and turns on once. launchctl is always a stub."""
import json
import os
from pathlib import Path
import plistlib
import pwd
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CRON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRON))
import schedule  # noqa: E402


class Schedule(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='nightly-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.user = self.root / 'user'
        self.home = self.root / 'system'
        self.portfolio = self.root / 'portfolio'
        for path in (self.user, self.home / 'config', self.portfolio):
            path.mkdir(parents=True)
        self.calls = self.root / 'calls.log'
        self.stub = self.root / 'launchctl'
        self.stub.write_text('#!/bin/sh\necho "$@" >> %s\nexit "${STUB_EXIT:-0}"\n' % self.calls)
        self.stub.chmod(0o755)
        patch = mock.patch.dict(os.environ, {'FOXRUN_LAUNCHCTL': str(self.stub)})
        patch.start()
        self.addCleanup(patch.stop)

    def clock(self, **values):
        (self.home / 'config/dream.json').write_text(json.dumps(values))

    def on(self):
        return schedule.turn_on(self.home, self.portfolio, user_home=self.user,
                                python='/usr/bin/python3', uid=501)

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_render_fills_every_placeholder(self):
        self.clock(hour=3, minute=15, interval_seconds=None)
        job = schedule.render(self.home, self.portfolio, user_home=self.user, python='/usr/bin/python3')
        text = plistlib.dumps(job).decode()
        self.assertNotRegex(text, r'@[A-Z_]+@')
        self.assertEqual(job['ProcessType'], 'Background')
        self.assertIs(job['LowPriorityIO'], True)
        self.assertEqual(job['Label'], 'com.foxrun.session-nightly')
        self.assertEqual(job['ProgramArguments'], ['/usr/bin/python3', '-B', str(self.home / 'cron/nightly.py')])
        self.assertEqual(job['WorkingDirectory'], str(self.home))
        self.assertEqual(job['EnvironmentVariables']['HOME'], str(self.user))
        self.assertEqual(job['EnvironmentVariables']['FOXRUN_HOME'], str(self.home))
        self.assertEqual(job['EnvironmentVariables']['FOXRUN_PORTFOLIO'], str(self.portfolio))
        self.assertEqual(job['StartCalendarInterval'], {'Hour': 3, 'Minute': 15})
        self.assertNotIn('StartInterval', job)
        self.assertEqual(job['StandardOutPath'], str(self.user / '.local/state/foxrun/session-nightly/stdout.log'))

    def test_interval_and_bad_clock(self):
        self.clock(interval_seconds=3600)
        job = schedule.render(self.home, self.portfolio, user_home=self.user)
        self.assertEqual(job['StartInterval'], 3600)
        self.assertNotIn('StartCalendarInterval', job)
        for values in ({'interval_seconds': 30}, {'hour': 24, 'minute': 0}, {'hour': '2', 'minute': 30}):
            with self.subTest(values=values):
                self.clock(**values)
                with self.assertRaises(ValueError):
                    schedule.render(self.home, self.portfolio, user_home=self.user)

    def test_missing_clock_uses_starter_time(self):
        job = schedule.render(self.home, self.portfolio, user_home=self.user)
        self.assertEqual(job['StartCalendarInterval'], {'Hour': 2, 'Minute': 30})

    def test_turn_on_is_idempotent_and_backs_up_a_change(self):
        self.clock(hour=2, minute=30, interval_seconds=None)
        path = self.user / 'Library/LaunchAgents/com.foxrun.session-nightly.plist'
        self.assertEqual(self.on(), 'written')
        self.assertEqual(plistlib.loads(path.read_bytes()),
                         schedule.render(self.home, self.portfolio, user_home=self.user, python='/usr/bin/python3'))
        self.assertTrue((self.user / '.local/state/foxrun/session-nightly').is_dir())
        watcher = schedule.target_watchdog(self.user)
        self.assertEqual(plistlib.loads(watcher.read_bytes()),
                         schedule.render_watchdog(self.home, user_home=self.user, python='/usr/bin/python3'))
        self.assertEqual(self.calls_made(), ['bootstrap gui/501 ' + str(path),
                                            'bootstrap gui/501 ' + str(watcher)])
        # Same job: nothing written, nothing loaded.
        before = path.stat().st_mtime_ns
        self.assertEqual(self.on(), 'unchanged')
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(len(self.calls_made()), 2)
        # A new clock: the old file is kept, the job is replaced and reloaded.
        old = path.read_bytes()
        self.clock(hour=4, minute=0, interval_seconds=None)
        self.assertEqual(self.on(), 'replaced')
        backups = list(path.parent.glob(path.name + '.bak-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old)
        self.assertEqual(plistlib.loads(path.read_bytes())['StartCalendarInterval'], {'Hour': 4, 'Minute': 0})
        self.assertEqual(self.calls_made()[2:], ['bootout gui/501/com.foxrun.session-nightly',
                                                  'bootstrap gui/501 ' + str(path)])

    def test_links_planted_at_the_old_temporary_names_are_never_followed(self):
        folder = self.user / 'Library/LaunchAgents'
        folder.mkdir(parents=True)
        outside = self.root / 'outside.txt'
        outside.write_text('keep')
        planted = [folder / 'com.foxrun.session-nightly.plist.tmp', folder / 'com.foxrun.session-nightly-watchdog.tmp']
        for link in planted:
            link.symlink_to(outside)
        self.clock(hour=2, minute=30, interval_seconds=None)
        self.assertEqual(self.on(), 'written')
        self.assertEqual(outside.read_text(), 'keep')
        for link in planted:
            self.assertTrue(link.is_symlink(), link)
        path = schedule.target(self.user)
        for job in (path, schedule.target_watchdog(self.user)):
            self.assertFalse(job.is_symlink(), job)
            self.assertEqual(job.stat().st_mode & 0o777, 0o644, job)
        self.assertEqual(sorted(p.name for p in folder.iterdir() if p.name.endswith('.tmp') and not p.is_symlink()), [])
        # A replaced job keeps the old file in a new backup only this user can read.
        self.clock(hour=4, minute=0, interval_seconds=None)
        self.assertEqual(self.on(), 'replaced')
        backup, = folder.glob(path.name + '.bak-*')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_bootstrap_failure_is_reported(self):
        with mock.patch.dict(os.environ, {'STUB_EXIT': '5'}):
            with self.assertRaisesRegex(ValueError, 'bootstrap failed'):
                self.on()

    def test_linked_job_file_refused(self):
        folder = self.user / 'Library/LaunchAgents'
        folder.mkdir(parents=True)
        outside = self.root / 'outside.plist'
        outside.write_text('keep')
        (folder / 'com.foxrun.session-nightly.plist').symlink_to(outside)
        with self.assertRaises(ValueError):
            self.on()
        self.assertEqual(outside.read_text(), 'keep')
        self.assertEqual(self.calls_made(), [])

    def test_nightly_schedule_prints_the_same_render(self):
        self.clock(hour=1, minute=5, interval_seconds=None)
        # nightly.py renders for the home it lives in.
        (self.home / 'cron/launchd').mkdir(parents=True)
        for name in ('nightly.py', 'schedule.py', 'launchd/session-nightly.plist.template'):
            (self.home / 'cron' / name).write_bytes((CRON / name).read_bytes())
        env = dict(os.environ, HOME=str(self.user), FOXRUN_PORTFOLIO=str(self.portfolio))
        result = subprocess.run([sys.executable, '-B', str(self.home / 'cron/nightly.py'), '--schedule'],
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(plistlib.loads(result.stdout),
                         schedule.render(self.home, self.portfolio, user_home=self.user))
        self.assertEqual(self.calls_made(), [])

    def test_portfolio_comes_from_the_install(self):
        (self.home / 'config/person.json').write_text(json.dumps({'portfolio': '../portfolio'}))
        env = {key: value for key, value in os.environ.items() if key != 'FOXRUN_PORTFOLIO'}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(schedule.portfolio_of(self.home), self.portfolio)
            with mock.patch.dict(os.environ, {'FOXRUN_PORTFOLIO': str(self.root / 'other')}):
                self.assertEqual(schedule.portfolio_of(self.home), self.root / 'other')
            (self.home / 'config/person.json').unlink()
            with mock.patch.dict(os.environ, {'HOME': str(self.user)}):
                self.assertEqual(schedule.portfolio_of(self.home), self.user / 'foxrun')

    def test_template_names_no_person(self):
        text = schedule.TEMPLATE.read_text()
        self.assertNotIn('/Users/', text)
        self.assertNotIn(pwd.getpwuid(os.getuid()).pw_name.lower(), text.lower())


if __name__ == '__main__':
    unittest.main()
