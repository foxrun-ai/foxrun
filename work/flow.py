#!/usr/bin/env python3
"""Run a flow or a workflow, and say where a run stands.

  flow.py run <flow> [--workspace NAME] [--task ID] [--input key=value]... [--no-workers] [--dry-run]
  flow.py run --resume <run> [--yes STEP | --no STEP] [--words "the exact words"] [--no-workers] [--dry-run]
  flow.py status [<run>] [--json]

A workflow connects many skills. It is one file: skillwright/workflows/<name>.yaml.
A flow belongs to one skill. It is the file flow.yaml inside that skill.
Both have one shape: members (who: the team, with its lead), graph (the steps and what each needs),
loop (the repair rule). The team of a squad is the members block: one file holds a team and its graph.

Workers. A member with a runtime (claude, codex, hermes) is a worker this program starts. When its
step is ready, run and run --resume start it through the installed orchestrate resolver
(skills/orchestrate/bin/orchestrate in the system home), all ready workers at the same time, and wait.
A member with access: read gets a read-only route; access: write gets a route that may change files.
The final reply of a worker is its result: this program writes it, word for word, at the step's file,
only when the worker did not write that file itself. It never overwrites a file. Each worker start is
kept in runner/workers/<step>-<try>/. A member with no runtime is done by hand, as before.
With --task, each worker step and each code step is also a run on that task in the tracker
(work/work.py run-start and run-end): the workspace's own data.db when it has one, else the system one.
--no-workers starts nobody.

Two rules hold at every place where this program decides:

  1. FAIL CLOSED. What this program can not prove is valid stops the run, before a step is
     offered and before code runs. A place it can not read or list, a file it can not parse,
     a link it can not follow, a run file that is not the one the run started with, an event
     it does not know, a key it does not know, a key that is missing: each one stops the run
     and is named. It never carries on with what is left.
  2. STRICT SCHEMA. One table, SCHEMA, lists every key of a definition, of the run file, of
     an event, and of the record of a yes or a no, with its type. One validator checks a
     definition against it before a run starts and again each time a run is read. A key that
     is not in the table, a wrong type, an empty value: each is a named problem. No other
     code reads a value of a definition before the validator has passed it.

Which definition a name means. One resolver answers this for run and for status:
  the places of a workspace   <workspace>/workflows/<name>.yaml, <workspace>/skills/<name>/flow.yaml
  the shared places           skillwright/workflows/<name>.yaml, skills/<name>/flow.yaml (the shelf),
                              small-talk/skills/<name>/flow.yaml, skillwright/skills/<name>/flow.yaml (the source)
  the product fallback        skillwright/workflows/.product/<name>.yaml (released product snapshot)
  - A name resolves only when every place it could come from was read, and every definition
    found under that name is valid. The places of a run with --workspace are the place of
    that workspace and the shared places. The places of a shared run are the shared places.
  - A place that is missing holds no definition: it is read as empty, and status names it as
    not there. A place that is a file, is a link that leads nowhere, or can not be listed
    stops every name for the runs that would read it. The error names the place. A lower
    level is never taken in its stead. status shows the place and ends with exit code 1.
  - For a run with --workspace, the definition of that workspace wins over a shared one.
    The run and status say: local definition overrides shared.
  - A name that two places of one level define with different text is refused, with both paths.
    Two places with the same text are one definition (the shelf is a copy of the source).
  - A definition is one real file. A file that several places reach through links is one
    definition with several places. status shows it once, with every workspace that can run it.
    A link from a workspace to a shared file is not an override: it is that shared file.
  - A flow can be given by its path. The path must be one of the places above. A shared path
    gives a shared run, unless --workspace names a workspace. Only a path inside a workspace
    gives a run in that workspace.
  - A definition outside the two homes is never taken. A link is followed first, then checked.
  - A member with a seat needs its seat file: <workspace>/team/<seat>.md, or agents/<seat>.md.
    A code step needs its script: a file inside the system home. Without them no run starts.
  - A run keeps the full path and the sha256 of the definition it took. It works from its
    frozen copy only: a later change of the file on disk is shown and changes nothing in the run.

This program is the only thing that moves a run forward. It does no step that needs
judgment. It checks the file, makes the run folder, runs each code step, and says which
step is next and who does it. A member writes its result as a file into the run folder.

Order and gates are enforced here, in code:
  - A result counts only after `run --resume` accepts it, and only when every step it
    needs is done. A result written before that is early. It is not accepted.
  - An accepted result is frozen. If its file changes, the run is blocked.
  - A step with a gate waits for the person. The yes is recorded by this program, for one
    exact result:  run --resume <run> --yes <step> --words "<the exact words>"
    A yes file that this program did not record is not a yes.
  - A code step with a gate does not run before its yes. The yes names the exact command.
  - A no is recorded with --no. A no ends the whole run: the state is `refused`, and it is
    final. Nothing in any branch is accepted, offered, or run after it. Only a new run
    starts work again.
  - A blocked run does nothing more in any branch until the cause is gone.
  - A run that is done is final too.
  - --dry-run changes nothing, with every other flag: no folder, no event, no file, no code.
  - One program at a time works on a run. The first write is the lock file runner/lock;
    a second caller fails at once with exit code 3. A lock whose program is gone is
    reported and is never removed by this program.
  - Before a code step runs, the event code-start is written. A start with no end means
    the step may have run: the run is blocked, and the step is not run again.

Each run is one folder, runs/<date>-<flow>/ (for a workspace with its own data.db:
<workspace>/history/runs/<date>-<flow>/), with two kinds of file that never mix:
  runner/       only this program writes here: run.yaml, events.jsonl, lock, end.json,
                decisions/<step>.yes.md and .no.md, attempts/<n>/ (the results of an older round).
                No step may name a file here, and nothing here is ever read as the result of a step.
  <file>        the result of one step, at the exact name the step gives in done_when.
                This program never overwrites such a file. It writes one only for a worker it
                started (see Workers). It moves the results of a failed round into runner/attempts/<n>/.
A flow whose step names a file of the runner, the folder runner, a .yes.md or .no.md name,
the file of another step, or a path that leaves the run folder is refused before a run starts.
Capital and small letters count as the same name.

Exit codes: 0 fine. 1 the run is blocked or refused, or status found a problem. 2 the call is
refused (FAIL). 3 another program holds the run. 4 an error this program did not expect; it stops.
Standard library only.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
sys.path.insert(0, str(ROOT))
from base import paths, person, simple_yaml  # noqa: E402

NAME = re.compile(r'(?=[a-z0-9-]*[a-z])[a-z0-9][a-z0-9-]*\Z')    # lowercase letters, digits, dashes; one letter or more, so a number is never a name
FILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\Z')
SCRIPT = re.compile(r'[A-Za-z0-9_][A-Za-z0-9._/-]*\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
STEP_SECONDS = 15 * 60
RESERVED = 'runner'    # the one folder of a run that only this program writes
# Names a step may not use for its result, in any mix of capital and small letters. They are the
# files of the runner (of this version and of the one before), and the page state.py --run-dir writes.
RUNNER_NAMES = ('runner', 'run.yaml', 'events.jsonl', 'lock', '.lock', 'end.json', 'result.json',
                'attempts', 'decisions', 'start-page.md')
PROGRAMS = ('python3',)     # the programs a code step may name first. The second word is the script.
NOTHING = 'nothing was accepted yet'    # what a no is for, when no result was accepted before it
ABSENT = object()      # in SCHEMA: when the key is not written, it stays absent

# ---------------------------------------------------------------- the schema, as data
#
# One row for each key this program knows. A key that is not here is a problem.
#   object   what the key is a key of
#   key      the key
#   need     must = the key has to be there.  may = it can be left out; then it gets the default
#   type     see TYPES below.  list:<type> = a list of that type.  map:<object> = a map from names to
#            that object.  object:<object> = one map of that object.  "a or b" = one of the two types
#   default  what the key is when a `may` key is left out
SCHEMA = (
    # object          key                  need     type                               default
    # --- a definition: one workflow file, or the flow.yaml of one skill
    ('flow',          'version',           'must',  'int:1..1',                        None),
    ('flow',          'flow',              'must',  'name',                            None),
    ('flow',          'kind',              'may',   'word:workflow|flow',              'workflow'),
    ('flow',          'purpose',           'must',  'sentence',                        None),
    ('flow',          'inputs',            'may',   'map:input',                       {}),
    ('flow',          'lead',              'may',   'null or name',                    None),
    ('flow',          'worker_minutes',    'may',   'int:1..240',                      30),
    ('flow',          'members',           'may',   'map:member',                      {}),
    ('flow',          'graph',             'must',  'map:step',                        None),
    ('flow',          'loop',              'may',   'object:loop',                     None),
    ('flow',          'rules',             'may',   'list:sentence',                   []),
    # --- one input a run can take with --input
    ('input',         'required',          'may',   'bool',                            False),
    ('input',         'what',              'must',  'sentence',                        None),
    # --- one member: who does a step. A seat is a seat file; a runtime voice has no seat
    ('member',        'seat',              'may',   'name',                            None),
    ('member',        'what',              'may',   'sentence',                        None),
    ('member',        'voice',             'may',   'bool',                            False),
    ('member',        'runtime',           'may',   'word:claude|codex|hermes',        None),
    ('member',        'model',             'may',   'token',                           None),
    ('member',        'tier',              'may',   'null or word:judgment|work|cheap|code',       None),
    ('member',        'effort',            'may',   'word:low|medium|high|xhigh|max',  None),
    ('member',        'access',            'may',   'word:read|write',                 'read'),
    # --- one step. It has member (an agent does it) or run (code does it), never both
    ('step',          'member',            'may',   'name',                            ABSENT),
    ('step',          'run',               'may',   'command',                         ABSENT),
    ('step',          'skill',             'may',   'null or name',                    None),
    ('step',          'needs',             'may',   'list:step-name',                  []),
    ('step',          'input',             'may',   'list:sentence',                   []),
    ('step',          'output',            'may',   'sentence',                        ''),
    ('step',          'done_when',         'may',   'object:done_when',                ABSENT),
    ('step',          'verdict',           'may',   'bool',                            False),
    ('step',          'gate',              'may',   'name',                            None),
    ('step',          'return',            'may',   'name',                            ''),
    ('done_when',     'file',              'must',  'file',                            None),
    ('loop',          'repair',            'must',  'object:repair',                   None),
    ('repair',        'on',                'must',  'step-name',                       None),
    ('repair',        'repeat',            'must',  'list:step-name',                  None),
    ('repair',        'max_rounds',        'must',  'int:1..5',                        None),
    # --- the run file runner/run.yaml. This program writes it one time, at the start
    ('run',           'run',               'must',  'file',                            None),
    ('run',           'flow',              'must',  'name',                            None),
    ('run',           'workspace',         'must',  'null or folder',                  None),
    ('run',           'task',              'must',  'null or token',                   None),
    ('run',           'inputs',            'must',  'texts',                           None),
    ('run',           'started_at',        'must',  'time',                            None),
    ('run',           'definition_path',   'must',  'path',                            None),
    ('run',           'definition_sha256', 'must',  'hash',                            None),
    ('run',           'definition_source', 'must',  'sentence',                        None),
    ('run',           'overrides',         'must',  'list:path',                       None),
    ('run',           'definition',        'must',  'definition',                      None),
    # --- one line of runner/events.jsonl. Every event has the three keys of `event` and the keys of its own rows
    ('event',         'at',                'must',  'time',                            None),
    ('event',         'ts',                'must',  'number',                          None),
    ('event',         'event',             'must',  'event-name',                      None),
    ('run-start',     'step',              'must',  'null',                            None),
    ('run-start',     'flow',              'must',  'name',                            None),
    ('run-start',     'frozen_sha256',     'must',  'hash',                            None),
    ('accepted',      'step',              'must',  'step-name',                       None),
    ('accepted',      'attempt',           'must',  'int:1..',                         None),
    ('accepted',      'sha256',            'must',  'hash',                            None),
    ('accepted',      'verdict',           'must',  'null or word:pass|fail',          None),
    ('approval',      'step',              'must',  'step-name',                       None),
    ('approval',      'attempt',           'must',  'int:1..',                         None),
    ('approval',      'decision',          'must',  'word:yes|no',                     None),
    ('approval',      'bound',             'must',  'null or hash',                    None),
    ('approval',      'words',             'must',  'sentence',                        None),
    ('approval',      'by',                'must',  'sentence',                        None),
    ('code-start',    'step',              'must',  'step-name',                       None),
    ('code-start',    'attempt',           'must',  'int:1..',                         None),
    ('code-start',    'command_sha256',    'must',  'hash',                            None),
    ('code-start',    'pid',               'must',  'int:1..',                         None),
    ('code-step',     'step',              'must',  'step-name',                       None),
    ('code-step',     'attempt',           'must',  'int:1..',                         None),
    ('code-step',     'exit',              'must',  'int',                             None),
    ('code-step',     'command_sha256',    'must',  'hash',                            None),
    ('code-step',     'detail',            'must',  'string',                          None),
    ('repeat-start',  'step',              'must',  'step-name',                       None),
    ('repeat-start',  'round',             'must',  'int:1..',                         None),
    ('repeat-start',  'steps',             'must',  'list:step-name',                  None),
    ('repeat',        'step',              'must',  'step-name',                       None),
    ('repeat',        'round',             'must',  'int:1..',                         None),
    ('repeat',        'steps',             'must',  'list:step-name',                  None),
    ('run-refused',   'step',              'must',  'step-name',                       None),
    ('run-refused',   'words',             'must',  'string',                          None),
    ('run-done',      'step',              'must',  'null',                            None),
    # --- the record of a yes or a no: runner/decisions/<step>.yes.md or .no.md, one `key: value` line for each key
    ('decision',      'decision',          'must',  'word:yes|no',                     None),
    ('decision',      'for',               'must',  'hash or word:' + NOTHING,         None),
    ('decision',      'by',                'must',  'sentence',                        None),
    ('decision',      'at',                'must',  'time',                            None),
    ('decision',      'words',             'must',  'sentence',                        None),
)
EVENTS = ('run-start', 'accepted', 'approval', 'code-start', 'code-step', 'repeat-start', 'repeat', 'run-refused', 'run-done')

# Each plain type: (what the value must be, in words; the same for many; the check).
TYPES = {
    'null':       ('null', 'nulls', lambda v: v is None),
    'bool':       ('true or false', 'true or false values', lambda v: isinstance(v, bool)),
    'int':        ('a whole number', 'whole numbers', lambda v: isinstance(v, int) and not isinstance(v, bool)),
    'number':     ('a number that is not below 0 and has an end', 'numbers', lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
                   and 0 <= v < float('inf')),
    'string':     ('a text', 'texts', lambda v: isinstance(v, str)),
    'sentence':   ('one sentence (a text that is not empty)', 'sentences (texts that are not empty)',
                   lambda v: isinstance(v, str) and bool(v.strip())),
    'name':       ('a name (lowercase letters, digits, dashes; one letter or more)', 'names (lowercase letters, digits, dashes)',
                   lambda v: isinstance(v, str) and bool(NAME.match(v))),
    'step-name':  ('a step name (lowercase letters, digits, dashes; one letter or more)', 'step names', lambda v: isinstance(v, str) and bool(NAME.match(v))),
    'event-name': ('an event this program writes', 'events', lambda v: isinstance(v, str) and v in EVENTS),
    'folder':     ('one folder name', 'folder names', lambda v: isinstance(v, str) and bool(v.strip()) and '/' not in v
                   and '\n' not in v and v not in ('.', '..')),
    'file':       ('one file name, with no folder and no ..', 'file names', lambda v: isinstance(v, str) and bool(FILE.match(v))),
    'token':      ('one word of letters, digits, dots, and dashes', 'such words', lambda v: isinstance(v, str) and bool(FILE.match(v))),
    'hash':       ('a sha256 in 64 small hex letters', 'sha256 values', lambda v: isinstance(v, str) and bool(HASH.match(v))),
    'time':       ('a time in ISO form', 'times', lambda v: isinstance(v, str) and is_time(v)),
    'path':       ('a full path', 'full paths', lambda v: isinstance(v, str) and v.startswith('/') and '\n' not in v),
    'texts':      ('a map from names to texts', 'such maps', lambda v: isinstance(v, dict) and all(
        isinstance(k, str) and bool(NAME.match(k)) and isinstance(x, str) for k, x in v.items())),
    'definition': ('a definition (the rows of the object flow)', 'definitions', lambda v: isinstance(v, dict)),
    'command':    ('a command: a list of two words or more, first the program (' + ', '.join(PROGRAMS) +
                   '), then a script by its path inside the system home (no / first, no ..)', 'commands', lambda v: is_command(v)),
}

# The rules that need more than one key. Each has a line in problems() with its id.
RULES = (
    ('R01', 'flow equals the name of the file (a workflow file) or of the skill folder (a flow)'),
    ('R02', 'the graph has one step or more'),
    ('R03', 'a step has member or run, and never both'),
    ('R04', 'the member of a step is a key of members'),
    ('R05', 'a step with a member has done_when with one file name'),
    ('R06', 'a result file is not a name of the runner, and not a .yes.md or .no.md name'),
    ('R07', 'no two steps write the same file; capital and small letters are the same'),
    ('R08', 'a code step has only run, needs, and gate'),
    ('R09', 'each step in needs is a step of the graph, is not the step itself, and is there one time'),
    ('R10', 'the needs of the steps form no circle'),
    ('R11', 'loop.repair.on is a step with a member and verdict: true'),
    ('R12', 'loop.repair.repeat lists steps of the graph, one time each, and includes the step of loop.repair.on'),
    ('R13', 'a member has seat, runtime, or what'),
    ('R14', 'the lead is a key of members'),
    ('D01', 'the seat of a member is a seat file on disk: <workspace>/team/<seat>.md, or agents/<seat>.md'),
    ('D02', 'the script of a code step is a file on disk, inside the system home'),
)
PREFIX = {'step': 'step ', 'member': 'member ', 'input': 'input '}


class FlowError(ValueError):
    pass


class Busy(FlowError):
    """Another program holds the run, or the run folder can not be written. Exit code 3."""


def clock():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def is_time(value):
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:      # closed: the value is not a time, and the caller names it as a problem
        return False


def is_command(value):
    """A list of two non-empty words or more: an allowed program, then a script path that stays inside the system home."""
    if not isinstance(value, list) or len(value) < 2:
        return False
    if not all(isinstance(word, str) and word.strip() == word and word and "\x00" not in word for word in value):
        return False
    return value[0] in PROGRAMS and bool(SCRIPT.match(value[1])) and '..' not in value[1].split('/')


def one_time(pairs):
    """For json.loads: a map whose keys are each there one time. A key that is there two times is an error, not a choice."""
    found = {}
    for key, value in pairs:
        if key in found:
            raise ValueError('the key ' + str(key)[:40] + ' is there two times')
        found[key] = value
    return found


def person_name():
    name = person.configuration().get('name')      # closed: a label in a sentence only; no decision reads it
    return name.strip() if isinstance(name, str) and name.strip() else 'the person'


def inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):     # closed: not proven inside means not inside
        return False


# ---------------------------------------------------------------- the one validator

def rows_of(kind):
    return [row for row in SCHEMA if row[0] == kind]


def words_of(kind, many=False):
    """The type in words, for a problem line."""
    if ' or ' in kind:
        return ' or '.join(words_of(option, many) for option in kind.split(' or '))
    head, _, rest = kind.partition(':')
    if head == 'word':
        return 'one of: ' + ', '.join(rest.split('|'))
    if head == 'int' and rest:
        low, _, high = rest.partition('..')
        return low if low == high else 'a whole number from ' + low + ' to ' + high if high else 'a whole number from ' + low
    return TYPES[head][1 if many else 0]


def said(kind):
    """Any type of SCHEMA in words."""
    head, _, rest = kind.partition(':')
    if head == 'list':
        return 'a list of ' + words_of(rest, many=True)
    return 'a map' if head in ('map', 'object') else words_of(kind)


def plain(kind, value):
    """Does the value have this plain type? A plain type is a key of TYPES, word:<a|b>, or int:<low>..<high>."""
    if ' or ' in kind:
        return any(plain(option, value) for option in kind.split(' or '))
    head, _, rest = kind.partition(':')
    if head == 'word':
        return isinstance(value, str) and value in rest.split('|')
    if head == 'int' and rest:
        low, _, high = rest.partition('..')
        return TYPES['int'][2](value) and value >= int(low) and (not high or value <= int(high))
    return TYPES[head][2](value)


def check(kind, value, where, key, bad):
    """Check one value against one type of SCHEMA. Every problem goes into bad, with the place it is at."""
    head, _, rest = kind.partition(':')
    if head == 'list':
        if not isinstance(value, list):
            bad.append(where + key + ' must be ' + said(kind))
            return
        for item in value:
            if not plain(rest, item):
                bad.append(where + key + ' must be a list of ' + words_of(rest, many=True) + '; this is not ' +
                           words_of(rest) + ': ' + str(item)[:60])
    elif head == 'map':
        if not isinstance(value, dict):
            bad.append(where + key + ' must be a map')
            return
        for name, item in value.items():
            inner = PREFIX[rest] + str(name) + ': '
            if not isinstance(name, str) or not NAME.match(name):
                bad.append(inner + 'a ' + rest + ' name has lowercase letters, digits, and dashes')
            check_object(rest, item, inner, bad)
    elif head == 'object':
        check_object(rest, value, where + key + ': ', bad, lead=where + key + ' ')
    elif not plain(kind, value):
        bad.append(where + key + ' must be ' + words_of(kind) + ('' if isinstance(value, (dict, list)) else ': ' + str(value)[:60]))


def check_object(kind, value, where, bad, lead=None):
    """Check one map against the rows of its object in SCHEMA: no unknown key, each must key there, each value of its type."""
    if not isinstance(value, dict):
        bad.append((lead or where) + 'must be a map')
        return
    rows = rows_of(kind)
    known = [row[1] for row in rows]
    for key in value:
        if key not in known:
            bad.append(where + 'unknown key: ' + str(key)[:60])
    for _, key, need, type_, _ in rows:
        if key in value:
            check(type_, value[key], where, key, bad)
        elif need == 'must':
            bad.append(where + key + ' must be ' + said(type_) + ' (the key is missing)')


def part(value, key, kind):
    """value[key] when it is there and has this type; else ABSENT. The rules read a definition only through this."""
    if not isinstance(value, dict) or key not in value:
        return ABSENT
    item = value[key]
    head, _, rest = kind.partition(':')
    if head == 'list':
        return item if isinstance(item, list) and all(plain(rest, one) for one in item) else ABSENT
    if head == 'map':
        return item if isinstance(item, dict) else ABSENT
    return item if plain(kind, item) else ABSENT


def problems(data, name):
    """Every way a definition breaks the schema: the rows of SCHEMA first, then the rules R01 to R13.

    An empty list means the definition is valid. Nothing else may read a value of it before that.
    """
    bad = []
    check_object('flow', data, '', bad)
    if not isinstance(data, dict):
        return bad
    if part(data, 'flow', 'name') != name:                                                  # R01
        bad.append('flow must equal the file name: ' + name)
    every = part(data, 'graph', 'map:step')
    graph = {} if every is ABSENT else {step: body for step, body in every.items()
                                        if isinstance(step, str) and NAME.match(step) and isinstance(body, dict)}
    if every is ABSENT or not every:                                                        # R02
        bad.append('graph must be a map with one step or more')
    members = part(data, 'members', 'map:member')
    members = {} if members is ABSENT else members
    files = {}
    for step, body in graph.items():
        where = 'step ' + step + ': '
        by_member, by_code = 'member' in body, 'run' in body
        if by_member == by_code:                                                            # R03
            bad.append(where + 'needs one of member (an agent does it) or run (code does it)')
        member = part(body, 'member', 'name')
        if member is not ABSENT and member not in members:                                  # R04
            bad.append(where + 'member is not in members: ' + member)
        if by_member:
            target = part(part(body, 'done_when', 'map:done_when'), 'file', 'file')
            if target is ABSENT:                                                            # R05
                bad.append(where + 'done_when needs file: one file name in the run folder, with no folder and no ..')
            elif target.lower() in RUNNER_NAMES or target.lower().endswith(('.yes.md', '.no.md')):   # R06
                bad.append(where + 'done_when.file is a name of the runner: ' + target + '. A step may not use it')
            elif target.lower() in files:                                                   # R07
                bad.append(where + 'writes the same file as step ' + files[target.lower()])
            else:
                files[target.lower()] = step
        if by_code and not by_member:                                                       # R08
            bad += [where + 'a code step has no ' + key + ': it has run, needs, and gate only'
                    for key in sorted(str(key) for key in body) if key in ('done_when', 'verdict', 'skill', 'input', 'output', 'return')]
        needs = part(body, 'needs', 'list:step-name')
        for index, need in enumerate([] if needs is ABSENT else needs):                     # R09
            if need not in graph:
                bad.append(where + 'needs a step that is not in the graph: ' + need)
            if need == step:
                bad.append(where + 'needs itself')
            if need in needs[:index]:
                bad.append(where + 'needs names the step ' + need + ' two times')
    seen, done = set(), set()

    def walk(step, trail):                                                                  # R10
        if step in done or step not in graph:
            return
        if step in seen:
            bad.append('the needs of ' + ' > '.join(trail + [step]) + ' form a circle')
            return
        seen.add(step)
        needs = part(graph[step], 'needs', 'list:step-name')
        for need in ([] if needs is ABSENT else needs):
            walk(need, trail + [step])
        done.add(step)
    for step in graph:
        walk(step, [])
    repair = part(part(data, 'loop', 'map:loop'), 'repair', 'map:repair')
    if repair is not ABSENT:
        review = part(repair, 'on', 'step-name')
        if review is ABSENT or review not in graph or 'member' not in graph[review] \
                or part(graph[review], 'verdict', 'bool') is not True:                      # R11
            bad.append('loop.repair.on must name a step with a member and verdict: true')
        repeat = part(repair, 'repeat', 'list:step-name')
        if repeat is ABSENT or not repeat or any(step not in graph for step in repeat) or review not in repeat \
                or len(set(repeat)) != len(repeat):                                         # R12
            bad.append('loop.repair.repeat must list steps of the graph, one time each, and include the review step')
    for member, body in members.items():
        if isinstance(body, dict) and body.get('tier') and body.get('model'):
            bad.append('member ' + str(member) + ': choose tier, not both tier and model')
        if isinstance(body, dict) and not any(key in body for key in ('seat', 'runtime', 'what')):   # R13
            bad.append('member ' + str(member) + ': needs seat, runtime, or what')
    lead = part(data, 'lead', 'name')
    if lead is not ABSENT and lead not in members:                                          # R14
        bad.append('lead is not in members: ' + lead)
    return bad


def normal(data):
    """The definition with every key of SCHEMA present. Only a definition that problems() passed comes here."""
    def fill(kind, value):
        filled = {}
        for _, key, _, type_, default in rows_of(kind):
            head, _, rest = type_.partition(':')
            if key not in value:
                if default is not ABSENT:
                    filled[key] = json.loads(json.dumps(default))      # a new list or map each time
            elif head == 'object':
                filled[key] = fill(rest, value[key])
            elif head == 'map':
                filled[key] = {name: fill(rest, item) for name, item in value[key].items()}
            else:
                filled[key] = json.loads(json.dumps(value[key]))
        return filled
    return fill('flow', data)


def seat_spots(seat, workspace):
    spots = [spot for spot in [paths.resolve_seat(seat)] if spot is not None]
    if workspace:
        spots.insert(0, paths.workspace(workspace) / 'team' / (seat + '.md'))
    return spots


def seat_file(seat, workspace):
    """Resolve through the shared seat rule, then check the run's boundaries."""
    spot = paths.resolve_seat(seat, workspace_root=paths.workspace(workspace) if workspace else None)
    return spot if spot is not None and in_homes(spot) else None

def script_file(command):
    """The script of a code step when it is a file inside the system home; else None."""
    target = paths.system_home() / command[1]
    return target if target.is_file() and inside(target, paths.system_home()) else None


def disk_problems(data, workspace):
    """The rules D01 and D02, for one place a run can be in. data is a normal definition. An empty list means: it can run there."""
    bad = []
    try:
        for name, member in data['members'].items():
            if member['seat'] is not None and seat_file(member['seat'], workspace) is None:       # D01
                bad.append('member ' + name + ': the seat ' + member['seat'] + ' has no seat file. Looked in: ' +
                           ', '.join(str(spot) for spot in seat_spots(member['seat'], workspace)))
        for step, body in data['graph'].items():
            if 'run' in body and script_file(body['run']) is None:                                # D02
                bad.append('step ' + step + ': the script is not a file inside the system home: ' + body['run'][1])
    except OSError as error:        # closed: a seat or a script that can not be looked at is a problem; the run does not start
        bad.append('a seat file or a script can not be read: ' + str(error))
    return bad


def skill_file(skill, workspace):
    """The page of a skill for a readout: its SKILL.md, or None when it is not built. No decision of a run reads this.

    A place that can not be read raises OSError; skill_word() and status say so in words.
    """
    home = paths.system_home()
    spots = [home / 'skills' / skill / 'SKILL.md', home / 'skillwright/skills' / skill / 'SKILL.md']
    if workspace:
        spots.insert(0, paths.workspace(workspace) / 'skills' / skill / 'SKILL.md')
    for spot in spots:
        if spot.is_file():
            return spot
    return None


def skill_built(skill, workspace):
    try:
        return skill_file(skill, workspace) is not None
    except OSError:     # closed: a count in a readout only; status lists the place that can not be read
        return False


def skill_word(body, workspace):
    """How a step names its skill in a readout. A skill can be bound and not built yet; the readout says so."""
    skill = body['skill']
    if skill is None:
        return 'not bound'
    try:
        file = skill_file(skill, workspace)
    except OSError:     # closed: a readout line only; it says that the place can not be read
        return skill + ' (its place can not be read)'
    return skill + ' (' + str(file) + ')' if file else skill + ' (not built)'


def member_word(data, body, workspace):
    """Who does a step, for a readout: the seat file, or the runtime, or what the member is."""
    member = data['members'][body['member']]
    if member['seat'] is not None:
        return body['member'] + ' (' + str(seat_file(member['seat'], workspace) or 'seat file not on disk') + ')'
    if member['runtime'] is not None:
        return body['member'] + ' (' + ', '.join(str(member[key]) for key in ('runtime', 'model', 'effort') if member[key] is not None) + ')'
    return body['member'] + ' (' + str(member['what']) + ')'


# ---------------------------------------------------------------- where a definition is

def homes():
    return [paths.system_home().resolve(), paths.portfolio().resolve()]


def real_path(path):
    """The real place of a path, with every link followed. None for a link loop or a link that leads nowhere."""
    try:
        real = Path(path).resolve()
        return real if real.exists() else None
    except (OSError, RuntimeError):     # closed: a path that can not be followed has no real place; the caller refuses it
        return None


def in_homes(path):
    """Is the real place of this path inside one of the two homes? A link is followed first."""
    try:
        real = Path(path).resolve()
    except (OSError, RuntimeError):     # closed: not proven inside means not inside
        return False
    return any(real == home or home in real.parents for home in homes())


def by_home(path):
    """The same path, said from the home it is in. A home can be reached through a link; the places are listed from the real home."""
    for parent in reversed(path.parents):
        try:
            real = parent.resolve()
        except (OSError, RuntimeError):     # closed: the path stays as given; it then matches no place and is refused
            return path
        if real != parent and real in homes():
            return real / path.relative_to(parent)
    return path


def listing(folder):
    """The names in one folder: (names, None). Or (None, why) when it is not proven that this is a folder and that it was read."""
    try:
        first = os.lstat(str(folder))
    except FileNotFoundError:
        return None, 'the folder is missing'
    except OSError as error:
        return None, 'the folder can not be read: ' + (error.strerror or type(error).__name__)
    if stat.S_ISLNK(first.st_mode) and real_path(folder) is None:
        return None, 'the folder is a link that leads nowhere, or a link loop'
    if not in_homes(folder):        # the folder itself, or a folder above it, is a link out of the homes
        return None, 'the folder is a link that leaves the two homes'
    try:
        if not stat.S_ISDIR(os.stat(str(folder)).st_mode):
            return None, 'a file is here in place of the folder'
        return sorted(os.listdir(str(folder))), None    # the exact names on disk; this disk ignores case, the list does not
    except OSError as error:
        return None, 'the folder can not be listed: ' + (error.strerror or type(error).__name__)


def workspaces():
    """(names, error). The workspaces are the list in config/person.json when it has one; else every folder of the portfolio."""
    roster = person.configured_workspaces()
    if roster is not None:
        return sorted(set(roster)), None
    names, error = listing(paths.portfolio())
    if error:
        return [], error
    return [name for name in names if not name.startswith('.') and (paths.portfolio() / name).is_dir()], None


def flow_places(names):
    """Every place a flow can be defined, in the one order of the resolver: (level, place, folder, shape, workspace).

    shape 'skill' means <folder>/<name>/flow.yaml. shape 'file' means <folder>/<name>.yaml.
    A workspace has workflows and skill-local flows. The shelf wins over the product snapshot.
    Authoring source is never read as a released personal workflow.
    """
    home = paths.system_home()
    return [('workspace', 'workspace workflow', paths.portfolio() / name / 'workflows', 'file', name) for name in names] + [
        ('workspace', 'workspace skill', paths.portfolio() / name / 'skills', 'skill', name) for name in names] + [
        ('shared', 'system workflow', home / 'skillwright/workflows', 'file', None),
        ('shared', 'shelf skill', home / 'skills', 'skill', None),
        ('shared', 'small-talk skill', home / 'small-talk/skills', 'skill', None),
        ('shared', 'skill source', home / 'skillwright/skills', 'skill', None),
        ('product', 'product workflow', home / 'skillwright/workflows/.product', 'file', None)]


def load(file):
    try:
        data = simple_yaml.safe_load(file.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise FlowError(str(file) + ': ' + str(error))
    if not isinstance(data, dict):
        raise FlowError(str(file) + ': the file must hold one map')
    return data


def read_definition(real, name, cache):
    """What one real file holds, read one time: its sha256, its content, and every problem of it under this name.

    Every error of a file is a problem of that file. A file with a problem is never taken.
    """
    key = (str(real), name)
    if key not in cache:
        found = {'sha256': None, 'data': None, 'normal': None, 'kind': '?', 'problems': []}
        try:
            found['sha256'] = hashlib.sha256(real.read_bytes()).hexdigest()
            if not NAME.match(name):
                found['problems'].append('the name must have lowercase letters, digits, and dashes: ' + name)
            else:
                data = load(real)
                found['problems'] += problems(data, name)
                if not found['problems']:
                    found.update(data=data, normal=normal(data))
                    found['kind'] = found['normal']['kind']
        except FlowError as error:
            found['problems'].append(str(error))
        except Exception as error:      # closed: whatever went wrong, the file gets a problem and is never taken
            found.update(data=None, normal=None, kind='?')
            found['problems'].append('the file can not be checked as a flow: ' + type(error).__name__ + ': ' + str(error)[:120])
        cache[key] = found
    return cache[key]


def entry_of(level, place, folder, shape, owner, item, cache):
    """The entry for one name in one place. None only when it is proven that no definition is there."""
    if item.startswith('.'):
        return None                     # a hidden name is never a flow name
    if shape == 'file':
        if not item.lower().endswith(('.yaml', '.yml')):
            return None                 # only <name>.yaml is a workflow file; a page beside it defines nothing
        file, name = folder / item, item[:-len('.yaml')] if item.endswith('.yaml') else item
    else:
        file, name = folder / item / 'flow.yaml', item
    entry = {'flow': name, 'level': level, 'source': place, 'workspace': owner, 'file': str(file), 'problems': [],
             'real': None, 'sha256': None, 'kind': '?', 'data': None, 'normal': None}
    try:
        if shape == 'file' and not item.endswith('.yaml'):
            entry['problems'].append('a workflow file is <name>.yaml; this name is not that, and it is never taken: ' + item)
        elif shape == 'skill':
            holder = os.lstat(str(folder / item))
            if stat.S_ISLNK(holder.st_mode):
                target = real_path(folder / item)
                if target is None:      # nobody can say what the folder held: the name is reported, and it is never taken
                    entry['problems'].append('the path is a link that leads nowhere, or a link loop; it is never taken')
                elif not target.is_dir():
                    return None         # a link to a file is no skill folder: no flow.yaml can be in it
            elif not stat.S_ISDIR(holder.st_mode):
                return None             # a file in a skills folder is no skill
            if not entry['problems']:
                try:
                    os.lstat(str(file))
                except FileNotFoundError:
                    return None         # the skill folder was read, and it has no flow.yaml: a skill with no flow
        if not entry['problems']:
            real = real_path(file)
            if real is None:
                entry['problems'].append('the path is a link that leads nowhere, or a link loop; it is never taken')
            elif not real.is_file():
                entry['problems'].append('the path is not a file; it is never taken')
            elif not in_homes(file):
                entry['problems'].append('the file is a link that leaves the two homes; it is never taken')
            else:
                found = read_definition(real, name, cache)
                entry.update(real=str(real), sha256=found['sha256'], kind=found['kind'], data=found['data'],
                             normal=found['normal'], problems=list(found['problems']))
    except OSError as error:            # closed: the name gets an entry with a problem; it is never taken
        entry.update(real=None, sha256=None, kind='?', data=None, normal=None,
                     problems=['the place can not be read: ' + (error.strerror or type(error).__name__) + '; it is never taken'])
    entry['valid'] = not entry['problems']
    return entry


def inventory():
    """Every place a flow can be defined, read one time. run and status both use this and no other.

    places: one row for each place, with its error when it could not be listed. resolve() refuses every
            name that could come from a place with an error.
    entries: one row for each definition file found: the path as it is declared there, and the real file behind it.
             Two entries with one real file are one definition with two places; neither entry is dropped.
    """
    names, error = workspaces()
    places, entries, cache = [], [], {}
    if error:   # no list of workspaces: every run with --workspace is refused; a shared run reads the shared places only
        places.append({'level': 'workspace', 'source': 'the workspaces', 'workspace': None, 'folder': str(paths.portfolio()), 'error': error,
                       'missing': False})
    for level, place, folder, shape, owner in flow_places(names):
        found, error = listing(folder)
        missing = error == 'the folder is missing'      # a place that is not there holds no definition: it is read as empty
        if missing:
            found, error = [], None
        places.append({'level': level, 'source': place, 'workspace': owner, 'folder': str(folder), 'error': error, 'missing': missing})
        if error is None:
            for item in found:
                entry = entry_of(level, place, folder, shape, owner, item, cache)
                if entry is not None:
                    entries.append(entry)
    return {'workspaces': names, 'places': places, 'entries': entries}


def near(item, context):
    """Does a run in this context read this place, or this entry? The context None is a shared run."""
    return item['level'] in ('shared', 'product') or (context is not None and item['workspace'] in (context, None))


def trusted(found, name, context):
    """The entries for one name in one context, after the two checks of rule 1. It raises when the name can not be proven.

    Every place the name could come from was listed. Every definition found under the name is valid.
    """
    stuck = [place for place in found['places'] if near(place, context) and place['error'] is not None]
    if stuck:
        raise FlowError('flow ' + name + ' can not be looked up. A place where it could be defined can not be read:\n  ' +
                        '\n  '.join(place['folder'] + ': ' + place['error'] for place in stuck) +
                        '\nNothing is taken from another place in its stead. Repair the place, then run again')
    named = [entry for entry in found['entries'] if near(entry, context) and entry['flow'] == name]
    # A folder with the name in other letters is the same folder on a disk that ignores case. It is never taken;
    # and when the name is defined in another place too, nobody can say which one was meant: the name is refused.
    letters = [entry for entry in found['entries'] if near(entry, context) and entry['flow'] != name and entry['flow'].lower() == name]
    broken = [entry for entry in named + (letters if named else []) if entry['problems']]
    if broken and not letters and all(entry['real'] is None for entry in named):
        raise FlowError('flow ' + name + ' is only defined by a link that leaves the two homes or leads nowhere, '
                        'or by a place that can not be read: ' + ', '.join(entry['file'] for entry in named))
    if broken:
        raise FlowError('\n'.join((entry['real'] or entry['file']) + ' is not valid:\n  ' + '\n  '.join(entry['problems'])
                                  for entry in broken) +
                        ('\nflow ' + name + ' is not taken from another place in its stead' if len(broken) < len(named) + len(letters) else ''))
    return named


def one_of(entries, name):
    """The one definition among places of one level. Places that reach one real file, or hold the same text, are one definition."""
    if len({entry['sha256'] for entry in entries}) > 1:
        raise FlowError('flow ' + name + ' is defined in more than one place of one level, and the files differ:\n  ' +
                        '\n  '.join(entry['file'] for entry in entries) +
                        '\nMake them the same, remove one, or give the path of the one you mean')
    return entries[0]


def can_run(chosen, context):
    """Rules D01 and D02 for the place of the run. It raises when a seat file or a script is not on disk."""
    bad = disk_problems(chosen['normal'], context)
    if bad:
        raise FlowError(chosen['real'] + ' is not valid for ' + ('the workspace ' + context if context else 'a shared run') +
                        ':\n  ' + '\n  '.join(bad))


def resolve(name, workspace=None, found=None):
    """The definition a name means: (entry, overridden, workspace of the run). It raises when that can not be proven.

    name is a flow name, or the path of a definition in one of the places.
    overridden: the shared definitions with another real file that the definition of the workspace wins over.
    workspace of the run: the workspace given; or, for a path inside a workspace, that workspace; else None, a shared run.
    """
    found = inventory() if found is None else found
    if workspace is not None and workspace not in found['workspaces']:
        raise FlowError('unknown workspace: ' + str(workspace) + '. The workspaces are: ' + (', '.join(found['workspaces']) or 'none'))
    if name and ('/' in name or name.endswith('.yaml')):
        given = Path(name).expanduser()
        given = Path(os.path.normpath(str(given if given.is_absolute() else paths.system_home() / given)))
        if not in_homes(given):
            raise FlowError('the path is outside the two homes; a flow is never taken from there: ' + str(given))
        given = by_home(given)
        # First the place the path names. A shared path stays shared; only a path inside a workspace names a workspace.
        declared = [entry for entry in found['entries'] if os.path.normpath(entry['file']) == str(given)]
        if not declared:
            real = real_path(given)
            same = [entry for entry in found['entries'] if real is not None and entry['real'] == str(real)]
            declared = [entry for entry in same if entry['level'] in ('shared', 'product')]
            if not declared:
                declared = [entry for entry in same if workspace is not None and entry['workspace'] == workspace]
            if not declared and same:
                raise FlowError('the path is not a place of a flow. Its file is reached from: ' +
                                ', '.join(entry['file'] for entry in same) + '. Give one of these paths')
        if not declared:
            stuck = [place for place in found['places'] if place['error'] is not None
                     and (str(given) + '/').startswith(place['folder'] + '/')]
            if stuck:
                raise FlowError('the path is in a place that can not be read: ' + stuck[0]['folder'] + ': ' + stuck[0]['error'])
            raise FlowError('no flow is defined at ' + str(given) + '. A flow lives in: ' +
                            ', '.join(sorted({place['folder'] for place in found['places']})))
        chosen = declared[0]
        if chosen['level'] == 'workspace' and workspace is not None and workspace != chosen['workspace']:
            raise FlowError('that path is in the workspace ' + chosen['workspace'] + ', not in ' + workspace)
        context = chosen['workspace'] if chosen['level'] == 'workspace' else workspace
        trusted(found, chosen['flow'], context)
        can_run(chosen, context)
        return chosen, [], context
    if not isinstance(name, str) or not NAME.match(name):
        raise FlowError('a flow name has lowercase letters, digits, and dashes: ' + str(name))
    named = trusted(found, name, workspace)
    local = [entry for entry in named if entry['level'] == 'workspace']
    shared = [entry for entry in named if entry['level'] == 'shared']
    product = [entry for entry in named if entry['level'] == 'product']
    if local:
        chosen = one_of(local, name)
        # A link from the workspace to a shared file is that shared definition. A shared copy with the same text is the same one too.
        is_shared = any(entry['real'] == chosen['real'] for entry in shared)
        overridden = [entry for entry in shared if entry['real'] != chosen['real']
                      and not (is_shared and entry['sha256'] == chosen['sha256'])]
    elif shared:
        chosen, overridden = one_of(shared, name), product
    elif product:
        chosen, overridden = one_of(product, name), []
    else:
        looked = ', '.join(place['folder'] for place in found['places'] if near(place, workspace))
        raise FlowError('no flow named ' + name + '. Looked in: ' + looked if workspace is not None else
                        'no flow named ' + name + ' in the shared places. A flow of a workspace needs --workspace. Looked in: ' + looked)
    can_run(chosen, workspace)
    return chosen, overridden, workspace


def where_from(entry):
    place = entry['source'] + (' of ' + entry['workspace'] if entry['workspace'] else '')
    return place + (', a link to ' + entry['real'] if os.path.normpath(entry['file']) != entry['real'] else '')


# ---------------------------------------------------------------- one run

REFUSAL = re.compile(r"\W*(no|nope|don'?t|do not|stop|hold|wait|not yet|never|cancel|reject)\b", re.I)


def runs_home(workspace=None):
    """The folder of the runs. A workspace with its own tracker (data.db) keeps its runs next to it, in
    <workspace>/history/runs/, so a result file can be the proof of a run on its task. Every other run is in runs/."""
    if workspace is not None:
        folder = paths.workspace(workspace)
        if (folder / 'data.db').is_file():
            return folder / 'history/runs'
    return paths.system_home() / 'runs'


def run_homes():
    """Every folder a run can be in: runs/ of the system home, then each workspace that has its own tracker."""
    homes = [runs_home()]
    for name in workspaces()[0]:
        try:
            home = runs_home(name)
        except (ValueError, OSError):   # closed: a workspace that can not be resolved has no tracker of its own a run could use
            continue
        if home not in homes:
            homes.append(home)
    return homes


def kept(folder):
    """The reserved folder of a run. Only this program writes here."""
    return folder / RESERVED


def result_file(folder, body):
    """The one place the result of a step is looked for: its own name, at the top of the run folder."""
    return folder / body['done_when']['file']


def there(path):
    """Is a thing at this path: a file, a folder, or a link? Only `no such file` means no. Every other error is raised."""
    try:
        os.lstat(str(path))
        return True
    except FileNotFoundError:   # closed: proven absent; an error of another kind (no right to look) is raised and stops the call
        return False


def decision_file(folder, step, decision):
    return kept(folder) / 'decisions' / (step + '.' + decision + '.md')


def run_path(run):
    if not isinstance(run, str) or not FILE.match(run):
        raise FlowError('a run is one folder name in ' + str(runs_home()))
    homes = run_homes()
    found = [home / run for home in homes if there(home / run)]
    if len(found) > 1:
        raise FlowError('two folders have the run name ' + run + ': ' + ', '.join(str(path) for path in found) + '. Neither is read')
    folder = found[0] if found else runs_home() / run
    if folder.is_symlink() or kept(folder).is_symlink():
        raise FlowError('the run folder, or its folder ' + RESERVED + ', is a link. It is not read: ' + str(folder))
    if not (kept(folder) / 'run.yaml').is_file():
        if (folder / 'run.yaml').is_file():
            raise FlowError('the folder ' + run + ' has the shape of an older flow.py: run.yaml is at its top. '
                            'It is not read. Start a new run')
        raise FlowError('no run named ' + run + ' in ' + ', '.join(str(home) for home in homes))
    return folder


def frozen_hash(raw):
    """One hash over what a run may never change after its start: the flow, the definition and where it came from, the inputs, the workspace."""
    fixed = {key: raw[key] for key in ('run', 'flow', 'definition', 'inputs', 'workspace', 'task',
                                       'definition_path', 'definition_sha256', 'definition_source', 'overrides')}
    return hashlib.sha256(json.dumps(fixed, sort_keys=True).encode('utf-8')).hexdigest()


def read_run(folder):
    """The run file, checked against SCHEMA: the rows of the object run, and its definition by problems().

    It returns the content with a normal definition, and as `frozen` the hash of the file as it is on disk.
    A run file that is not valid stops everything: nothing of the run is accepted, offered, or run.
    """
    file = kept(folder) / 'run.yaml'
    try:
        raw = json.loads(file.read_text(encoding='utf-8'), object_pairs_hook=one_time)
    except (OSError, ValueError) as error:
        raise FlowError('the run file can not be read: ' + str(file) + ': ' + str(error)[:120] + '. Nothing is accepted or run')
    bad = []
    check_object('run', raw, '', bad)
    if not bad and raw['run'] != folder.name:
        bad.append('run must equal the name of the run folder: ' + folder.name)
    if not bad:
        bad += ['definition: ' + line for line in problems(raw['definition'], raw['flow'])]
    if not bad:
        known = part(raw['definition'], 'inputs', 'map:input')
        bad += ['inputs: this is not an input of the flow: ' + key for key in raw['inputs'] if known is ABSENT or key not in known]
    if bad:
        raise FlowError('the run file is not valid: ' + str(file) + '\n  ' + '\n  '.join(bad) + '\nNothing is accepted or run')
    info = dict(raw)
    info['frozen'] = frozen_hash(raw)
    info['definition'] = normal(raw['definition'])
    return info


def events(folder):
    """Every line of runner/events.jsonl, each one checked against SCHEMA. A line that can not be proven stops the run."""
    file = kept(folder) / 'events.jsonl'
    try:
        lines = file.read_text(encoding='utf-8').splitlines()
    except (OSError, ValueError) as error:
        raise FlowError('the event file can not be read: ' + str(file) + ': ' + str(error)[:120] + '. Nothing is accepted or run')
    log = []
    for number, line in enumerate(lines, 1):
        bad = []
        try:
            row = json.loads(line, object_pairs_hook=one_time)
        except ValueError:      # closed: the problem is named two lines down, and it stops the run
            row = None
        if not isinstance(row, dict):
            bad.append('the line is not one JSON map')
        elif part(row, 'event', 'event-name') is ABSENT:
            bad.append('unknown event: ' + str(row['event'])[:40] if 'event' in row else 'the key event is missing')
        else:
            rows = rows_of('event') + rows_of(row['event'])
            bad += ['unknown key: ' + str(key)[:40] for key in row if key not in [known[1] for known in rows]]
            for _, key, _, type_, _ in rows:
                if key in row:
                    check(type_, row[key], '', key, bad)
                else:
                    bad.append('the key ' + key + ' is missing')
        if bad:
            raise FlowError('line ' + str(number) + ' of the event file is not an event this program wrote: ' + '; '.join(bad) +
                            '. Nothing is accepted or run. The file: ' + str(file))
        log.append(row)
    return log


def opened(folder):
    """The run file and the events, both checked, and checked against each other. Every reader of a run starts here."""
    info, log = read_run(folder), events(folder)
    graph = info['definition']['graph']
    for number, row in enumerate(log, 1):
        named = ([] if row['step'] is None else [row['step']]) + (row['steps'] if row['event'] in ('repeat-start', 'repeat') else [])
        strange = [step for step in named if step not in graph]
        if strange:
            raise FlowError('line ' + str(number) + ' of the event file names a step that is not in this run: ' + ', '.join(strange) +
                            '. Nothing is accepted or run. The file: ' + str(kept(folder) / 'events.jsonl'))
    return info, log


class Lock:
    """The one lock of a run: the file runner/lock, made so that only one caller can make it.

    It is taken before the state is read and released after the last event is written.
    A lock that is already there is never removed here: the caller fails and says who holds it.
    """

    def __init__(self, folder, word):
        self.folder, self.file, self.word, self.held = folder, kept(folder) / 'lock', word, False

    def __enter__(self):
        for place in (self.folder, kept(self.folder)):
            if place.is_symlink() or not place.is_dir() or not os.access(str(place), os.W_OK | os.X_OK):
                raise Busy('the run folder can not be written: ' + str(place) + '. Nothing was changed')
        try:
            handle = os.open(str(self.file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise Busy(self.who())
        except OSError as error:
            raise Busy('the run folder can not be written: ' + str(error) + '. Nothing was changed')
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'at': clock(), 'word': self.word}) + '\n')
        self.held = True
        return self

    def __exit__(self, *error):
        if self.held:
            try:
                os.unlink(str(self.file))
            except OSError:     # closed: the lock stays; the next caller is told so and changes nothing
                pass
        return False

    def who(self):
        try:
            owner = json.loads(self.file.read_text(encoding='utf-8'))
            pid, since = int(owner['pid']), str(owner['at'])
        except (OSError, ValueError, KeyError, TypeError):      # closed: the caller still fails, with exit code 3
            return 'this run is locked and the lock file can not be read: ' + str(self.file) + '. Nothing was changed'
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except OSError:         # closed: a program that can not be asked counts as alive; the caller fails
            alive = True
        if alive:
            return ('another flow.py works on this run now (process ' + str(pid) + ', since ' + since +
                    '). Nothing was changed. Try again when it has ended')
        return ('this run has a stale lock: process ' + str(pid) + ' made it at ' + since + ' and is gone. Nothing was changed, '
                'and the lock was not removed. Read runner/events.jsonl, then remove ' + str(self.file) + ' by hand')


def note(folder, event, step=None, **more):
    row = dict(at=clock(), ts=time.time(), event=event, step=step, **more)
    with (kept(folder) / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, sort_keys=True) + '\n')
    return row


def text_of(file):
    """The text of a file that a member or the runner wrote. A link, a folder, or no file reads as no text: it is never a result."""
    return file.read_text(encoding='utf-8', errors='replace').strip() if file.is_file() and not file.is_symlink() else ''


def sha_of(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def verdict_of(file):
    """pass, fail, or None when the first line is not 'verdict: pass' or 'verdict: fail'. None is never accepted."""
    lines = [line.strip() for line in text_of(file).splitlines() if line.strip() and line.strip() != '---']
    match = re.match(r'verdict:\s*(pass|fail)\s*\Z', lines[0], re.I) if lines else None
    return match.group(1).lower() if match else None


def command_hash(run, step, attempt, command):
    """The yes for a gated code step names this exact command in this exact run."""
    return hashlib.sha256(json.dumps([run, step, attempt, list(command)]).encode('utf-8')).hexdigest()


def order(graph):
    """Step names with every needed step before the step that needs it."""
    seen, result = set(), []

    def visit(step):
        if step not in seen:
            seen.add(step)
            for need in graph[step]['needs']:
                visit(need)
            result.append(step)
    for step in graph:
        visit(step)
    return result


def after(graph, steps):
    """The given steps and every step that needs one of them, directly or through others."""
    found = set(steps)
    grew = True
    while grew:
        grew = False
        for step, body in graph.items():
            if step not in found and found & set(body['needs']):
                found.add(step)
                grew = True
    return [step for step in graph if step in found]


def fields_of(file):
    """The record of a yes or a no, checked against the object decision of SCHEMA. None when the file is not such a record."""
    found = {}
    known = [row[1] for row in rows_of('decision')]
    for line in text_of(file).splitlines():
        key, mark, value = line.partition(':')
        key = key.strip()
        if not mark or key not in known or key in found:
            return None
        found[key] = value.strip()
    bad = []
    check_object('decision', found, '', bad)
    return None if bad else found


def refusal(folder, graph, log):
    """The recorded no of this run: (step, words), or None.

    A no is a recorded event. A thing at runner/decisions/<step>.no.md of a gated step is a no too, whatever it holds.
    """
    for row in log:
        if row['event'] == 'approval' and row['decision'] == 'no':
            return row['step'], row['words']
    for step, body in graph.items():
        if body['gate'] is not None and there(decision_file(folder, step, 'no')):
            fields = fields_of(decision_file(folder, step, 'no'))
            return step, fields['words'] if fields is not None else 'read the no file of ' + step
    return None


def decision_of(folder, step, bound, attempt, log):
    """Is there a yes for this exact thing? Returns (True|False, why not).

    A yes counts only when all of this holds: this program recorded it (an approval event
    for this step, this try, and this exact thing), the file runner/decisions/<step>.yes.md is still there
    and says the same, and its words do not read as a no.
    """
    # The record of a yes is a file of the runner. It is never the result of a step, and it opens only the gate of its own step.
    if not text_of(decision_file(folder, step, 'yes')):
        return False, ''
    yes = fields_of(decision_file(folder, step, 'yes'))
    if yes is None or yes['decision'] != 'yes' or not HASH.match(yes['for']):
        return False, 'the file of the yes is not a recorded yes; record it with run --resume <run> --yes ' + step
    if yes['for'] != bound:
        return False, 'the yes is for another version; this version needs a new yes'
    if REFUSAL.match(yes['words']):
        return False, 'the words read as a no; record a no with --no ' + step
    recorded = any(row['event'] == 'approval' and row['decision'] == 'yes' and row['step'] == step
                   and row['attempt'] == attempt and row['bound'] == bound for row in log)
    if not recorded:
        return False, 'this yes was not recorded by the runner; record it with run --resume <run> --yes ' + step
    return True, ''


def distrust(info, log):
    """Why the files of the runner can not be trusted as one run; or None.

    The event run-start is the first line, one time, with the hash of the run file. An end is the last line, one time.
    The event run-done is there only when the events show every step done.
    """
    starts = [row for row in log if row['event'] == 'run-start']
    if len(starts) != 1 or log[0] is not starts[0] or starts[0]['frozen_sha256'] != info['frozen']:
        return 'runner/run.yaml is not the file this run started with; nothing is accepted or run'
    ends = [row for row in log if row['event'] in ('run-done', 'run-refused')]
    if len(ends) > 1 or (ends and log[-1] is not ends[0]):
        return 'the event file has an end that is not its one last line; nothing is accepted or run'
    if ends and ends[0]['event'] == 'run-done':
        for step, body in info['definition']['graph'].items():
            attempt = 1 + sum(1 for row in log if row['event'] == 'repeat' and step in row['steps'])
            wanted = 'code-step' if 'run' in body else 'accepted'
            shown = any(row['event'] == wanted and row['step'] == step and row['attempt'] == attempt
                        and (wanted == 'accepted' or row['exit'] == 0) for row in log)
            said_yes = body['gate'] is None or any(row['event'] == 'approval' and row['step'] == step and row['attempt'] == attempt
                                                   and row['decision'] == 'yes' for row in log)
            if not shown or not said_yes:
                return 'the event run-done is there, and the events do not show the step ' + step + ' done; nothing is accepted or run'
    return None


def stopped(graph, state, why):
    return {step: {'state': state, 'detail': why, 'attempt': 1, 'done_at': 0.0, 'bound': None} for step in graph}


def stand(folder, info=None, log=None):
    """Where each step stands. This only reads. Returns (steps, overall).

    Steps are judged in order: a step is looked at only after every step it needs.
    A step is done only when all its needs are done, its result was accepted by code,
    the accepted file has not changed, and its gate has a yes for that exact result.
    """
    if info is None:
        info, log = opened(folder)
    data = info['definition']
    graph = data['graph']
    if distrust(info, log) is not None:
        return stopped(graph, 'stopped', distrust(info, log)), 'blocked'
    over = any(row['event'] in ('run-done', 'run-refused') for row in log)
    missing = [] if over else disk_problems(data, info['workspace'])
    if not over and info['workspace'] is not None and info['workspace'] not in workspaces()[0]:
        missing.append('the workspace of this run is not a workspace now: ' + info['workspace'])
    if missing:
        # The validator runs again each time a run is read. A seat file or a script that is gone stops the run.
        return stopped(graph, 'stopped', 'the definition is not valid now: ' + '; '.join(missing)), 'blocked'
    repair = data['loop']['repair'] if data['loop'] is not None else None
    rounds = sum(1 for row in log if row['event'] == 'repeat')
    if sum(1 for row in log if row['event'] == 'repeat-start') > rounds:
        # A repair round began and its end was not recorded. Until run --resume finishes it, no step is judged.
        return stopped(graph, 'held', 'a repair round started and did not end; run --resume finishes it'), 'repair'
    steps = {}
    for step in order(graph):
        body = graph[step]
        attempt = 1 + sum(1 for row in log if row['event'] == 'repeat' and step in row['steps'])
        needs_done = all(steps[need]['state'] == 'done' for need in body['needs'])
        cleared = max([steps[need]['done_at'] for need in body['needs']] or [0.0])
        state, detail, done_at, bound = 'waiting', '', 0.0, None
        if 'run' in body:
            bound = command_hash(info['run'], step, attempt, body['run'])
            last = next((row for row in reversed(log) if row['event'] == 'code-step' and row['step'] == step
                         and row['attempt'] == attempt), None)
            began = any(row['event'] == 'code-start' and row['step'] == step and row['attempt'] == attempt for row in log)
            other = [row for row in log if row['event'] in ('code-start', 'code-step') and row['step'] == step
                     and row['attempt'] == attempt and row['command_sha256'] != bound]
            if other:
                state, detail = 'changed', 'an event of this code step is for another command; nothing is run'
            elif began and not last:
                state, detail = 'interrupted', 'the code step started and no end was recorded; it may have run; it is not run again'
            elif last and not needs_done:
                state, detail = 'held', 'a step it needs is not done'
            elif last:
                state, detail, done_at = ('done', '', float(last['ts'])) if last['exit'] == 0 else ('failed', 'exit ' + str(last['exit']), 0.0)
            elif needs_done and body['gate'] is not None:
                yes, why = decision_of(folder, step, bound, attempt, log)
                state, detail = ('ready', '') if yes else ('waits-for-yes', why or body['gate'] + ' gate')
            elif needs_done:
                state = 'ready'
        else:
            file = result_file(folder, body)
            accepted = next((row for row in reversed(log) if row['event'] == 'accepted' and row['step'] == step
                             and row['attempt'] == attempt), None)
            if accepted:
                bound = accepted['sha256']
                if not needs_done:
                    state, detail = 'held', 'a step it needs is not done'
                elif not text_of(file) or sha_of(file) != accepted['sha256']:
                    state, detail = 'changed', 'the result changed after it was accepted; put it back, or start again'
                elif body['verdict'] and accepted['verdict'] != 'pass':
                    exhausted = repair is None or rounds >= repair['max_rounds'] or repair['on'] != step
                    state, detail = ('blocked', 'the review failed; no repair round is left') if exhausted \
                        else ('review-failed', 'a repair round starts at the next run --resume')
                elif body['gate'] is not None:
                    yes, why = decision_of(folder, step, bound, attempt, log)
                    if yes:
                        yes_row = [row for row in log if row['event'] == 'approval' and row['step'] == step][-1]
                        state, done_at = 'done', max(float(accepted['ts']), float(yes_row['ts']))
                    else:
                        state, detail = 'waits-for-yes', why or body['gate'] + ' gate'
                else:
                    state, done_at = 'done', float(accepted['ts'])
            elif not needs_done:
                if text_of(file):
                    state, detail = 'early', 'a result is here before the steps it needs are done; it is not accepted'
            elif not text_of(file):
                state = 'ready'
            elif file.stat().st_mtime < cleared:
                state, detail = 'ready', 'the result here was written before the steps it needs were done; write it again'
            elif body['verdict'] and verdict_of(file) is None:
                state, detail = 'ready', 'the first line must be: verdict: pass, or verdict: fail'
            else:
                state, detail = 'result-in', 'run --resume accepts it'
        steps[step] = {'state': state, 'detail': detail, 'attempt': attempt, 'done_at': done_at, 'bound': bound}
    steps = {step: steps[step] for step in graph}
    said_no = refusal(folder, graph, log)
    if said_no:
        # A no is final. Every step that is not done is over: the refused one, and each one in every other branch.
        for step, row in steps.items():
            if step == said_no[0]:
                row.update(state='refused', detail='the person said no: ' + said_no[1])
            elif row['state'] != 'done':
                row.update(state='stopped', detail='the run was refused at ' + said_no[0])
        return steps, 'refused'
    states = [row['state'] for row in steps.values()]
    if any(row['event'] == 'run-done' for row in log):
        overall = 'done'
    elif all(state == 'done' for state in states):
        overall = 'done'
    elif any(state in ('blocked', 'failed', 'changed', 'held', 'interrupted') for state in states):
        overall = 'blocked'
    elif any(state in ('ready', 'result-in', 'review-failed') for state in states):
        overall = 'running'
    elif 'waits-for-yes' in states:
        overall = 'waits for ' + person_name()
    else:
        overall = 'blocked'
    return steps, overall


def is_over(folder):
    """refused or done when the run reached its end and code recorded it. Else None."""
    info, log = opened(folder)
    if distrust(info, log) is not None:
        return None             # a run that can not be trusted is not over: it is blocked, and resume says why
    names = {row['event'] for row in log}
    return 'refused' if 'run-refused' in names else 'done' if 'run-done' in names else None


def code_step(folder, step, body, attempt, bound, runner=subprocess.run):
    home = paths.system_home()
    target = script_file(body['run'])
    if target is None:      # the script was a file when the run started; now it is not: the step fails, and the run is blocked
        return note(folder, 'code-step', step, attempt=attempt, exit=127, command_sha256=bound,
                    detail='not a file in the system home: ' + body['run'][1])
    command = [sys.executable, '-B', str(target)] + list(body['run'][2:])
    environment = dict(os.environ, FOXRUN_HOME=str(home), FOXRUN_RUN_DIR=str(folder), PYTHONDONTWRITEBYTECODE='1')
    info = opened(folder)[0]
    tracked = track_start(folder, info, 'flow.py', 'none', 'code', step, attempt)
    # The start is on disk before the command runs. If this program dies now, the next caller sees a start with no end.
    note(folder, 'code-start', step, attempt=attempt, command_sha256=bound, pid=os.getpid())
    try:
        result = runner(command, cwd=str(home), env=environment, text=True, errors='replace', capture_output=True, timeout=STEP_SECONDS)
        tail = (result.stderr or result.stdout or '').strip().splitlines()
        row = note(folder, 'code-step', step, attempt=attempt, exit=result.returncode, command_sha256=bound,
                   detail=tail[-1][:200] if tail else '')
    except (OSError, subprocess.TimeoutExpired) as error:       # closed: the step is recorded as failed; the run is blocked
        row = note(folder, 'code-step', step, attempt=attempt, exit=124, command_sha256=bound,
                   detail=type(error).__name__ + ': ' + str(error)[:160])
    track_end(info, tracked, 'pass' if row['exit'] == 0 else 'fail', kept(folder) / 'events.jsonl')
    return row


# ---------------------------------------------------------------- the tracker: each step a worker or code does is a run on the task

def tracker_of(info):
    """(database, receipt root) for the task of a run, or None when the run has no task.

    The database is the workspace's data.db when it has one, else the system tracker: the rule of work.py --workspace.
    The receipt root is the folder of that database: its state export lands where it always does, and the run
    folder of such a workspace is inside it (runs_home). It raises when the task is not there.
    """
    if info.get('task') is None:
        return None
    database = paths.database()
    if info['workspace'] is not None and (paths.workspace(info['workspace']) / 'data.db').is_file():
        database = paths.workspace(info['workspace']) / 'data.db'
    root = database.parent
    if not database.is_file():
        raise FlowError('--task ' + info['task'] + ': no tracker at ' + str(database))
    try:
        import sqlite3
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
            found = db.execute('SELECT 1 FROM tasks WHERE id=?', (info['task'],)).fetchone()
    except Exception as error:      # closed: a tracker that can not be read refuses the task
        raise FlowError('--task ' + info['task'] + ': the tracker can not be read: ' + str(database) + ': ' + str(error)[:120])
    if not found:
        raise FlowError('--task ' + info['task'] + ': no such task in ' + str(database))
    home = runs_home(info['workspace'])
    if not inside(home, root):
        raise FlowError('--task ' + info['task'] + ': the run folder ' + str(home) + ' is not inside ' + str(root) +
                        ', the folder of the tracker ' + str(database) + '. A run can not be its receipt')
    return database, root


def tracked_call(info, words):
    """One call of work/work.py for the task of the run. Returns its last line, or None after a warning. A failed write never stops a run."""
    try:
        place = tracker_of(info)
        if place is None:
            return None
        database, root = place
        result = subprocess.run([sys.executable, '-B', str(paths.system_home() / 'work/work.py'), '--db', str(database),
                                 '--receipt-root', str(root)] + words, text=True, capture_output=True, timeout=60,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    except (FlowError, OSError, subprocess.TimeoutExpired) as error:
        print('warning: the tracker was not written: ' + str(error)[:200], file=sys.stderr)
        return None
    if result.returncode != 0:
        print('warning: the tracker was not written: ' + ' '.join((result.stderr or result.stdout).split())[:200], file=sys.stderr)
        return None
    lines = result.stdout.strip().splitlines()
    return lines[-1] if lines else ''


def track_start(folder, info, by, model, runtime, step, attempt):
    """run-start on the task of the run. Returns the run id, or None."""
    if info.get('task') is None:
        return None
    return tracked_call(info, ['--by', by, '--model', model, '--runtime', runtime,
                               '--note', 'flow ' + info['flow'] + ', run ' + info['run'] + ', step ' + step + ', try ' + str(attempt),
                               'run-start', info['task']])


def track_end(info, tracked, result, proof):
    """run-end of a run that track_start made. The proof is a file of the run, said from the receipt root."""
    if not tracked:
        return
    place = tracker_of(info)
    tracked_call(info, ['--result', result, '--proof', os.path.relpath(str(proof), str(place[1])), 'run-end', tracked])


# ---------------------------------------------------------------- workers: members with a runtime, started through orchestrate

def launcher():
    """The installed orchestrate resolver of the system home, or None. No other place is looked in."""
    path = paths.system_home() / 'skills/orchestrate/bin/orchestrate'
    return path if path.is_file() else None


def worker_folder(folder, step, attempt):
    return kept(folder) / 'workers' / (step + '-' + str(attempt))


def is_worker(data, body):
    return 'member' in body and data['members'][body['member']]['runtime'] is not None


def ancestors(graph, step):
    found, todo = [], list(graph[step]['needs'])
    while todo:
        need = todo.pop(0)
        if need not in found:
            found.append(need)
            todo += graph[need]['needs']
    return [name for name in graph if name in found]


def brief(folder, info, step, attempt):
    """What one worker is told. Plain text; it names each file it may read by its full path."""
    data = info['definition']
    body = data['graph'][step]
    member = data['members'][body['member']]
    seat = seat_file(member['seat'], info['workspace']) if member['seat'] else None
    earlier = [result_file(folder, data['graph'][name]) for name in ancestors(data['graph'], step) if 'member' in data['graph'][name]]
    older = sorted(str(path) for path in (kept(folder) / 'attempts').rglob('*') if path.is_file()) if attempt > 1 else []
    lines = ['You are one worker of a flow. Do this one step, then stop. Start no other worker.',
             'Flow: ' + info['flow'] + '. ' + data['purpose'],
             'Step: ' + step + ' (try ' + str(attempt) + ').',
             'You are the member ' + body['member'] + ('. ' + member['what'] if member['what'] else '.')]
    if seat:
        lines.append('Read your seat file first: ' + str(seat))
    if info['inputs']:
        lines += ['Inputs of the run:'] + ['  ' + key + ': ' + value for key, value in sorted(info['inputs'].items())]
    if body['input']:
        lines.append('This step needs: ' + '; '.join(body['input']))
    if earlier:
        lines += ['Read the results of the steps before this one:'] + ['  ' + str(path) for path in earlier]
    if older:
        lines += ['This is a repair round. Read the results of the round before, the review first:'] + ['  ' + path for path in older]
    lines.append('Your job: ' + (body['output'] or 'the result of the step ' + step + '.'))
    if body['skill']:
        lines.append('Use the skill ' + body['skill'] + ' when you have it.')
    rules = list(data['rules']) + ['Send nothing, pay nothing, publish nothing, and change no live system. A gate asks the person later.',
                                   'Write no file of another step, and nothing in ' + str(kept(folder)) + '.']
    lines += ['Rules:'] + ['  - ' + rule for rule in rules]
    if member['access'] == 'write':
        lines.append('You may change files in ' + str(worker_cwd(folder, info)) + ' to do the job.')
    else:
        lines.append('Read only: change no file.')
    lines.append('Your final reply is saved word for word as ' + str(result_file(folder, body)) + '. Reply with that page only.')
    if body['verdict']:
        lines.append('The first line of your reply must be: verdict: pass, or verdict: fail.')
    return '\n'.join(lines) + '\n'


def worker_cwd(folder, info):
    return paths.workspace(info['workspace']) if info['workspace'] is not None else folder


def routed(route, cwd, work):
    """The native command of a resolved orchestrate route, as a list. It raises for a route this program can not run without a shell."""
    if route.get('status') != 'resolved' or route.get('mode') != 'one-shot' or route.get('opens_window'):
        raise FlowError('orchestrate gave no one-shot route: ' + str(route.get('status')) + ' ' + str(route.get('reason') or route.get('use_instead') or ''))
    import shlex
    parts = shlex.split(route.get('command') or '', comments=True)
    if parts[:1] == ['cd']:
        if len(parts) < 4 or parts[2] != '&&' or Path(parts[1]).resolve() != Path(cwd).resolve():
            raise FlowError('orchestrate gave another working folder: ' + ' '.join(parts[:2]))
        parts = parts[3:]
    if len(parts) >= 4 and parts[-4:-2] == ['</dev/null', '>'] and parts[-1] == '2>&1':
        parts = parts[:-4]          # the event stream is captured here instead
    if not parts or parts[0] not in ('claude', 'codex', 'hermes'):
        raise FlowError('orchestrate gave a command this program does not run: ' + ' '.join(parts[:1]))
    if any(part in ('&&', ';', '|', '>', '<', '2>&1', '</dev/null') for part in parts):
        raise FlowError('orchestrate gave a shell command; it is not run')
    if parts[0] == 'codex' and '-o' in parts and parts.index('-o') + 1 < len(parts):
        parts[parts.index('-o') + 1] = str(work / 'reply.md')
    return parts


def with_member(parts, member, folder, cwd):
    """The member's model and effort, put into the native command. The route keeps its own safety flags."""
    runtime, model, effort = parts[0], member['model'], member['effort']
    if member.get('tier'):
        from base.agent_catalog import resolve_model
        model = resolve_model(member['tier'], runtime)
    extra = []
    if runtime == 'claude':
        extra = (['--model', model] if model else []) + (['--effort', effort] if effort else [])
        if Path(cwd).resolve() != folder.resolve():
            extra += ['--add-dir', str(folder)]
    elif runtime == 'codex':
        if model:
            if '-m' in parts:
                parts[parts.index('-m') + 1] = model
            else:
                extra += ['-m', model]
        if effort:
            setting = 'model_reasoning_effort=' + effort
            have = [index for index, part in enumerate(parts) if part.startswith('model_reasoning_effort=')]
            if have:
                parts[have[0]] = setting
            else:
                extra += ['-c', setting]
        return parts[:2] + extra + parts[2:]
    elif runtime == 'hermes' and model:
        extra = ['-m', model]
    return parts[:1] + extra + parts[1:]


def reply_of(runtime, stdout, work):
    """The final reply of a worker, as text. Empty when there is none."""
    if runtime == 'claude':
        try:
            envelope = json.loads(stdout)
        except ValueError:      # closed: no JSON is no reply
            return ''
        if not isinstance(envelope, dict) or envelope.get('is_error') or not isinstance(envelope.get('result'), str):
            return ''
        return envelope['result'].strip()
    if runtime == 'codex':
        return text_of(work / 'reply.md')
    return stdout.strip()


def start_workers(folder, steps, started):
    """Start every ready worker step at the same time, wait for all, and write each reply. Returns how many started.

    A step starts at most one time in one call (started). A step whose file is already there is never started.
    """
    info = opened(folder)[0]
    data = info['definition']
    graph = data['graph']
    resolver = launcher()
    ready = [step for step, row in steps.items() if row['state'] == 'ready' and is_worker(data, graph[step])
             and (step, row['attempt']) not in started and not there(result_file(folder, graph[step]))]
    if not ready or resolver is None:
        return 0
    cwd = worker_cwd(folder, info)
    live = []
    for step in ready:
        attempt = steps[step]['attempt']
        started.add((step, attempt))
        member = dict(data['members'][graph[step]['member']])
        if member.get('tier'):
            from base.agent_catalog import resolve_model
            member['model'] = resolve_model(member['tier'], member['runtime'])
        work = worker_folder(folder, step, attempt)
        work.mkdir(parents=True, exist_ok=True)
        task = brief(folder, info, step, attempt)
        (work / 'brief.md').write_text(task, encoding='utf-8')
        try:
            asked = subprocess.run([sys.executable, '-B', str(resolver), 'resolve', '--from', 'codex', '--to', member['runtime'],
                                    '--want', 'fix' if member['access'] == 'write' else 'quick', '--cwd', str(cwd),
                                    '--run-dir', str(work), '--task', task], text=True, capture_output=True, timeout=60)
            (work / 'route.json').write_text(asked.stdout, encoding='utf-8')
            if asked.returncode != 0:
                raise FlowError('orchestrate refused: ' + ' '.join((asked.stderr or asked.stdout).split())[:200])
            command = with_member(routed(json.loads(asked.stdout), cwd, work), member, folder, cwd)
            (work / 'argv.json').write_text(json.dumps(command, indent=2) + '\n', encoding='utf-8')
            tracked = track_start(folder, info, graph[step]['member'], member['model'] or 'default', member['runtime'], step, attempt)
            out, err = (work / 'stdout').open('w', encoding='utf-8'), (work / 'stderr').open('w', encoding='utf-8')
            process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True,
                                       env=dict(os.environ, FOXRUN_RUN_DIR=str(folder)))
            live.append((step, attempt, member, work, process, (out, err), tracked))
        except (FlowError, OSError, ValueError, subprocess.TimeoutExpired) as error:      # closed: this worker did not start; it is written down
            (work / 'end.json').write_text(json.dumps({'step': step, 'try': attempt, 'started': False, 'why': str(error)[:300]}, indent=2) + '\n',
                                           encoding='utf-8')
            print('warning: the worker of ' + step + ' did not start: ' + str(error)[:200], file=sys.stderr)
    deadline = time.time() + data['worker_minutes'] * 60
    for step, attempt, member, work, process, streams, tracked in live:
        try:
            code = process.wait(timeout=max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
        for stream in streams:
            stream.close()
        file = result_file(folder, graph[step])
        reply = reply_of(member['runtime'], (work / 'stdout').read_text(encoding='utf-8', errors='replace'), work)
        wrote = False
        if code == 0 and reply and not there(file):
            file.write_text(reply + '\n', encoding='utf-8')      # the worker's own words; a file that is there is never overwritten
            wrote = True
        done = bool(text_of(file))
        end = work / 'end.json'
        end.write_text(json.dumps({'step': step, 'try': attempt, 'started': True, 'exit': code, 'reply_written': wrote,
                                   'result': str(file) if done else None}, indent=2) + '\n', encoding='utf-8')
        track_end(info, tracked, 'pass' if done else 'fail', file if done else end)
    return len(live)


def drive(folder, workers=True, runner=subprocess.run):
    """Move the run as far as code and workers can: advance, start the ready workers, and again, until nothing more starts."""
    started = set()
    while True:
        steps, overall = advance(folder, runner)
        if not workers or not (overall == 'running' or overall.startswith('waits for')):
            return steps, overall
        if not start_workers(folder, steps, started):
            return steps, overall


def move_round(folder, graph, steps, number):
    """Put the result and the yes of each step of a finished round into runner/attempts/<number>/. Doing it twice is harmless."""
    keep = kept(folder) / 'attempts' / str(number)
    keep.mkdir(parents=True, exist_ok=True)
    for step in steps:
        body = graph[step]
        moves = [(decision_file(folder, step, 'yes'), keep / (step + '.yes.md'))]
        if 'run' not in body:
            moves.append((result_file(folder, body), keep / body['done_when']['file']))
        for source, target in moves:
            if source.is_file() or source.is_symlink():
                os.replace(str(source), str(target))


def write_end(folder, info, state, **more):
    """The end summary of the run. It is a file of the runner: runner/end.json. No file of a worker is touched."""
    summary = dict(run=info['run'], flow=info['flow'], state=state, ended_at=clock(), **more)
    (kept(folder) / 'end.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')


def advance(folder, runner=subprocess.run):
    """Move the run as far as code can. Each pass reads and checks the whole run first, then does one thing, then reads again.

    A pass does nothing when the run is refused, done, or blocked. Else it accepts one result
    whose needs are done, or starts one repair round, or runs one code step that is ready;
    a gated code step is ready only after its recorded yes. Nothing here can pass a gate.
    """
    passes = len(opened(folder)[0]['definition']['graph']) * 12 + 12
    for _ in range(passes):
        info, log = opened(folder)
        graph = info['definition']['graph']
        steps, overall = stand(folder, info, log)
        names = {row['event'] for row in log}
        if overall == 'repair':
            begun = [row for row in log if row['event'] == 'repeat-start'][-1]
            move_round(folder, graph, begun['steps'], begun['round'])
            note(folder, 'repeat', begun['step'], round=begun['round'], steps=begun['steps'])
            continue        # the round is closed; the next pass reads the run again
        if overall == 'refused':
            if 'run-refused' not in names and 'run-done' not in names:
                step, words = refusal(folder, graph, log)
                note(folder, 'run-refused', step, words=words)
                write_end(folder, info, 'refused', step=step)
            return steps, overall
        if 'run-done' in names or overall == 'blocked':
            return steps, overall
        arrived = next((step for step, row in steps.items() if row['state'] == 'result-in'), None)
        if arrived:
            file = result_file(folder, graph[arrived])
            note(folder, 'accepted', arrived, attempt=steps[arrived]['attempt'], sha256=sha_of(file),
                 verdict=verdict_of(file) if graph[arrived]['verdict'] else None)
            continue        # one result is accepted; the next pass reads the run again
        failed = next((step for step, row in steps.items() if row['state'] == 'review-failed'), None)
        if failed:
            number = 1 + sum(1 for row in log if row['event'] == 'repeat')
            again = after(graph, info['definition']['loop']['repair']['repeat'])   # the repeated steps and every step after them
            note(folder, 'repeat-start', failed, round=number, steps=again)   # first the plan, then the move, then the end
            move_round(folder, graph, again, number)
            note(folder, 'repeat', failed, round=number, steps=again)
            continue        # one repair round is started; the next pass reads the run again
        ready_code = next((step for step, row in steps.items() if row['state'] == 'ready' and 'run' in graph[step]), None)
        if ready_code:
            code_step(folder, ready_code, graph[ready_code], steps[ready_code]['attempt'], steps[ready_code]['bound'], runner)
            continue        # one code step ran; the next pass reads the run again
        if overall == 'done':
            note(folder, 'run-done')
            write_end(folder, info, 'done')
        return steps, overall
    raise FlowError('the run did not settle; read ' + str(kept(folder) / 'events.jsonl'))


def gate_of(folder, step):
    """The gate of a step of this run. It raises when the step is not a step with a gate."""
    graph = opened(folder)[0]['definition']['graph']
    if not isinstance(step, str) or step not in graph or graph[step]['gate'] is None:
        raise FlowError('step ' + str(step) + ' has no gate in this flow')
    return graph[step]['gate']


def check_words(folder, step, words, decision='yes'):
    """The checks of a decision that need no state: the step has a gate, and there are words; the words of a yes do not read as a no."""
    gate_of(folder, step)
    if not isinstance(words, str) or not ' '.join(words.split()):
        raise FlowError('--words is needed: the exact words of ' + person_name())
    if decision == 'yes' and REFUSAL.match(' '.join(words.split())):
        raise FlowError('the words read as a no. Record a no with --no ' + step + ', or give the exact words of the yes')


def check_decision(folder, step, decision, words, steps, overall):
    """Every reason a decision can not be recorded now. Raises FlowError; writes nothing."""
    check_words(folder, step, words, decision)
    if overall == 'refused':
        raise FlowError('this run is refused. No decision is recorded. Only a new run starts work again')
    row = steps[step]
    if decision == 'yes' and row['state'] != 'waits-for-yes':
        raise FlowError('step ' + step + ' does not wait for a yes now; it is ' + row['state'])
    if decision == 'no' and row['state'] == 'done':
        raise FlowError('step ' + step + ' is done; a no can not undo it')
    return row


def decide(folder, step, decision, words):
    """Record the person's yes or no. Only this function writes a decision that counts. The caller holds the lock.

    A yes is for the exact thing a step waits on, and only a step that waits can get one.
    A no can be recorded for any gated step that is not done; it ends the whole run.
    """
    over = is_over(folder)
    if over:
        raise FlowError('this run is ' + over + '. No decision is recorded. Only a new run starts work again')
    doubt = distrust(*opened(folder))
    if doubt is not None:       # a yes or a no is never written into a run that can not be trusted
        raise FlowError('no decision is recorded: ' + doubt)
    # The cheap checks come first, so a wrong call accepts nothing and runs nothing.
    before, overall = stand(folder)
    if decision == 'no':
        check_decision(folder, step, decision, words, before, overall)
    else:
        check_words(folder, step, words)
        if before[step]['state'] not in ('waits-for-yes', 'result-in'):
            raise FlowError('step ' + step + ' does not wait for a yes now; it is ' + before[step]['state'])
    # A no is recorded at once: nothing is accepted or run first. A yes needs the result accepted first.
    steps, overall = stand(folder) if decision == 'no' else advance(folder)
    row = check_decision(folder, step, decision, words, steps, overall)
    words = ' '.join(words.split())
    seat = os.environ.get('FOXRUN_SEAT') or 'seat not set'      # closed: a label in the record; no decision reads it
    lines = ['decision: ' + decision, 'for: ' + (row['bound'] or NOTHING), 'by: ' + seat, 'at: ' + clock(), 'words: ' + words]
    note(folder, 'approval', step, attempt=row['attempt'], decision=decision, bound=row['bound'], words=words, by=seat)
    decision_file(folder, step, decision).parent.mkdir(exist_ok=True)
    decision_file(folder, step, decision).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def preview(folder, args):
    """--dry-run with --resume: say what a real call would do first. This only reads. Nothing is locked or written."""
    info, log = opened(folder)
    steps, overall = stand(folder, info, log)
    report(folder, steps, overall)
    graph = info['definition']['graph']
    would = []
    over = is_over(folder)
    if args.yes or args.no:
        decision, step = ('yes', args.yes) if args.yes else ('no', args.no)
        try:
            if over:
                raise FlowError('this run is ' + over + '. No decision is recorded. Only a new run starts work again')
            if decision == 'yes' and step in steps and steps[step]['state'] == 'result-in':
                check_words(folder, step, args.words)
                would.append('accept the result of ' + step + ', then record the yes for it')
            else:
                check_decision(folder, step, decision, args.words, steps, overall)
                would.append('record the ' + decision + ' for ' + step + (': the run ends as refused' if decision == 'no' else ''))
        except FlowError as error:      # closed: a dry run writes nothing; it says that the real call refuses, and why
            would.append('refuse the ' + decision + ': ' + str(error))
    if over or overall in ('refused', 'blocked', 'done'):
        would.append('change nothing more: this run is ' + (over or overall))
    elif overall == 'repair':
        would.append('finish the repair round that started')
    elif not (args.no and not would[-1].startswith('refuse')):
        for step, row in steps.items():
            if row['state'] == 'result-in':
                would.append('accept the result of ' + step)
            elif row['state'] == 'review-failed':
                would.append('start a repair round after the failed review ' + step)
            elif row['state'] == 'ready' and 'run' in graph[step]:
                would.append('run the code step ' + step + ': ' + command_line(graph[step]))
            elif row['state'] == 'ready' and is_worker(info['definition'], graph[step]) and not args.no_workers and launcher() is not None:
                would.append('start the worker of ' + step + ' (' + info['definition']['members'][graph[step]['member']]['runtime'] + ')')
        if len(would) == (1 if (args.yes or args.no) else 0):
            would.append('change nothing: no result waits and no code step is ready')
    print('\nDry run: nothing was changed. A real call would first:')
    for line in would:
        print('  - ' + line)
    return 0


def command_line(body):
    return ' '.join(body['run'])


def report(folder, steps, overall, out=None):
    out = out or sys.stdout
    info = opened(folder)[0]
    data, workspace = info['definition'], info['workspace']
    graph = data['graph']
    resume = 'python3 work/flow.py run --resume ' + info['run']
    out.write('Run: ' + info['run'] + '\nFlow: ' + info['flow'] + ' (' + data['kind'] + ')\n')
    out.write('State: ' + overall + '\nFolder: ' + str(folder) + '\n')
    out.write('Workspace: ' + (workspace or 'none (a shared run)') + '\n')
    if info['task'] is not None:
        out.write('Task: ' + info['task'] + '\n')
    if data['lead'] is not None:
        out.write('Lead: ' + data['lead'] + '\n')
    out.write('Definition: ' + info['definition_path'] + ' (' + info['definition_source'] + ')\n')
    for path in info['overrides']:
        out.write('Local definition overrides shared: ' + path + '\n')
    # The run works from its frozen copy only. The file on disk is looked at here to say so, and for nothing else.
    source = Path(info['definition_path'])
    try:
        if not source.is_file():
            out.write('The definition file is gone. This run uses its frozen copy.\n')
        elif hashlib.sha256(source.read_bytes()).hexdigest() != info['definition_sha256']:
            out.write('The definition file changed after the start. This run uses its frozen copy.\n')
    except OSError:     # closed: the run never reads this file; the readout says that it can not be read
        out.write('The definition file can not be read now. This run uses its frozen copy.\n')
    out.write('\n')
    width = max(len(step) for step in graph) + 2
    for step, body in graph.items():
        row = steps[step]
        who = body['member'] if 'member' in body else 'code'
        out.write(step.ljust(width) + row['state'].ljust(15) + who + ('  try ' + str(row['attempt']) if row['attempt'] > 1 else '') +
                  ('  (' + row['detail'] + ')' if row['detail'] else '') + '\n')
    live = overall == 'running' or overall.startswith('waits for')
    # A step is offered only in a live run. A refused, blocked, or done run offers nothing.
    for step, body in (graph.items() if live else ()):
        row = steps[step]
        if row['state'] == 'ready' and 'member' in body:
            out.write('\nNEXT  ' + step + '\n')
            out.write('  member  ' + member_word(data, body, workspace) + '\n')
            out.write('  skill   ' + skill_word(body, workspace) + '\n')
            out.write('  input   ' + ', '.join(body['input']) + '\n')
            out.write('  output  ' + body['output'] + '\n')
            out.write('  write   ' + str(folder / body['done_when']['file']) +
                      ('  (first line: verdict: pass, or verdict: fail)' if body['verdict'] else '') + '\n')
            out.write('  return  ' + body['return'] + '\n')
            if is_worker(data, body):
                work = worker_folder(folder, step, row['attempt'])
                if (work / 'end.json').is_file():
                    out.write('  worker  started, and gave no result: read ' + str(work) + '. Run --resume to start it again\n')
                elif launcher() is None:
                    out.write('  worker  not started: no launcher at ' + str(paths.system_home() / 'skills/orchestrate/bin/orchestrate') +
                              '. Do the step by hand\n')
                else:
                    out.write('  worker  starts at the next run --resume\n')
        elif row['state'] == 'waits-for-yes':
            out.write('\nWAITS FOR ' + person_name().upper() + '  ' + step + ' (' + body['gate'] + ' gate)\n')
            if 'run' in body:
                out.write('  to run  ' + command_line(body) + '\n')
            else:
                out.write('  read    ' + str(folder / body['done_when']['file']) + '\n')
            out.write('  yes     ' + resume + ' --yes ' + step + ' --words "<the exact words>"\n')
            out.write('  no      ' + resume + ' --no ' + step + ' --words "<the exact words>"\n')
    if data['rules']:
        out.write('\nRules:\n' + ''.join('  - ' + rule + '\n' for rule in data['rules']))
    if overall == 'refused':
        out.write('\nThis run is over: ' + person_name() + ' said no. Nothing more is accepted, offered, or run in it.\n'
                  'Only a new run starts work again: python3 work/flow.py run ' + info['flow'] + '\n')
    elif overall == 'blocked':
        out.write('\nThis run is blocked. Nothing more is accepted, offered, or run in it until the cause above is gone.\n')
    elif overall != 'done':
        out.write('\nThen run: ' + resume + '\n')


def start(args):
    chosen, overridden, workspace = resolve(args.flow, args.workspace)     # None = a shared run, in no workspace
    file, name, data = Path(chosen['real']), chosen['flow'], chosen['normal']
    inputs = {}
    for item in args.input or []:       # closed: no --input given is no input; a required one is then named as missing
        key, mark, value = item.partition('=')
        if not mark or key not in data['inputs'] or key in inputs:
            raise FlowError('--input needs key=value with a key from inputs, one time each: ' + item)
        inputs[key] = value
    missing = [key for key, spec in data['inputs'].items() if spec['required'] and key not in inputs]
    if missing:
        raise FlowError('missing --input: ' + ', '.join(key + '=' for key in missing))
    task = args.task
    if task is not None:
        if not TYPES['token'][2](task):
            raise FlowError('--task needs one task id, such as T12: ' + task)
        tracker_of({'task': task, 'workspace': workspace})     # the task is there before a run starts, or nothing starts
    if args.dry_run:
        print('Valid: ' + str(file) + ' (' + where_from(chosen) + ')')
        print('Workspace: ' + (workspace or 'none (a shared run)'))
        if data['lead'] is not None:
            print('Lead: ' + data['lead'])
        if task is not None:
            print('Task: ' + task + ' (each worker step and code step is a run on it)')
        for entry in overridden:
            print('Local definition overrides shared: ' + entry['file'])
        for step, body in data['graph'].items():
            print('  ' + step + ': ' + (body['member'] if 'member' in body else 'code') +
                  (' (worker: ' + data['members'][body['member']]['runtime'] + ')' if is_worker(data, body) else '') +
                  '; needs ' + (', '.join(body['needs']) or 'nothing') +
                  ('; skill ' + skill_word(body, workspace) if 'member' in body else '') +
                  ('; ' + body['gate'] + ' gate' if body['gate'] is not None else ''))
        print('Dry run: no run folder was made.')
        return 0
    day = datetime.now().astimezone().strftime('%Y-%m-%d')
    home = runs_home(workspace)
    home.mkdir(parents=True, exist_ok=True)
    others = [other for other in run_homes() if other != home]
    run, number = day + '-' + name, 1
    while True:
        folder = home / run
        try:
            if any(there(other / run) for other in others):
                raise FileExistsError(run)      # a run name is one name in every runs folder
            folder.mkdir()          # only one caller can make this folder
            break
        except FileExistsError:
            number += 1
            run = day + '-' + name + '-' + str(number)
        except OSError as error:
            raise Busy('the runs folder can not be written: ' + str(error) + '. Nothing was changed')
    kept(folder).mkdir()
    with Lock(folder, 'run'):
        # The run keeps the text it resolved: the full path, its sha256, where it came from, and what it overrides.
        info = {'run': run, 'flow': name, 'workspace': workspace, 'task': task, 'inputs': inputs, 'started_at': clock(),
                'definition_path': str(file), 'definition_sha256': chosen['sha256'], 'definition_source': where_from(chosen),
                'overrides': [entry['file'] for entry in overridden], 'definition': chosen['data']}
        (kept(folder) / 'run.yaml').write_text(json.dumps(info, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        note(folder, 'run-start', None, flow=name, frozen_sha256=frozen_hash(info))
        steps, overall = drive(folder, not args.no_workers)
    report(folder, steps, overall)
    return 1 if overall in ('blocked', 'refused') else 0


def resume(args):
    folder = run_path(args.resume)
    if args.dry_run:
        return preview(folder, args)
    over = is_over(folder)
    if over:
        # A run that reached its end is not touched again: no lock, no event, no file, no step.
        if args.yes or args.no:
            raise FlowError('this run is ' + over + '. No decision is recorded. Only a new run starts work again')
        steps, overall = stand(folder)
        report(folder, steps, overall)
        print('\nNothing was changed: this run is ' + over + '.')
        return 1 if over == 'refused' else 0
    # The lock is the first write. It is held until the last event of this call is on disk.
    with Lock(folder, 'run --resume'):
        if args.yes or args.no:
            decide(folder, args.yes or args.no, 'yes' if args.yes else 'no', args.words)
        steps, overall = drive(folder, not args.no_workers)
    report(folder, steps, overall)
    return 1 if overall in ('blocked', 'refused') else 0


def status(args):
    if args.run:
        folder = run_path(args.run)
        steps, overall = stand(folder)
        if args.json:
            shown = {step: {key: row[key] for key in ('state', 'detail', 'attempt')} for step, row in steps.items()}
            print(json.dumps({'run': args.run, 'state': overall, 'steps': shown}, indent=2, sort_keys=True))
        else:
            report(folder, steps, overall)
        return 1 if overall in ('blocked', 'refused') else 0
    # The same list the resolver of run uses: every place, every workspace. One row for each definition:
    # a real file under one name, with every place that reaches it and every place a run takes it from.
    found = inventory()
    groups, order_of = {}, []
    for entry in found['entries']:
        key = (entry['real'] or entry['file'], entry['flow'])
        if key not in groups:
            groups[key] = []
            order_of.append(key)
        groups[key].append(entry)
    contexts = [None] + found['workspaces']
    flows = []
    for key in order_of:
        places = groups[key]
        # The first place is the one where the real file is; else the first in the order of the resolver.
        entry = next((e for e in places if e['real'] is not None and os.path.normpath(e['file']) == e['real']), places[0])
        graph = entry['normal']['graph'] if entry['valid'] else {}
        agent_steps = [body for body in graph.values() if 'member' in body]
        bound = [body for body in agent_steps if body['skill'] is not None]
        built = [body for body in bound if skill_built(body['skill'], entry['workspace'])]
        row = {key_: entry[key_] for key_ in ('flow', 'kind', 'file', 'real', 'level', 'source', 'workspace', 'sha256', 'valid')}
        row.update(problems=list(entry['problems']), steps=len(graph), skills_bound=len(bound), skills_built=len(built),
                   agent_steps=len(agent_steps), gates=sorted({body['gate'] for body in graph.values() if body['gate'] is not None}),
                   places=[{'source': e['source'], 'workspace': e['workspace'], 'file': e['file']} for e in places])
        # Where a run by this name takes this file: as a shared run, and in which workspaces. Each refusal is kept, with its place.
        runs_in, refused, notes, lost_in = [], {}, [], []
        for context in contexts:
            try:
                chosen, overridden, _ = resolve(entry['flow'], context, found)
            except FlowError as error:      # closed: the refusal is kept and shown; the row is not taken in that place
                if any(near(e, context) for e in places):
                    refused[context or 'shared'] = ' '.join(str(error).split())
                continue    # this place can not run it; the next place is asked
            if context is not None and any(e['real'] == entry['real'] for e in overridden):
                lost_in.append(context)
            if chosen['real'] == entry['real'] and chosen['flow'] == entry['flow']:
                runs_in.append(context or 'shared')
                if overridden:
                    label = 'local definition overrides shared: ' if chosen['level'] == 'workspace' else 'shelf definition overrides product: '
                    notes.append(label + ', '.join(e['file'] for e in overridden))
            elif chosen['sha256'] == entry['sha256'] and context is None and entry['level'] == 'shared':
                notes.append('same text as ' + chosen['file'])
        row.update(runs_in=runs_in, taken=bool(runs_in), refused=refused)
        if entry['valid'] and not runs_in and refused and all(' is not valid for ' in why for why in refused.values()):
            # A valid shape that no place can run: its seat files or its script are nowhere. That is a problem of the definition.
            row['valid'] = False
            row['problems'] = sorted(set(refused.values()))
        if lost_in:
            notes.append('overridden in the workspace ' + ', '.join(lost_in))
        first = next(iter(refused.values()), '')
        row['note'] = '; '.join(dict.fromkeys(notes)) or ('' if row['taken'] else ('REFUSED: ' + first if first else
                                                                                   'not valid' if not row['valid'] else 'not taken'))
        flows.append(row)
    runs, unreadable = [], 0
    entries = []
    for home in run_homes():
        names, error = listing(home)
        if error == 'the folder is missing':
            names = []          # no runs folder yet means no run yet; the first run makes it
        elif error is not None:
            raise FlowError('the runs folder can not be read: ' + str(home) + ': ' + error)
        entries += [(name, home) for name in names]
    for name, home in sorted(entries, reverse=True):
        try:
            path = home / name
            if not path.is_symlink() and (not path.is_dir() or not there(kept(path))):
                continue        # proven: a plain file, or a plain folder with no folder runner in it, is not a run of this program
            folder = run_path(name)
            info, log = opened(folder)
            doubt = distrust(info, log)
            if doubt is not None:
                raise FlowError(doubt)
            runs.append({'run': name, 'flow': info['flow'], 'state': stand(folder, info, log)[1], 'folder': str(folder)})
        except (FlowError, OSError, ValueError) as error:       # closed: the run is listed as not readable, and status ends with 1
            runs.append({'run': name, 'flow': '?', 'state': 'NOT READABLE: ' + ' '.join(str(error).split())[:160], 'folder': str(path)})
            unreadable += 1
    stuck = [place for place in found['places'] if place['error'] is not None]
    fine = not stuck and not unreadable and all(row['valid'] for row in flows)
    if args.json:
        print(json.dumps({'flows': flows, 'places': found['places'], 'runs': runs, 'workspaces': found['workspaces']},
                         indent=2, sort_keys=True))
        return 0 if fine else 1      # the same exit code as the plain form
    print('Flows: ' + str(len(flows)))
    for row in flows:
        print('  ' + row['flow'] + ' (' + row['kind'] + '): ' + ('valid' if row['valid'] else 'NOT VALID') + '; ' +
              str(row['steps']) + ' steps; skills bound ' + str(row['skills_bound']) + ' of ' + str(row['agent_steps']) +
              ', built ' + str(row['skills_built']) + ('; gates: ' + ', '.join(row['gates']) if row['gates'] else ''))
        print('    ' + row['source'] + (' of ' + row['workspace'] if row['workspace'] else '') + ': ' + row['file'] +
              (', a link to ' + row['real'] if row['real'] is not None and os.path.normpath(row['file']) != row['real'] else '') +
              ('' if row['taken'] else '  (a run does not take this file)'))
        for place in row['places']:
            if place['file'] != row['file']:
                print('    also at: ' + place['source'] + (' of ' + place['workspace'] if place['workspace'] else '') + ': ' + place['file'])
        if row['taken']:
            print('    runs in: ' + ', '.join(row['runs_in']))
        if row['note']:
            print('    ' + row['note'])
        reasons, first = {}, next(iter(row['refused'].values()), '')
        for context, why in row['refused'].items():
            reasons.setdefault(why, []).append(context)
        for why, where in reasons.items():
            if row['taken'] or why != first:
                print('    not in ' + ', '.join(where) + ': ' + why)
        for bad in row['problems']:
            print('    ' + bad)
    if stuck:
        print('Places that can not be read: ' + str(len(stuck)) + '. No flow is taken for a run that reads one of them.')
        for place in stuck:
            print('  ' + place['source'] + (' of ' + place['workspace'] if place['workspace'] else '') + ': ' + place['folder'] +
                  ': ' + place['error'])
    gone = [place for place in found['places'] if place.get('missing')]
    if gone:
        print('Places that are not there: ' + str(len(gone)) + '. Each is read as empty.')
        for place in gone:
            print('  ' + place['source'] + (' of ' + place['workspace'] if place['workspace'] else '') + ': ' + place['folder'])
    print('Runs: ' + str(len(runs)))
    for row in runs[:20]:
        place = str(Path(row['folder']).parent)
        print('  ' + row['run'] + ': ' + row['state'] + ('' if place == str(runs_home()) else '  (in ' + place + ')'))
    return 0 if fine else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    words = parser.add_subparsers(dest='word', required=True)
    go = words.add_parser('run', help='start a flow, or move a run forward')
    go.add_argument('flow', nargs='?', help='the flow name')
    go.add_argument('--resume', metavar='RUN', help='move this run forward')
    go.add_argument('--workspace', help='the workspace the run is for; its team and skills are read first')
    go.add_argument('--input', action='append', metavar='KEY=VALUE', help='one input the flow names')
    go.add_argument('--task', metavar='ID', help='with a new run: the task in the tracker; each worker step and code step is a run on it')
    go.add_argument('--no-workers', action='store_true', help='start no worker; every member step is done by hand')
    go.add_argument('--dry-run', action='store_true', help='change nothing: for a new run, check the flow and show its steps; with --resume, say what a real call would do')
    choice = go.add_mutually_exclusive_group()
    choice.add_argument('--yes', metavar='STEP', help='with --resume: record the yes of the person for this gated step')
    choice.add_argument('--no', metavar='STEP', help='with --resume: record the no of the person for this gated step')
    go.add_argument('--words', help='with --yes or --no: the exact words of the person')
    see = words.add_parser('status', help='where a run stands; with no run: every flow and every run')
    see.add_argument('run', nargs='?')
    see.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.word == 'status':
            return status(args)
        if bool(args.flow) == bool(args.resume):
            raise FlowError('give a flow name to start, or --resume <run> to continue')
        if (args.yes or args.no or args.words) and not args.resume:
            raise FlowError('--yes, --no, and --words go with --resume <run>')
        if args.resume and (args.input or args.workspace or args.task):
            raise FlowError('--input, --workspace, and --task go with a new run, not with --resume')
        return resume(args) if args.resume else start(args)
    except Busy as error:
        print('FAIL flow ' + args.word + ': ' + str(error), file=sys.stderr)
        return 3
    except (FlowError, OSError, ValueError) as error:
        print('FAIL flow ' + args.word + ': ' + str(error), file=sys.stderr)
        return 2
    except Exception as error:      # closed: an error this program did not expect stops it; nothing more is done in this call
        print('FAIL flow ' + args.word + ': internal error, the program stops: ' + type(error).__name__ + ': ' + str(error)[:200],
              file=sys.stderr)
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
