#!/usr/bin/env python3
"""The legacy release fetcher runs downloaded code only after a pinned manifest hash matches (T750 F11).

Each test builds a made-up release in a temporary folder. No network is used.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

SCRIPT = Path(__file__).resolve().parents[1] / 'distribution/fetch_install.py'
spec = importlib.util.spec_from_file_location('fetch_install_under_test', SCRIPT)
fetch_install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_install)

# The made-up installer leaves one file behind when it runs, so a test can see if downloaded code ran.
INSTALLER = b"from pathlib import Path\nimport sys\nPath(sys.argv[2], 'RAN').write_text('ran')\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class FetchInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='fetch-install-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.release = self.root / 'release'
        self.release.mkdir()
        files = {'base/distribution/install.py': (INSTALLER, 0o4755), 'README.md': (b'made-up release\n', 0o666)}
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name, (raw, mode) in files.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(raw), mode
                archive.addfile(info, io.BytesIO(raw))
        raw = buffer.getvalue()
        (self.release / 'r.tar').write_bytes(raw)
        manifest = {'format': 'foxrun-workspace-release/v1', 'version': '1.0',
                    'archive': {'url': 'r.tar', 'sha256': sha(raw), 'bytes': len(raw)},
                    'files': [{'archive_path': name, 'bytes': len(body), 'sha256': sha(body)}
                              for name, (body, _) in files.items()]}
        self.manifest = self.release / 'manifest.json'
        self.manifest.write_text(json.dumps(manifest))
        self.digest = sha(self.manifest.read_bytes())

    def run_fetch(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), '--manifest', str(self.manifest), *args],
                              capture_output=True, text=True, timeout=60)

    def test_no_pinned_hash_refuses_before_any_read(self):
        home = self.root / 'home'
        done = self.run_fetch('--home', str(home))
        self.assertEqual(done.returncode, 2)
        self.assertIn('--manifest-sha256', done.stderr)
        self.assertFalse(home.exists())

    def test_a_replaced_release_with_matching_inner_hashes_never_runs(self):
        # A release address that swaps both the manifest and the archive keeps every inner hash right.
        home = self.root / 'home'
        done = self.run_fetch('--manifest-sha256', '0' * 64, '--home', str(home))
        self.assertEqual(done.returncode, 1)
        self.assertIn('Manifest hash differs', done.stderr)
        self.assertFalse((home / 'RAN').exists())
        self.assertFalse((home / '.local/share/foxrun/modules').exists())
        done = self.run_fetch('--manifest-sha256', 'not-a-hash', '--fetch-only', str(self.root / 'out'))
        self.assertEqual(done.returncode, 1)
        self.assertIn('64-character manifest hash', done.stderr)

    def test_pinned_hash_installs_and_drops_special_mode_bits(self):
        home = self.root / 'home'
        done = self.run_fetch('--manifest-sha256', self.digest, '--home', str(home))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((home / 'RAN').read_text(), 'ran')
        checkout = home / '.local/share/foxrun/modules/1.0'
        self.assertEqual((checkout / 'base/distribution/install.py').stat().st_mode & 0o7777, 0o755)
        self.assertEqual((checkout / 'README.md').stat().st_mode & 0o7777, 0o644)

    def test_redirects_leave_https_never(self):
        handler = fetch_install.HttpsOnlyRedirects()
        request = Request('https://release.example.invalid/manifest.json')
        for target in ('http://release.example.invalid/manifest.json', 'file:///etc/passwd', 'ftp://x.invalid/m'):
            with self.subTest(target=target):
                with self.assertRaises(HTTPError) as caught:
                    handler.redirect_request(request, io.BytesIO(), 302, 'Found', {}, target)
                caught.exception.close()
        moved = handler.redirect_request(request, io.BytesIO(), 302, 'Found', {}, 'https://mirror.example.invalid/m')
        self.assertEqual(moved.full_url, 'https://mirror.example.invalid/m')

    def test_https_manifest_cannot_point_its_archive_at_a_local_file(self):
        manifest = json.loads(self.manifest.read_text())
        manifest['archive']['url'] = (self.release / 'r.tar').as_uri()
        raw = json.dumps(manifest).encode()
        with mock.patch.object(fetch_install, 'read_url', side_effect=lambda url: raw) as read:
            with self.assertRaisesRegex(ValueError, 'manifest address scheme'):
                fetch_install.fetch('https://release.example.invalid/manifest.json', self.root / 'out', sha(raw))
        self.assertEqual(read.call_count, 1)

    def test_other_schemes_are_refused(self):
        for url in ('http://release.example.invalid/manifest.json', 'ftp://release.example.invalid/m'):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'local file or HTTPS'):
                fetch_install.read_url(url)


if __name__ == '__main__':
    unittest.main()
