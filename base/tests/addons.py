"""The core blueprint plus the installed add-on blueprints, for tests of add-on tables.

The core blueprint holds only the core model (g-business-packs-do-not-ship, g-people-ships-with-small-talk).
A test of People, commerce, Amazon, or UGC tables needs those add-ons' own blueprint rows.
It finds them in FOXRUN_TEST_ADDONS (folders, split by ':'), or else in the installed home ~/.foxrun.
With no add-on found, the folder holds the core rows only.
"""
import atexit
import json
import os
from pathlib import Path
import shutil
import tempfile

try:
    from core import BLUEPRINT as VERSION, installed_addons
except ImportError:  # a test that imports base.core, not core
    from base.core import BLUEPRINT as VERSION, installed_addons

CORE = Path(__file__).resolve().parent.parent / 'blueprint'


def folders():
    listed = [Path(p) for p in os.environ.get('FOXRUN_TEST_ADDONS', '').split(':') if p]
    return listed or installed_addons(Path.home() / '.foxrun')


def merged(core=CORE):
    """One temporary blueprint folder: the core rows, then each add-on's rows and rules."""
    temp = tempfile.TemporaryDirectory(prefix='addon-blueprint-')
    atexit.register(temp.cleanup)
    # A blueprint folder sits beside core.py, as in base/; some tools load core.py from there.
    out = Path(temp.name) / 'blueprint'
    out.mkdir()
    (out.parent / 'core.py').symlink_to(Path(core).resolve().parent / 'core.py')
    # The table commands sit beside it too: the core's, then each add-on's own.
    commands = out.parent / 'commands'
    commands.mkdir()
    for folder in [Path(core).resolve()] + [Path(f) for f in folders()]:
        for command in sorted((folder.parent / 'commands').glob('*')):
            if command.is_file() and not (commands / command.name).exists():
                (commands / command.name).symlink_to(command.resolve())
    for item in Path(core).iterdir():
        if item.is_file():
            shutil.copy2(item, out / item.name)
    rules = json.loads((out / 'implementation-rules.json').read_text())
    for folder in folders():
        for kind in ('target', 'columns'):
            name = kind + '-v' + VERSION + '.jsonl'
            extra = [line for line in (folder / name).read_text().splitlines() if line.strip()]
            body = (out / name).read_text().rstrip('\n')
            (out / name).write_text(body + '\n' + '\n'.join(extra) + '\n')
        if (folder / 'implementation-rules.json').is_file():
            for key, rows in json.loads((folder / 'implementation-rules.json').read_text()).items():
                if isinstance(rows, list):
                    rules[key] = rules.get(key, []) + rows
    (out / 'implementation-rules.json').write_text(json.dumps(rules, indent=1, sort_keys=True) + '\n')
    return out


BLUEPRINT = merged()
