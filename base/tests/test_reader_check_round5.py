"""Assigned-key fixtures. Key bytes remain in temporary memory and files only."""

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
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import reader_check as rc

# The PEM header in two parts, so a secret scanner does not read this test as a key.
PEM_BEGIN='-----BEGIN '+'PRIVATE KEY-----'


class Round5PrivateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.openssl = shutil.which('openssl')
        if not cls.openssl:
            raise RuntimeError('fixture generator unavailable')
        cls.env = {**os.environ, 'OPENSSL_CONF': '/dev/null',
                   'RANDFILE': str(Path(cls.fixture.name)/'random-state')}
        generated = subprocess.run([cls.openssl, 'genpkey', '-algorithm', 'RSA', '-pkeyopt',
                                    'rsa_keygen_bits:1024', '-outform', 'DER'],
                                   cwd=cls.fixture.name, env=cls.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, check=True, timeout=15)
        cls.der = generated.stdout
        cls.encoded = base64.b64encode(cls.der).decode('ascii')

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.src = self.base/'src'; self.src.mkdir()
        self.out = self.base/'out'; self.trial = self.base/'trial'
        self.plan = {'thing': {'kind': 'table', 'name': 'people', 'database': str(self.base/'data/x.db')},
                     'roots': [{'path': str(self.src), 'program': 'plant'}]}

    def assigned(self, value=None):
        return 'payload = "'+(self.encoded if value is None else value)+'"\n'

    def closed_source(self, name, body, encoded=None):
        p = self.src/name; p.write_text(body)
        full_reads = []; real_read = Path.read_bytes
        def audited(path):
            if path == p: full_reads.append(str(path))
            return real_read(path)
        stdout = io.StringIO(); stderr = io.StringIO()
        with patch.object(Path, 'read_bytes', audited), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code, verdict = rc.check(self.plan, self.out, self.trial)
            rc.copy_workspace(self.src, self.base/'copy')
        scan = json.loads((self.out/'scan.json').read_text())
        self.assertEqual(code, 1)
        self.assertEqual(scan['files_read'], 0)
        self.assertEqual(verdict['private_named_source_files_searched'], 0)
        self.assertEqual(verdict['private_named_files_closed'], 1)
        self.assertEqual(full_reads, [])
        self.assertEqual([(r['path'],r['line']) for r in verdict['blocking_readers']], [(str(p),0)])
        self.assertFalse((self.base/'copy'/name).exists())
        emitted = stdout.getvalue()+stderr.getvalue()+''.join(f.read_text() for f in self.out.iterdir())
        self.assertNotIn(self.encoded, emitted)
        if encoded: self.assertNotIn(encoded, emitted)
        self.assertEqual(stderr.getvalue(), '')

    def searchable(self, name, body):
        p = self.src/name; p.write_text(body)
        code, verdict = rc.check(self.plan, self.out, self.trial)
        self.assertEqual(code, 1)
        self.assertEqual(verdict['private_named_files_closed'], 0)
        self.assertEqual(json.loads((self.out/'scan.json').read_text())['files_read'], 1)
        self.assertTrue(any(r['path']==str(p) and r['line']==2 for r in verdict['blocking_readers']))
        rc.copy_workspace(self.src, self.base/'copy')
        if not name.startswith('auth'):
            self.assertTrue((self.base/'copy'/name).exists())

    def test_key_fixture_is_valid_der(self):
        result = subprocess.run([self.openssl,'rsa','-inform','DER','-check','-noout'],
                                input=self.der, cwd=self.fixture.name, env=self.env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        self.assertEqual(result.returncode, 0)

    def test_base64_assignment_named(self): self.closed_source('auth.py', self.assigned())

    def test_base64_assignment_neutral(self): self.closed_source('module.py', self.assigned())

    def test_base64_assignment_javascript(self):
        self.closed_source('module.js', 'const payload = "'+self.encoded+'";\n')

    def test_base64_assignment_urlsafe_unpadded(self):
        value = base64.urlsafe_b64encode(self.der).decode().rstrip('=')
        self.closed_source('module.py', self.assigned(value), value)

    def test_base64_assignment_after_200_code_lines(self):
        self.closed_source('module.py', 'x = 1\n'*200+self.assigned())

    def test_base64_pem_assignment_neutral(self):
        pem = PEM_BEGIN+'\n'+self.encoded+'\n-----END PRIVATE KEY-----\n'
        value = base64.b64encode(pem.encode()).decode()
        self.closed_source('module.py', self.assigned(value), value)

    def test_raw_key_base64_assignment_neutral(self):
        value = base64.b64encode(bytes(range(32))).decode()
        self.closed_source('module.py', self.assigned(value), value)

    def test_split_base64_assignment_neutral(self):
        self.closed_source('module.py', 'payload = "'+self.encoded[:100]+'" + "'+self.encoded[100:]+'"\n')

    def test_base64_image_blob_is_closed(self):
        value = base64.b64encode(b'\x89PNG\r\n\x1a\n'+bytes(range(128))).decode()
        self.closed_source('module.js', 'const image = "data:image/png;base64,'+value+'";\n', value)

    def test_base64_font_blob_is_closed(self):
        value = base64.b64encode(b'wOFF'+bytes(range(128))).decode()
        self.closed_source('module.js', 'const font = "data:font/woff;base64,'+value+'";\n', value)

    def test_pem_header_comment_stays_searchable(self):
        self.searchable('module.py', '# '+PEM_BEGIN+'\nconn.execute("SELECT * FROM people")\n')

    def test_sha256_hex_constant_named_stays_searchable(self):
        digest = hashlib.sha256(b'public fixture').hexdigest()
        self.searchable('auth.py', self.assigned(digest)+'conn.execute("SELECT * FROM people")\n')

    def test_sha256_hex_constant_neutral_stays_searchable(self):
        digest = hashlib.sha256(b'public fixture').hexdigest().upper()
        self.searchable('module.py', self.assigned(digest)+'conn.execute("SELECT * FROM people")\n')

    def test_invalid_base64_literal_stays_searchable(self):
        self.searchable('module.py', self.assigned('A'*41)+'conn.execute("SELECT * FROM people")\n')

    def test_base64_key_target_never_enters_dry_test_copy(self):
        p = self.base/'data/module.py'; p.parent.mkdir(); p.write_text(self.assigned())
        (self.src/'probe.py').write_text('import sys\nassert len(sys.argv)==2\n')
        self.plan['thing'] = {'kind':'file','name':'module.py','path':str(p)}
        self.plan['roots'].append({'path':str(p),'program':'plant'})
        self.plan['readers'] = [{'program':'plant','workspace':str(self.src),'offline':True,
                                 'commands':[[sys.executable,'probe.py','{copy}']]}]
        code, verdict = rc.check(self.plan, self.out, self.trial, True)
        self.assertEqual(code, 1)
        self.assertTrue(verdict['test_setup_failed'])
        self.assertEqual(verdict['private_named_files_closed'], 1)
        for copy in self.trial.rglob('*'):
            if copy.is_file():
                self.assertNotIn(self.encoded.encode(), copy.read_bytes())


if __name__=='__main__': unittest.main()
