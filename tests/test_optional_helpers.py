#!/usr/bin/env python3
"""The optional reader scripts keep their keys out of argv and never download code (T750 F08, F09).

Each test runs the script with fake programs on PATH. Nothing reaches a network or a real key.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

TREE = Path(__file__).resolve().parents[1]
IG_READ = TREE / 'tools/bin/ig-read'
TWEET_READ = TREE / 'tools/bin/tweet-read'

# Each fake program writes one JSON line: its name, argv, the key it sees, and its stdin.
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
stdin = '' if sys.stdin.isatty() else sys.stdin.read()
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({'name': os.path.basename(sys.argv[0]), 'argv': sys.argv[1:], 'stdin': stdin,
                          'key': os.environ.get('SCRAPECREATORS_API_KEY')}) + '\n')
if os.path.basename(sys.argv[0]) == 'curl':
    print(json.dumps({'data': {'id': '1', 'text': 'hello', 'author_id': '9'},
                      'includes': {'users': [{'id': '9', 'name': 'Sample', 'username': 'sample'}]}}))
elif os.path.basename(sys.argv[0]) == 'secret-reader':
    print('KEY-FROM-STORE')
else:
    print('{}')
'''


class HelperCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='optional-helpers-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'

    def fake(self, *names):
        for name in names:
            path = self.bin / name
            path.write_text(FAKE)
            path.chmod(0o755)
        return self.bin

    def run_script(self, script, *args, **env):
        environment = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.root), 'FAKE_LOG': str(self.log)}
        environment.update(env)
        return subprocess.run(['/bin/bash', str(script), *args], env=environment, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []


class TweetReadTests(HelperCase):
    TOKEN = 'AAAA' + 'synthetic%2Ftoken' + 'Zz9'

    def test_bearer_token_is_never_a_process_argument(self):
        self.fake('curl')
        done = self.run_script(TWEET_READ, 'https://x.com/sample/status/1', X_BEARER_TOKEN=self.TOKEN)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('hello', done.stdout)
        (curl,) = self.calls()
        self.assertNotIn(self.TOKEN, ' '.join(curl['argv']))
        self.assertEqual(curl['argv'][:3], ['-s', '-K', '-'])
        self.assertEqual(curl['stdin'], 'header = "Authorization: Bearer %s"\n' % self.TOKEN)
        self.assertNotIn(self.TOKEN, done.stdout + done.stderr)

    def test_a_token_that_could_break_the_config_line_is_refused(self):
        self.fake('curl')
        for bad in ('abc"\nurl = "http://elsewhere', 'abc\\x', 'abc def'):
            with self.subTest(bad=bad):
                done = self.run_script(TWEET_READ, 'https://x.com/sample/status/1', X_BEARER_TOKEN=bad)
                self.assertEqual(done.returncode, 1)
                self.assertIn('characters a bearer token does not use', done.stderr)
        self.assertEqual(self.calls(), [])


class IgReadTests(HelperCase):
    def test_no_installed_provider_stops_and_never_downloads(self):
        self.fake('npx', 'npm', 'secret-reader')
        done = self.run_script(IG_READ, 'profile', 'sample', SCRAPECREATORS_API_KEY_REF='ref://sample',
                               AGENT_SECRET_READ=str(self.bin / 'secret-reader'))
        self.assertEqual(done.returncode, 1)
        self.assertIn('never downloads it', done.stderr)
        # Neither a package runner nor the secret reader ran: the key is never loaded without a provider.
        self.assertEqual(self.calls(), [])

    def test_installed_provider_runs_with_the_key_and_no_package_runner(self):
        self.fake('npx', 'scrapecreators')
        done = self.run_script(IG_READ, 'profile', '@sample', SCRAPECREATORS_API_KEY='SYNTHETIC-KEY')
        self.assertEqual(done.returncode, 0, done.stderr)
        (call,) = self.calls()
        self.assertEqual(call['name'], 'scrapecreators')
        self.assertEqual(call['argv'], ['--json', '--no-color', 'instagram', 'profile', '--handle', 'sample'])
        self.assertEqual(call['key'], 'SYNTHETIC-KEY')

    def test_named_provider_must_be_an_executable_file(self):
        self.fake('npx')
        done = self.run_script(IG_READ, 'profile', 'sample', SCRAPECREATORS_API_KEY='SYNTHETIC-KEY',
                               SCRAPECREATORS_BIN=str(self.root / 'missing'))
        self.assertEqual(done.returncode, 1)
        self.assertIn('SCRAPECREATORS_BIN is not an executable file', done.stderr)
        self.assertEqual(self.calls(), [])
        provider = self.fake('scrapecreators') / 'scrapecreators'
        done = self.run_script(IG_READ, 'post', 'https://www.instagram.com/p/abc/', SCRAPECREATORS_API_KEY='K',
                               SCRAPECREATORS_BIN=str(provider))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([c['name'] for c in self.calls()], ['scrapecreators'])

    def test_the_script_holds_no_package_download(self):
        code = [line for line in IG_READ.read_text().splitlines() if not line.lstrip().startswith('#')]
        self.assertEqual([line for line in code if 'npx' in line], [])


if __name__ == '__main__':
    unittest.main()
