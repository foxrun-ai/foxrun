#!/usr/bin/env python3
"""Check the local release in two clean homes. No network or runtime adoption."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(root, times=False):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('A test home contains a symlink.')
        if path.is_file():
            info = path.stat()
            result[path.relative_to(root).as_posix()] = [digest(path.read_bytes()), info.st_mode & 0o777]
            if times:
                result[path.relative_to(root).as_posix()].append(info.st_mtime_ns)
    return result


def call(argv, home, interpreter=sys.executable):
    env = {'HOME': str(home), 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'LC_ALL': 'C'}
    return subprocess.run([interpreter, *map(str, argv)], cwd=home, env=env,
                          capture_output=True, text=True)


def require(test, message):
    if not test:
        raise ValueError(message)


def run(root, cases):
    repo = root / 'code/foxrun-modules'
    here = repo / 'distribution'
    home_root = root / 'home'
    home_root.mkdir(parents=True, exist_ok=True)
    build = load(here / 'build_release.py', 'clean_build')
    privacy = load(here / 'privacy.py', 'clean_privacy')
    release = home_root / 'wib-release'
    manifest = build.build(root, release)
    manifest_path = release / 'manifest.json'
    # The clean install uses the hash the release owner would hand out; fetch_install requires it (T750 F11).
    pinned = ['--manifest-sha256', digest(manifest_path.read_bytes())]
    original = json.loads((here / 'release/manifest.json').read_text())
    require({r['archive_path'] for r in manifest['files']} ==
            {r['archive_path'] for r in original['files']}, 'WIa shipped file list differs.')
    require(bool(manifest['files']), 'The shipped file list is empty.')
    references = privacy.references(root / 'vault/people', root / 'vault/cedar-shop')
    results, steps = [], []
    for name in cases:
        try:
            if name == 'release':
                before = tree(release, True)
                build.build(root, release)
                require(tree(release, True) == before, 'The second release build changes files.')
            elif name == 'zero':
                # Each check starts from zero. Older homes are retained as evidence.
                for number in (1, 2):
                    home = home_root / ('clean-' + str(number))
                    if home.exists():
                        archive = home_root / 'archive/clean-install'
                        archive.mkdir(parents=True, exist_ok=True)
                        count = len(list(archive.iterdir()))
                        home.rename(archive / (home.name + '-' + str(count)))
                    home.mkdir()
                    require(not list(home.iterdir()), 'The home is not empty.')
                    result = call([release / 'fetch_install.py', '--manifest', manifest_path, *pinned,
                                   '--home', home], home)
                    steps.append({'step': 'zero clean-' + str(number), 'exit': result.returncode,
                                  'stdout': result.stdout, 'stderr': result.stderr})
                    require(result.returncode == 0, 'Install step breaks: ' + result.stderr.strip())
                    checkout = home / '.local/share/foxrun/modules' / manifest['version']
                    require(set(tree(checkout)) == {r['archive_path'] for r in manifest['files']},
                            'Unshipped files appear in the installed modules.')
                    for row in manifest['files']:
                        require(digest((checkout / row['archive_path']).read_bytes()) == row['sha256'],
                                'An installed module file differs.')
                require(tree(home_root / 'clean-1') == tree(home_root / 'clean-2'),
                        'The two clean installs have different bytes or modes.')
            elif name == 'commands':
                home = home_root / 'clean-1'
                checkout = home / '.local/share/foxrun/modules' / manifest['version']
                db = home / '.local/share/foxrun/data.db'
                result = call([checkout / 'base/distribution/lookup.py', 'task', '--db', db], home)
                require(result.returncode == 0 and json.loads(result.stdout)['result'] == 'matched',
                        'The installed lookup command fails.')
                with tempfile.TemporaryDirectory(prefix='wib-table-command-', dir=home_root) as temporary:
                    control = Path(temporary)
                    copy = control / 'data.db'
                    copy.write_bytes(db.read_bytes())
                    result = call([checkout / 'base/commands/work_tasks', '--db', copy,
                                   '--workspace', 'cedar-shop', '--actor', 'sample-owner', '--session', 'clean-install',
                                   'update', '--id', '1', '--json', '{"title":"Pack garden tools"}'],
                                  control, interpreter='/bin/sh')
                    require(result.returncode == 0, 'The installed table command fails: ' + result.stderr.strip())
                    changed = _fox_person.connect(copy.resolve().as_uri() + '?mode=ro', uri=True)
                    try:
                        require(changed.execute('SELECT title,version FROM work_tasks WHERE id=1').fetchone() ==
                                ('Pack garden tools', 2), 'The installed command does not update the sample task.')
                    finally:
                        changed.close()
                current = _fox_person.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
                try:
                    require(current.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Database integrity fails.')
                    require(not list(current.execute('PRAGMA foreign_key_check')), 'Database links fail.')
                    require(current.execute('SELECT count(*) FROM work_tasks').fetchone()[0] == 2, 'Sample tasks differ.')
                    require(current.execute('SELECT count(*) FROM base_installs').fetchone()[0] == 6, 'Installed-module rows differ.')
                finally:
                    current.close()
            elif name == 'conformance':
                home = home_root / 'clean-1'
                checkout = home / '.local/share/foxrun/modules' / manifest['version']
                result = call([checkout / 'base/check_workspace.py', home / 'Workspaces/cedar-shop',
                               '--function', 'commerce'], home)
                report = json.loads(result.stdout)
                require(result.returncode == 0 and report['status'] == 'clean' and not report['findings'],
                        'Sample conformance has findings.')
                steps.append({'step': 'conformance', 'status': report['status'], 'findings': report['summary']['findings']})
            elif name == 'repeat':
                for number in (1, 2):
                    home = home_root / ('clean-' + str(number))
                    before = tree(home, True)
                    result = call([release / 'fetch_install.py', '--manifest', manifest_path, *pinned, '--home', home], home)
                    require(result.returncode == 0, 'The second install fails.')
                    require(tree(home, True) == before, 'The second install changes bytes, modes, or file times.')
            elif name == 'privacy':
                report = privacy.sweep(root, manifest_path, root / 'vault/people', root / 'vault/cedar-shop', references)
                require(report['result'] == 'PASS' and report['files'] > 3, 'The shipped privacy sweep has findings.')
                steps.append({'step': 'privacy', **report})
                with tempfile.TemporaryDirectory(prefix='wib-private-control-', dir=home_root) as temporary:
                    control = Path(temporary)
                    planted = control / 'planted.txt'
                    planted.write_text('Cedar Shop\n')
                    files = {'planted.txt': planted.read_bytes()}
                    archive = privacy.canonical_archive(files)
                    (control / 'control.tar').write_bytes(archive)
                    (control / 'bootstrap.py').write_bytes(b'# sample bootstrap\n')
                    copied = dict(manifest, files=[{'path': planted.relative_to(root).as_posix(),
                        'archive_path': 'planted.txt', 'sha256': digest(planted.read_bytes()), 'bytes': planted.stat().st_size}],
                        archive={'url': 'control.tar', 'sha256': digest(archive), 'bytes': len(archive)},
                        bootstrap={'path': (control / 'bootstrap.py').relative_to(root).as_posix(),
                            'sha256': digest((control / 'bootstrap.py').read_bytes()), 'bytes': (control / 'bootstrap.py').stat().st_size})
                    planted_manifest = control / 'manifest.json'
                    planted_manifest.write_text(json.dumps(copied))
                    argv = [here / 'privacy.py', root, '--manifest', planted_manifest,
                            '--people', root / 'vault/people', '--business', root / 'vault/cedar-shop']
                    result = call(argv, control)
                    require(result.returncode != 0 and 'private-brand' in result.stdout,
                            'The planted privacy control does not fail.')
                    copied['files'] = []
                    planted_manifest.write_text(json.dumps(copied))
                    require(call(argv, control).returncode != 0, 'The empty shipped list does not fail.')
            elif name == 'preserve':
                with tempfile.TemporaryDirectory(prefix='wib-preserve-', dir=home_root) as temporary:
                    home = Path(temporary)
                    argv = [release / 'fetch_install.py', '--manifest', manifest_path, *pinned, '--home', home]
                    require(call(argv, home).returncode == 0, 'The preservation control install fails.')
                    page = home / 'Workspaces/cedar-shop/CONCEPTS.md'
                    page.write_bytes(page.read_bytes() + b'\nLocal change.\n')
                    before = tree(home, True)
                    require(call(argv, home).returncode != 0 and tree(home, True) == before,
                            'A changed workspace is overwritten.')
                    # Restore only the planted change before testing a changed database.
                    page.write_bytes(page.read_bytes().removesuffix(b'\nLocal change.\n'))
                    db = home / '.local/share/foxrun/data.db'
                    current = _fox_person.connect(db)
                    try:
                        current.execute('CREATE TABLE local_change(value TEXT)')
                        current.commit()
                    finally:
                        current.close()
                    before = tree(home, True)
                    require(call(argv, home).returncode != 0 and tree(home, True) == before,
                            'A changed database is overwritten.')
            else:
                raise ValueError('Unknown check.')
            results.append({'case': name, 'result': 'PASS'})
            print('PASS ' + name, flush=True)
        except (OSError, ValueError, KeyError, sqlite3.Error) as error:
            results.append({'case': name, 'result': 'FAIL', 'reason': str(error)})
            print('FAIL ' + name + ': ' + str(error), flush=True)
    report = {'task': 'clean-install', 'version': manifest['version'],
              'manifest_sha256': digest(manifest_path.read_bytes()), 'archive_sha256': manifest['archive']['sha256'],
              'results': results, 'steps': steps, 'later': 'A real second machine remains OUT-OF-SCOPE.'}
    (home_root / 'wib-install-checks.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 1 if any(row['result'] == 'FAIL' for row in results) else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--case', choices=['release', 'zero', 'commands', 'conformance', 'repeat', 'privacy', 'preserve'])
    args = parser.parse_args()
    sys.path.insert(0, str(args.root / 'code/foxrun-modules/distribution'))
    raise SystemExit(run(args.root.resolve(), [args.case] if args.case else
                         ['release', 'zero', 'commands', 'conformance', 'repeat', 'privacy', 'preserve']))
