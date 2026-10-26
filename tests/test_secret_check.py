#!/usr/bin/env python3
"""Prove staged-only blocking, safe output, history bounds, chaining, and speed."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TREE = Path(__file__).resolve().parents[1]
CHECK = TREE / 'base/secret_check.py'
spec = importlib.util.spec_from_file_location('secret_check', CHECK)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class SecretCheck(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith('GIT_'):
                del self.env[key]
        self.git('init', '-q')
        self.git('config', 'user.name', 'Sample')
        self.git('config', 'user.email', 'sample@example.invalid')
        self.git('config', 'core.hooksPath', str(TREE / 'hooks/git'))

    def git(self, *args, **kwargs):
        return subprocess.run(['git', '-C', str(self.repo), *args], env=self.env,
                              capture_output=True, text=True, **kwargs)

    def stage(self, text, name='sample.txt'):
        (self.repo / name).write_text(text)
        self.assertEqual(0, self.git('add', '--', name).returncode)

    def test_real_commit_block_and_normal_commit_and_timing(self):
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        self.stage(value + '\n')
        result = self.git('commit', '-qm', 'blocked')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn(value, result.stdout + result.stderr)
        self.assertIn('github-token', result.stderr)
        self.assertIn('sample.txt', result.stderr)
        self.stage('A secret belongs in op://Vault/Item/password.\n')
        start = time.monotonic()
        self.assertEqual(0, self.git('commit', '-qm', 'normal').returncode)
        self.assertLess(time.monotonic() - start, 1)

    def test_hash_metadata_uuid_and_code_expressions_pass(self):
        digest = '0123456789abcdef' * 4
        for name in ('product-manifest.tsv', 'release.sha256', 'package-lock.json',
                     'uv.lock', 'pnpm-lock.yaml'):
            self.stage(f'api_key="{digest}"\n', name)
        self.stage('secret_key=fill_from_markdown(row.get("auth_token"))\n', 'builder.py')
        self.stage('token_key="123e4567-e89b-42d3-a456-426614174000"\n', 'metadata.txt')
        self.assertEqual([], scanner.staged(self.repo))
        start = time.monotonic()
        self.assertEqual(0, self.git('commit', '-qm', 'digest metadata').returncode)
        self.assertLess(time.monotonic() - start, 1)

    def test_keyword_argument_inside_a_call_is_code(self):
        self.stage('digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()\n',
                   'hashing.py')
        self.assertEqual([], scanner.staged(self.repo))
        self.stage('api_token = "Zq8Lr2Vx9Pn4Ks7Mw3Ty6Hb1Jd5Gf0Rc"\n', 'quoted.py')
        self.assertIn('entropy-assignment', [hit['pattern'] for hit in scanner.staged(self.repo)])

    def test_pure_move_passes_and_moved_then_edited_is_scanned(self):
        self.stage('key=key+suffix\nsvg_sha256=hashlib.sha256(data).hexdigest()\n', 'old.py')
        self.assertEqual(0, self.git('commit', '-qm', 'base', '--no-verify').returncode)
        (self.repo / 'moved').mkdir()
        self.assertEqual(0, self.git('mv', 'old.py', 'moved/old.py').returncode)
        self.assertEqual([], scanner.staged(self.repo))
        self.assertEqual(0, self.git('commit', '-qm', 'move').returncode)
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        self.assertEqual(0, self.git('mv', 'moved/old.py', 'again.py').returncode)
        with open(self.repo / 'again.py', 'a') as handle:
            handle.write(value + '\n')
        self.assertEqual(0, self.git('add', '--', 'again.py').returncode)
        self.assertIn('github-token', [hit['pattern'] for hit in scanner.staged(self.repo)])

    def test_synthetic_fixture_and_ordinary_fake_token(self):
        value = f"ghp_{'a' * 36}"
        self.stage(value + '\n', 'fake-token.fixture')
        self.assertEqual([], scanner.staged(self.repo))
        start = time.monotonic()
        self.assertEqual(0, self.git('commit', '-qm', 'synthetic fixture').returncode)
        self.assertLess(time.monotonic() - start, 1)
        self.stage(value + '\n', 'credentials.txt')
        result = self.git('commit', '-qm', 'ordinary token refuses')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn(value, result.stdout + result.stderr)
        self.assertIn('github-token', result.stderr)

    def test_provider_token_still_blocks_in_hash_and_fixture_files(self):
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        for name in ('product-manifest.tsv', 'release.sha256', 'package-lock.json',
                     'fake-token.fixture', 'test_credentials.py'):
            with self.subTest(path=name):
                self.assertIn('github-token', scanner.names(value, scanner.patterns(), name))
        digest = '0123456789abcdef' * 4
        self.assertIn('entropy-assignment', scanner.names(f'api_key="{digest}"',
                      scanner.patterns(), 'credentials.txt'))
        self.assertIn('entropy-assignment', scanner.names(
            f'secret_key="{value}!@#"',
            scanner.patterns(), 'test_credentials.py'))

    def test_static_ids_paths_and_shell_references_are_narrow(self):
        rules = scanner.patterns()
        for text, path in (
                ('const storageKey="fake-sample-test-example-only-1";', 'ui.js'),
                ('const stateKey="fake-sample-test-example-only-1";', 'index.html'),
                ('<div data-key="fake-sample-test-example-only-1">', 'index.html'),
                ('key="k-123e4567-e89b-42d3-a456-426614174000"', 'manifest.json'),
                ('readonly TOKEN_READER="/Users/sample/bin/agent-secret-read"', 'runner.zsh'),
                ('auth_token=$auth_token', 'runner.zsh'),
                ('auth_token=${AUTH_TOKEN:-}', 'runner.zsh'),
                ('auth_token: token', 'guide.md')):
            with self.subTest(path=path):
                self.assertEqual([], scanner.names(text, rules, path))
        # A generic key and credential assignment retain the entropy check.
        for binding, path in (('key', 'manifest.json'), ('storageKey', 'credentials.env')):
            self.assertIn('entropy-assignment', scanner.names(
                f'{binding}="fake-sample-test-example-only-v1"', rules, path))
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        for text, path in ((f'storageKey="{value}"', 'ui.js'),
                           (f'key="{value}"', 'integrity.json'),
                           (f'TOKEN_READER="/Users/sample/{value}"', 'runner.zsh')):
            self.assertIn('github-token', scanner.names(text, rules, path))

    def test_unquoted_credentials_keep_punctuation_and_block_commits(self):
        # A generic, runtime-made fake exercises entropy without provider prefixes.
        value = 'aB3dE5gH7jK9mN2pQ4sT6vX8'
        for name, binding, ending in (('shell.sh', 'token', ';'),
                                       ('.env', 'secret', '!')):
            with self.subTest(path=name):
                self.stage(f'{binding}={value}{ending}\n', name)
                hits = scanner.staged(self.repo)
                self.assertTrue(any(hit['pattern'] == 'entropy-assignment' for hit in hits))
                start = time.monotonic()
                result = self.git('commit', '-qm', 'punctuated credential refuses')
                self.assertNotEqual(0, result.returncode)
                self.assertLess(time.monotonic() - start, 1)
                self.assertIn('entropy-assignment', result.stderr)
                self.assertNotIn(value, result.stdout + result.stderr)
                self.stage('safe now\n', name)
        self.assertEqual([], scanner.staged(self.repo))
        embedded = f"source = 'api_key={value}!'"
        self.assertIn('entropy-assignment', scanner.names(embedded, scanner.patterns(), 'test_source.py'))

    def test_record_ids_and_python_expressions_are_narrow(self):
        rules = scanner.patterns()
        label = 'fake-sample-test-example-only-v1'
        for binding in ('row_key', 'import_key'):
            self.assertEqual([], scanner.names(f'{binding}="{label}"', rules, 'records.py'))
        self.assertIn('entropy-assignment', scanner.names(f'api_key="{label}"', rules, 'records.py'))
        source = 'secret_key=fill_from_markdown(row.get("auth_token"))'
        self.assertEqual([], scanner.names(source, rules, 'builder.py'))
        self.assertEqual([], scanner.names(f'example = {source!r}', rules, 'test_builder.py'))
        self.assertIn('entropy-assignment', scanner.names(source, rules, '.env'))
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        for binding in ('row_key', 'import_key'):
            self.assertIn('github-token', scanner.names(f'{binding}="{value}"', rules, 'records.py'))

    def test_javascript_and_typescript_unquoted_code_and_random_tokens(self):
        rules = scanner.patterns()
        random = ''.join(('Zq8Lr2Vx9Pn4Ks7M', 'w3Ty6Hb1Jd5Gf0Rc'))
        expressions = (
            'calculateCredentialValue(currentConfiguration)',
            'configuration.credentials.currentValue',
            'configuration[currentCredentialIndex]',
            'currentCredentialValue;',
            '(currentCredentialValue)',
            'currentCredentialValue,fallbackCredentialValue',
            'currentCredentialValue=>nextCredentialValue',
            'currentCredentialValue??fallbackCredentialValue',
            '{currentCredentialValue}</span>',
            '`snapshot:record:${currentConfiguration}`',
        )
        for suffix in ('.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'):
            path = 'credentials' + suffix
            with self.subTest(path=path):
                for expression in expressions:
                    self.assertEqual([], scanner.names('secret_key=' + expression, rules, path))
                for quote in ('', '"', "'"):
                    hits = scanner.names('secret_key=' + quote + random + quote, rules, path)
                    self.assertIn('entropy-assignment', hits)
                # Quoting makes punctuation data, rather than a code expression.
                self.assertIn('entropy-assignment', scanner.names(
                    'secret_key="' + random + '.[];,=>??"', rules, path))
        self.assertIn('entropy-assignment', scanner.names(
            'secret_key=' + expressions[0], rules, 'credentials.env'))

    def test_python_block_headers_and_random_default_still_block(self):
        rules = scanner.patterns()
        headers = (
            'def safe_dump(value,sort_keys=True,allow_unicode=True):',
            'async def safe_dump(value,sort_keys=True,allow_unicode=True):',
            'class Writer(secret_key=current_configuration_value):',
            'if secret_key==current_configuration_value:',
            'while secret_key==current_configuration_value:',
            'with open(current_configuration_file,secret_key=current_configuration_value):',
        )
        for header in headers:
            with self.subTest(shape=header.split()[0]):
                self.assertEqual([], scanner.names(header, rules, 'writer.py'))
        random = ''.join(('Zq8Lr2Vx9Pn4Ks7M', 'w3Ty6Hb1Jd5Gf0Rc'))
        for header in ('def safe_dump(secret_key="{value}"):',
                       'class Writer(secret_key="{value}"):',
                       'with open(current_configuration_file,secret_key="{value}") :'):
            self.assertIn('entropy-assignment', scanner.names(
                header.format(value=random), rules, 'writer.py'))
        self.assertIn('entropy-assignment', scanner.names(
            'secret_key="' + random + '"', rules, 'writer.py'))

    def test_quoted_word_ids_require_two_parts_and_exact_shape(self):
        rules = scanner.patterns()
        random = ''.join(('Zq8Lr2Vx9Pn4Ks7M', 'w3Ty6Hb1Jd5Gf0Rc'))
        for path in ('records.py', 'credentials.env', 'config.ts', 'playwright.config.mjs'):
            for separator in ('-', ':', '_', ','):
                label = separator.join(('stable', 'deduplication', '2026', 'credential', '1234'))
                for quote in ('"', "'"):
                    with self.subTest(path=path, separator=separator, quote=quote):
                        self.assertEqual([], scanner.names(
                            'api_key=' + quote + label + quote, rules, path))
                self.assertIn('entropy-assignment', scanner.names(
                    'api_key="' + random + '"', rules, path))
        for label in ('ab-cd-ef-gh-ij-kl-mn-op-qr-st-uv',
                      'stable-Deduplication-2026-credential',
                      'stable.deduplication.2026.credential',
                      'stable-deduplication2026-credential',
                      'stable-deduplication-2026-credential!',
                      'a-deduplication-2026-credential'):
            self.assertIn('entropy-assignment', scanner.names(
                'api_key="' + label + '"', rules, 'credentials.env'))
        self.assertIn('entropy-assignment', scanner.names(
            'api_key=stable-deduplication-2026-credential', rules, 'credentials.env'))

    def test_word_id_two_letter_parts_and_digit_groups_pass(self):
        rules = scanner.patterns()
        for separator in ('-', ':', '_', ','):
            for parts in (('schedule', 'ab', '2026', '10', '21'),
                          ('deduplication', '1234567890')):
                for quote in ('"', "'"):
                    label = separator.join(parts)
                    self.assertEqual([], scanner.names(
                        'api_key=' + quote + label + quote, rules, 'credentials.env'))

    def test_work_retry_key_digest_passes_and_nothing_wider(self):
        # work.py done writes 'retry-key=' + a sha256 hexdigest into activity notes; state/ exports it.
        import hashlib
        rules = scanner.patterns()
        digest = hashlib.sha256(b'T799 sample done call').hexdigest()
        row = '{"field":"receipt","note":"Proof: sample. | retry-key=' + digest + '","verb":"attached"}'
        self.assertEqual([], scanner.names(row, rules, 'activity.jsonl'))
        self.assertEqual([], scanner.names('note | retry-key=' + digest, rules, 'activity.jsonl'))
        random = ''.join(('Zq8Lr2Vx9Pn4Ks7M', 'w3Ty6Hb1Jd5Gf0Rc')) * 2
        for text in ('api_key=' + digest, 'retry_key=' + digest, 'x-retry-key=' + digest,
                     'retry-key=' + digest.upper(), 'retry-key=' + digest + 'a',
                     'retry-key=' + random, 'retry-key=' + digest + '-' + random):
            self.assertIn('entropy-assignment', scanner.names(text, rules, 'activity.jsonl'), text[:12])
        self.stage(row + '\n', 'activity.jsonl')
        self.assertEqual([], scanner.staged(self.repo))

    def test_sort_keys_argument_in_prose_passes_and_nothing_wider(self):
        # A bug row quotes the json.dumps call that an earlier check flagged; bugs.jsonl is not code.
        rules = scanner.patterns()
        call = 'sort_keys=True' + ').encode()).hexdigest()'
        self.assertEqual([], scanner.names('"problem":"matched ' + call + ' in install.py"', rules, 'bugs.jsonl'))
        random = ''.join(('Zq8Lr2Vx9Pn4Ks7M', 'w3Ty6Hb1Jd5Gf0Rc'))
        for text in ('sort_keys=' + random, 'sort_keys=True' + random + ')',
                     'api_key=True).' + random, 'my_sort_keys=' + random):
            self.assertIn('entropy-assignment', scanner.names(text, rules, 'bugs.jsonl'), text[:12])

    def test_word_id_exception_keeps_mixed_case_random_tokens_blocked(self):
        rules = scanner.patterns()
        random = ''.join(('Zq8Lr2Vx9Pn4Ks7M', 'w3Ty6Hb1Jd5Gf0Rc'))
        for suffix in ('.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'):
            self.assertIn('entropy-assignment', scanner.names(
                'api_key="stable-ab-' + random + '-2026"', rules, 'credentials' + suffix))

    def test_lowercase_test_values_are_limited_to_quoted_test_assignments(self):
        rules = scanner.patterns()
        value = ''.join(('zq8lr2vx9pn4ks7m', 'w3ty6hb1jd5gf0rc'))
        paths = ('bridge-auth.test.ts', 'bridge_test.ts', 'test_bridge.py',
                 'tests/bridge.ts', 'src/tests/bridge.py')
        for path in paths:
            for quote in ('"', "'"):
                self.assertEqual([], scanner.names(
                    'api_key=' + quote + value + quote, rules, path))
            for ending in ('+', '/', '='):
                self.assertIn('entropy-assignment', scanner.names(
                    'api_key="' + value + ending + '"', rules, path))
            if not path.endswith('.py'):
                self.assertIn('entropy-assignment', scanner.names('api_key=' + value, rules, path))
        for path in ('bridge.ts', 'contest/bridge.ts',
                     'test_bridge.ts', 'bridge_testdata.ts', 'bridge_test', 'Tests/bridge.ts'):
            self.assertIn('entropy-assignment', scanner.names('api_key="' + value + '"', rules, path))

    def test_test_value_exception_keeps_mixed_case_random_tokens_blocked(self):
        rules = scanner.patterns()
        random = ''.join(('Zq8Lr2Vx9Pn4Ks7M', 'w3Ty6Hb1Jd5Gf0Rc'))
        paths = ['credentials.test' + suffix for suffix in
                 ('.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx')]
        paths += ['credentials_test.ts', 'test_credentials.py', 'src/tests/credentials.ts']
        for path in paths:
            self.assertIn('entropy-assignment', scanner.names('api_key="' + random + '"', rules, path))

    def test_word_id_exception_keeps_provider_patterns(self):
        rules = scanner.patterns()
        lower = 'abcdefghijklmnopqrstuvwxyzabcdefghij'
        cases = (
            ('github-token', 'ghp_' + lower),
            ('github-fine-grained', 'github_pat_' + lower * 2),
            ('openai-token', 'sk-proj-' + lower * 2),
            ('anthropic-token', 'sk-ant-api03-' + lower * 2),
            ('aws-access-key', 'AKIA' + 'ABCDEFGH12345678'),
            ('slack-token', 'xoxb-' + lower + '-1234567890'),
        )
        for pattern, value in cases:
            for path in ('credentials.py', 'credentials.ts', 'credentials.env',
                         'credentials.test.ts', 'credentials_test.ts', 'test_credentials.py',
                         'src/tests/credentials.ts'):
                with self.subTest(pattern=pattern, path=path):
                    self.assertIn(pattern, scanner.names('api_key="' + value + '"', rules, path))

    def test_tuned_history_has_same_context_rules(self):
        digest = '0123456789abcdef' * 4
        self.stage(f'api_key="{digest}"\n', 'product-manifest.tsv')
        self.stage(f"ghp_{'a' * 36}\n", 'fake-token.fixture')
        self.assertEqual(0, self.git('commit', '-qm', 'metadata and fake fixture').returncode)
        result = scanner.history(self.repo)
        self.assertEqual([], result['findings'])
        self.assertFalse(result['bounded'])

    def test_staged_bytes_only_and_line_numbers(self):
        value = 'sk-' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6'
        self.stage('normal\n')
        (self.repo / 'sample.txt').write_text(value)
        self.assertEqual([], scanner.staged(self.repo))
        self.stage('first\nsecond\n' + value + '\n')
        (self.repo / 'sample.txt').write_text('safe now\n')
        hits = scanner.staged(self.repo)
        self.assertEqual(3, hits[0]['line'])
        self.assertNotIn(value, json.dumps(hits))

    def test_all_rules_and_references(self):
        rules = scanner.patterns()
        key_kind = 'RSA'
        cases = {
            'github-token': 'ghp_' + 'a' * 36,
            'github-fine-grained': 'github_pat_' + 'A1' * 30,
            'openai-token': 'sk-proj-' + 'A1b2' * 12,
            'anthropic-token': 'sk-ant-api03-' + 'A1b2' * 12,
            'aws-access-key': 'AKIA' + 'A1' * 8,
            'aws-secret-key': 'aws_secret_access_key=' + 'aB1/' * 10,
            'slack-token': 'xoxb-' + '12ab-' * 10,
            'google-api-key': 'AIza' + 'a' * 35,
            'google-oauth-token': 'ya29.' + 'aB1_' * 10,
            'private-key': f'-----BEGIN {key_kind} PRIVATE KEY-----',
            'bearer-value': 'Authorization: Bearer ' + 'aB1_' * 8,
            'cookie-value': '; '.join(f'{key}={value}' for key, value in [('auth_token', 'abc123'), ('ct0', 'xyz987')]),
            'entropy-assignment': 'api_key="' + 'aB3dE5gH7jK9mN2pQ4sT6vX8' + '"',
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.assertIn(name, scanner.names(text, rules))
        punctuated = 'password=\"' + 'aB!2@cD#4$eF%6^gH&8*iJ(0)' + '\"'
        self.assertIn('entropy-assignment', scanner.names(punctuated, rules))
        for text in ('secret in prose', 'token = op://Vault/Item/key',
                     'auth_token=op://Vault/Item/key', 'ct0=', 'password="example"',
                     'Authorization: Bearer ${TOKEN}'):
            self.assertEqual([], scanner.names(text, rules), text)
        self.assertIn('github-token', scanner.names('op://Vault/Item/key ' + cases['github-token'], rules))

    def test_unicode_path_and_added_diff_header_text(self):
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        self.stage('++ ' + value + '\n', 'café name.txt')
        hit = scanner.staged(self.repo)[0]
        self.assertEqual('café name.txt', hit['file'])
        self.assertEqual(1, hit['line'])

    def test_binary_diff_and_original_hook_staging_a_token(self):
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        path = self.repo / 'sample.bin'
        path.write_bytes(b'\0' + value.encode())
        self.git('add', '--', 'sample.bin')
        self.assertTrue(scanner.staged(self.repo))
        result = self.git('commit', '-qm', 'binary refuses')
        self.assertNotEqual(0, result.returncode)
        path.write_text('safe\n');self.git('add', '--', 'sample.bin')
        hook = self.repo / '.git/hooks/pre-commit'
        # The original hook copies a runtime-generated fixture into the index.
        (self.repo / 'fixture').write_text(value)
        hook.write_text('#!/bin/sh\ncp fixture sample.bin\ngit add -- sample.bin\n')
        hook.chmod(0o755)
        result = self.git('commit', '-qm', 'original stages secret')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn(value, result.stdout + result.stderr)
        self.assertIn('github-token', result.stderr)

    def test_labels_arguments_references_prose_and_empty_policy(self):
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        self.stage(value, value + '.txt')
        result = self.git('commit', '-qm', 'sensitive name')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn(value, result.stdout + result.stderr)
        self.assertIn('[REDACTED].txt', result.stderr)
        result = subprocess.run([sys.executable, str(CHECK), '--commits', value],
            capture_output=True, text=True, env=self.env)
        self.assertEqual(2, result.returncode)
        self.assertNotIn(value, result.stdout + result.stderr)
        self.assertEqual([], scanner.names('op://Vault/' + value + '/key', scanner.patterns()))
        self.assertIn('github-token', scanner.names('op://Vault/' + value + '/key ' + value, scanner.patterns()))
        self.assertEqual([], scanner.names('Use bearer authentication and keep the secret closed.', scanner.patterns()))
        for prose in ('The bearer acknowledges/accepts these terms.', 'The bearer authentication scheme is documented.'):
            self.assertEqual([], scanner.names(prose, scanner.patterns()))
        for quote in ('"', "'", '`'):
            reference = quote + 'op://Vault/Item name ' + value + '/field' + quote
            self.assertEqual([], scanner.names(reference, scanner.patterns()))
        start = time.monotonic()
        for text in ('a' * 15000, 'key' * 5000, 'key' + 'a' * 15000):
            self.assertEqual([], scanner.names(text, scanner.patterns()))
        self.assertLess(time.monotonic() - start, 0.5)
        with patch.object(scanner.json, 'loads', return_value=[]):
            with self.assertRaises(ValueError):scanner.patterns()

    def test_preserved_hooks_keep_arguments_stdin_and_failure(self):
        hook = self.repo / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\necho original-hook-ran >&2\nexit 13\n')
        hook.chmod(0o755)
        self.stage('normal\n')
        result = self.git('commit', '-qm', 'original refuses')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('original-hook-ran', result.stderr)
        hook.write_text('#!/bin/sh\nexit 0\n')
        post = self.repo / '.git/hooks/post-commit'
        post.write_text('#!/bin/sh\ntouch original-post-ran\n')
        post.chmod(0o755)
        self.assertEqual(0, self.git('commit', '-qm', 'original passes').returncode)
        self.assertTrue((self.repo / 'original-post-ran').exists())
        merge = self.repo / '.git/hooks/post-merge'
        merge.write_text('#!/bin/sh\nprintf "%s" "$1" > original-argument\ncat > original-stdin\nexit 17\n')
        merge.chmod(0o755)
        result = subprocess.run([str(TREE / 'hooks/git/post-merge'), 'argument'],
            cwd=self.repo, input='sample stdin', text=True, capture_output=True, env=self.env)
        self.assertEqual(17, result.returncode)
        self.assertEqual('argument', (self.repo / 'original-argument').read_text())
        self.assertEqual('sample stdin', (self.repo / 'original-stdin').read_text())

    def test_history_removed_lines_and_limits(self):
        value = 'ghp_' + 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4'
        self.stage(value + '\n', 'space name.txt')
        # Bypass only the disposable fixture hook to make contaminated history.
        self.assertEqual(0, self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture').returncode)
        self.stage('safe\n', 'space name.txt')
        self.assertEqual(0, self.git('commit', '-qm', 'remove').returncode)
        result = scanner.history(self.repo)
        self.assertTrue(result['findings'])
        self.assertFalse(result['bounded'])
        self.assertTrue(all(len(hit['commit']) == 40 for hit in result['findings']))
        self.assertNotIn(value, json.dumps(result))
        self.assertEqual('commits', scanner.history(self.repo, commits=1)['limit'])
        self.assertEqual('bytes', scanner.history(self.repo, max_bytes=30)['limit'])


if __name__ == '__main__':
    unittest.main()
