#!/usr/bin/env python3
"""Build the exact, versioned Workspace Install archive. Never publish it."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from public_sources import source as public_source, rows as public_rows
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import pack_policy

VERSION = '13-night.1'
HERE = (Path(__file__).resolve().parent)
MODULES = ['base', 'work', 'people', 'design', 'memory', 'commerce']

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()

def save(path, raw):
    if not path.exists() or path.read_bytes() != raw:
        path.write_bytes(raw)

def load_sample(path):
    spec = importlib.util.spec_from_file_location('release_sample', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def build(root, output):
    repo = root / 'code/foxrun-modules'
    source = repo / 'base/distribution'
    files = {}
    origins = {}
    changing = []
    def add(origin, destination, changes=False):
        path = root / origin
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked source: ' + origin)
        files[destination] = public_source(destination, path.read_bytes())
        origins[destination] = origin
        if changes:
            changing.append({'path': origin, 'ship_path': destination, 'state': 'changing tonight'})
    for name in ['sample_workspace.py', 'sample/rows.json', 'install.py', 'lookup.py', 'privacy.py', 'skills/lookup/SKILL.md']:
        add('code/foxrun-modules/base/distribution/' + name, 'base/distribution/' + name)
    add('code/foxrun-modules/base/check_workspace.py', 'base/check_workspace.py')
    for name in ['core.py', 'views.py', 'paths.py', 'person.py', 'dictionary_v11.py', 'pack_policy.py']:
        add('code/foxrun-modules/base/' + name, 'base/' + name, True)
    for path in sorted([*repo.glob('*/install.json'), *repo.glob('modules/*/install.json')]):
        add(path.relative_to(root).as_posix(), path.relative_to(repo).as_posix())
    commands = sorted((repo / 'base/commands').iterdir())
    for path in commands:
        if path.is_file() and not path.name.startswith('.'):
            add(path.relative_to(root).as_posix(), 'base/commands/' + path.name, True)
    add('code/foxrun-modules/events/history_actions.py', 'events/history_actions.py')
    add('code/foxrun-modules/events/history_action_map.csv', 'events/history_action_map.csv')
    add('code/agent-team/tools/render_capabilities.py', 'agent-team/tools/render_capabilities.py', True)
    add('code/agent-team/tools/paths.py', 'agent-team/tools/paths.py', True)
    template_root = root / 'vault/foxrun/docs/contract-templates'
    for path in sorted(template_root.glob('*.md')):
        if path.name != 'README.md':
            add(path.relative_to(root).as_posix(), 'base/contract-templates/' + path.name, True)
    sample = load_sample(source / 'sample_workspace.py')
    targets, columns = sample.portable_blueprint(repo / 'base/blueprint', template=True)
    for name, rows in [('target-v13.jsonl', public_rows(targets)), ('columns-v13.jsonl', public_rows(columns))]:
        destination = 'base/blueprint/' + name
        files[destination] = b''.join((json.dumps(row, sort_keys=True) + '\n').encode() for row in rows)
        origins[destination] = 'code/foxrun-modules/base/blueprint/' + name
        changing.append({'path': origins[destination], 'ship_path': destination, 'state': 'changing tonight'})
    files['README.md'] = (source / 'release-README.md').read_bytes()
    origins['README.md'] = 'code/foxrun-modules/base/distribution/release-README.md'
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, raw in sorted(files.items()):
        target = output / 'files' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != raw:
            target.write_bytes(raw)
        entries.append({'path': target.relative_to(root).as_posix(), 'archive_path': name,
                        'source_path': origins[name], 'sha256': sha(raw), 'bytes': len(raw),
                        'state': 'changing tonight' if any(c['ship_path'] == name for c in changing) else 'fixed for review'})
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, raw in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mtime = 0
            info.mode = 0o755 if name.startswith('base/commands/') else 0o644
            archive.addfile(info, io.BytesIO(raw))
    raw_archive = archive_bytes.getvalue()
    archive_name = 'foxrun-workspace-' + VERSION + '.tar'
    archive_path = output / archive_name
    if not archive_path.exists() or archive_path.read_bytes() != raw_archive:
        archive_path.write_bytes(raw_archive)
    manifest = {
        'format': 'foxrun-workspace-release/v1', 'version': VERSION, 'blueprint_version': '13',
        'state': 'in review, ready for your yes', 'publication': 'local archive; no publish or push',
        'archive': {'url': archive_name, 'sha256': sha(raw_archive), 'bytes': len(raw_archive)},
        'modules': [{'name': name, 'version': '12'} for name in pack_policy.shipped_names(repo, MODULES)],
        'skills': [{'name': 'lookup', 'version': VERSION, 'path': 'base/distribution/skills/lookup/SKILL.md'}],
        'files': entries, 'changing_tonight': changing,
        'dependencies': {'install': 'Python 3.9+ and SQLite 3.37+, standard library only',
                         'agent_team_generator': 'PyYAML is required only when this optional generator runs'},
        'excluded': ['Private examples, personal agent identities, business fixtures, generated business pages, runtime settings, secrets, archived files, and undeclared files never ship.'],
        'install_command': 'python3 fetch_install.py --manifest manifest.json --manifest-sha256 <hash from the release owner> --home /path/to/clean-home',
        'later_checks': ['Clean-home installation, twice', 'Real second machine', 'Public release URL after approval'],
        'public_copy': 'Private source bindings are replaced in the shipped copy. Model object type, table, field, collection, module, link, and status names stay exact. Private workspace picks do not ship.',
    }
    # The bootstrap is beside the manifest. It is also part of the privacy file list.
    bootstrap = (source / 'fetch_install.py').read_bytes()
    save(output / 'fetch_install.py', bootstrap)
    manifest['bootstrap'] = {'path': (output / 'fetch_install.py').relative_to(root).as_posix(),
                             'sha256': sha(bootstrap), 'bytes': len(bootstrap)}
    save(output / 'manifest.json', encoded(manifest))
    return manifest

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    output = args.output or args.root / 'code/foxrun-modules/base/distribution/release'
    manifest = build(args.root.resolve(), output.resolve())
    print('PASS release: ' + str(len(manifest['files'])) + ' files; version ' + VERSION)

if __name__ == '__main__':
    main()
