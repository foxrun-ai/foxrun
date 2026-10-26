#!/usr/bin/env python3
"""Create product configuration in a chosen system home without replacing local choices."""
import argparse
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from base import person


def install_configuration(target, person_name):
    target = Path(target)
    if target.is_symlink():
        raise ValueError('system home must not be a symbolic link')
    config = target / 'config'
    if config.is_symlink():
        raise ValueError('config must not be a symbolic link')
    config.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent.parent / 'config/templates'
    copied = []
    for name in ('catalog.yaml', 'models.yaml', 'modules.yaml'):
        destination = config / name
        if not destination.exists() and not destination.is_symlink():
            with destination.open('xb') as stream:
                stream.write(((source.parent / name) if name == 'models.yaml' else (source / name)).read_bytes())
            copied.append(name)
    if person.install_configuration(target, person_name):
        copied.append('person.json')
    return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('system_home', type=Path)
    parser.add_argument('--person', required=True)
    args = parser.parse_args()
    print('created: ' + (', '.join(install_configuration(args.system_home, args.person)) or 'none; existing configuration kept'))


if __name__ == '__main__':
    main()
