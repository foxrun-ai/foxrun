#!/usr/bin/env python3
"""Find installed module commands and render their capability section. Read-only."""
import json
import os
from pathlib import Path
import sqlite3

START = '<!-- module-commands:start -->'
END = '<!-- module-commands:end -->'


def installed(home):
    database = Path(home) / 'data.db'
    if not database.is_file():
        return set()
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        return {row[0] for row in connection.execute(
            "SELECT DISTINCT module FROM installed_modules WHERE status='complete'")}
    except sqlite3.OperationalError as error:
        # A new workspace has no install record until its database is initialized.
        if 'no such table: installed_modules' in str(error):
            return set()
        raise
    finally:
        connection.close()


def render(system, home, catalog=None):
    system, home = Path(system), Path(home)
    catalog = Path(catalog) if catalog else system / 'config/module-commands.json'
    entries = json.loads(catalog.read_text())['commands']
    names = installed(home)
    lines = [START, '## Module write commands', '',
             'Use these checked commands for local rows. Each write records its actor and activity.',
             'Run help first. Existing money, send, catalog, and deletion gates still apply.', '',
             '| Module | Catalog set | Command |', '|---|---|---|']
    for module, entry in sorted(entries.items()):
        if module not in names:
            continue
        from agent_catalog import expand
        resolved = expand({'sets': [entry['set']]}, system / 'config/catalog.yaml')
        if entry['path'] not in resolved['commands']:
            raise ValueError('Module command is absent from its catalog set: ' + module)
        command = system / entry['path']
        if not command.is_file():
            raise ValueError('Installed module command is missing: ' + str(command))
        link = os.path.relpath(command, home / 'tools')
        run = 'python3 -B ' + str(command) + ' --db ' + str(home / 'data.db') + ' --help'
        lines.append('| %s | `%s` | [%s](%s): `%s` |' % (module, entry['set'], command.name, link, run))
    if not names.intersection(entries):
        lines += ['', 'No module in this command catalog has a complete install record here.']
    lines += ['', '`add`, `set`, and `propose` require `--by <actor>`.',
              'Example: replace `--help` with `list <table>` to read before a checked write.', END]
    return '\n'.join(lines) + '\n'


def update(page, section):
    if START in page:
        before, tail = page.split(START, 1)
        if END not in tail:
            raise ValueError('Incomplete generated module section')
        return before + section.rstrip('\n') + tail.split(END, 1)[1]
    return page.rstrip() + '\n\n' + section
