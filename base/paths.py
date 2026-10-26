#!/usr/bin/env python3
"""Portable locations for one installed system and its workspaces."""
from pathlib import Path
import os
import json

# App repositories are not workspaces: lint and the shape check both skip them.
APP_FOLDERS = frozenset({'apps'})
# A person may keep a workspace in its own layout. They list it in this local file.
# Only the shape check skips it; lint still runs there. With no file, only APP_FOLDERS are skipped.
SHAPE_EXCEPTIONS = 'config/workspaces.local.json'


def _location(name, default):
    return Path(os.environ.get(name, str(default))).expanduser().resolve()


def system_home():
    return _location('FOXRUN_HOME', Path.home() / '.foxrun')


def shape_exceptions(home=None):
    """Read the workspaces this person keeps out of the shape check, from their local settings."""
    path = (Path(home) if home is not None else system_home()) / SHAPE_EXCEPTIONS
    if not path.exists() and not path.is_symlink():
        return frozenset()
    if path.is_symlink() or not path.is_file():
        raise ValueError(SHAPE_EXCEPTIONS + ' must be a regular file')
    settings = json.loads(path.read_text(encoding='utf-8'))
    names = settings.get('shape_exceptions') if isinstance(settings, dict) else None
    if not isinstance(names, list):
        raise ValueError(SHAPE_EXCEPTIONS + ' needs a shape_exceptions list')
    for name in names:
        if (not isinstance(name, str) or not name or name in ('.', '..')
                or Path(name).name != name or '/' in name or '\\' in name):
            raise ValueError(SHAPE_EXCEPTIONS + ' has an invalid workspace name: ' + repr(name))
    return frozenset(names)


def skip_workspaces(home=None):
    """The folders the shape check skips: the app folders and the person's own exceptions."""
    return APP_FOLDERS | shape_exceptions(home)


def __getattr__(name):
    # SKIP_WORKSPACES is read from the person's local settings each time a caller imports it.
    if name == 'SKIP_WORKSPACES':
        return skip_workspaces()
    raise AttributeError('module ' + repr(__name__) + ' has no attribute ' + repr(name))


def resolve_seat(seat, home=None, workspace_root=None, shipped_dir=None):
    """Choose one seat source: workspace team, personal copy, then shipped seat.

    Workspace callers retain their existing team priority. System callers omit
    workspace_root. Unsafe personal copies fail instead of loading another seat.
    shipped_dir supports the agent tools' explicit repository fixtures.
    """
    seat = str(seat)
    if not seat or seat in ('.', '..') or Path(seat).name != seat or '/' in seat or '\\' in seat:
        raise ValueError('seat must be one file name')
    home = Path(home) if home is not None else system_home()
    shipped = Path(shipped_dir) if shipped_dir is not None else home / 'agents'
    candidates = []
    if workspace_root is not None:
        candidates.append((Path(workspace_root), 'team/' + seat + '.md', False))
    candidates += [(home, 'profile/agents/' + seat + '.md', True), (shipped, seat + '.md', False)]
    for root, relative, personal in candidates:
        try:
            if root == portfolio() or portfolio() in root.parents:
                candidate = resolve_portfolio_path(root / relative)
            else:
                candidate = root
                if root.is_symlink():
                    raise ValueError('linked seat folder: ' + str(root))
                for part in Path(relative).parts:
                    candidate /= part
                    if candidate.is_symlink():
                        raise ValueError('linked seat source: ' + str(candidate))
                candidate.resolve().relative_to(root.resolve())
            if candidate.is_file():
                return candidate
            if personal and candidate.exists():
                raise ValueError('personal seat is not a regular file: ' + str(candidate))
        except (OSError, ValueError):
            if personal:
                raise
    return None


def portfolio():
    if os.environ.get('FOXRUN_PORTFOLIO'):
        return _location('FOXRUN_PORTFOLIO', Path.home() / 'foxrun')
    config = system_home() / 'config/person.json'
    if config.is_file() and not config.is_symlink():
        value = json.loads(config.read_text()).get('portfolio')
        if isinstance(value, str) and value:
            return (system_home() / value).expanduser().resolve()
    return (Path.home() / 'foxrun').resolve()


def state():
    return _location('FOXRUN_STATE', Path.home() / '.local/state/foxrun')


def database():
    return system_home() / 'data.db'


def workspace_database(name):
    """Read a workspace tracker path from the person's local settings."""
    workspace(name)  # Validate the workspace id before looking up its setting.
    config = system_home() / 'config/person.json'
    if not config.is_file() or config.is_symlink():
        raise ValueError('config/person.json is required for a workspace database')
    settings = json.loads(config.read_text(encoding='utf-8')).get('workspace_settings', {})
    value = settings.get(str(name), {}).get('database')
    if not isinstance(value, str) or not value:
        raise ValueError('Set workspace_settings.' + str(name) + '.database in config/person.json')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('workspace database setting must be an absolute path')
    return path.resolve()


def workspace(name):
    name = str(name)
    if not name or name in ('.', '..') or Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('workspace must be one folder name')
    return resolve_portfolio_path(portfolio() / name)


def runs():
    """Run trails belong to the system home; service state() stays separate."""
    return system_home() / "runs"


def resolve_portfolio_path(value, portfolio_root=None):
    """Resolve portfolio links, checking every hop, including leave-and-return chains.

    Paths outside the portfolio keep the existing no-links rule. Missing leaves
    are allowed here; callers still check existence, file type, and permissions.
    """
    declared = Path(portfolio_root).expanduser().absolute() if portfolio_root is not None else portfolio()
    boundary = declared.resolve()
    path = Path(value).expanduser().absolute()
    if declared != boundary and (path == declared or declared in path.parents):
        path = boundary / path.relative_to(declared)
    pending = list(path.parts[1:])
    current = Path(path.anchor)
    hops = 0
    while pending:
        part = pending.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            if current == boundary:
                raise ValueError('path leaves portfolio during link resolution: ' + str(path))
            current = current.parent
            continue
        current /= part
        if not current.is_symlink():
            continue
        if current != boundary and boundary not in current.parents:
            raise ValueError('symlink boundary outside portfolio: ' + str(current))
        hops += 1
        if hops > 40:
            raise ValueError('symlink loop or excessive link chain: ' + str(path))
        target = Path(os.readlink(current))
        target = target if target.is_absolute() else current.parent / target
        normalized = Path(os.path.abspath(str(target)))
        if normalized != boundary and boundary not in normalized.parents:
            raise ValueError('symlink leaves portfolio: ' + str(current))
        # Restart from the anchor, without collapsing .. across another link.
        pending = list(target.parts[1:]) + pending
        current = Path(target.anchor)
    return current


def discover_workspaces(root, include_aliases=False):
    """Register immediate contract folders; include safe alias names only when requested."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Portfolio is absent or linked: ' + str(root))
    names=set()
    for child in root.iterdir():
        if child.name.startswith('.') or child.is_symlink() and not include_aliases:continue
        try:checked=resolve_portfolio_path(child,root)
        except ValueError:continue
        contract=checked/'AGENTS.md'
        if checked.is_dir() and contract.is_file() and not contract.is_symlink():names.add(child.name)
    return names
