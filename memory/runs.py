#!/usr/bin/env python3
"""Runs: every run lives in one home, in one shape, and this file checks both.

  runs.py new --task T123 --seat keeper --what short-name [--reason "why heavy/ may pass 1 GB"]
  runs.py where <old path>
  runs.py check [--json]
  runs.py size [--json]

The home is ~/.foxrun/runs/. Its shape:

  <YYYY-MM-DD>/sessions.jsonl             one line for each session start
  <YYYY-MM-DD>/<task>-<seat>-<what>/      one run: brief.md, result.md, heavy/
  <YYYY-MM-DD>/legacy/<source>/<name>     a dated run moved in from an older home, kept as it was
  nightly/                                the nightly receipts, lint reports, watchdog alerts, dream folders
  legacy/<source>/<name>                  an undated run moved in from an older home
  moves.tsv                               the move map: old path, new path

A few undated items at the top are the current output of one command. FIXED names them.
brief.md and result.md are never cleared. heavy/ stays until its findings are copied into rows or pages.
Standard library only.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
from base import paths  # noqa: E402

MB = 1024 * 1024
GB = 1024 * MB
RUN_WARN_BYTES = 200 * MB        # the check warns when one run passes this
HEAVY_LIMIT_BYTES = 1 * GB       # heavy/ may pass this only when brief.md names a reason
TOTAL_WARN_BYTES = 10 * GB       # doctor warns when all runs pass this
FREE_WARN_BYTES = 20 * GB        # doctor warns when the disk has less free space than this
RULE_START = '2026-10-23'        # runs from this day on must have the shape; older ones wait for the move
REASON = re.compile(r'^\s*Heavy reason:\s*\S', re.M)

DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
RUN = re.compile(r'^(?:T\d+|B\d+|none)-[a-z][a-z0-9_]*(?:-[a-z0-9_]+)+$')
NIGHTLY = re.compile(r'^(?:\d{8}T\d{6,12}Z-(?:nightly|lint|nightly-watchdog)|\d{4}-\d{2}-\d{2}-dream(?:-\d+)?)$')
DATED = re.compile(r'^(\d{4})-?(\d{2})-?(\d{2})(?![0-9])')
FIXED = {'README.md': 'file', 'state-markers.json': 'file', 'nightly-watchdog-state.json': 'file',
         'kept-link-review.json': 'file', 'moves.tsv': 'file', 'handoff-check': 'dir', 'lead-beats': 'dir',
         'tidy': 'dir', 'standing': 'dir', 'generated': 'dir', 'nightly': 'dir', 'legacy': 'dir'}
RUN_PARTS = {'brief.md', 'result.md', 'heavy'}
SEEN = {'.DS_Store', '.gitkeep'}


def home(system=None) -> Path:
    return Path(system) / 'runs' if system else paths.runs()


def day(moment=None) -> str:
    return (moment or datetime.now().astimezone()).strftime('%Y-%m-%d')


def nightly(system=None) -> Path:
    return home(system) / 'nightly'


def nightly_folders(system=None, pattern='*-nightly'):
    """Folders of one nightly kind: nightly/<name>, then any left at the top of runs/ from before the move."""
    root = home(system)
    found = []
    for parent in (root / 'nightly', root):
        if parent.is_dir() and not parent.is_symlink():
            found += [p for p in parent.glob(pattern) if p.is_dir() and not p.is_symlink()]
    return found


def run_name(task, seat, what) -> str:
    name = '-'.join(str(part).strip() for part in (task, seat, what))
    if not RUN.match(name):
        raise ValueError('a run is <task>-<seat>-<what>: a task id (T123, B12, or none), a seat id, '
                         'and a short lower-case name: ' + name)
    return name


BRIEF = """# {name}

Task: {task}
Seat: {seat}
Started: {at}
{reason}
## Run rules

- Write only in this folder: {folder}
- brief.md says what the run is for. result.md says what it found and where the proof is.
- Everything else goes in heavy/: logs, copies, data, practice repositories.
- Budget: the run check warns above 200 MB. heavy/ may pass 1 GB only when this brief has a line `Heavy reason: <why>`.
- Never clear brief.md or result.md. Keep heavy/ until its findings are copied into rows or pages.
"""


def new_run(task, seat, what, system=None, moment=None, reason=None) -> Path:
    """Make <date>/<task>-<seat>-<what>/ with brief.md and heavy/. The name gets -2, -3 when it is taken."""
    moment = moment or datetime.now().astimezone()
    name = run_name(task, seat, what)
    parent = home(system) / day(moment)
    parent.mkdir(parents=True, exist_ok=True)
    folder, number = parent / name, 1
    while True:
        try:
            folder.mkdir()
            break
        except FileExistsError:
            number += 1
            folder = parent / (name + '-' + str(number))
    (folder / 'heavy').mkdir()
    (folder / 'brief.md').write_text(BRIEF.format(
        name=folder.name, task=task, seat=seat, at=moment.replace(microsecond=0).isoformat(), folder=folder,
        reason=('Heavy reason: ' + reason.strip() + '\n') if reason and reason.strip() else ''), encoding='utf-8')
    return folder


def record_session(record: dict, system=None, moment=None) -> Path:
    """Append one line for a session start to <date>/sessions.jsonl. One write of one line."""
    moment = moment or datetime.now().astimezone()
    target = home(system) / day(moment) / 'sessions.jsonl'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError('sessions.jsonl must not be a link: ' + str(target))
    line = json.dumps(dict({'at': moment.replace(microsecond=0).isoformat()}, **record), sort_keys=True) + '\n'
    descriptor = os.open(str(target), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(descriptor, line.encode('utf-8'))
    finally:
        os.close(descriptor)
    return target


def sessions(system=None):
    """Every session start line, oldest day first. A line that is not a JSON object is skipped."""
    root = home(system)
    rows = []
    if not root.is_dir():
        return rows
    for folder in sorted(p for p in root.iterdir() if DAY.match(p.name) and p.is_dir() and not p.is_symlink()):
        file = folder / 'sessions.jsonl'
        if not file.is_file() or file.is_symlink():
            continue
        for line in file.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def moves(system=None):
    """The move map rows as (old, new). None when no move ran."""
    file = home(system) / 'moves.tsv'
    if not file.is_file():
        return []
    rows = []
    for line in file.read_text(encoding='utf-8').splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def where(old, system=None):
    """The new path of an old run path from the move map; None when the map does not name it."""
    text = os.path.abspath(os.path.expanduser(str(old)))
    for source, target in sorted(moves(system), key=lambda row: len(row[0]), reverse=True):
        if text == source or text.startswith(source + '/'):
            return target + text[len(source):]
    return None


def tree_bytes(path: Path) -> int:
    """Bytes of every file under path. Links are not followed; a link counts as itself."""
    total = 0
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size
    except OSError:
        return 0
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(current, d))]:
            try:
                total += os.lstat(os.path.join(current, name)).st_size
            except OSError:
                continue
    return total


def legacy(path: Path) -> bool:
    """An entry from before the rule: its name has an older date, or it has no date and is older than the rule."""
    found = DATED.match(path.name)
    if found:
        return '-'.join(found.groups()) < RULE_START
    try:
        return datetime.fromtimestamp(path.lstat().st_mtime).strftime('%Y-%m-%d') < RULE_START
    except OSError:
        return True


def points_into(link: Path, real_root: Path) -> bool:
    """Does this link's own first hop land inside the runs home? A move pointer does; its target may link on."""
    try:
        first = os.path.normpath(os.path.join(os.path.realpath(link.parent), os.readlink(link)))
        parent = Path(os.path.realpath(os.path.dirname(first)))
    except OSError:
        return False
    return parent == real_root or real_root in parent.parents


def finding(level, path, what, how):
    return {'level': level, 'path': str(path), 'what': what, 'how_to_fix': how}


def check_run(folder: Path, today: str, findings: list):
    parts = {p.name for p in folder.iterdir()} - SEEN
    if 'brief.md' not in parts:
        findings.append(finding('error', folder, 'Run has no brief.md.',
                                'Make runs with: python3 ~/.foxrun/memory/runs.py new --task <id> --seat <seat> --what <name>.'))
    if 'result.md' not in parts and folder.parent.name < today:
        findings.append(finding('warning', folder, 'Run has no result.md.',
                                'Write result.md: what the run found and where the proof is.'))
    extra = sorted(parts - RUN_PARTS)
    if extra:
        findings.append(finding('error', folder, 'Run is off-shape: ' + ', '.join(extra[:5]) +
                                (' and ' + str(len(extra) - 5) + ' more' if len(extra) > 5 else '') + ' at its top.',
                                'Keep only brief.md, result.md, and heavy/ at the top. Move the rest into heavy/.'))
    size = tree_bytes(folder)
    if size > RUN_WARN_BYTES:
        findings.append(finding('warning', folder, 'Run is %d MB, above the 200 MB budget.' % (size // MB),
                                'Keep only what mining needs; whole-repository practice copies count.'))
    heavy = folder / 'heavy'
    if heavy.is_dir() and not heavy.is_symlink() and tree_bytes(heavy) > HEAVY_LIMIT_BYTES:
        brief = folder / 'brief.md'
        text = brief.read_text(encoding='utf-8', errors='replace') if brief.is_file() else ''
        if not REASON.search(text):
            findings.append(finding('error', heavy, 'heavy/ is above 1 GB and brief.md names no reason.',
                                    'Add a line `Heavy reason: <why>` to brief.md, or keep heavy/ under 1 GB.'))


def check(system=None, portfolio=None, today=None):
    """Findings for runs written elsewhere or off-shape. Older runs that wait for the move are one warning per place."""
    system = Path(system) if system else paths.system_home()
    portfolio = Path(portfolio) if portfolio else paths.portfolio()
    today = today or day()
    root = home(system)
    findings = []
    if not root.is_dir() or root.is_symlink():
        return [finding('error', root, 'The runs home is absent or a link.', 'Make ~/.foxrun/runs/ a real folder.')]
    real_root = root.resolve()
    old_tops = {Path(old).name for old, _ in moves(system) if Path(os.path.realpath(Path(old).parent)) == real_root}
    waiting = 0
    for entry in sorted(root.iterdir()):
        name = entry.name
        if name.startswith('.') or name in SEEN:
            continue
        if entry.is_symlink():
            if name in old_tops:
                continue
            findings.append(finding('error', entry, 'Link at the top of runs/ that the move map does not name.',
                                    'Write the run in its dated folder; a link here is only a move pointer.'))
            continue
        if name in FIXED:
            kind = 'dir' if entry.is_dir() else 'file'
            if kind != FIXED[name]:
                findings.append(finding('error', entry, 'Fixed item has the wrong kind.', 'Restore it as a ' + FIXED[name] + '.'))
            continue
        if DAY.match(name) and entry.is_dir():
            for child in sorted(entry.iterdir()):
                if child.name.startswith('.') or child.name in SEEN or child.name in ('sessions.jsonl', 'legacy'):
                    continue
                if child.is_symlink() or not child.is_dir() or not RUN.match(child.name):
                    findings.append(finding('error', child, 'Entry in a day folder is not a run: <task>-<seat>-<what>/.',
                                            'Make runs with: python3 ~/.foxrun/memory/runs.py new --task <id> --seat <seat> --what <name>.'))
                    continue
                check_run(child, today, findings)
            continue
        if legacy(entry):
            waiting += 1
            continue
        findings.append(finding('error', entry, 'Run written off-shape at the top of runs/.',
                                'Write runs in runs/<date>/<task>-<seat>-<what>/ (runs.py new).'))
    if waiting:
        findings.append(finding('warning', root, '%d older entries at the top of runs/ wait for the move into legacy/.' % waiting,
                                'Move each into legacy/<source>/, and add its old and new path to moves.tsv.'))
    nightly_root = root / 'nightly'
    if nightly_root.is_dir():
        for entry in sorted(nightly_root.iterdir()):
            if not entry.name.startswith('.') and entry.name not in SEEN and not NIGHTLY.match(entry.name):
                findings.append(finding('error', entry, 'Entry in nightly/ is not a nightly receipt.',
                                        'Only the nightly, its lint, the watchdog, and dream write in nightly/.'))
    # Elsewhere: each workspace history/runs and the old service-state runs.
    places, seen = [], set()
    if portfolio.is_dir():
        for folder in sorted(portfolio.iterdir()):
            place = folder / 'history/runs'
            if folder.is_symlink() or not place.is_dir():
                continue
            real = place.resolve()
            if real not in seen:
                seen.add(real)
                places.append(place)
    service = paths.state() / 'runs'
    if service.is_dir() and service.resolve() not in seen:
        places.append(service)
    for place in places:
        older = 0
        for entry in sorted(place.iterdir()):
            if entry.name in SEEN or entry.name.startswith('.'):
                continue
            if entry.is_symlink() and points_into(entry, real_root):
                continue
            if legacy(entry):
                older += 1
                continue
            findings.append(finding('error', entry, 'Run written outside ~/.foxrun/runs/.',
                                    'Write runs only in ~/.foxrun/runs/<date>/<task>-<seat>-<what>/ (runs.py new).'))
        if older:
            findings.append(finding('warning', place, '%d older runs here wait for a move into ~/.foxrun/runs/.' % older,
                                    'Move each into ~/.foxrun/runs/legacy/<source>/, and add its old and new path to moves.tsv.'))
    return findings


def disk(system=None):
    """Sizes for doctor: total bytes of runs/, the runs above 200 MB, and free bytes on the disk."""
    root = home(system)
    total, big = 0, []
    if root.is_dir():
        for entry in root.iterdir():
            if entry.is_symlink():
                continue
            if DAY.match(entry.name) and entry.is_dir():
                for child in entry.iterdir():
                    size = tree_bytes(child)
                    total += size
                    if child.is_dir() and child.name != 'legacy' and size > RUN_WARN_BYTES:
                        big.append((size, str(child)))
                    if child.name == 'legacy' and child.is_dir():
                        for source in child.iterdir():
                            for item in (source.iterdir() if source.is_dir() and not source.is_symlink() else []):
                                size = tree_bytes(item)
                                if size > RUN_WARN_BYTES:
                                    big.append((size, str(item)))
            else:
                total += tree_bytes(entry)
    free = shutil.disk_usage(root if root.is_dir() else root.parent).free
    return {'total_bytes': total, 'free_bytes': free, 'big': sorted(big, reverse=True)}


def warnings(system=None):
    """Doctor lines: WARN when all runs pass 10 GB, a run passes 200 MB, or the disk has under 20 GB free."""
    sizes = disk(system)
    lines = []
    if sizes['total_bytes'] > TOTAL_WARN_BYTES:
        lines.append('runs total %.1f GB, above the %d GB limit' % (sizes['total_bytes'] / GB, TOTAL_WARN_BYTES // GB))
    if sizes['big']:
        size, path = sizes['big'][0]
        lines.append('%d runs above 200 MB; largest %d MB: %s' % (len(sizes['big']), size // MB, path))
    if sizes['free_bytes'] < FREE_WARN_BYTES:
        lines.append('free disk %.1f GB, below %d GB' % (sizes['free_bytes'] / GB, FREE_WARN_BYTES // GB))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('new', help='make a run folder in the shape')
    make.add_argument('--task', required=True)
    make.add_argument('--seat', required=True)
    make.add_argument('--what', required=True)
    make.add_argument('--reason', help='why heavy/ may pass 1 GB; written into brief.md')
    look = commands.add_parser('where', help='the new path of an old run path')
    look.add_argument('path')
    for name in ('check', 'size'):
        commands.add_parser(name).add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'new':
            print(new_run(args.task, args.seat, args.what, reason=args.reason))
            return 0
        if args.command == 'where':
            found = where(args.path)
            if found is None:
                print('not in the move map: ' + args.path)
                return 1
            print(found)
            return 0
        if args.command == 'check':
            rows = check()
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for row in rows:
                    print(row['level'].upper() + ' ' + row['path'] + ': ' + row['what'])
                print('Run check: %d errors, %d warnings' % (sum(r['level'] == 'error' for r in rows),
                                                             sum(r['level'] == 'warning' for r in rows)))
            return int(any(r['level'] == 'error' for r in rows))
        sizes = disk()
        if args.json:
            print(json.dumps(sizes, indent=2))
        else:
            print('runs %.2f GB; free %.1f GB; %d runs above 200 MB' % (
                sizes['total_bytes'] / GB, sizes['free_bytes'] / GB, len(sizes['big'])))
        return 0
    except (OSError, ValueError) as error:
        print('FAIL runs: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
