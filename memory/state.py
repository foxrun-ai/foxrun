#!/usr/bin/env python3
"""Build and show STATE.md, the page an agent reads at the start.

  state.py build [--workspace NAME | --system | --all] [--check]
  state.py show  [--workspace NAME] [--seat SEAT] [--mark] [--run-dir DIR]

build  Makes STATE.md from the rows of data.db: one page in the system home,
       one at the top of each workspace. The page is written in one step.
       With --check nothing is written; the exit code is 1 when a page is
       missing or does not match its rows.
show   Prints the readout: the system page, then one workspace page.
       With --seat it adds what is new for that seat since its last session.
       show writes nothing unless --mark or --run-dir is given.

Standard library only. Every database is opened read-only.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
sys.path.insert(0, str(ROOT))
from base import paths, person  # noqa: E402
from base.tracker import tracker  # noqa: E402

DAYS = 7
MAX_LINES = 90
GROUP_ROWS = 8   # the most rows in the table Open; the rest is one line
CLOSED = ('done', 'canceled', 'superseded')
INTRO = 'An agent reads this page at the start. A script makes it from the rows in {link}. Change a row, not this page.'
# Question and the view that answers it. A view is listed only when the database has it.
QUESTIONS = (
    ('What is open?', 'open_tasks'),
    ('What waits for {person}?', 'needs_me'),
    ('What is in review?', 'close_now'),
    ('What is planned or due in the next 7 days?', 'this_week'),
    ('Which decisions are open?', 'open_decisions'),
    ('Which stock is at zero or less?', 'v_low_stock'),
    ('Which restocks are due?', 'v_restock_due'),
    ('How old is each mirror?', 'v_mirror_age'),
)
# Question, the foxrun.py words that answer it, and the table they read. Listed only when the database has it.
COMMANDS = (
    ('What did {person} rule about X?', 'rulings <words>', 'decisions'),
)


class StateError(ValueError):
    pass


def now():
    return datetime.now().astimezone()


def stamp(moment):
    """ISO 8601 with seconds and offset, for example 2026-10-13T17:08:42-04:00."""
    return moment.replace(microsecond=0).isoformat()


def minute(value):
    """A stored time as YYYY-MM-DD HH:MM. Unknown shapes are shown as stored."""
    match = re.match(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})', value or '')
    return match.group(1) + ' ' + match.group(2) if match else (value or 'none')


def readonly(database):
    connection = sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def has(db, name, kind=None):
    sql = 'SELECT 1 FROM sqlite_master WHERE name=?' + (' AND type=?' if kind else '')
    return db.execute(sql, (name, kind) if kind else (name,)).fetchone() is not None


def columns(db, table):
    return {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}


def link(page_folder, target):
    """A relative link from the page to a file or folder."""
    return os.path.relpath(str(target), str(page_folder))


def page_link(page_folder, target, label=None):
    """A link when the target is on disk. Else the name and the words (not on disk). Never a broken link."""
    label = label or target.name
    if target.exists() and not target.is_symlink():
        return '[`' + label + '`](' + link(page_folder, target) + ')'
    return '`' + label + '` (not on disk)'


def works_here(folder, home):
    """Who works in a workspace that has no lead seat: `works_here:` in its config/team.yaml (T711).

    The names are data of the workspace, never code. A name is a seat file, in the workspace team
    folder or in the system agents folder; `hermes:<profile>` names a Hermes profile.
    """
    settings = folder / 'config/team.yaml'
    if not settings.is_file() or settings.is_symlink():
        return None
    match = re.search(r'^works_here:[ \t]*\[([^\]\n]*)\][ \t]*(?:#.*)?$', settings.read_text(encoding='utf-8'), re.M)
    names = [part.strip().strip('"\'') for part in match.group(1).split(',')] if match else []
    names = [name for name in names if name]
    if not names:
        return None
    cells = []
    for name in names:
        if name.startswith('hermes:'):
            cells.append('`' + name[len('hermes:'):] + '` (Hermes profile)')
            continue
        seat = paths.resolve_seat(name, home=home, workspace_root=folder) or folder / 'team' / (name + '.md')
        cells.append(page_link(folder, seat, name))
    return ' · '.join(cells)


def home_text(path):
    """A path with the home folder written as ~, for a command a person can paste."""
    text, home = str(path), str(Path.home())
    return '~' + text[len(home):] if text == home or text.startswith(home + '/') else text


def workspaces():
    root = paths.portfolio()
    if not root.is_dir():
        return []
    # Atlas is a standard workspace (g-atlas-is-a-standard-workspace-with-its-wiki-at-the-top).
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink()
                  and not p.name.startswith('.') and p.name != 'inbox')


def contract_workspaces():
    """The workspaces build --all makes a page for: those with AGENTS.md at the top (T693).
    A folder with no contract (apps/, a preview) gets no STATE.md unless it is named."""
    return [name for name in workspaces() if (paths.portfolio() / name / 'AGENTS.md').is_file()]


def canonical(name):
    """The workspace a name stands for. A renamed workspace keeps a link at its old name (T634);
    a link that stays inside the portfolio names the workspace it points to. Else the name as given."""
    if name in workspaces():
        return name
    alias = paths.portfolio() / name
    if alias.is_symlink():
        try:
            target = paths.resolve_portfolio_path(alias)
        except Exception:
            return name
        if target.parent == paths.portfolio().resolve() and target.name in workspaces():
            return target.name
    return name


def default_workspace():
    """The workspace that owns rows with no workspace tag. An old name that links to a renamed workspace
    means that workspace (T693: default_workspace foxrun-dev hid every untagged task from foxrun-hq)."""
    config = person.configuration()
    if config.get('default_workspace') or config.get('workspaces'):
        return canonical(person.workspace())
    names = workspaces()
    return names[0] if names else None


def person_name():
    value = person.configuration().get('name')
    return value.strip() if isinstance(value, str) and value.strip() else 'the person'


def approval_label():
    try:
        name = person.display_name()
    except person.PersonError:
        return 'Your yes first'
    return 'Your yes first' if name == 'Person' else name + "'s yes first"


# ---------------------------------------------------------------- rows

def task_rows(db):
    """Open top-level tasks: the rows of the view open_tasks, with tags and the stream title."""
    if not has(db, 'tasks'):
        return []
    marks = ','.join('?' * len(CLOSED))
    tags = 'tags' if 'tags' in columns(db, 'tasks') else 'NULL'
    title = ('(SELECT p.title FROM projects p WHERE p.id=t.project)' if has(db, 'projects')
             and 'title' in columns(db, 'projects') else 'NULL')
    sql = ('SELECT t.id,t.title,t.status,t.project,' + tags + ' AS tags,' + title + ' AS stream '
           'FROM tasks t WHERE t.status NOT IN (' + marks + ') AND t.parent IS NULL')
    return [dict(row) for row in db.execute(sql, CLOSED)]


def in_workspace(row, workspace, default):
    """A row with no workspace tag belongs to the default workspace. The launcher uses this rule too."""
    tags = [tag.strip() for tag in (row.get('tags') or '').split(',')]
    scopes = [tag[len('workspace:'):] for tag in tags if tag.startswith('workspace:')]
    return workspace in scopes if scopes else workspace == default


def owners_of(db, default):
    """task id -> the set of workspaces the task belongs to, by the tag rule. For a database that workspaces share."""
    if not has(db, 'tasks'):
        return {}
    tags = 'tags' if 'tags' in columns(db, 'tasks') else 'NULL'
    owners = {}
    for task, value in db.execute('SELECT id,' + tags + ' FROM tasks'):
        scopes = {tag.strip()[len('workspace:'):] for tag in (value or '').split(',') if tag.strip().startswith('workspace:')}
        owners[task] = scopes or {default}
    return owners


def belongs(subject_type, subject_id, owners, workspace, default):
    """Does a row about this subject count for this workspace, in a shared database?

    A row about a task counts for the workspace of that task, and for no other.
    A row that names no task of any workspace is counted once: for the default workspace.
    """
    if subject_type in (None, 'task') and subject_id in owners:
        return workspace in owners[subject_id]
    return workspace == default


def subject_columns(db, table):
    """The SQL for the subject of a row: its type and its id, or NULL when the table has no such column."""
    names = columns(db, table)
    return ('subject_type' if 'subject_type' in names else 'NULL') + ',' + ('subject_id' if 'subject_id' in names else 'NULL')


def task_number(task_id):
    match = re.search(r'(\d+)$', task_id or '')
    return int(match.group(1)) if match else -1


def parse_when(value):
    """A stored time as (moment, has_time). A value with no offset is local time. None when it is not a time."""
    text = (value or '').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return datetime.strptime(text, '%Y-%m-%d').astimezone(), False
    try:
        moment = datetime.fromisoformat(text.replace('Z', '+00:00').replace(' ', 'T', 1))
    except ValueError:
        return None, False
    return (moment if moment.tzinfo else moment.astimezone()), True


def newer(value, since, exact, same_day):
    """Is this row newer than the boundary?

    Not exact: by day, for the page that shows the last days.
    Exact: a row with a time is compared with the full boundary. A row with a date and no time
    counts only from the day after the boundary; one on the boundary day is put in same_day.
    """
    if not exact:
        return (value or '')[:10] >= since.strftime('%Y-%m-%d')
    moment, has_time = parse_when(value)
    if moment is None:
        return False
    if has_time:
        return moment > since
    if moment.date() == since.astimezone().date():
        same_day.append(value)
        return False
    return moment.date() > since.astimezone().date()


def scope_facts(database, workspace, since, own, exact=False):
    """Facts for one workspace from one database. own = the workspace has its own data.db.

    exact=True compares each event time with the full boundary (the part for one seat).
    """
    facts = {'tasks': [], 'needs_me': 0, 'bugs': 0, 'newest': None, 'new_tasks': 0,
             'to_review': 0, 'decisions': [], 'decision_count': 0, 'runs': 0, 'views': [],
             'commands': [], 'programs': [], 'functions': [], 'date_only': 0}
    same_day = []
    if not database.is_file():
        return facts
    default = default_workspace()
    # A wide first cut by day; newer() makes the exact cut. One day earlier covers rows stored in another time zone.
    day = (since - timedelta(days=1 if exact else 0)).strftime('%Y-%m-%d')
    with closing(readonly(database)) as db:
        # Every row below passes one test: mine(). In a shared database a row of another workspace never passes it.
        owners = {} if own else owners_of(db, default)

        def mine(subject_type, subject_id):
            return own or belongs(subject_type, subject_id, owners, workspace, default)
        tasks = [row for row in task_rows(db) if mine('task', row['id'])]
        facts['tasks'] = tasks
        open_ids = {row['id'] for row in tasks}
        if has(db, 'needs_me', 'view'):
            facts['needs_me'] = sum(1 for row in db.execute('SELECT id FROM needs_me') if own or row[0] in open_ids)
        if has(db, 'tasks'):
            facts['new_tasks'] = sum(1 for row in db.execute(
                "SELECT id,created_on FROM tasks WHERE parent IS NULL AND substr(coalesce(created_on,''),1,10)>=?", (day,))
                if mine('task', row[0]) and newer(row[1], since, exact, same_day))
        if has(db, 'activity'):
            facts['to_review'] = len({row[0] for row in db.execute(
                "SELECT subject_id,at FROM activity WHERE subject_type='task' AND field='status' "
                "AND new_value='in-review' AND substr(coalesce(at,''),1,10)>=?", (day,))
                if mine('task', row[0]) and newer(row[1], since, exact, same_day)})
            facts['newest'] = max((row[2] for row in db.execute('SELECT ' + subject_columns(db, 'activity') + ',at FROM activity')
                                   if row[2] and mine(row[0], row[1])), default=None)
        if has(db, 'runs'):
            facts['runs'] = sum(1 for row in db.execute(
                'SELECT ' + subject_columns(db, 'runs') + ",started_at FROM runs WHERE substr(coalesce(started_at,''),1,10)>=?", (day,))
                if mine(row[0], row[1]) and newer(row[2], since, exact, same_day))
        if has(db, 'decisions'):
            tags = 'tags' if 'tags' in columns(db, 'decisions') else 'NULL'
            rows = [row for row in db.execute(
                'SELECT name,decided_on,' + tags + " FROM decisions WHERE substr(coalesce(decided_on,''),1,10)>=? "
                'ORDER BY decided_on DESC, id', (day,))
                if (own or in_workspace({'tags': row[2]}, workspace, default)) and newer(row[1], since, exact, same_day)]
            facts['decision_count'] = len(rows)
            facts['decisions'] = [(row[0], row[1]) for row in rows[:5]]
        # These three tables carry no workspace and no task. They are counted once: in their own database, or for the default workspace.
        if own or workspace == default:
            if has(db, 'bugs'):
                facts['bugs'] = db.execute("SELECT count(*) FROM bugs WHERE status='open'").fetchone()[0]
            if has(db, 'programs'):
                state = "WHERE coalesce(status,'') NOT IN ('done','canceled','superseded')" \
                    if 'status' in columns(db, 'programs') else ''
                facts['programs'] = [row[0] + ' ' + row[1] for row in
                                     db.execute('SELECT id,name FROM programs ' + state + ' ORDER BY id')]
            if has(db, 'functions'):
                facts['functions'] = [row[0] for row in db.execute('SELECT id FROM functions ORDER BY id')]
        facts['views'] = [(question, view) for question, view in QUESTIONS if has(db, view, 'view')]
        facts['commands'] = [(question, words) for question, words, table in COMMANDS if has(db, table, 'table')]
    facts['date_only'] = len(same_day)
    return facts


# ---------------------------------------------------------------- the page

def cell(count):
    return str(count) if count else '—'


def clean(text, limit=70):
    text = ' '.join(str(text or '').replace('|', '/').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def count_block(pairs):
    """Labels in capitals, values in one column. Numbers line up on the right."""
    width = max(len(label) for label, _ in pairs) + 3
    digits = max([len(str(value)) for _, value in pairs if isinstance(value, int)] or [1])
    return ['```'] + [label.ljust(width) + (str(value).rjust(digits) if isinstance(value, int) else str(value))
                      for label, value in pairs] + ['```']


def groups_of(tasks, key, name):
    """One row for each group with an open task: in progress, in review, not started, blocked."""
    groups = {}
    for row in tasks:
        group = groups.setdefault(row.get(key) or '', {'id': row.get(key) or '', 'name': name(row),
                                                      'progress': 0, 'review': 0, 'waiting': 0, 'blocked': 0})
        status = row['status']
        slot = ('progress' if status == 'in-progress' else 'review' if status == 'in-review'
                else 'blocked' if status == 'blocked' else 'waiting')
        group[slot] += 1
    ordered = sorted(groups.values(), key=lambda g: (-(g['progress'] + g['review'] + g['waiting'] + g['blocked']), g['id']))
    return ordered


def nightly_status(home):
    """The newest nightly result and the last state push to GitHub (T801). Read-only; never raises.

    The result comes from the newest runs/nightly/*-nightly/receipt.json that is not a dry run
    (T755; a receipt left at the top of runs/ from before the move still counts).
    The push time is the newest 'update by push' entry in the reflog of the upstream ref of state/;
    without one, it is the commit time of that ref. A missing receipt or repo gives None.
    """
    result = at = backup = None
    runs = Path(home) / 'runs'
    from memory.runs import nightly_folders
    folders = sorted(nightly_folders(home), key=lambda folder: folder.name, reverse=True) \
        if runs.is_dir() and not runs.is_symlink() else []
    for folder in folders:
        try:
            if folder.is_symlink():
                continue
            row = json.loads((folder / 'receipt.json').read_text(encoding='utf-8'))
            if not isinstance(row, dict) or row.get('dry_run'):
                continue
            stamp_text = folder.name[:-len('-nightly')]
            at = datetime.strptime(stamp_text, '%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc).astimezone()
            result = 'ok' if row.get('exit') == 0 else 'failed'
            break
        except (OSError, ValueError, TypeError):
            continue
    folder = Path(home) / 'state'
    if not folder.is_symlink() and (folder / '.git').exists():
        def git(*arguments):
            done = subprocess.run(['git', '-C', str(folder)] + list(arguments),
                                  capture_output=True, text=True, timeout=10)
            return done.stdout if done.returncode == 0 else ''
        try:
            upstream = git('rev-parse', '--symbolic-full-name', '@{upstream}').strip()
            if upstream.startswith('refs/remotes/'):
                for line in git('log', '-g', '--date=unix', '--format=%gd%x09%gs', upstream).splitlines():
                    found = re.search(r'@\{(\d+)\}\t(.*)$', line)
                    if found and found.group(2).startswith('update by push'):
                        backup = datetime.fromtimestamp(int(found.group(1)), timezone.utc).astimezone()
                        break
                if backup is None:
                    seconds = git('log', '-1', '--format=%ct', upstream).strip()
                    if seconds.isdigit():
                        backup = datetime.fromtimestamp(int(seconds), timezone.utc).astimezone()
        except (OSError, ValueError, subprocess.SubprocessError):
            backup = None
    return {'result': result, 'at': at, 'backup': backup}


STALE_NIGHTLY_HOURS = 36


def nightly_value(home, moment=None):
    """One line for the count block: the last nightly result and when, then the last GitHub backup.
    A nightly older than 36 hours gets a flag that names /tidy (T755). No run yet says so already."""
    status = nightly_status(home)
    moment = moment or now()
    stale = status['at'] is not None and moment - status['at'] > timedelta(hours=STALE_NIGHTLY_HOURS)
    return format_nightly(status) + (' · OLDER THAN 36 HOURS: run /tidy' if stale else '')


def format_nightly(status):
    """The words of the nightly line from a nightly_status() row. The nightly message uses the same words."""
    first = (status['result'] + ' ' + status['at'].strftime('%Y-%m-%d %H:%M')) if status['result'] else 'no run yet'
    backup = status['backup'].strftime('%Y-%m-%d %H:%M') if status['backup'] else 'none'
    return first + ' · GitHub backup ' + backup


def render(scope, moment=None, since=None):
    """The whole page as text. scope is 'system' or a workspace name. Nothing is written.

    The table Open gets fewer rows until the page fits in MAX_LINES. The rows left out are one line.
    """
    moment = moment or now()
    nightly = nightly_value(paths.system_home(), moment)
    for group_rows in range(GROUP_ROWS, 0, -1):
        text = compose(scope, moment, since, group_rows, nightly)
        if len(text.splitlines()) <= MAX_LINES:
            return text
    raise StateError('STATE.md for ' + scope + ' does not fit in ' + str(MAX_LINES) + ' lines')


def compose(scope, moment, since, group_rows, nightly=None):
    since = since or (moment - timedelta(days=DAYS))
    home = paths.system_home()
    nightly = nightly or nightly_value(home, moment)
    system_db = home / 'data.db'
    if scope == 'system':
        folder, word = home, 'Workspace'
        parts = []
        for name in contract_workspaces():
            database = tracker(name)
            own = database.parent != home
            parts.append((name, scope_facts(database, name, since, own)))
        tasks = []
        for name, facts in parts:
            tasks += [dict(row, group=name) for row in facts['tasks']]
        groups = groups_of(tasks, 'group', lambda row: row['group'])
        counted = [facts for _, facts in parts]
        needs_me = sum(f['needs_me'] for f in counted)
        bugs = sum(f['bugs'] for f in counted)
        newest = max([f['newest'] for f in counted if f['newest']] or [None], key=lambda v: v or '')
        new_tasks = sum(f['new_tasks'] for f in counted)
        to_review = sum(f['to_review'] for f in counted)
        # Newest first; the name breaks a tie, so two builds from the same rows give the same page (T693).
        decisions = sorted({item for f in counted for item in f['decisions']}, key=lambda d: (d[1] or '', d[0]), reverse=True)[:5]
        decision_count = sum(f['decision_count'] for f in counted)
        runs = sum(f['runs'] for f in counted)
        system_facts = scope_facts(system_db, default_workspace() or '', since, True)
        views, programs, functions = system_facts['views'], system_facts['programs'], system_facts['functions']
        commands, command_scope = system_facts['commands'], ''
        database, lead = system_db, ('chief-of-staff', paths.resolve_seat('chief-of-staff', home=home) or home / 'agents/chief-of-staff.md')
        lead_label, lead_cell = 'Lead', None
        gates = home / 'config/gates.md'
        if not gates.is_file() and default_workspace():
            gates = paths.portfolio() / default_workspace() / 'notes/gates.md'
        read_first = ('The global contract ' + page_link(folder, home / 'profile/AGENTS.md') + ', then ' + page_link(folder, folder / 'RESOLVER.md') +
                      ', then the workspace you work in')
    else:
        # A renamed workspace keeps a link at its old name (T634).
        scope = canonical(scope)
        if scope not in workspaces():
            raise StateError('unknown workspace: ' + scope)
        folder, word = paths.portfolio() / scope, 'Stream'
        database = tracker(scope)
        own = database.parent != home
        facts = scope_facts(database, scope, since, own)
        tasks = [dict(row, group=row.get('project') or '') for row in facts['tasks']]
        groups = groups_of(tasks, 'group', lambda row: ((row.get('project') or 'No stream') + ' ' + (row.get('stream') or '')).strip())
        needs_me, bugs, newest = facts['needs_me'], facts['bugs'], facts['newest']
        new_tasks, to_review, decisions = facts['new_tasks'], facts['to_review'], facts['decisions']
        decision_count, runs, views = facts['decision_count'], facts['runs'], facts['views']
        programs, functions = facts['programs'], facts['functions']
        # A workspace with its own database names itself, so the command reads that database too.
        commands, command_scope = facts['commands'], (' --workspace ' + scope if own else '')
        lead_id = ('lead-' + scope)[:40]
        lead = (lead_id, folder / 'team' / (lead_id + '.md'))
        lead_label, lead_cell = 'Lead', None
        if not lead[1].is_file():
            # No lead seat: name the agents that work here, when the workspace says (T711).
            lead_cell = works_here(folder, home)
            lead_label = 'Works here' if lead_cell else 'Lead'
        gates = next((path for path in (folder / 'notes/gates.md', folder / 'docs/gates.md',
                                       home / 'config/gates.md') if path.is_file()), folder / 'notes/gates.md')
        read_first = ('The global contract ' + page_link(folder, home / 'profile/AGENTS.md') + ', then ' +
                      page_link(folder, folder / 'AGENTS.md') + ', then ' + page_link(folder, folder / 'RESOLVER.md'))
    blocked = sum(group['blocked'] for group in groups)
    review = sum(group['review'] for group in groups)
    name = person_name()
    lines = ['---', 'type: state', 'workspace: ' + scope, 'timestamp: ' + stamp(moment), '---',
             '# State: ' + scope, '', INTRO.format(link=page_link(folder, database, 'data.db')), '']
    lines += count_block([('OPEN TASKS', len(tasks)), ('BLOCKED', blocked),
                          ('WAITING FOR ' + name.upper(), needs_me), ('OPEN BUGS', bugs),
                          ('NEWEST CHANGE', minute(newest)), ('MADE', moment.strftime('%Y-%m-%d %H:%M')),
                          ('NIGHTLY', nightly)])
    lead_cell = lead_cell or page_link(folder, lead[1], lead[0])
    gates_cell = ('See [`' + link(folder, gates) + '`](' + link(folder, gates) + ').' if gates.is_file()
                  else 'The gates page is not on disk.')
    lines += ['', '## Always', '', '| What | Value |', '|---|---|',
              '| ' + lead_label + ' | ' + lead_cell + ' |',
              '| Program | ' + (clean(' · '.join(programs), 120) if programs else 'none in the rows') + ' |',
              '| Functions | ' + (clean(' · '.join(functions), 240) if functions else 'none in the rows') + ' |',
              '| ' + approval_label() + ' | Money, sends, deletes, production changes. ' + gates_cell + ' |',
              '| Read first | ' + read_first + ' |',
              '', '## Open', '']
    if not tasks:
        lines += ['No task is open.']
    else:
        lines += ['| ' + word + ' | In progress | In review | Not started |', '|---|---|---|---|']
        shown = groups[:group_rows]
        for group in shown:
            lines.append('| ' + clean(group['name'] or 'No stream', 40) + ' | ' + cell(group['progress']) + ' | ' +
                         cell(group['review']) + ' | ' + cell(group['waiting']) + ' |')
        rest = groups[group_rows:]
        if rest:
            lines.append('| ' + str(len(rest)) + ' more | ' + cell(sum(g['progress'] for g in rest)) + ' | ' +
                         cell(sum(g['review'] for g in rest)) + ' | ' + cell(sum(g['waiting'] for g in rest)) + ' |')
        if review:
            newest_review = sorted((row for row in tasks if row['status'] == 'in-review'),
                                   key=lambda row: task_number(row['id']), reverse=True)[:5]
            lines += ['', str(review) + (' tasks are' if review != 1 else ' task is') + ' in review. The ' +
                      (str(len(newest_review)) + ' newest:' if review > 1 else 'task:'), '',
                      '| Task | Title | ' + word + ' |', '|---|---|---|']
            lines += ['| ' + row['id'] + ' | ' + clean(row['title'], 60) + ' | ' + (row['group'] or '—') + ' |'
                      for row in newest_review]
    lines += ['', '## New since ' + since.strftime('%Y-%m-%d'), '', 'This page shows the last ' + str(DAYS) + ' days.', '']
    lines += count_block([('NEW TASKS', new_tasks), ('MOVED TO IN REVIEW', to_review),
                          ('DECISIONS', decision_count), ('RUNS', runs)])
    if decisions:
        lines += ['', '| Decision | Ruled |', '|---|---|']
        lines += ['| ' + clean(title, 70) + ' | ' + (day or '')[:10] + ' |' for title, day in decisions]
    lines += ['', '## Ask the rows', '']
    if views:
        lines += ['```sh', 'sqlite3 -readonly ' + link(folder, database) + ' "select * from <view>"', '```', '',
                  '| Question | View |', '|---|---|']
        lines += ['| ' + question.format(person=name) + ' | `' + view + '` |' for question, view in views]
    else:
        lines += ['The database holds no view yet. Build it first: `python3 base/build_database.py --help`.']
    if commands:
        lines += ['', '| Question | Command |', '|---|---|']
        lines += ['| ' + question.format(person=name) + ' | `python3 ' + home_text(home / 'foxrun.py') + ' ' +
                  words + command_scope + '` |' for question, words in commands]
    if scope != 'system':
        lines += ['', 'One task:', '', '```sh',
                  'python3 ' + home_text(home / 'work/work.py') + ' --workspace ' + scope + ' \\',
                  '  --receipt-root ' + home_text(folder) + ' show <task>', '```']
    return '\n'.join(lines) + '\n'


def page_path(scope):
    return (paths.system_home() if scope == 'system' else paths.portfolio() / scope) / 'STATE.md'


def write_once(path, text):
    """Write the whole page in one step. A reader sees the old page or the new page, never a part."""
    if path.is_symlink():
        raise StateError('STATE.md must not be a symbolic link: ' + str(path))
    descriptor, temporary = tempfile.mkstemp(prefix='.STATE.md.', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, str(path))
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def steady(text):
    """The page without the lines that change at every build or every nightly run."""
    return '\n'.join(line for line in text.splitlines()
                     if not line.startswith(('timestamp: ', 'MADE ', 'NIGHTLY ')))


def scopes_for(args):
    if args.all:
        return ['system'] + contract_workspaces()
    if args.workspace:
        return [args.workspace]
    return ['system']


def build(args):
    failures = 0
    moment = now()
    for scope in scopes_for(args):
        try:
            text = render(scope, moment)
            path = page_path(scope)
            if args.check:
                current = path.read_text(encoding='utf-8') if path.is_file() else None
                if current is None:
                    print('FAIL ' + str(path) + ': the page is missing')
                    failures += 1
                elif steady(current) != steady(text):
                    print('FAIL ' + str(path) + ': the page does not match its rows; run state.py build')
                    failures += 1
                else:
                    print('PASS ' + str(path))
            else:
                write_once(path, text)
                print('built ' + str(path) + ' (' + str(len(text.splitlines())) + ' lines)')
        except (OSError, sqlite3.Error, ValueError) as error:
            print('FAIL ' + scope + ': ' + ' '.join(str(error).splitlines()))
            failures += 1
    return int(bool(failures))


# ---------------------------------------------------------------- the part for one seat

def marker_file():
    return paths.system_home() / 'runs/state-markers.json'


def read_markers():
    file = marker_file()
    if not file.is_file() or file.is_symlink():
        return {}
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def last_run_end(database, seat, workspace=None, own=True):
    """The end of the newest ended run of this seat in this workspace: (moment, run id), or (None, None).

    In a database that workspaces share, only a run on a task of this workspace counts.
    A run of the seat in another workspace, or a run that names no task, is never the boundary.
    """
    if not database.is_file():
        return None, None
    with closing(readonly(database)) as db:
        if not has(db, 'runs') or not {'by', 'ended_at'} <= columns(db, 'runs'):
            return None, None
        owners = {} if own else owners_of(db, default_workspace())
        best = (None, None)
        for run_id, ended, subject_type, subject_id in db.execute(
                'SELECT id,ended_at,' + subject_columns(db, 'runs') + ' FROM runs WHERE "by"=? AND ended_at IS NOT NULL', (seat,)):
            if not own and not (subject_type in (None, 'task') and subject_id in owners and workspace in owners[subject_id]):
                continue
            moment, has_time = parse_when(ended)
            if moment is not None and has_time and (best[0] is None or moment > best[0]):
                best = (moment, run_id)
        return best


def seat_part(seat, scope, moment):
    """What is new for one seat in one home since the end of the seat's last session there.

    The boundary is the newer of two recorded times: the seat's last ended run in this
    workspace, and the session marked with --mark for this workspace. A run or a mark of
    another workspace is never used. Each event time is compared with the full boundary.
    """
    if not re.fullmatch(r'[a-z][a-z0-9_-]*', seat):
        raise StateError('seat must be a seat id, for example chief-of-staff')
    home = paths.system_home()
    database = home / 'data.db' if scope == 'system' else tracker(scope)
    own = scope == 'system' or database.parent != home
    marked, _ = parse_when(read_markers().get(seat + '|' + scope))
    ended, run_id = last_run_end(database, seat, scope, own)
    lines = ['## For ' + seat + ' in ' + scope, '']
    if marked is None and ended is None:
        since = moment - timedelta(days=DAYS)
        lines.append('The rows hold no session of this seat here. This part shows the last ' + str(DAYS) + ' days.')
    else:
        since = max(value for value in (marked, ended) if value is not None)
        source = 'the run row ' + str(run_id) if since == ended else 'the marked session'
        lines.append('This part shows the time since your last session here: ' +
                     since.astimezone().strftime('%Y-%m-%d %H:%M:%S') + ' (' + source + ').')
    facts = scope_facts(database, scope if scope != 'system' else (default_workspace() or ''), since, own, exact=True)
    lines += [''] + count_block([('NEW TASKS', facts['new_tasks']), ('MOVED TO IN REVIEW', facts['to_review']),
                                 ('DECISIONS', facts['decision_count']), ('RUNS', facts['runs'])])
    if facts['date_only']:
        one = facts['date_only'] == 1
        lines += ['', str(facts['date_only']) + (' row has' if one else ' rows have') +
                  ' the date ' + since.astimezone().strftime('%Y-%m-%d') + ' and no time. ' +
                  ('It is' if one else 'They are') + ' not counted: the row does not say if it is newer.']
    if facts['decisions']:
        lines += ['', '| Decision | Ruled |', '|---|---|']
        lines += ['| ' + clean(title, 70) + ' | ' + (day or '')[:10] + ' |' for title, day in facts['decisions']]
    return '\n'.join(lines) + '\n'


def show(args):
    moment = now()
    scope = args.workspace or default_workspace()
    parts = [render('system', moment)]
    if scope:
        parts.append(render(scope, moment))
    if args.seat:
        parts.append(seat_part(args.seat, scope or 'system', moment))
    text = '\n'.join(parts)
    sys.stdout.write(text)
    if args.run_dir:
        folder = Path(args.run_dir).expanduser().resolve()
        runs = (paths.system_home() / 'runs').resolve()
        if folder != runs and runs not in folder.parents:
            raise StateError('--run-dir must be a folder inside ' + str(runs))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'start-page.md').write_text(text, encoding='utf-8')
    if args.mark:
        if not args.seat:
            raise StateError('--mark needs --seat')
        file = marker_file()
        file.parent.mkdir(parents=True, exist_ok=True)
        lock = file.with_name('.' + file.name + '.lock')
        try:
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)   # one writer of the markers at a time
        except FileExistsError:
            raise StateError('another state.py writes the session markers now, or its lock was left behind: ' + str(lock) +
                             '. The session was not marked. Remove the lock by hand when no state.py runs')
        try:
            os.write(handle, (str(os.getpid()) + ' ' + stamp(moment) + '\n').encode('utf-8'))
            os.close(handle)
            markers = read_markers()
            markers[args.seat + '|' + (scope or 'system')] = stamp(moment)
            # A private, new temporary file (0600, O_EXCL): a planted link at a fixed name is never followed (T750 F07).
            descriptor, temporary = tempfile.mkstemp(prefix='.' + file.name + '.', suffix='.tmp', dir=str(file.parent))
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    stream.write(json.dumps(markers, indent=2, sort_keys=True) + '\n')
                os.replace(temporary, str(file))
            except BaseException:
                if os.path.exists(temporary):
                    os.unlink(temporary)
                raise
        finally:
            os.unlink(str(lock))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    words = parser.add_subparsers(dest='word', required=True)
    make = words.add_parser('build', help='make STATE.md from rows')
    target = make.add_mutually_exclusive_group()
    target.add_argument('--workspace', help='one workspace page')
    target.add_argument('--system', action='store_true', help='the system page (the default)')
    target.add_argument('--all', action='store_true', help='the system page and every workspace page')
    make.add_argument('--check', action='store_true', help='write nothing; exit 1 when a page is missing or stale')
    read = words.add_parser('show', help='print the readout')
    read.add_argument('--workspace', help='the workspace page to print after the system page')
    read.add_argument('--seat', help='add what is new for this seat since its last marked session')
    read.add_argument('--mark', action='store_true', help='record this session as the last one of the seat')
    read.add_argument('--run-dir', help='keep a copy as start-page.md in this run folder')
    args = parser.parse_args(argv)
    try:
        return build(args) if args.word == 'build' else show(args)
    except (OSError, sqlite3.Error, ValueError) as error:
        print('FAIL state ' + args.word + ': ' + ' '.join(str(error).splitlines()), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
