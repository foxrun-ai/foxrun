#!/usr/bin/env python3
"""Nightly exit (T293): lint and check findings are reported, not failures. A crashed step or a failed push fails."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CRON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRON))
import nightly  # noqa: E402

FINDINGS = [{'rule_id': 'R1', 'level': 'error', 'path': 'x', 'line': 1, 'what': 'w', 'how_to_fix': 'h'},
            {'rule_id': 'R2', 'level': 'warn', 'path': 'y', 'line': 2, 'what': 'w', 'how_to_fix': 'h'}]


class Runner:
    """Stub for subprocess.run. Each step answers from its table; nothing real runs."""

    def __init__(self, **answers):
        self.answers = {
            'lint.py': (1, json.dumps(FINDINGS)),
            'dream.py': (0, ''),
            'check.py': (1, 'handoff check: h.md\nMemory checks: 2 failed\n'),
        }
        self.answers.update(answers)

    def __call__(self, command, **_):
        name = Path(command[2]).name if len(command) > 2 else command[0]
        answer = self.answers.get(name, (0, ''))
        if isinstance(answer, Exception):
            raise answer
        code, out = answer
        return subprocess.CompletedProcess(command, code, stdout=out, stderr='')


class Notifier:
    def __init__(self, code=0):
        self.code = code
        self.calls = []

    def __call__(self, command, **_):
        self.calls.append(command)
        return subprocess.CompletedProcess(command, self.code, stdout='', stderr='notification failed' if self.code else '')


TOKEN = '1234567890:' + 'A' * 35
CHAT = '424242'  # A synthetic chat id, labeled fake; no real Telegram chat.


class Bot:
    """Stub for the secret reader and the Bot API. With fail_test, any use fails the test: no setting, no message."""

    def __init__(self, answer=None, fail_test=None, read_code=0):
        self.answer = answer if answer is not None else {'ok': True, 'result': {'message_id': 77}}
        self.fail_test, self.read_code = fail_test, read_code
        self.reads, self.posts = [], []

    def read(self, command, **_):
        if self.fail_test:
            self.fail_test.fail('a secret was read without the local setting')
        self.reads.append(command)
        value = TOKEN if command[1].endswith('TOKEN') else CHAT
        return subprocess.CompletedProcess(command, self.read_code, stdout=value + '\n', stderr='')

    def post(self, token, chat, text):
        if self.fail_test:
            self.fail_test.fail('a message was sent without the local setting')
        self.posts.append((token, chat, text))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class NightlyExit(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='nightly-exit-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for name in ('base/lint.py', 'memory/dream.py', 'memory/check.py'):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text('# stub\n')
        self.portfolio = self.root / 'portfolio'
        self.portfolio.mkdir()
        self.notifier = Notifier()

    def run_nightly(self, runner, bot=None, dry_run=False):
        bot = bot or Bot(fail_test=self)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = nightly.sequence(self.root, runner=runner, portfolio=self.portfolio, notifier=self.notifier,
                                    reader=bot.read, post=bot.post, dry_run=dry_run)
        receipts = sorted((self.root / 'runs/nightly').glob('*-nightly/receipt.json'))
        return code, json.loads(receipts[-1].read_text())

    def test_findings_do_not_fail_the_job(self):
        code, receipt = self.run_nightly(Runner())
        self.assertEqual(code, 0)
        self.assertEqual(receipt['exit'], 0)
        self.assertIsNone(receipt['alert'])
        self.assertFalse(self.notifier.calls)
        self.assertEqual(receipt['steps']['lint'], {'failed': False, 'findings': 2})
        self.assertEqual(receipt['steps']['check'], {'failed': False, 'findings': 2})
        lint = json.loads(next((self.root / 'runs/nightly').glob('*-lint/receipt.json')).read_text())
        self.assertEqual((lint['exit'], lint['findings'], lint['failed']), (1, 2, False))

    def test_check_that_crashed_before_its_summary_fails(self):
        code, receipt = self.run_nightly(Runner(**{'check.py': (1, 'FAIL memory checks: bad path\n')}))
        self.assertEqual(code, 1)
        self.assertTrue(receipt['steps']['check']['failed'])

    def test_lint_that_could_not_complete_fails(self):
        for answer in [(2, json.dumps(FINDINGS)), (1, 'not json')]:
            with self.subTest(answer=answer):
                code, receipt = self.run_nightly(Runner(**{'lint.py': answer}))
                self.assertEqual(code, 1)
                self.assertTrue(receipt['steps']['lint']['failed'])

    def test_dream_crash_fails(self):
        code, receipt = self.run_nightly(Runner(**{'dream.py': (1, '')}))
        self.assertEqual(code, 1)
        self.assertEqual(receipt['steps']['dream'], {'failed': True, 'exit': 1})
        self.assertTrue(receipt['alert']['delivered'])
        self.assertEqual(receipt['alert']['channel'], 'macOS')
        self.assertEqual(len(self.notifier.calls), 1)
        alert_file = next((self.root / 'runs/nightly').glob('*-nightly/alert.json'))
        self.assertEqual(json.loads(alert_file.read_text())['delivered'], True)

    def test_notification_failure_stays_visible(self):
        self.notifier.code = 1
        code, receipt = self.run_nightly(Runner(**{'dream.py': (1, '')}))
        self.assertEqual(code, 1)
        self.assertFalse(receipt['alert']['delivered'])
        self.assertIn('notification failed', receipt['alert']['detail'])

    def test_missing_program_fails(self):
        (self.root / 'memory/check.py').unlink()
        with self.assertRaises(ValueError):
            nightly.sequence(self.root, runner=Runner(), portfolio=self.portfolio)

    def test_runner_exception_propagates(self):
        # main() turns OSError and ValueError into exit 1.
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(FileNotFoundError):
                nightly.sequence(self.root, runner=Runner(**{'dream.py': FileNotFoundError('python3')}),
                                 portfolio=self.portfolio)

    def test_failed_push_fails(self):
        original = nightly.push_state
        nightly.push_state = lambda *a, **k: 1
        self.addCleanup(setattr, nightly, 'push_state', original)
        code, receipt = self.run_nightly(Runner())
        self.assertEqual(code, 1)
        self.assertEqual(receipt['steps']['push'], {'failed': True, 'exit': 1})


    # T801: one short message on an install whose local config names the bot; none elsewhere.
    def message_settings(self, **change):
        settings = {'sender': 'relay-bot', 'reader': '/opt/bin/secret-read',
                    'token_ref': 'op://Vault/Bot/TOKEN', 'chat_ref': 'op://Vault/Bot/CHAT_ID'}
        settings.update(change)
        (self.root / 'config').mkdir(exist_ok=True)
        (self.root / nightly.MESSAGE_SETTINGS).write_text(json.dumps({'telegram': settings}))

    def test_no_local_setting_sends_no_message(self):
        code, receipt = self.run_nightly(Runner())
        self.assertEqual(code, 0)
        self.assertIsNone(receipt['message'])

    def test_local_setting_sends_one_short_message_and_stores_no_value(self):
        self.message_settings()
        bot = Bot()
        code, receipt = self.run_nightly(Runner(**{'dream.py': (1, '')}), bot)
        self.assertEqual(code, 1)
        self.assertEqual(bot.reads, [['/opt/bin/secret-read', 'op://Vault/Bot/TOKEN'],
                                     ['/opt/bin/secret-read', 'op://Vault/Bot/CHAT_ID']])
        self.assertEqual(len(bot.posts), 1)
        token, chat, text = bot.posts[0]
        self.assertEqual((token, chat), (TOKEN, CHAT))
        self.assertRegex(text, r'^Foxrun nightly: failed \d{4}-\d\d-\d\d \d\d:\d\d · GitHub backup none$')
        message = receipt['message']
        self.assertEqual((message['sent'], message['message_id'], message['sender']), (True, 77, 'relay-bot'))
        everything = json.dumps(receipt) + ''.join(p.read_text() for p in (self.root / 'runs').rglob('*.json'))
        self.assertNotIn(TOKEN, everything)
        self.assertNotIn(CHAT, everything)

    def test_a_dry_run_sends_no_message(self):
        self.message_settings()
        code, receipt = self.run_nightly(Runner(), Bot(fail_test=self), dry_run=True)
        self.assertIsNone(receipt['message'])

    def test_a_refused_send_keeps_the_exit_and_hides_the_values(self):
        self.message_settings()
        bot = Bot(answer={'ok': False, 'description': 'Bad Request: chat ' + CHAT + ' not found for bot' + TOKEN})
        code, receipt = self.run_nightly(Runner(), bot)
        self.assertEqual(code, 0)
        self.assertFalse(receipt['message']['sent'])
        self.assertNotIn(TOKEN, json.dumps(receipt))
        self.assertNotIn(CHAT, json.dumps(receipt))
        self.assertIn('[REDACTED]', receipt['message']['detail'])

    def test_a_failed_secret_read_sends_nothing(self):
        self.message_settings()
        bot = Bot(read_code=1)
        code, receipt = self.run_nightly(Runner(), bot)
        self.assertFalse(bot.posts)
        self.assertFalse(receipt['message']['sent'])
        self.assertIn('secret read failed', receipt['message']['detail'])

    def test_an_invalid_setting_sends_nothing_and_says_why(self):
        self.message_settings(token_ref='plain-token-value')
        code, receipt = self.run_nightly(Runner(), Bot(fail_test=self))
        self.assertFalse(receipt['message']['sent'])
        self.assertIn('invalid', receipt['message']['detail'])
        self.assertNotIn('plain-token-value', json.dumps(receipt))


if __name__ == '__main__':
    unittest.main()
