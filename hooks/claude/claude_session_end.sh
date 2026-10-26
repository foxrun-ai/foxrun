#!/usr/bin/env python3
"""Run the session hook and keep its optional failure from blocking the runtime."""
from pathlib import Path
import subprocess
import sys
try:
    subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / 'events/session_run.py'), 'hook-end', '--runtime', 'claude'], check=False)
except Exception:  # the logger never fails or blocks the session
    pass
raise SystemExit(0)
