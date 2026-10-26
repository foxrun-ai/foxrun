#!/usr/bin/env python3
"""Run the link and handoff checks. Explicit inputs win; with none, the nightly finds its own."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
sys.path.insert(0, str(ROOT))
from base import paths
from foxrun import installed_path, local_path, workspace_name


def newest_handoff(folder):
    """Newest handoff file (NNNN-NN-NN-NNN-*.md) whose session: line names a transcript on disk."""
    if not folder.is_dir():
        return None
    from memory.handoff_check import HANDOFF_NAME, transcript
    for path in sorted((p for p in folder.glob('*.md')
                          if HANDOFF_NAME.fullmatch(p.name) and not p.name.endswith('.coverage.md')), reverse=True):
        match = re.search(r"(?m)^session:\s*['\"]?([0-9a-f-]{13,})", path.read_text(encoding='utf-8')[:4096])
        if not match:
            continue
        try:
            transcript(match.group(1))
        except ValueError:
            continue
        return path
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=('run', 'beat'), default='run',
                        help='run the existing memory command')
    parser.add_argument('--workspace')
    parser.add_argument('--health-only', action='store_true')
    parser.add_argument('--readonly', action='store_true')
    parser.add_argument('--seat')
    parser.add_argument('--handoff-only', action='store_true')
    parser.add_argument('--transcript', default=os.environ.get('FOXRUN_TRANSCRIPT'))
    parser.add_argument('--handoff', default=os.environ.get('FOXRUN_HANDOFF'))
    args = parser.parse_args(argv)
    failures = 0
    try:
        from memory.health import check_health, beat
        if args.command == 'beat':
            beat(args.seat)
            return 0
        failures += check_health(write=not args.readonly)
        if args.health_only:
            return int(bool(failures))
        if not args.handoff_only:
            folder = local_path(paths.portfolio(), workspace_name(args.workspace))
            manifest = local_path(folder, 'history/outputs/workspace-pages/wiki.json')
            wiki = local_path(folder, 'wiki')
            script = ROOT / 'memory/link_check.py'
            if not script.is_file():
                print('not built yet: memory link check', flush=True)
            elif not manifest.is_file() and not (wiki.is_dir() and any(wiki.rglob('*.md'))):
                print('SKIP links: no wiki pages in ' + folder.name, flush=True)
            else:
                # No compiled manifest: link_check reads the wiki pages that exist.
                failures += bool(subprocess.run([sys.executable, str(script), '--workspace', str(folder), '--no-oracle']).returncode)
        script = ROOT / 'memory/handoff_check.py'
        if not script.is_file():
            print('not built yet: memory handoff check', flush=True)
        else:
            command = [sys.executable, str(script), '--db', str(local_path(paths.system_home(), 'data.db')),
                       '--out', str(local_path(paths.system_home(), 'runs/handoff-check'))]
            if args.transcript and args.handoff:
                transcript = installed_path(args.transcript)
                handoff = installed_path(args.handoff)
                if not transcript.is_file() or not handoff.is_file():
                    raise ValueError('transcript and handoff must be existing files inside the install')
                command += ['--transcript', str(transcript)]
                skip = None
            elif args.transcript or args.handoff:
                skip = 'supply --transcript and --handoff together'
            else:
                # Nightly: the newest handoff whose session transcript is still on disk.
                handoffs = local_path(local_path(paths.portfolio(), workspace_name(args.workspace)), 'history/handoffs')
                handoff = newest_handoff(handoffs)
                skip = None if handoff else 'no handoff with a session transcript in ' + str(handoffs)
            if skip:
                print('SKIP handoff: ' + skip, flush=True)
            else:
                print('handoff check: ' + str(handoff), flush=True)
                failures += bool(subprocess.run(command + ['--handoff', str(handoff)]).returncode)
        print('Memory checks: {} failed'.format(failures))
        return int(bool(failures))
    except (OSError, ValueError) as error:
        print('FAIL memory checks: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
