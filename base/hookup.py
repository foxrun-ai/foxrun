"""Connect the Foxrun session hooks to Claude Code and Codex settings.

`install.py --hookup` and `foxrun.py hookup` share this one merge. It keeps every
other entry in the settings file and adds only the Foxrun entries that are missing.
It removes one entry: the exact start-rules group that older installs wrote.
Before it changes a file, it copies that file to <home>/backups/hookup-<time>-<id>/.
A second run finds every entry in place and writes nothing.

The hooks follow g-hook-verdicts-2026-10-21: session-start, after-compact,
before-compact, and session-end. start-rules is for Hermes only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import uuid

RUNTIMES = ('claude', 'codex')
SCRIPTS = ('session-start', 'after-compact', 'before-compact')


def write_text(path, text):
    """Write generated UTF-8 text with LF newlines, including on Python 3.9."""
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def settings_name(runtime):
    return 'settings.json' if runtime == 'claude' else 'hooks.json'


def hook_entries(home, runtime):
    def command(name):
        path = home / 'hooks' / runtime / name
        if not path.is_file():
            # A fixture has no worker B hooks. Each fixture command still invokes its launcher.
            if name == 'before-compact':
                return shlex.join([sys.executable, str(home / 'memory/handoff_check.py'), '--help'])
            return shlex.join([sys.executable, str(home / 'foxrun.py'), 'start'])
        return 'FOXRUN_HOME=' + shlex.quote(str(home)) + ' sh ' + shlex.quote(str(path))
    entries = {'SessionStart': [
        {'matcher': 'startup|resume', 'hooks': [{'type': 'command', 'command': command('session-start')}]},
        {'matcher': 'compact', 'hooks': [{'type': 'command', 'command': command('after-compact')}]}
    ], 'PreCompact': [{'hooks': [{'type': 'command', 'command': command('before-compact')}]}]}
    # No start-rules here: Claude and Codex load the soul and rules from their contracts
    # (g-hook-verdicts-2026-10-21). Hermes keeps it in hermes_entries.
    # session-start logs the session as a run; this closes that run. The script always exits 0.
    end = home / 'hooks' / runtime / (runtime + '_session_end.sh')
    if end.is_file():
        entries['SessionEnd'] = [{'hooks': [{'type': 'command', 'timeout': 3, 'command':
            'FOXRUN_HOME=' + shlex.quote(str(home)) + ' python3 ' + shlex.quote(str(end))}]}]
    return entries


def hook_script(home, group):
    """The Foxrun hook script a group runs, or None for a fixture command."""
    for handler in group.get('hooks', []):
        try:
            words = shlex.split(str(handler.get('command', '')))
        except ValueError:
            continue
        for word in words:
            if word.startswith(str(home / 'hooks') + '/'):
                return word
    return None


def merge(data, home, runtime):
    """Add the missing Foxrun entries to one settings object. Return what was added.
    An entry counts as present when an existing command of the same event runs its script,
    as setup's status check reads it. Nothing else in the object changes."""
    if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
        raise ValueError('runtime settings must contain a JSON object with hooks')
    hooks = data.setdefault('hooks', {})
    added = []
    for event, groups in hook_entries(home, runtime).items():
        previous = hooks.setdefault(event, [])
        if not isinstance(previous, list):
            raise ValueError('runtime hook event must contain a list: ' + event)
        commands = [str(handler.get('command', '')) for group in previous if isinstance(group, dict)
                    for handler in group.get('hooks', []) if isinstance(handler, dict)]
        for group in groups:
            script = hook_script(home, group)
            if group in previous or (script and any(script in command for command in commands)):
                continue
            previous.append(group)
            added.append({'event': event, 'script': script or group['hooks'][0]['command']})
    return added


def old_start_rules(home):
    """The SessionStart group install wrote for Claude and Codex before g-hook-verdicts-2026-10-21.
    These are the exact bytes of the old hook_entries, so only Foxrun's own entry ever matches."""
    rules = Path(home) / 'hooks/start-rules.py'
    return {'hooks': [{'type': 'command', 'command': 'python3 ' + shlex.quote(str(rules)) + ' ' + str(part), 'timeout': 5}
                      for part in range(1, 5)]}


def drop_old(data, home):
    """Remove the old start-rules group from one settings object. Return what was removed.
    A group that differs in any way, such as a changed timeout or an extra handler, is the person's and stays."""
    groups = data.get('hooks', {}).get('SessionStart')
    old = old_start_rules(home)
    if not isinstance(groups, list) or old not in groups:
        return []
    data['hooks']['SessionStart'] = [group for group in groups if group != old]
    return [{'event': 'SessionStart', 'script': str(Path(home) / 'hooks/start-rules.py')}]


def codex_event_key(event):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', event).lower()


def codex_hook_hash(event, matcher, handler):
    """The hash Codex stores as trusted_hash: sha256 of the sorted, compact JSON of the
    normalized hook (event, matcher, one handler with its default timeout filled in)."""
    key = codex_event_key(event)
    short = key in ('session_end', 'interrupt')
    timeout = max(1, int(handler.get('timeout', 1 if short else 600)))
    normal = {'type': 'command', 'command': handler['command'],
              'timeout': min(timeout, 3) if short else timeout,
              'async': bool(handler.get('async', False))}
    if handler.get('statusMessage') is not None:
        normal['statusMessage'] = handler['statusMessage']
    identity = {'event_name': key, 'hooks': [normal]}
    if matcher is not None:
        identity['matcher'] = matcher
    text = json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return 'sha256:' + hashlib.sha256(text.encode()).hexdigest()


def codex_trust_plan(settings, home, data=None):
    """The config.toml text that trusts every Foxrun hook in hooks.json, and its rows.
    A Foxrun hook is a handler whose command equals one that hook_entries(home, 'codex') makes for
    the same event. A hook that only names the home is not Foxrun's, so it is never trusted here.
    Other hooks and their rows stay as they are. A stale row for a Foxrun hook gets the new hash."""
    rows = {}
    if data is None:
        data = json.loads(settings.read_text(encoding="utf-8"))
    ours = {(event, handler['command']) for event, groups in hook_entries(Path(home), 'codex').items()
            for group in groups for handler in group['hooks']}
    for event, groups in data.get('hooks', {}).items():
        for i, group in enumerate(groups):
            for j, handler in enumerate(group.get('hooks', []) if isinstance(group, dict) else []):
                if (isinstance(handler, dict) and handler.get('type') == 'command'
                        and (event, handler.get('command')) in ours
                        and set(handler) <= {'type', 'command', 'timeout', 'async', 'statusMessage'}):
                    key = '%s:%s:%d:%d' % (settings, codex_event_key(event), i, j)
                    rows[key] = codex_hook_hash(event, group.get('matcher'), handler)
    config = settings.parent / 'config.toml'
    if config.is_symlink():
        raise ValueError('Codex config.toml must not be a symlink')
    lines = config.read_text(encoding="utf-8").splitlines() if config.exists() else []
    for key, value in rows.items():
        header, row = '[hooks.state.' + json.dumps(key) + ']', 'trusted_hash = ' + json.dumps(value)
        start = next((n for n, line in enumerate(lines) if line.strip() == header), None)
        if start is None:
            lines += ['', header, row]
            continue
        end = next((n for n in range(start + 1, len(lines)) if lines[n].lstrip().startswith('[')), len(lines))
        found = next((n for n in range(start + 1, end) if re.match(r'\s*trusted_hash\s*=', lines[n])), None)
        if found is None:
            lines.insert(start + 1, row)
        else:
            lines[found] = row
    text = '\n'.join(lines).lstrip('\n') + '\n'
    try:
        import tomllib
    except ImportError:
        tomllib = None
    if tomllib:
        try:
            state = tomllib.loads(text).get('hooks', {}).get('state', {})
        except tomllib.TOMLDecodeError as error:
            raise ValueError('Codex config.toml would not parse after trust rows: ' + str(error))
        if any(state.get(key, {}).get('trusted_hash') != value for key, value in rows.items()):
            raise ValueError('Codex config.toml trust rows did not read back')
    return config, text, rows


def codex_trust(settings, home):
    """Trust every Foxrun hook in hooks.json, so Codex runs it with no prompt."""
    config, text, rows = codex_trust_plan(settings, home)
    if not config.exists():
        config.touch(mode=0o600)
    write_text(config, text)
    return rows


def replace_text(path, text, mode=None):
    """Write the new text beside the file, then move it into place, so a crash leaves the old file."""
    # The merged file keeps the original's mode. The temporary copy starts private, so no other user reads it.
    final = mode if mode is not None else (path.stat().st_mode & 0o777 if path.exists() else 0o644)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    private_file(temporary, text.encode('utf-8'), 0o600)
    os.chmod(str(temporary), final)
    os.replace(str(temporary), str(path))


def private_folder(path):
    """Make one new folder that only the person can open."""
    path.mkdir(mode=0o700)
    os.chmod(str(path), 0o700)


def private_file(path, raw, mode=0o600):
    """Write a new file that only the person can read; refuse to replace one that exists."""
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
    os.chmod(str(path), mode)


def backup_files(home, files):
    """Copy each existing file into one new private backup folder; return the folder.
    files maps a name inside the backup (such as claude/settings.json) to (source path, its bytes).
    Settings files can hold tokens: folders are 0o700, and each copy is 0o600 or the original's
    mode when it is stricter. A copy is read back before any settings file changes. Contents are never printed."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = home / 'backups' / ('hookup-' + stamp + '-' + uuid.uuid4().hex[:8])
    backup.parent.mkdir(parents=True, exist_ok=True)
    private_folder(backup)
    sources = {}
    for name, (path, raw) in files.items():
        copy = backup / name
        # Path.parents takes no slice before Python 3.10.
        for folder in reversed(list(copy.relative_to(backup).parents)[:-1]):
            if not (backup / folder).is_dir():
                private_folder(backup / folder)
        private_file(copy, raw, path.stat().st_mode & 0o600)
        if copy.read_bytes() != raw:
            raise ValueError('backup did not read back: ' + str(copy))
        sources[name] = str(path)
    private_file(backup / 'sources.json', (json.dumps(sources, indent=2, sort_keys=True) + '\n').encode('utf-8'))
    return backup


def connect(home, paths):
    """Merge the Foxrun hooks into each runtime's settings file. paths maps runtime to its settings file.
    Every file is read and planned before any write. Each changed file that existed is copied
    to the backup first, and the copy is checked. Return one report row for each runtime."""
    home = Path(home)
    plans, report = [], []
    for runtime, settings in paths.items():
        settings = Path(settings)
        if settings.is_symlink():
            raise ValueError('runtime settings must not be a symlink: ' + str(settings))
        if settings.exists() and not settings.is_file():
            raise ValueError('runtime settings must be a file: ' + str(settings))
        raw = settings.read_bytes() if settings.exists() else None
        try:
            data = json.loads(raw.decode('utf-8')) if raw is not None and raw.strip() else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError('runtime settings are not valid JSON: ' + str(settings) + ': ' + str(error))
        # merge checks the shape of the settings first; then the old group can go.
        added = merge(data, home, runtime)
        removed = drop_old(data, home)
        if added or removed:
            plans.append((runtime, settings, raw, json.dumps(data, indent=2) + '\n', None))
        row = {'runtime': runtime, 'settings': str(settings), 'added': added, 'removed': removed}
        if runtime == 'codex':
            config, text, _ = codex_trust_plan(settings, home, data)
            old = config.read_bytes() if config.exists() else None
            if old is None or old.decode('utf-8') != text:
                plans.append((runtime, config, old, text, 0o600 if old is None else None))
            row['trust'] = str(config)
        report.append(row)
    backup = None
    kept = [(runtime, path, raw) for runtime, path, raw, _, _ in plans if raw is not None]
    if kept:
        backup = backup_files(home, {runtime + '/' + path.name: (path, raw) for runtime, path, raw in kept})
    for _, path, _, text, mode in plans:
        path.parent.mkdir(parents=True, exist_ok=True)
        replace_text(path, text, mode)
    for row in report:
        row['written'] = [str(path) for runtime, path, _, _, _ in plans if runtime == row['runtime']]
        row['backup'] = str(backup) if backup and any(runtime == row['runtime'] for runtime, _, _ in kept) else None
    return report


def runtime_settings(runtime, runtime_home=None, both=False):
    """The settings file of one runtime. A runtime home wins; then CLAUDE_CONFIG_DIR or CODEX_HOME,
    as setup reads them; then ~/.claude or ~/.codex."""
    if runtime_home:
        folder = Path(runtime_home).expanduser()
        if both:
            folder /= runtime
    else:
        base = os.environ.get('CLAUDE_CONFIG_DIR' if runtime == 'claude' else 'CODEX_HOME')
        folder = Path(base).expanduser() if base else Path.home() / ('.' + runtime)
    return folder / settings_name(runtime)


def hookup_existing(home, runtime, runtime_home=None):
    """`foxrun.py hookup`: connect the hooks of an existing install. Refuse before any write
    when the home is not an install or its hook scripts are missing."""
    home = Path(home).expanduser().resolve()
    if not (home / 'config/person.json').is_file():
        raise ValueError('no Foxrun install at ' + str(home) + ' (config/person.json is missing)')
    chosen = RUNTIMES if runtime == 'both' else (runtime,)
    missing = [str(home / 'hooks' / name / script) for name in chosen for script in SCRIPTS
               if not (home / 'hooks' / name / script).is_file()]
    if missing:
        raise ValueError('hook scripts are missing; update the install first: ' + ', '.join(missing))
    paths = {name: runtime_settings(name, runtime_home, runtime == 'both') for name in chosen}
    for name, settings in paths.items():
        folder = settings.parent.resolve()
        if folder == home or home in folder.parents:
            raise ValueError('runtime settings must not be inside the Foxrun home: ' + str(settings))
    return connect(home, paths)


def hermes_entries(home):
    """Hermes shell hooks: the start check and start page on the first turn, the handoff before a compression."""
    def command(*words):
        return shlex.join(['/usr/bin/env', 'PATH=/opt/homebrew/bin:/usr/bin:/bin', *words])
    hooks = home / 'hooks'
    return [('pre_llm_call', command('python3', str(hooks / 'start-rules.py')), 10),
            ('pre_llm_call', command('/bin/sh', str(hooks / 'hermes/session-start')), 30),
            ('pre_auxiliary_call', command('/bin/sh', str(hooks / 'hermes/before-compact')), 60)]


def hermes_hookup(home):
    """Wire the Foxrun hooks into ~/.hermes/config.yaml and each profile's config.yaml, and record
    Hermes consent for them. No Hermes, nothing written. Running gateways load them on their next start.
    Every file is planned before any write. Each changed file that existed is first copied to one
    private backup under <home>/backups/, as connect does for Claude and Codex."""
    hermes = Path.home() / '.hermes'
    home = Path(home)
    written, plans = [], []
    for config in [hermes / 'config.yaml', *sorted(hermes.glob('profiles/*/config.yaml'))]:
        if not config.is_file() or config.is_symlink():
            continue
        text = config.read_text(encoding="utf-8")
        lines = text.splitlines()
        start = next((i for i, line in enumerate(lines) if re.fullmatch(r'hooks:\s*(\{\}|null|~)?\s*', line)), None)
        if start is None:
            lines.append('hooks:')
            start = len(lines) - 1
        lines[start] = 'hooks:'
        end = next((i for i in range(start + 1, len(lines)) if lines[i][:1] not in ('', ' ', '#')), len(lines))
        body = [line for line in lines[start + 1:end] if line.strip() and not line.lstrip().startswith('#')]
        pad = ' ' * (len(body[0]) - len(body[0].lstrip())) if body else '  '
        events = {line.strip()[:-1] for line in body if re.fullmatch(pad + r'\w+:', line)}
        added, block = [], []
        for event, command, timeout in hermes_entries(home):
            if command in text:
                continue
            if event in events:
                print('Hermes ' + event + ' already has hooks in ' + str(config) + '; add by hand: ' + command)
                continue
            if not any(event == e for e, _ in added):
                block.append(pad + event + ':')
            value = json.dumps(command) if ': ' in command or ' #' in command else command
            block += [pad + '  - command: ' + value, pad + '    timeout: ' + str(timeout)]
            added.append((event, command))
        if not added:
            continue
        lines[end:end] = block
        allowlist = config.parent / 'shell-hooks-allowlist.json'
        data = json.loads(allowlist.read_text(encoding="utf-8")) if allowlist.is_file() else {}
        approvals = [row for row in data.get('approvals', []) if (row.get('event'), row.get('command')) not in added]
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        for event, command in added:
            words = shlex.split(command)
            script = next((w for w in words if w.endswith('.py')), None) or next(w for w in words if '/' in w)
            mtime = datetime.fromtimestamp(os.path.getmtime(script), timezone.utc).isoformat().replace('+00:00', 'Z') if os.path.exists(script) else None
            approvals.append({'approved_at': now, 'command': command, 'event': event, 'script_mtime_at_approval': mtime})
        data['approvals'] = approvals
        plans.append((config, '\n'.join(lines) + '\n', allowlist, json.dumps(data, indent=2, sort_keys=True) + '\n'))
    kept = {}
    for config, _, allowlist, _ in plans:
        for path in (config, allowlist):
            if path.is_file():
                kept['hermes/' + path.relative_to(hermes).as_posix()] = (path, path.read_bytes())
    if kept:
        backup_files(home, kept)
    for config, text, allowlist, approvals in plans:
        write_text(config, text)
        write_text(allowlist, approvals)
        allowlist.chmod(0o600)
        written.append(config)
    return written
