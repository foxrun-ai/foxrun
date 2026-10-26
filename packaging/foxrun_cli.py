"""The foxrun command from a uv install (T873).

The wheel holds the product tree in foxrun/product/. `foxrun install` runs that
tree's install.py with the same arguments, so it behaves like
`python3 install.py ...` from a source checkout. `foxrun hookup` runs that
tree's foxrun.py hookup, so it behaves like `python3 ~/.foxrun/foxrun.py hookup`.
Standard library only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PRODUCT = Path(__file__).resolve().parent / 'product'
USAGE = '''usage: foxrun install [install.py arguments]
       foxrun update [--home PATH]
       foxrun hookup --runtime claude|codex|both [--home PATH] [--runtime-home PATH] [--json]
       foxrun --version

Commands:
  update    Refresh an existing home from this package; keeps personal state.
  hookup    Connect the session hooks to an existing home; backs up the
            settings first. A second run writes nothing.
  install   Install Foxrun into two empty folders. Takes the same arguments as
            install.py: --home, --portfolio, --person, --workspace, --runtime,
            --runtime-home, --hookup, --yes, --list-addons, --no-schedule.
            Run `foxrun install --help` for the list.

After install, run python3 "$HOME/.foxrun/foxrun.py" doctor.'''


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(USAGE)
        return 0 if argv else 2
    if argv[0] == '--version':
        print('foxrun ' + (PRODUCT / 'VERSION').read_text(encoding='utf-8').strip())
        return 0
    if argv[0] == 'update':
        return subprocess.run([sys.executable, '-I', '-B', str(PRODUCT / 'update.py'), *argv[1:]]).returncode
    if argv[0] == 'hookup':
        # Not isolated: hookup reads FOXRUN_HOME, CLAUDE_CONFIG_DIR, and CODEX_HOME, as foxrun.py does.
        return subprocess.run([sys.executable, '-B', str(PRODUCT / 'foxrun.py'), 'hookup', *argv[1:]]).returncode
    if argv[0] != 'install':
        print('foxrun: unknown command ' + repr(argv[0]) + '\n\n' + USAGE, file=sys.stderr)
        return 2
    # A child process keeps install.py's own folder first on sys.path, as from a checkout.
    return subprocess.run([sys.executable, '-B', str(PRODUCT / 'install.py'), *argv[1:]]).returncode


if __name__ == '__main__':
    raise SystemExit(main())
