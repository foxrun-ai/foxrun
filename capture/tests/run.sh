#!/usr/bin/env python3
"""Run capture fixtures with the same interpreter as this entry point."""
import os
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parent
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
subprocess.run([sys.executable, str(root / 'test_files.py')], env=env, check=True)
raise SystemExit(subprocess.run([sys.executable, str(root / 'test_capture.py'), *sys.argv[1:]], env=env).returncode)
