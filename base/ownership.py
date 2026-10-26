#!/usr/bin/env python3
"""Build ownership rows and check writes. Python 3.9 standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from base import simple_yaml, paths

def owners(home):
    result = {}
    names = {p.stem for folder in (home / 'agents', home / 'profile/agents') for p in folder.glob('*.md')}
    for name in sorted(names):
        path = paths.resolve_seat(name, home=home)
        if path is None:
            continue
        text = path.read_text()
        if not text.startswith('---\n'):
            continue
        front = text[4:].split('\n---\n', 1)[0]
        data = simple_yaml.safe_load(front)
        for part in data.get('owns', []):
            # Business responsibilities are not system paths.
            if not isinstance(part, str) or ' ' in part or part.startswith('/') or '..' in Path(part).parts:
                continue
            part = part.strip('/')
            agent = data.get('id', data.get('name'))
            if not agent:
                raise ValueError('identity has no id: ' + str(path))
            if part in result and result[part] != agent:
                raise ValueError('two owners: ' + part)
            result[part] = agent
    return result

def write_details(home, target, seat=None):
    # Keep the declared home: a home behind a link (macOS /var is /private/var) maps onto its real folder.
    declared = Path(os.path.abspath(os.path.expanduser(str(home))))
    home = declared.resolve()
    target = Path(os.path.abspath(os.path.expanduser(str(target))))
    # Resolve links and missing leaf components before choosing ownership.
    relative = paths.resolve_portfolio_path(target, declared).relative_to(home).as_posix()
    rows = owners(home)
    matches = [(part, owner) for part, owner in rows.items()
               if relative == part or relative.startswith(part + '/')]
    part, owner = max(matches, key=lambda row: len(row[0])) if matches else (None, None)
    seat = seat or os.environ.get('FOXRUN_SEAT') or 'worker'
    return dict(target=str(home / relative), area=part, owner=owner, writer=seat,
                reason='writer is not the owner' if owner else 'no owner for ' + relative)


# B-20261024-run-folder-writes-raise-ownership-alarms: a run folder is its worker's own space.
# The shapes match memory/runs.py DAY and RUN; runs/ itself and legacy/ stay guarded.
RUN_DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
RUN_FOLDER = re.compile(r'^(?:T\d+|B\d+|none)-[a-z][a-z0-9_]*(?:-[a-z0-9_]+)+$')

def run_folder_write(relative):
    parts = relative.split('/')
    return (len(parts) > 3 and parts[0] == 'runs' and bool(RUN_DAY.fullmatch(parts[1]))
            and bool(RUN_FOLDER.fullmatch(parts[2])))


def allowed(home, target, seat=None):
    detail = write_details(home, target, seat)
    owner, seat = detail['owner'], detail['writer']
    relative = Path(detail['target']).relative_to(home.resolve()).as_posix()
    if run_folder_write(relative):
        return True, 'ALLOW: ' + seat + ' -> ' + relative + '; inside a run folder'
    if owner is None:
        return False, 'ALARM: no owner for ' + relative
    return seat == owner, ('ALLOW: ' if seat == owner else 'ALARM: ') + seat + ' -> ' + relative + '; owner=' + owner


def write_check(home, target, workspace=None, database=None, writer=None, alarm=None):
    ok, message = allowed(home, target, writer)
    print(message)
    if ok:
        return 0
    if '; owner=' in message:
        # T863: name the owner's route so the work keeps moving instead of stopping here.
        owner = message.rsplit('; owner=', 1)[1]
        print('ROUTE: hand this write to ' + owner + ': start a background worker as the ' + owner +
              ' seat (orchestrate skill) with this change as its brief, then keep working.')
    from base import person
    workspace = workspace or person.workspace()
    command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'work/work.py'),
               '--workspace', workspace, '--receipt-root', str(paths.workspace(workspace))]
    if database is not None:
        command += ['--db', str(database)]
    command += ['ownership-check' if alarm else 'ownership-alarm']
    if alarm:
        command += [alarm]
    command += ['--write-path', str(target), '--by', writer or os.environ.get('FOXRUN_SEAT') or 'worker']
    environment = dict(os.environ, FOXRUN_HOME=str(home.resolve()))
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode:
        print('ALARM: tracker check failed; write remains blocked', file=sys.stderr)
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return 2
    return 0 if alarm else 2

def fingerprints(home):
    result = {}
    protected = {'.git', '.env', '.ssh', '.netrc', 'auth.json', 'credentials',
                 'credentials.json', 'secrets', 'tokens', 'token.json', 'tokens.json',
                 'id_rsa', '.git-credentials', '.aws', '.credentials', '.credentials.json', '.secrets'}
    def excluded(path):
        return any(p.lower() in protected or p.lower().startswith('.env.') for p in path.relative_to(home).parts)
    # Ownership is used to classify changes, never to limit the scan boundary.
    for current, dirs, files in os.walk(home, followlinks=False):
        kept = []
        for name in dirs:
            path = Path(current)/name
            if excluded(path):
                continue
            if path.is_symlink():
                result[path.relative_to(home).as_posix()] = 'link:' + os.readlink(path)
            else:
                kept.append(name)
        dirs[:] = kept
        for name in dirs:
            path = Path(current)/name
            result[path.relative_to(home).as_posix() + '/'] = 'directory'
        for name in files:
            path = Path(current)/name
            if excluded(path):
                continue
            if path.is_symlink():
                result[path.relative_to(home).as_posix()] = 'link:' + os.readlink(path)
                continue
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024*1024), b''): digest.update(chunk)
            result[path.relative_to(home).as_posix()] = digest.hexdigest()
    return result

def section(home):
    def display(part):
        # A file with no suffix (VERSION, .gitignore) is still a file.
        return part if Path(part).suffix or (home / part).is_file() else part + '/'
    return '## Who Owns What\n\nGenerated from `owns:` in `agents/*.md`.\n\n| Part | Owner |\n|---|---|\n' + ''.join('| `' + display(part) + '` | ' + owner + ' |\n' for part, owner in sorted(owners(home).items()))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('FOXRUN_HOME', str(Path.home()/'.foxrun'))))
    sub = parser.add_subparsers(dest='command', required=True)
    write = sub.add_parser('write-check'); write.add_argument('path')
    write.add_argument('--workspace'); write.add_argument('--db', type=Path)
    write.add_argument('--by', help='writer name; defaults to FOXRUN_SEAT or worker')
    write.add_argument('--alarm', help='use this cleared alarm for this writer and exact path')
    sub.add_parser('rows'); sub.add_parser('section')
    snap = sub.add_parser('snapshot'); snap.add_argument('--out', type=Path, required=True)
    audit = sub.add_parser('audit'); audit.add_argument('--baseline', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'write-check':
        os.environ['FOXRUN_HOME'] = str(args.home.expanduser().resolve())
        return write_check(args.home, args.path, args.workspace, args.db, args.by, args.alarm)
    if args.command == 'rows': print(json.dumps(owners(args.home), indent=2))
    elif args.command == 'section': print(section(args.home))
    elif args.command == 'snapshot':
        args.out.write_text(json.dumps(fingerprints(args.home), indent=2) + '\n')
        print('Ownership baseline saved.')
    elif args.command == 'audit':
        before = json.loads(args.baseline.read_text()); after = fingerprints(args.home)
        changed = sorted(p for p in set(before)|set(after) if before.get(p) != after.get(p))
        rows = owners(args.home)
        for path in changed:
            matches = [(p,o) for p,o in rows.items() if path.rstrip('/') == p or path.startswith(p + '/')]
            owner = max(matches,key=lambda r:len(r[0]))[1] if matches else 'UNOWNED'
            print('ALARM: direct write or removal: ' + path + '; owner=' + owner)
        print(str(len(changed)) + ' changes since baseline; check the owner and write receipt.')
        return 2 if changed else 0
    return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except (OSError, ValueError) as error:
        print('ALARM: ' + str(error)); sys.exit(2)
