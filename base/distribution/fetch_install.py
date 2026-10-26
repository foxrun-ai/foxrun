#!/usr/bin/env python3
"""Fetch the versioned Workspace Install archive, then install into an explicit home.

The manifest SHA-256 is required. It is the trust anchor: it must come from the release owner by
another channel than the release address. The manifest then pins the archive and every file.
Without it, whoever controls the release address controls the code this command runs (T750 F11)."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, build_opener

MAX_ARCHIVE = 32_000_000

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

class HttpsOnlyRedirects(HTTPRedirectHandler):
    """Follow a redirect only to another HTTPS address."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != 'https':
            raise HTTPError(req.full_url, code, 'Refused a redirect away from HTTPS.', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def read_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in ('file', 'https'):
        raise ValueError('Use a local file or HTTPS release URL.')
    with build_opener(HttpsOnlyRedirects).open(value, timeout=30) as handle:
        if urlparse(handle.geturl()).scheme != parsed.scheme:
            raise ValueError('The release address moved to another scheme.')
        raw = handle.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('Release exceeds the size limit.')
    return raw

def safe_relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or path.as_posix() != value or '\\' in value:
        raise ValueError('Unsafe archive path.')
    return path

def safe_target(path):
    path = path.absolute()
    if path == Path(path.anchor):
        raise ValueError('Target cannot be a filesystem root.')
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError('Target crosses a symlink.')
    return path

def manifest_url(location):
    return location if urlparse(location).scheme else Path(location).resolve().as_uri()

def pinned_digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value.lower()):
        raise ValueError('Give --manifest-sha256: the 64-character manifest hash from the release owner.')
    return value.lower()

def load_manifest(location, expected_manifest_sha256):
    """Read the manifest once and check it against the pinned hash. Return (url, manifest)."""
    expected = pinned_digest(expected_manifest_sha256)
    url = manifest_url(location)
    manifest_bytes = read_url(url)
    if sha(manifest_bytes) != expected:
        raise ValueError('Manifest hash differs.')
    return url, json.loads(manifest_bytes)

def file_mode(mode):
    """Keep only whether a file runs. An archive never sets setuid, setgid, sticky, or group/other write bits."""
    return 0o755 if mode & 0o111 else 0o644

def fetch(manifest_location, target, expected_manifest_sha256, loaded=None):
    url, manifest = loaded or load_manifest(manifest_location, expected_manifest_sha256)
    if manifest.get('format') != 'foxrun-workspace-release/v1' or not manifest.get('files'):
        raise ValueError('Use a nonempty Workspace Install manifest.')
    expected = {}
    for entry in manifest['files']:
        name = safe_relative(entry['archive_path']).as_posix()
        if name in expected:
            raise ValueError('Duplicate archive path.')
        expected[name] = entry
    archive_url = urljoin(url, manifest['archive']['url'])
    if urlparse(archive_url).scheme != urlparse(url).scheme:
        raise ValueError('The archive must use the manifest address scheme.')
    archive_bytes = read_url(archive_url)
    if sha(archive_bytes) != manifest['archive']['sha256'] or len(archive_bytes) != manifest['archive']['bytes']:
        raise ValueError('Archive hash or length differs.')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:') as archive:
        for member in archive:
            name = safe_relative(member.name).as_posix()
            if not member.isfile() or name in files or name not in expected:
                raise ValueError('Unexpected, linked, or duplicate archive member.')
            if member.size != expected[name]['bytes']:
                raise ValueError('Archive member length differs.')
            raw = archive.extractfile(member).read()
            if sha(raw) != expected[name]['sha256']:
                raise ValueError('Archive member hash differs.')
            files[name] = (raw, member.mode)
    if set(files) != set(expected):
        raise ValueError('Archive file list differs.')
    target = safe_target(target)
    if target.exists():
        present = {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file() or p.is_symlink()}
        if present != set(files) or any((target / name).is_symlink() or (target / name).read_bytes() != raw for name, (raw, _) in files.items()):
            raise ValueError('Existing fetch target differs; nothing changed.')
        return manifest
    target.mkdir(parents=True)
    for name, (raw, mode) in files.items():
        path = target.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(file_mode(mode))
    return manifest

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--manifest-sha256', required=True,
                   help='Required: the manifest hash you received from the release owner by another channel.')
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument('--fetch-only', type=Path, help='Fetch and verify files without an installation.')
    target.add_argument('--home', type=Path, help='Install the made-up workspace into this explicit home.')
    args = p.parse_args()
    try:
        if args.fetch_only:
            fetch(args.manifest, args.fetch_only, args.manifest_sha256)
        else:
            home = safe_target(args.home)
            db = home / '.local/share/foxrun/data.db'
            if db.exists() and not (home / '.local/share/foxrun/install-receipt.json').is_file():
                raise ValueError('Existing data.db has no matching install receipt; nothing changed.')
            loaded = load_manifest(args.manifest, args.manifest_sha256)
            manifest = loaded[1]
            version = manifest['version']
            if not version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in version):
                raise ValueError('Unsafe version.')
            checkout = home / '.local/share/foxrun/modules' / version
            fetch(args.manifest, checkout, args.manifest_sha256, loaded)
            env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
            subprocess.run([sys.executable, str(checkout / 'base/distribution/install.py'), '--home', str(home), '--version', version], check=True, env=env)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print('FAIL Workspace Install: ' + str(error), file=sys.stderr)
        return 1
    print('PASS Workspace Install fetch: verified version and file hashes')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
