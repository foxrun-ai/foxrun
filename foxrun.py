#!/usr/bin/env python3
"""Read the installed Foxrun start page, installation checks, and version.

Words: start, status, where, glossary, rulings, doctor, version, hookup.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing, nullcontext

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
sys.path.insert(0, str(ROOT))
from base import paths, person
from work import program

SYSTEM_FOLDERS = (
    'config', 'raw', 'runs', 'archive', 'backups/jsonl',
    'tools/cli', 'tools/mcp', 'tools/service', 'tools/external-app',
    'tools/schedule', 'tools/plugin', 'agents/generated', 'agents/tools',
    'profile', 'evals', 'wiki',
)
# The two lists the installer leaves behind. Doctor needs both.
PRODUCT_LIST = 'base/product-manifest.tsv'
MADE_LIST = 'base/made-at-install.tsv'


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def local_path(root, value):
    """Reject traversal and symbolic links before reading an installed path."""
    relative = Path(value)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('unsafe path: ' + value)
    # The public skill shelf is the one ruled internal directory alias.
    if relative.parts and relative.parts[0] == 'skills' and root == paths.system_home() and (root / 'skills').is_symlink():
        target = (root / 'skills').resolve(strict=True)
        if not within(target, root / 'skillwright/skill-releases'):
            raise ValueError('skill shelf leaves the managed releases')
        canonical = target.relative_to(root).joinpath(*relative.parts[1:])
        return local_path(root, canonical.as_posix())
    target = root / relative
    if within(root, paths.portfolio()):
        return paths.resolve_portfolio_path(target)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('symbolic link: ' + str(current))
    if not within(target.resolve(), root.resolve()):
        raise ValueError('path leaves home: ' + value)
    return target


def workspace_name(value=None):
    if value:
        paths.workspace(value)  # Existing workspace-name validation.
        return value
    local_path(paths.system_home(), 'config/person.json')
    config = person.configuration()
    if config.get('default_workspace') or config.get('workspaces'):
        return person.workspace()
    portfolio = paths.portfolio()
    names = sorted(p.name for p in portfolio.iterdir()
                   if safe_workspace(p) and p.name not in ('atlas', 'inbox')
                   and (p / 'AGENTS.md').is_file()) if portfolio.is_dir() else []
    return names[0] if names else 'my-workspace'


class UnknownWorkspace(ValueError):
    pass


def safe_workspace(path):
    try:
        return paths.resolve_portfolio_path(path).is_dir()
    except (OSError, ValueError):
        return False


def known_workspaces():
    root = paths.portfolio()
    return sorted(p.name for p in root.iterdir() if safe_workspace(p)
                  and p.name != 'inbox' and not p.name.startswith('.')) if root.is_dir() else []


def open_rows(database):
    if not database.is_file():
        return []
    with closing(program.connect(database)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='open_tasks' AND type='view'").fetchone():
            raise ValueError('tracker needs the open_tasks view: ' + str(database))
        columns = {row[1] for row in db.execute('PRAGMA table_info(tasks)')}
        sql = ('SELECT o.*,t.tags FROM open_tasks o JOIN tasks t ON t.id=o.id ORDER BY o.id'
               if 'tags' in columns else 'SELECT * FROM open_tasks ORDER BY id')
        return [dict(row) for row in db.execute(sql)]


def scoped_rows(rows, workspace):
    default = workspace_name()
    def belongs(row):
        tags = [tag.strip() for tag in (row.get('tags') or '').split(',')]
        scopes = [tag[len('workspace:'):] for tag in tags if tag.startswith('workspace:')]
        return workspace in scopes if scopes else workspace == default
    return [row for row in rows if belongs(row)]


def start(workspace=None, function=None, seat=None, run_dir=None, native_context=None):
    home = paths.system_home()
    local_path(home, 'config/person.json')
    config = person.configuration()
    name = config.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('config/person.json needs a non-empty name')
    workspace = workspace_name(workspace)
    folder = local_path(paths.portfolio(), workspace)
    if workspace not in known_workspaces():
        raise UnknownWorkspace('Unknown workspace: ' + workspace + '. Workspaces: ' +
                               (', '.join(known_workspaces()) or 'none'))
    from memory.start_context import start_context
    return start_context(workspace, function, seat, run_dir, native_context=native_context)


def rows(home, name, columns):
    """Rows of one list file inside the home. A symbolic link on the way is refused."""
    file = local_path(home, name)
    with file.open(encoding='utf-8', newline='') as stream:
        reader = csv.reader(stream, delimiter='\t')
        first = True
        for number, row in enumerate(reader, 1):
            if not row or all(not item.strip() for item in row):
                continue
            if first and tuple(row) == columns:
                first = False
                continue
            first = False
            if len(row) != len(columns):
                raise ValueError('{} line {} needs {} columns'.format(file.name, number, len(columns)))
            yield dict(zip(columns, row))


def installed_path(value):
    home, portfolio = paths.system_home(), paths.portfolio()
    value = value.replace("<agent>", ("lead-" + workspace_name())[:40])
    value = value.replace("<workspace>", workspace_name())
    for prefix, root in (('system/', home), ('portfolio/', portfolio),
                         ('<home>/', home), ('<portfolio>/', portfolio)):
        if value.startswith(prefix):
            return local_path(root, value[len(prefix):])
    if Path(value).is_absolute():
        path = Path(value)
        for root in (home, portfolio):
            if within(path, root):
                return local_path(root, str(path.relative_to(root)))
        raise ValueError('path is outside the install: ' + value)
    return local_path(home, value)


def check_generated_seat_paths(home):
    """Refuse runtime loaders that point at a seat the resolver no longer selects."""
    for runtime, suffix in (('claude', '*.md'), ('codex', '*.toml')):
        folder = local_path(home, 'agents/generated/' + runtime)
        for file in sorted(folder.glob(suffix)):
            text = local_path(home, file.relative_to(home).as_posix()).read_text(encoding='utf-8')
            if runtime == 'codex':
                values = [line.split('=', 1)[1].strip() for line in text.splitlines()
                          if line.startswith('developer_instructions =')]
                if len(values) != 1:
                    raise ValueError(str(file) + ': expected developer_instructions')
                text = json.loads(values[0])
                if not isinstance(text, str):
                    raise ValueError(str(file) + ': developer_instructions must be text')
            sources = [match.group(1) for line in text.splitlines()
                       for match in [re.fullmatch(r'Read (.+) fully before anything else\.', line)] if match]
            contracts = [match.group(1) for line in text.splitlines()
                         for match in [re.fullmatch(r'Read the client contract at (.+)\.', line)] if match]
            if len(contracts) > 1:
                raise ValueError(str(file) + ': expected at most one client contract')
            workspace = None
            if contracts:
                contract = Path(contracts[0])
                relative = contract.relative_to(paths.portfolio())
                if len(relative.parts) != 2 or relative.name != 'AGENTS.md':
                    raise ValueError(str(file) + ': invalid client contract')
                workspace = local_path(paths.portfolio(), relative.as_posix()).parent
            selected = paths.resolve_seat(file.stem, home=home, workspace_root=workspace)
            if selected is None or len(sources) != 1 or Path(sources[0]).expanduser() != selected:
                raise ValueError('{}: seat path {} differs from resolve_seat: {}; rebuild this runtime file'.format(
                    file, sources, selected))


def doctor(connection=None):
    home = paths.system_home()
    failures = []

    def check(label, action):
        try:
            action()
            print('PASS ' + label)
        except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
            failures.append(label)
            print('FAIL ' + label + ': ' + ' '.join(str(error).splitlines()))

    def database():
        target = local_path(home, 'data.db')
        with (closing(program.connect(target)) if connection is None else nullcontext(connection)) as db:
            result = db.execute('PRAGMA quick_check').fetchall()
            if [row[0] for row in result] != ['ok']:
                raise ValueError('database integrity check failed')

    def configuration():
        target = local_path(home, 'config/person.json')
        config = json.loads(target.read_text(encoding='utf-8'))
        if not isinstance(config, dict) or not isinstance(config.get('name'), str) or not config['name'].strip():
            raise ValueError('expected a JSON object with a non-empty name')

    def present(target, kind):
        # A link row (the skills shelf): local_path already followed the link and kept it inside the managed releases.
        valid = (target.is_dir() if kind in ('folder', 'directory', 'dir') else target.is_file() if kind in ('file', 'database')
                 else target.exists() if kind == 'link' else None)
        if valid is None:
            raise ValueError('unknown kind: ' + kind)
        if not valid:
            raise ValueError('missing ' + kind + ': ' + str(target))

    from base.agent_catalog import check_models
    extra = [home / 'skills'] if (home / 'skills').exists() else []
    personal = paths.portfolio() / 'skillwright'
    if personal.is_dir():
        extra.append(personal)
    check('model policy and literals', lambda: check_models(home, extra))
    check('data.db', database)
    check('config/person.json', configuration)
    check('generated runtime seat paths', lambda: check_generated_seat_paths(home))
    manifest = home / PRODUCT_LIST
    made = home / MADE_LIST

    def shipped_files():
        entries = list(rows(home, PRODUCT_LIST, ('path', 'bytes', 'sha256')))
        if not entries:
            raise ValueError('manifest has no shipped files')
        for row in entries:
            # update.py keeps a retired product file's row with this marker; the file is no longer shipped.
            if row['sha256'].startswith('retired:'):
                continue
            def verify(row=row):
                target = local_path(home, row['path'])
                present(target, 'file')
                body = target.read_bytes()
                if len(body) != int(row['bytes']):
                    raise ValueError('bytes differ: shipped file changed')
                if hashlib.sha256(body).hexdigest() != row['sha256']:
                    raise ValueError('sha256 differs: shipped file changed')
            check('shipped ' + row['path'], verify)

    def made_paths():
        entries = list(rows(home, MADE_LIST, ('path', 'kind')))
        if not entries:
            raise ValueError('list has no made-at-install paths')
        for row in entries:
            check('made ' + row['path'], lambda row=row: present(installed_path(row['path']), row['kind']))

    # An installed home always holds both lists. The installer is not in the home.
    check('required list ' + PRODUCT_LIST, lambda: present(local_path(home, PRODUCT_LIST), 'file'))
    check('required list ' + MADE_LIST, lambda: present(local_path(home, MADE_LIST), 'file'))
    if manifest.exists() or manifest.is_symlink():
        check(PRODUCT_LIST, shipped_files)
    if made.exists() or made.is_symlink():
        check(MADE_LIST, made_paths)
    if not manifest.exists() and not made.exists() and not manifest.is_symlink() and not made.is_symlink():
        for name in ('catalog.yaml', 'models.yaml', 'modules.yaml', 'tools.yaml'):
            check('config/' + name, lambda name=name: present(local_path(home, 'config/' + name), 'file'))
        for folder in SYSTEM_FOLDERS:
            check('folder ' + folder, lambda folder=folder: present(local_path(home, folder), 'folder'))
        for folder in ('atlas',):
            check('portfolio folder ' + folder, lambda folder=folder: present(local_path(paths.portfolio(), folder), 'folder'))
        check('workspace folder', lambda: present(local_path(paths.portfolio(), workspace_name()), 'folder'))
    # T755: run size and free disk warn; a warning never counts as a failure.
    warned = 0
    try:
        from memory.runs import warnings as run_warnings
        for line in run_warnings(home):
            warned += 1
            print('WARN runs: ' + line)
    except (ImportError, OSError, ValueError) as error:
        warned += 1
        print('WARN runs: size check cannot complete: ' + str(error))
    if not warned:
        print('PASS runs size and free disk')
    print('Doctor: {} failed'.format(len(failures)))
    return int(bool(failures))


def status():
    """Show installed paths and files without asserting activation or synchronization."""
    home = paths.system_home()
    portfolio = paths.portfolio()
    print('System: ' + str(home))
    print('Workspaces: ' + str(portfolio))
    version = local_path(home, 'VERSION')
    print('Version: ' + (version.read_text(encoding='utf-8').strip()
                        if version.is_file() else 'missing'))
    database = local_path(home, 'data.db')
    print('System database: ' + ('present' if database.is_file() else 'missing'))
    for name in (PRODUCT_LIST, MADE_LIST):
        print('List: ' + name + ' | ' + ('present' if local_path(home, name).is_file() else 'missing'))
    for name in known_workspaces():
        folder = local_path(portfolio, name)
        database = local_path(folder, 'data.db')
        print('Workspace: ' + name + ' | database: ' +
              ('present' if database.is_file() else 'uses system database'))
    return 0


def page_lines(file):
    """Lines of one installed page after its front matter, or nothing when the page is absent."""
    lines = file.read_text(encoding='utf-8').splitlines() if file.is_file() and not file.is_symlink() else []
    if lines[:1] == ['---'] and '---' in lines[1:]:
        lines = lines[lines.index('---', 1) + 1:]
    return lines


def dictionary_rows():
    """Rows of the installed dictionary. Empty when the table is absent."""
    database = local_path(paths.system_home(), 'data.db')
    if not database.is_file():
        return []
    with closing(program.connect(database)) as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(object_types)')}
        if not {'name', 'description', 'storage_name'} <= columns:
            return []
        return [dict(row) for row in db.execute(
            'SELECT name,description,storage_name FROM object_types ORDER BY name')]


def glossary_words(workspace=None):
    """Word and meaning pairs from GLOSSARY.md: 'Word: meaning' lines and table rows."""
    files = [local_path(paths.system_home(), 'GLOSSARY.md')]
    if workspace:
        files.append(local_path(local_path(paths.portfolio(), workspace), 'GLOSSARY.md'))
    words = []
    for file in files:
        for line in page_lines(file):
            line = line.strip()
            if line.startswith('|'):
                cells = [cell.strip().strip('`*') for cell in line.strip('|').split('|')]
                if len(cells) >= 2 and cells[0] and set(cells[0]) - set('-: ') and cells[0].lower() != 'word':
                    words.append((cells[0], cells[1], file))
            elif ':' in line and not line.startswith(('#', '-', '`', 'http')):
                word, meaning = line.split(':', 1)
                if word and len(word.split()) <= 4 and meaning.strip():
                    words.append((word.strip(), meaning.strip(), file))
    return words


def same_word(left, right):
    """Match one word in any case, with or without a final s, with space or dash."""
    def plain(value):
        value = value.lower().replace('_', '-').replace(' ', '-')
        return value[:-1] if value.endswith('s') and not value.endswith('ss') else value
    return plain(left) == plain(right)


def glossary(term=None, workspace=None):
    """Answer one question: what does this word mean here? Read the dictionary rows and GLOSSARY.md."""
    if workspace and workspace not in known_workspaces():
        raise UnknownWorkspace('Unknown workspace: ' + workspace)
    page_entries = [(word, meaning, 'Page: ' + str(file)) for word, meaning, file in glossary_words(workspace)]
    entries = [(row['name'], row['description'], 'Storage: ' + row['storage_name'])
               for row in dictionary_rows()
               if not any(same_word(row['name'], word) for word, _, _ in page_entries)]
    entries += page_entries
    if not entries:
        raise ValueError('no dictionary rows and no GLOSSARY.md words in this install')
    if term is None:
        shown = entries
    else:
        shown = [entry for entry in entries if same_word(entry[0], term)]
        if not shown:
            near = sorted({entry[0] for entry in entries if term.lower() in entry[0].lower()})
            raise ValueError('no word: ' + term + ('. Near: ' + ', '.join(near[:8]) if near else ''))
    for name, meaning, source in shown:
        print(name + ': ' + meaning)
        print('  ' + source)
    return 0


def resolver_rows(workspace=None):
    """Rows of the table 'Where things live' in RESOLVER.md: thing, home, path, writer."""
    files = [local_path(paths.system_home(), 'RESOLVER.md')]
    if workspace:
        files.append(local_path(local_path(paths.portfolio(), workspace), 'RESOLVER.md'))
    found = []
    for file in files:
        for line in page_lines(file):
            if not line.startswith('|'):
                continue
            cells = [cell.strip().strip('`') for cell in line.strip().strip('|').split('|')]
            if len(cells) < 3 or not set(cells[0]) - set('-: ') or cells[0].lower() in ('thing', 'agent'):
                continue
            found.append((cells, file))
    return found


def where(value=None, workspace=None):
    """Answer one question: where is this thing, or where does it go?

    An installed path is printed as it is. Any other word is looked up in
    RESOLVER.md and in the dictionary rows. Traversal and symbolic links are refused.
    """
    if workspace:
        if workspace not in known_workspaces():
            raise UnknownWorkspace('Unknown workspace: ' + workspace)
        root = local_path(paths.portfolio(), workspace)
    else:
        root = paths.system_home()
    if value is None:
        print(str(root))
        if not workspace:
            print(str(paths.portfolio()))
        return 0
    looks_like_path = '/' in value or '.' in value or value.startswith('~')
    if looks_like_path or (root / value).exists():
        target = local_path(root, value)
        if not target.exists():
            raise ValueError('installed path does not exist: ' + str(target))
        print(str(target))
        return 0
    answers = []
    for cells, file in resolver_rows(workspace):
        if value.lower() in cells[0].lower():
            answers.append(cells[0] + ': ' + ' | '.join(cell for cell in cells[1:] if cell) + '  (' + file.name + ')')
    for row in dictionary_rows():
        if same_word(row['name'], value):
            answers.append(row['name'] + ': ' + row['storage_name'] + '  (dictionary row)')
    if not answers:
        raise ValueError('no home found for: ' + value + '. Read RESOLVER.md, or give a path.')
    for answer in answers:
        print(answer)
    return 0


RULINGS_SHOWN = 10
# Live rulings first: ruled, then soft, open, deferred. Replaced rows last.
RULING_ORDER = {'ruled': 0, 'soft': 1, 'open': 2, 'deferred': 3}


def ruling_rows(database):
    """Every decision row of one database, read only. Empty when the table is absent."""
    if not database.is_file():
        return []
    from urllib.parse import quote
    uri = 'file:' + quote(str(database)) + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'").fetchone():
            return []
        have = {row[1] for row in db.execute('PRAGMA table_info(decisions)')}
        wanted = ('id', 'name', 'statement', 'person_words', 'status', 'replaces', 'decided_on')
        select = ','.join(name if name in have else 'NULL AS ' + name for name in wanted)
        return [dict(row) for row in db.execute('SELECT ' + select + ' FROM decisions')]


def one_line(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def rulings(words, workspace=None):
    """Answer one question: what did he rule about these words? Every word must appear. Read only."""
    if not words:
        raise ValueError('give one or more words, for example: rulings library atlas')
    databases = [local_path(paths.system_home(), 'data.db')]
    if workspace:
        if workspace not in known_workspaces():
            raise UnknownWorkspace('Unknown workspace: ' + workspace)
        from base.tracker import tracker
        if tracker(workspace) not in databases:
            databases.append(tracker(workspace))
    found = [row for database in databases for row in ruling_rows(database)]
    replaced_by = {}
    for row in found:
        for old in (row['replaces'] or '').replace(',', ' ').split():
            if old != 'none' and old != row['id']:
                replaced_by.setdefault(old, []).append(row['id'])
    terms = [word.lower() for word in words]
    hits = [row for row in found if all(term in ' '.join(str(row[key] or '') for key in
            ('id', 'name', 'statement', 'person_words')).lower() for term in terms)]
    if not hits:
        print('No ruling yet for: ' + ' '.join(words) + '. Try fewer or other words.')
        return 0
    def replaced(row):
        return row['id'] in replaced_by or row['status'] == 'superseded'
    hits.sort(key=lambda row: str(row['decided_on'] or ''), reverse=True)
    hits.sort(key=lambda row: (replaced(row), RULING_ORDER.get(row['status'], 4)))
    for row in hits[:RULINGS_SHOWN]:
        head = [row['id'], row['status'] or 'no status', str(row['decided_on'] or 'no date')[:10]]
        if replaced(row):
            head.append('REPLACED' + (' by ' + ', '.join(replaced_by[row['id']]) if row['id'] in replaced_by else ''))
        print(' | '.join(head))
        print('  ' + one_line(row['statement'] or row['name'], 200))
        if row['person_words']:
            print('  His words: ' + one_line(row['person_words'], 200))
    if len(hits) > RULINGS_SHOWN:
        print(str(len(hits) - RULINGS_SHOWN) + ' more rulings match. Add a word to narrow them.')
    return 0


def hookup(args):
    """Connect the session hooks to an existing install (base/hookup.py). A second run writes nothing."""
    from base.hookup import hookup_existing
    report = hookup_existing(args.home, args.runtime, args.runtime_home)
    if args.json:
        print(json.dumps({'home': str(args.home.expanduser().resolve()), 'runtimes': report}, indent=2))
        return 0
    for row in report:
        name = row['runtime'].capitalize()
        if row['added']:
            print('{}: connected {} hook{} in {}'.format(name, len(row['added']), 's' if len(row['added']) > 1 else '',
                                                        row['settings']))
            for item in row['added']:
                print('  {}: {}'.format(item['event'], item['script']))
        else:
            print('{}: already connected in {}'.format(name, row['settings']))
        for item in row.get('removed', []):
            print('{}: removed the old {} entry for {}'.format(name, item['event'], item['script']))
        if row.get('trust') and row['trust'] in row['written']:
            print('{}: trust rows written in {}'.format(name, row['trust']))
        if row['backup']:
            print('{}: backup of the old files in {}'.format(name, row['backup']))
    if not any(row['written'] for row in report):
        print('Nothing changed.')
    else:
        print('Open a new session: the start page prints when it starts and after each compact.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    wake = commands.add_parser('start')
    wake.add_argument('--workspace')
    wake.add_argument('--runtime', choices=('claude', 'codex'))
    wake.add_argument('--session-id')
    wake.add_argument('--hook-json', action='store_true')
    wake.add_argument('--function', default=os.environ.get('FOXRUN_FUNCTION'))
    wake.add_argument('--seat', default=os.environ.get('FOXRUN_SEAT'))
    wake.add_argument('--run-dir', default=os.environ.get('FOXRUN_RUN_DIR'))
    seat = commands.add_parser('standing')
    seat.add_argument('--seat', required=True)
    seat.add_argument('--runtime', choices=('claude', 'codex'), required=True)
    seat.add_argument('--name', required=True)
    seat.add_argument('--workspace', required=True)
    seat.add_argument('--conversation', required=True)
    seat.add_argument('--from', dest='caller', choices=('claude', 'codex', 'hermes'), default='codex')
    refresh = commands.add_parser('update', help='refresh an existing home from the current product source')
    update_home = Path.home() / '.foxrun' if paths.system_home() == ROOT and (ROOT / 'install.py').is_file() else paths.system_home()
    refresh.add_argument('--home', type=Path, default=update_home)
    refresh.add_argument('--source', type=Path, help='product folder; default: this one, then the recorded one')
    connect = commands.add_parser('hookup', help='connect the session hooks to an existing install; backs up the settings first')
    connect.add_argument('--runtime', choices=('claude', 'codex', 'both'), required=True)
    connect.add_argument('--runtime-home', type=Path,
                         help='settings folder; default: CLAUDE_CONFIG_DIR or ~/.claude, CODEX_HOME or ~/.codex')
    connect.add_argument('--home', type=Path, default=update_home)
    connect.add_argument('--json', action='store_true', help='print the report as JSON')
    commands.add_parser('doctor')
    commands.add_parser('status')
    words = commands.add_parser('glossary')
    words.add_argument('term', nargs='?')
    words.add_argument('--workspace')
    location = commands.add_parser('where')
    location.add_argument('path', nargs='?')
    location.add_argument('--workspace')
    ruled = commands.add_parser('rulings', help='show what the person ruled about some words; read only')
    ruled.add_argument('words', nargs='+')
    ruled.add_argument('--workspace')
    commands.add_parser('version')
    commands.add_parser('addons', help='show optional add-ons; install nothing')
    args = parser.parse_args(argv)
    try:
        if args.command == 'update':
            if args.source is None:
                # update.py finds the source: this product folder, then the one recorded in the home.
                return subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'update.py'), '--home', str(args.home)]).returncode
            # This home's own update.py checks the explicit source before any of its code runs,
            # then runs the source's update.py, as it does for a recorded source.
            source = args.source.expanduser().resolve()
            return subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'update.py'),
                                   '--source', str(source), '--home', str(args.home)]).returncode
        if args.command == 'hookup':
            return hookup(args)
        if args.command == 'addons':
            from base.optional_addons import show
            return show(paths.system_home())
        if args.command == 'standing':
            from work.standing import standing
            return standing(args)
        if args.command == 'start':
            from work.standing import start as seat_start
            hook = {}
            if args.hook_json:
                hook = json.load(sys.stdin)
                if not isinstance(hook, dict):
                    raise ValueError('native hook input must be an object')
            native_context = seat_start(args.workspace, args.runtime, args.session_id, hook)
            from memory.session_start import recover
            workspace, function, seat_id, run_dir = recover(
                args.workspace, args.function, args.seat, args.run_dir, hook, args.session_id)
            if native_context is not None:
                # Binding already validated the native identity, runtime, workspace, and hook cwd.
                from work.standing import read, store
                native_id = args.session_id or hook.get('session_id') or hook.get('thread_id')
                record = read(store('sessions/' + args.runtime + '/' + native_id + '.json'))
                if args.seat and args.seat != record['seat']:
                    raise ValueError('standing seat mismatch')
                workspace, seat_id = record['workspace'], record['seat']
                # Recover the function in the bound workspace even when the caller omitted it.
                workspace, function, _, run_dir = recover(
                    workspace, args.function, seat_id, run_dir, hook, native_id)
            from contextlib import redirect_stdout
            from io import StringIO
            output = StringIO()
            with redirect_stdout(output):
                result = start(workspace, function, seat_id, run_dir, native_context=native_context)
            context = output.getvalue()
            if args.hook_json:
                print(json.dumps({'hookSpecificOutput': {
                    'hookEventName': hook.get('hook_event_name') or 'SessionStart',
                    'additionalContext': context}}))
            else:
                print(context, end='')
            return result
        if args.command == 'status':
            return status()
        if args.command == 'glossary':
            return glossary(args.term, args.workspace)
        if args.command == 'where':
            return where(args.path, args.workspace)
        if args.command == 'rulings':
            return rulings(args.words, args.workspace)
        if args.command == 'doctor':
            return doctor()
        print(local_path(paths.system_home(), 'VERSION').read_text(encoding='utf-8').strip())
        return 0
    except UnknownWorkspace as error:
        print(str(error))
        return 2
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        print('FAIL {}: {}'.format(args.command, ' '.join(str(error).splitlines())))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
