#!/usr/bin/env python3
"""Restore seat context and replay input to the existing session receipt hook."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
data = sys.stdin.read()
environment = dict(os.environ, FOXRUN_HOME=str(root), PYTHONDONTWRITEBYTECODE='1')
result = subprocess.run([sys.executable, str(root / 'foxrun.py'), 'start',
                         '--runtime', 'codex', '--hook-json'],
                        input=data, text=True, env=environment)
try:
    subprocess.run([sys.executable, str(root / 'events/session_run.py'), 'hook-start',
                    '--runtime', 'codex'], input=data, text=True, env=environment,
                   stdout=subprocess.DEVNULL, check=False)
except Exception:  # the logger never fails or blocks the session
    pass
raise SystemExit(result.returncode)
