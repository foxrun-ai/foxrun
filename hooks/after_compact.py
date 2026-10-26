#!/usr/bin/env python3
"""Return the seat handoff and live Foxrun start context after compaction."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time


LIMIT = 8000  # one SessionStart result stays below both runtime hook limits


def run(command, payload):
    try:
        return subprocess.run(command, input=payload, text=True, capture_output=True,
                              timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return error


def context(result):
    if isinstance(result, Exception) or result.returncode:
        return None
    try:
        return json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
    except (ValueError, KeyError, TypeError):
        return None


def section(body, title):
    marker = '## ' + title
    offset = body.find(marker)
    if offset < 0:
        return ''
    end = body.find('\n## ', offset + len(marker))
    return body[offset:end if end >= 0 else None].strip()


def clipped(body, room, path):
    if len(body) <= room:
        return body
    marker = f'\n[Cut to fit the hook budget. Read the full file: {path}]'
    if room <= len(marker):
        return marker[:room]
    return body[:room - len(marker)].rstrip() + marker


def session_handoff(portfolio, session):
    """Find the newest handoff for this session across all workspaces."""
    if not isinstance(session, str) or not session:
        return None
    matches = []
    for workspace in portfolio.iterdir() if portfolio.is_dir() else []:
        folder = workspace / 'history/handoffs'
        if not workspace.is_dir() or not folder.is_dir():
            continue
        for path in folder.glob('????-??-??-???-*.md'):
            fields = {}
            try:
                with path.open(encoding='utf-8', errors='replace') as stream:
                    if stream.readline().strip() != '---':
                        continue
                    for line in stream:
                        if line.strip() == '---':
                            break
                        pair = re.match(r'([A-Za-z_][\w-]*):\s*(.*)', line)
                        if pair:
                            fields[pair.group(1)] = pair.group(2).strip().strip("'\"")
            except OSError:
                continue
            if fields.get('session') != session:
                continue
            try:
                stamp = datetime.fromisoformat(fields['timestamp'].replace('Z', '+00:00')).timestamp()
            except (KeyError, ValueError):
                stamp = path.stat().st_mtime
            matches.append((stamp, path.name, path, fields, workspace.name))
    if not matches:
        return None
    matches.sort(reverse=True)
    _, _, newest, _, workspace = matches[0]
    seat = next((fields['seat'] for _, _, _, fields, _ in matches if fields.get('seat')), None)
    if not seat:
        for _, _, _, fields, _ in matches:
            tags = fields.get('tags', '').strip('[]').split(',')
            seat = next((tag.strip() for tag in tags if tag.strip() and tag.strip() != 'precompact'), None)
            if seat:
                break
    if not seat:
        subject = re.sub(r'^\d{4}-\d{2}-\d{2}-\d{3}-', '', newest.stem)
        seat = subject.removesuffix('-precompact') if subject.endswith('-precompact') else subject.split('-')[0]
        if seat == 'precompact':
            seat = None
    return newest, workspace, seat


def default_workspace(home, portfolio):
    """The workspace start picks when none is named: the person's default, then the first workspace."""
    try:
        config = json.loads((home / 'config/person.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        config = {}
    if isinstance(config, dict):
        roster = config.get('workspaces')
        value = config.get('default_workspace') or (
            roster[0] if isinstance(roster, list) and roster else None)
        if isinstance(value, str) and re.fullmatch(r'[a-z0-9-]+', value):
            return value
    names = sorted(p.name for p in portfolio.iterdir()
                   if p.is_dir() and p.name not in ('atlas', 'inbox')
                   and (p / 'AGENTS.md').is_file()) if portfolio.is_dir() else []
    return names[0] if names else 'my-workspace'


def main(runtime):
    home = Path(os.environ.get('FOXRUN_HOME') or Path(__file__).resolve().parent.parent)
    portfolio = Path(os.environ.get('FOXRUN_PORTFOLIO', '~/foxrun')).expanduser()
    raw = sys.stdin.read()
    errors = []
    try:
        hook = json.loads(raw) if raw.strip() else {}
        if not isinstance(hook, dict):
            raise ValueError('hook input is not a JSON object')
    except ValueError as error:
        hook = {}
        errors.append(f'Hook input: {error}')
    cwd = Path(hook.get('cwd') or os.getcwd()).expanduser()
    try:
        workspace = cwd.resolve().relative_to(portfolio.resolve()).parts[0]
    except (ValueError, IndexError):
        workspace = hook.get('workspace') or default_workspace(home, portfolio)
    payload = json.dumps(hook)
    matched = session_handoff(portfolio, hook.get('session_id') or hook.get('thread_id'))
    if matched:
        path, workspace, seat = matched
        handoff_path = str(path)
        handoff_text = path.read_text(encoding='utf-8', errors='replace')
    else:
        boot = home / 'skills/handoff/bin/handoff-boot'
        lookup = run([sys.executable, str(boot), '--json', '--no-nightly', '--cwd', str(cwd),
                      '--vault', str(portfolio)], payload)
        report = {}
        if not isinstance(lookup, Exception):
            try:
                report = json.loads(lookup.stdout)
            except ValueError:
                pass
        printed = run([sys.executable, str(boot), '--no-nightly', '--cwd', str(cwd),
                       '--vault', str(portfolio)], payload)
        handoff_text = context(printed) or ''
        match = re.search(r'(?m)^File 1 of [0-9]+: ([^\n]+)', handoff_text)
        handoff_path = report.get('picked') or (match.group(1) if match else None)
        if handoff_path:
            try:
                workspace = Path(handoff_path).resolve().relative_to(portfolio.resolve()).parts[0]
            except (ValueError, IndexError):
                pass
        else:
            handoff_path = str(portfolio / workspace / 'history/handoffs')
        seat_match = re.search(r'(?m)^seat: ([a-z0-9-]+)\s*$', handoff_text)
        seat = report.get('seat') or (seat_match.group(1) if seat_match else None)
        workspace = report.get('workspace') or workspace
    seat = seat or os.environ.get('FOXRUN_SEAT')
    command = [sys.executable, str(home / 'foxrun.py'), 'start', '--workspace', workspace]
    if seat:
        command += ['--seat', seat]
    command += ['--runtime', runtime, '--hook-json']
    for attempt in range(4):
        started = run(command, payload)
        if (not isinstance(started, Exception) and started.returncode
                and 'another start writes markers' in started.stderr and attempt < 3):
            time.sleep(0.5 * (attempt + 1))
            continue
        break
    if isinstance(started, Exception):
        start_text = ''
        errors.append(f'foxrun.py start failed: {started}')
    elif started.returncode:
        start_text = ''
        errors.append(f'foxrun.py start failed ({started.returncode}): '
                      f'{started.stderr.strip() or started.stdout.strip() or "no error text"}')
    else:
        start_text = context(started) or ''
        if not start_text:
            errors.append('foxrun.py start returned no hook context')
    boot_order = section(handoff_text, 'Boot Order')
    if handoff_text and not boot_order:
        errors.append(f'Boot Order unavailable in {handoff_path}')
    before_state, _, state = start_text.partition('\n---\ntype: state')
    if len(before_state) > 4200 and '## Lessons' in before_state:
        intro, lessons = before_state.split('## Lessons', 1)
        before_state = clipped(intro, 1100, str(home / 'foxrun.py')) + '\n## Lessons' + lessons[:2700]
    next_action = re.search(r'(?ms)^4\. .*?(?=^\d+\. |\Z)', boot_order)
    open_items = section(handoff_text, 'Open Items')
    priority = (f'After compaction: read this handoff and live Lessons before replying.\n'
                f'Handoff path: {handoff_path}\n')
    if next_action:
        priority += '\n## Next action (Boot Order step 4)\n' + next_action.group().strip() + '\n'
    if open_items:
        priority += '\n' + open_items + '\n'
    if not matched and not handoff_text and not seat:
        priority += '\nNo session handoff or seat was found.\n'
    if errors:
        priority += '\n' + '\n'.join('Error: ' + error for error in errors) + '\n'
    order = boot_order.replace('## Boot Order', '', 1).strip() if boot_order else ''
    order = re.sub(r'(?m)^0\. .*\n?', '', order)
    if next_action:
        order = order.replace(next_action.group(), '', 1).strip()
    boot = (f'\n## Boot Order\n0. `python3 ~/.foxrun/foxrun.py start --workspace '
            f'{workspace} --seat {seat or "<seat>"}`\n')
    if order:
        boot += order + '\n'
    if not start_text:
        before_state += '\nLessons unavailable because foxrun.py start failed.\n'
    live = '\n## Live start: rules and Lessons\n' + before_state
    result = priority
    # Keep the next action and every Open Item intact. Clip long supporting sections.
    room = LIMIT - len(result)
    result += clipped(boot, min(room, 2200), handoff_path) if room > 0 else ''
    room = LIMIT - len(result)
    result += clipped(live, room, str(home / 'foxrun.py')) if room > 0 else ''
    room = LIMIT - len(result)
    extra = '\n\n## Seat handoff\n' + handoff_text.replace(boot_order, '[Boot Order printed above]', 1)
    if open_items:
        extra = extra.replace(open_items, '[Open Items printed above]', 1)
    extra += '\n\n## Live state\n' + ('---\ntype: state' + state if state else '')
    result += clipped(extra, room, handoff_path) if room > 0 else ''
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'SessionStart', 'additionalContext': result}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else 'claude'))
    except Exception as error:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
              'additionalContext': f'After-compaction error: {error}. Handoff path: '
                                   f'{Path(os.environ.get("FOXRUN_PORTFOLIO", "~/foxrun")).expanduser()}/<workspace>/history/handoffs'}},
              ensure_ascii=False))
