"""Private round-four fixtures and byte-open audits. No real key material."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import base64
import builtins
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import reader_check as rc

# The PEM header in two parts, so a secret scanner does not read this test as a key.
PEM_BEGIN='-----BEGIN '+'PRIVATE KEY-----'


class Round4PrivateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.src = self.base/'src'; self.src.mkdir()
        self.plan = {'thing': {'kind': 'table', 'name': 'people', 'database': str(self.base/'data/x.db')},
                     'roots': [{'path': str(self.src), 'program': 'plant'}]}

    def write(self, name, content):
        p = self.src/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
        return p

    def ignore_case(self, nested=False):
        if nested:
            subprocess.run(['git', 'init', '-q', str(self.src)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        self.write('.gitignore', 'private/**/auth.go\n')
        p = self.write('private/auth.go', 'package main\nfunc run() { db.Query("SELECT * FROM people") }\n')
        real_open = io.open
        opened = set()
        def audited(file, *args, **kwargs):
            if isinstance(file, (str, bytes, Path)): opened.add(str(Path(file)))
            return real_open(file, *args, **kwargs)
        with patch.object(io, 'open', audited):
            code, verdict = rc.check(self.plan, self.base/'out', self.base/'trial')
        self.assertNotIn(str(p), opened)
        self.assertEqual(code, 1)
        self.assertEqual(verdict['private_named_source_files_searched'], 0)
        self.assertEqual(verdict['private_named_files_closed'], 1)

    def test_ignore_nested_zero_git_repository(self): self.ignore_case(True)

    def test_ignore_nested_zero_without_repository(self): self.ignore_case(False)

    def test_nonrepository_double_star_matches_zero_one_and_many_folders(self):
        self.write('.gitignore', 'private/**/auth.go\n')
        for name in ['private/auth.go', 'private/one/auth.go', 'private/one/two/auth.go']:
            p=self.write(name, 'package main\n')
            with self.subTest(path=name): self.assertTrue(rc.gitignored_path(p))

    def test_git_own_answer_honors_negated_rule(self):
        subprocess.run(['git', 'init', '-q', str(self.src)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        self.write('.gitignore', '*.go\n!auth.go\n')
        p=self.write('auth.go', 'package main\n')
        self.assertFalse(rc.gitignored_path(p))

    def test_single_star_does_not_cross_directory_separator(self):
        self.write('.gitignore', 'private/*/auth.go\n')
        p=self.write('private/one/two/auth.go', 'package main\n')
        self.assertFalse(rc.gitignored_path(p))

    def closed_source(self, name, content):
        p=self.write(name, content)
        opened=set(); real_open=io.open
        def audited(file, *args, **kwargs):
            if isinstance(file, (str, bytes, Path)): opened.add(str(Path(file)))
            return real_open(file, *args, **kwargs)
        stdout=io.StringIO(); stderr=io.StringIO()
        with patch.object(io, 'open', audited), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code, verdict=rc.check(self.plan, self.base/'out', self.base/'trial')
            rc.copy_workspace(self.src, self.base/'copy')
        self.assertEqual(code, 1)
        self.assertEqual(verdict['private_named_source_files_searched'], 0)
        self.assertEqual(verdict['private_named_files_closed'], 1)
        self.assertFalse(verdict['blocking_readers'][0]['line'])
        self.assertEqual(verdict['blocking_readers'][0]['path'], str(p))
        self.assertFalse((self.base/'copy'/name).exists())
        self.assertIn(str(p), opened)  # First-look bytes are opened; no source search follows.
        scan=json.loads((self.base/'out/scan.json').read_text())
        self.assertEqual(scan['files_read'], 0)
        emitted=stdout.getvalue()+stderr.getvalue()+''.join(f.read_text() for f in (self.base/'out').iterdir())
        self.assertNotIn(self.marker, emitted)
        self.assertNotIn(base64.b64encode(self.marker.encode()).decode(), emitted)
        self.assertEqual(stderr.getvalue(), '')

    marker='SYNTHETIC_FIRST_LOOK_MARKER'

    def pem(self):
        return PEM_BEGIN+'\n'+base64.b64encode((self.marker*8).encode()).decode()+'\n-----END PRIVATE KEY-----\n'

    def test_pem_named_source(self): self.closed_source('auth.py', self.pem())

    def test_pem_plain_source(self): self.closed_source('module.py', self.pem())

    def test_pem_other_source_extension(self): self.closed_source('token.go', self.pem())

    def test_pem_with_bom_and_leading_space(self): self.closed_source('auth.ts', '\ufeff \n'+self.pem())

    def test_pem_after_long_leading_whitespace(self): self.closed_source('auth.py', ' '*300+self.pem())

    def test_pem_block_after_code_is_closed(self): self.closed_source('module.py', 'x = 1\ny = 2\n'+self.pem())

    def entropy(self):
        payload=base64.b64encode(bytes(range(256))*8).decode()
        return '\n'.join(payload[i:i+64] for i in range(0,len(payload),64))+'\n'

    def test_high_entropy_named_source(self): self.closed_source('token_utils.py', self.entropy())

    def test_high_entropy_plain_source(self): self.closed_source('module.js', self.entropy())

    def test_mostly_key_text_after_code_prefix_is_closed(self):
        self.closed_source('auth.py', 'x = 1\n'+self.entropy())

    def test_ordinary_private_named_code_still_finds_reader(self):
        self.write('auth.py', 'import sqlite3\nconn.execute("SELECT * FROM people")\n')
        code, verdict=rc.check(self.plan, self.base/'out', self.base/'trial')
        self.assertEqual(code, 1)
        self.assertEqual(verdict['private_named_source_files_searched'], 1)
        self.assertEqual(verdict['private_named_files_closed'], 0)
        self.assertTrue(any(r['line']==2 for r in verdict['blocking_readers']))

    def test_python_key_literal_remains_code_without_value_output(self):
        self.write('auth.py', 'value = "'+self.marker+'"\nconn.execute("SELECT * FROM people")\n')
        code, verdict=rc.check(self.plan, self.base/'out', self.base/'trial')
        self.assertEqual(code, 1)
        self.assertEqual(verdict['private_named_source_files_searched'], 1)
        self.assertNotIn(self.marker, json.dumps(verdict))


if __name__=='__main__': unittest.main()
