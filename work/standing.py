"""Standing seats: native argument token at birth, native-id binding on later wakes.

No environment transport through Herdr. No runtime store inspection.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

from base import paths, simple_yaml

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z')
NAME = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
TOKEN = re.compile(r'\bFOXRUN_STANDING=([a-f0-9]{32})\b')


def valid(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('invalid ' + label)
    return value


def safe(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('path leaves its home')
    current = root
    if current.is_symlink():
        raise ValueError('symbolic link in home')
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('symbolic link in standing path')
    return current


def store(relative):
    return safe(paths.system_home(), 'runs/standing/' + relative)


def read(file):
    value = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('standing record must be an object')
    return value


def write(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    os.replace(str(tmp), str(file))


@contextmanager
def locked():
    file = store('binding.lock')
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def event(record, kind, **details):
    file = store('launches/' + record['launch'] + '/trail.jsonl')
    file.parent.mkdir(parents=True, exist_ok=True)
    value = dict(time=datetime.now(timezone.utc).isoformat(), event=kind,
                 native_session_id=record.get('native_session_id'),
                 seat=record['seat'], workspace=record['workspace'],
                 runtime=record['runtime'], route=record.get('route'), **details)
    with file.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')


def identity(seat, runtime):
    valid(seat, NAME, 'seat')
    config = read(safe(paths.system_home(), 'config/standing-seats.json'))
    reference = config.get('seats', {}).get(seat)
    if not isinstance(reference, str) or ':' not in reference:
        raise ValueError('seat needs a current identity reference: ' + seat)
    home, relative = reference.split(':', 1)
    roots = {'system': paths.system_home(), 'portfolio': paths.portfolio()}
    if home not in roots:
        raise ValueError('identity home must be system or portfolio')
    if home == 'system' and relative in ('agents/' + seat + '.md', 'profile/agents/' + seat + '.md'):
        file = paths.resolve_seat(seat)
        if file is None:
            raise ValueError('seat identity is missing: ' + seat)
    else:
        file = safe(roots[home], relative)
    text = file.read_text(encoding='utf-8')
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        raise ValueError('identity needs frontmatter')
    front, body = text[4:].split('\n---\n', 1)
    data = simple_yaml.safe_load(front)
    if not isinstance(data, dict) or data.get('id') != seat:
        raise ValueError('reference is not the seat identity')
    if runtime not in data.get('runtimes', []):
        raise ValueError('identity excludes this runtime')
    if not re.search(r'^#{2,3} Boot reads$', body, re.M):
        raise ValueError('seat identity needs Boot reads')
    if any(old in text for old in ('~/Obsidian', '~/Code', '/Obsidian/', '/Code/')):
        raise ValueError('identity still names old homes; migrate its source first')
    # These are declared home aliases, not copied runtime capes.
    text = text.replace('~/.foxrun/', str(paths.system_home()) + '/')
    text = text.replace('~/foxrun/', str(paths.portfolio()) + '/')
    return file, text


def page(record):
    file, text = identity(record['seat'], record['runtime'])
    workspace = safe(paths.portfolio(), record['workspace'])
    contracts = [safe(paths.system_home(), 'agents/soul.md'),
                 safe(paths.system_home(), 'profile/AGENTS.md')]
    contracts += [safe(workspace, 'AGENTS.md'), safe(workspace, 'RESOLVER.md')]
    if any(not p.is_file() for p in contracts):
        raise ValueError('seat start needs soul and current contracts')
    return ('Seat: ' + record['seat'] + '\nWorkspace: ' + record['workspace'] +
            '\nNative session: ' + str(record.get('native_session_id') or 'pending') +
            '\nIdentity: ' + str(file) + '\n\n' + text.rstrip() +
            '\n\nRead the identity and its Boot reads in order before the first task.\n' +
            'Read contracts in order:\n' + ''.join('  ' + str(p) + '\n' for p in contracts))


def ancestry_launch(runtime, runner=subprocess.run, pid=None):
    """Only inspect our native process ancestors, never files or session stores.

    The controlled first prompt carries a non-secret launch token in argv.
    The native child does not need the launcher's environment.
    """
    pid = os.getppid() if pid is None else pid
    seen = set()
    for _ in range(24):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        try:
            result = runner(['/bin/ps', '-ww', '-p', str(pid), '-o', 'ppid=', '-o', 'command='],
                            capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            # Process inspection is optional for an unbound session. A denied
            # lookup cannot establish a standing identity; keep the ordinary boot.
            return None
        if result.returncode or not result.stdout.strip():
            break
        parent, command = result.stdout.strip().split(None, 1)
        # ps prints raw argv, not shell syntax. Inspect only the executable prefix;
        # quotes and backslashes in prompts must never enter a shell parser.
        words = command.split(None, 2)
        executable = Path(words[0]).name
        interpreter = re.fullmatch(r'(python(?:\d+(?:\.\d+)*)?|sh|bash|zsh)', executable)
        native = executable == runtime or (interpreter and len(words) > 1 and
                                          Path(words[1]).name == runtime)
        if native:
            matches = set(TOKEN.findall(command))
            if len(matches) > 1:
                raise ValueError('ambiguous standing launch tokens')
            # The nearest native process owns this hook. An ordinary child must
            # not inherit a standing parent's token through an older ancestor.
            return next(iter(matches), None)
        pid = int(parent)
    return None


def binding(runtime, session, workspace=None, cwd=None, launch=None):
    valid(runtime, re.compile(r'(claude|codex)\Z'), 'runtime')
    valid(session, ID, 'native session id')
    key = 'sessions/' + runtime + '/' + session + '.json'
    with locked():
        file = store(key)
        record = read(file) if file.is_file() else None
        if record is None:
            launch = launch or ancestry_launch(runtime)
            if launch is None:
                return None
            valid(launch, re.compile(r'[a-f0-9]{32}\Z'), 'launch token')
            launch_file = store('launches/' + launch + '/record.json')
            record = read(launch_file)
            if record.get('state') not in ('pending', 'bound', 'spawned'):
                raise ValueError('standing launch is not active')
            if record.get('native_session_id') not in (None, session):
                raise ValueError('launch already belongs to another native session')
        if record['runtime'] != runtime or record.get('launch') is None:
            raise ValueError('standing runtime mismatch')
        if workspace and workspace != record['workspace']:
            raise ValueError('standing workspace mismatch')
        if cwd:
            folder = safe(paths.portfolio(), record['workspace']).resolve()
            current = Path(cwd).expanduser().resolve()
            if current != folder and folder not in current.parents:
                raise ValueError('native hook cwd is outside the standing workspace')
        if not file.is_file():
            record.update(native_session_id=session, state='bound')
            write(file, record)
            write(store('launches/' + record['launch'] + '/record.json'), record)
            event(record, 'bound')
        return record


def start(workspace=None, runtime=None, session=None, hook=None):
    hook = hook or {}
    session = session or hook.get('session_id') or hook.get('thread_id')
    if not session:
        if runtime:
            raise ValueError('native hook needs a session id')
        return None
    if not runtime:
        raise ValueError('native session needs a runtime')
    record = binding(runtime, session, workspace, hook.get('cwd'))
    if record is None:
        return None  # Unmanaged sessions retain the ordinary start page.
    text = page(record)
    with locked():
        event(record, 'start', source=hook.get('source') or 'manual', start_output=text)
    return text


def standing(args, runner=subprocess.run):
    valid(args.name, NAME, 'session name')
    valid(args.seat, NAME, 'seat')
    if not args.conversation or not re.fullmatch(r'[a-z]+:[^\s]+', args.conversation):
        raise ValueError('standing needs a stable conversation id')
    workspace = safe(paths.portfolio(), args.workspace)
    if not workspace.is_dir():
        raise ValueError('unknown workspace')
    launch = uuid.uuid4().hex
    record = dict(launch=launch, seat=args.seat, workspace=args.workspace,
                  runtime=args.runtime, name=args.name, conversation=args.conversation,
                  native_session_id=None, state='pending', route=None)
    # Validate the current identity and required paths before any spawn.
    page(record)
    prompt = ('FOXRUN_STANDING=' + launch + '\n'
              'Use the standing seat context from the native start hook.\n'
              'If the hook provides no Seat and Identity, stop and report a failed seat start.\n'
              'Read that identity and its Boot reads before work. Await the next task.')
    resolver = Path.home() / '.agents/skills/orchestrate/bin/orchestrate'
    resolved = runner([str(resolver), 'resolve', '--from', args.caller, '--to', args.runtime,
                       '--want', 'converse', '--hosted', '--cwd', str(workspace),
                       '--conversation', args.conversation, '--task', prompt],
                      capture_output=True, text=True, timeout=30)
    if resolved.returncode:
        raise ValueError('orchestrate resolver failed')
    route = json.loads(resolved.stdout)
    command = shlex.split(route.get('command', ''))
    herdr = Path.home() / '.agents/skills/herdr/bin/herdr'
    if (route.get('mode') != 'herdr' or route.get('to') != args.runtime or
            command[:2] != ['~/.agents/skills/herdr/bin/herdr', 'spawn'] or
            '--durable' not in command or '--' not in command):
        raise ValueError('resolver did not return the durable Herdr route')
    command[0] = str(herdr)
    index = command.index('--')
    command[index:index] = ['--role', args.name, '--topic', args.name]
    record['route'] = route
    record['command'] = command
    namefile = store('names/' + args.runtime + '/' + args.name + '.json')
    with locked():
        if namefile.exists():
            raise ValueError('standing name exists; inspect its trail and resume the native id')
        write(namefile, {'launch': launch})
        write(store('launches/' + launch + '/record.json'), record)
        event(record, 'spawn-request')
    try:
        result = runner(command, capture_output=True, text=True, timeout=180)
        with locked():
            event(record, 'spawn-output', returncode=result.returncode,
                  stdout=result.stdout, stderr=result.stderr)
        payload = json.loads(result.stdout)
        if result.returncode or payload.get('status') != 'spawned':
            raise ValueError('Herdr did not spawn; inspect the saved output')
        session = valid(payload.get('session_id'), ID, 'returned native session id')
        # Native hooks run before Herdr returns. Never invent a successful first start.
        saved = store('sessions/' + args.runtime + '/' + session + '.json')
        with locked():
            if not saved.is_file():
                raise ValueError('native start hook did not bind the seat; inspect the existing session')
            bound = read(saved)
            if bound.get('launch') != launch:
                raise ValueError('Herdr native id disagrees with the start hook')
            trail = store('launches/' + launch + '/trail.jsonl')
            if not any(json.loads(line).get('event') == 'start' for line in trail.read_text().splitlines()):
                raise ValueError('native start hook did not produce seat context')
            bound.update(state='spawned', spawn_output=payload)
            write(saved, bound)
            write(store('launches/' + launch + '/record.json'), bound)
            event(bound, 'spawned', spawn_output=payload)
        print(json.dumps(dict(status='spawned', seat=args.seat, workspace=args.workspace,
                              name=args.name, native_session_id=session, trail=str(trail))))
        return 0
    except Exception as error:
        with locked():
            event(record, 'failed', reason=str(error))
            failed = read(store('launches/' + launch + '/record.json'))
            failed['state'] = 'failed'
            write(store('launches/' + launch + '/record.json'), failed)
        # Keep evidence and the reserved name. Never close or retry automatically.
        raise
