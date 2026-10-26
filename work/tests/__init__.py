"""Fixtures shared by the tracker regression tests."""
from pathlib import Path
import json
import shutil


def native_hooks(root: Path) -> Path:
    """Copy the real hooks and logger; stub the unrelated context startup."""
    from base import person

    source = Path(__file__).resolve().parents[2]
    home = root / 'hook-system'
    files = ('base/paths.py', 'base/person.py', 'work/work.py',
             'events/session_run.py', 'events/history_actions.py', 'events/history_action_map.csv')
    files += tuple(f'hooks/{runtime}/{runtime}_session_{event}.sh'
                   for runtime in ('claude', 'codex') for event in ('start', 'end'))
    for relative in files:
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    (home / 'config').mkdir()
    (home / 'config/person.json').write_text(json.dumps(person.configuration()))
    (home / 'foxrun.py').write_text('# Context startup is outside the logger test.\nraise SystemExit(0)\n')
    return home / 'hooks'
