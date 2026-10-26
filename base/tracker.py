"""Select the existing tracker without changing its schema."""
from base import paths
from pathlib import Path


def local_path(root, value):
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe path: " + value)
    if root == paths.portfolio() or paths.portfolio() in root.parents:
        return paths.resolve_portfolio_path(root / relative)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("symbolic link: " + str(current))
    current.resolve().relative_to(root.resolve())
    return current


def tracker(workspace, explicit=None):
    folder = local_path(paths.portfolio(), workspace)
    if not folder.is_dir():
        raise ValueError('unknown workspace: ' + workspace)
    if explicit is not None:
        return explicit
    database = local_path(folder, 'data.db')
    return database if database.is_file() else local_path(paths.system_home(), 'data.db')
