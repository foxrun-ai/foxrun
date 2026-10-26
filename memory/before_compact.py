#!/usr/bin/env python3
"""Check the latest workspace handoff; compaction always continues."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('FOXRUN_HOME', str(ROOT))


def main():
    try:
        from base import paths, person
        from base.tracker import local_path, tracker
        payload = sys.stdin.read() if not sys.stdin.isatty() else ''
        try:
            value = json.loads(payload) if payload.strip() else {}
        except ValueError:
            value = {}
        if not isinstance(value, dict):
            value = {}
        # Codex notifications can wrap the same fields in a data object.
        data = value.get('data', value)
        if not isinstance(data, dict):
            data = value
        portfolio = paths.portfolio()
        cwd = data.get('cwd')
        workspace = None
        if isinstance(cwd, str):
            try:
                relative = Path(cwd).resolve().relative_to(portfolio)
                if relative.parts:
                    workspace = relative.parts[0]
            except ValueError:
                pass
        workspace = workspace or person.workspace()
        folder = local_path(portfolio, workspace)
        handoffs = local_path(folder, 'history/handoffs')
        files = [p for p in handoffs.glob('*.md')
                 if p.is_file() and not p.is_symlink() and not p.name.endswith('.coverage.md')]
        if not files:
            print('No handoff yet in ' + str(handoffs) + '. Write one before the compact.')
            return 0
        handoff = max(files, key=lambda p: (p.stat().st_mtime_ns, p.name))
        script = local_path(paths.system_home(), 'memory/handoff_check.py')
        if not script.is_file():
            print('Memory handoff check is unavailable: ' + str(handoff))
            return 0
        command = [sys.executable, '-B', str(script), '--handoff', str(handoff),
                   '--db', str(tracker(workspace)), '--out', str(local_path(paths.system_home(), 'runs/handoff-check')),
                   '--tail-bytes', str(128 * 1024 * 1024)]
        transcript = data.get('transcript_path')
        if isinstance(transcript, str) and Path(transcript).is_file() and not Path(transcript).is_symlink():
            command += ['--transcript', transcript]
        else:
            command += ['--handoff-only']
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        for line in (result.stdout + result.stderr).splitlines():
            print(line)
    except Exception as error:
        print('Handoff check could not finish: ' + ' '.join(str(error).splitlines()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
