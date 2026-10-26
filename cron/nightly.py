#!/usr/bin/env python3
"""Run lint for the Keeper, the installed dream and check commands, the workspaces view, and the state push."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Secret values the state push refuses to send. Same families as base/distribution/privacy.py 'key'
# and base/lint_gate.py SECRET_PATTERNS, widened for the tokens state/ rows could carry.
STATE_SECRETS = (
    ('stripe-key', re.compile(r'\b[sr]k_live_[A-Za-z0-9]{10,}')),
    ('model-key', re.compile(r'\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}')),
    ('tailscale-key', re.compile(r'\btskey-[A-Za-z0-9-]{10,}')),
    ('telegram-bot-token', re.compile(r'\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b')),
    ('google-client-secret', re.compile(r'\bGOCSPX-[A-Za-z0-9_-]{10,}')),
    ('github-token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})')),
    ('slack-token', re.compile(r'\b(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}')),
    ('aws-key', re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('url-userinfo', re.compile(r'\b[a-z][a-z0-9+.-]*://[^/\s:@"\']+:[^/\s@"\']+@', re.I)),
    ('private-key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
)


def run_lint(root, portfolio, runner=subprocess.run):
    """Run the Keeper lint. Return (failed, findings): findings are reported, never a failure (T293).
    The step fails only when lint did not complete its scan: an invalid report or an exit other than 0 or 1."""
    script = root / 'base/lint.py'
    if not script.is_file() or script.is_symlink():
        raise ValueError('missing installed command: ' + str(script))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    parent = root / 'runs' / 'nightly'
    if parent.parent.is_symlink() or parent.is_symlink():
        raise ValueError('lint reports cannot use a linked runs folder')
    parent.mkdir(parents=True, exist_ok=True)
    report = parent / (stamp + '-lint')
    report.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    completed = runner([sys.executable, '-B', str(script), '--home', str(root),
                        '--workspaces', str(portfolio), '--json'],
                       cwd=str(root), env=environment, capture_output=True, text=True)
    try:
        findings = json.loads(completed.stdout)
        if not isinstance(findings, list) or any(not isinstance(row, dict) for row in findings):
            raise ValueError('invalid finding list')
    except (ValueError, TypeError):
        findings = [{'rule_id': 'CONFIG', 'level': 'error', 'path': str(script),
                     'line': 0, 'what': 'Lint returned an invalid report.',
                     'how_to_fix': 'Repair the command before the next nightly run.'}]
        status = 2
    else:
        status = completed.returncode
        if status == 0 and any(row.get('level') == 'error' for row in findings):
            status = 1
    # lint.py exits 1 when it finished with error findings, and 2 when it could not complete.
    failed = status not in (0, 1)
    (report / 'findings.json').write_text(json.dumps(findings, indent=2) + '\n')
    (report / 'receipt.json').write_text(json.dumps({
        'owner': 'keeper', 'at': stamp, 'exit': status, 'findings': len(findings), 'failed': failed,
        'system': str(root), 'portfolio': str(portfolio)}, indent=2) + '\n')
    print('Keeper lint: exit %d; %d findings%s; %s' % (status, len(findings),
          '; FAIL lint did not complete' if failed else '', report))
    return failed, len(findings)


CHECK_SUMMARY = re.compile(r'^Memory checks: (\d+) failed$')


def run_check(script, arguments, root, environment, runner=subprocess.run):
    """Run memory/check.py. Return (failed, findings). Failed checks are findings (T293).
    The step fails only when check.py did not reach its summary line and exited non-zero."""
    completed = runner([sys.executable, '-B', str(script)] + list(arguments), cwd=str(root), env=environment,
                       capture_output=True, text=True)
    sys.stdout.write(completed.stdout or '')
    sys.stderr.write(completed.stderr or '')
    summary = [match for match in map(CHECK_SUMMARY.match, (completed.stdout or '').splitlines()) if match]
    if summary:
        return False, int(summary[-1].group(1))
    return bool(completed.returncode), 0


def build_workspaces_view(root, portfolio, runner=subprocess.run, dry_run=False):
    """Rebuild the built TEAM, SKILLS, and TOOLS pages in workspaces/. A dry run builds them in a temp folder."""
    script = root / 'base/make_workspaces_view.py'
    if not script.is_file() or script.is_symlink():
        print('Workspaces view: skip; no ' + str(script))
        return 0
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) if dry_run else root / 'workspaces'
        completed = runner([sys.executable, '-B', str(script), '--system-home', str(root),
                            '--workspace-root', str(portfolio), '--output-root', str(output)],
                           cwd=str(root), capture_output=True, text=True)
    last = (completed.stdout or completed.stderr or '').strip().splitlines()
    print('Workspaces view%s: exit %d; %s' % (' (dry run, temp folder)' if dry_run else '',
                                             completed.returncode, last[-1] if last else ''))
    return completed.returncode


def secret_in(raw):
    """The name of the first STATE_SECRETS family in raw bytes, or None. Bytes map one to one onto characters."""
    text = raw.decode('latin-1')
    return next((name for name, pattern in STATE_SECRETS if pattern.search(text)), None)


def scan_outgoing(folder, runner=subprocess.run):
    """Read every object that HEAD has and no remote-tracking ref has: commits, trees, and blobs, whole.
    Return None when all are clean, or the refusal reason. A git error is a refusal, never a clean result."""
    base = ['git', '-C', str(folder)]
    listed = runner(base + ['rev-list', '--objects', 'HEAD', '--not', '--remotes'], capture_output=True, text=True)
    if listed.returncode:
        return 'secret scan could not list the outgoing objects (git rev-list exit %d)' % listed.returncode
    names = {}
    for line in listed.stdout.splitlines():
        sha, _, path = line.partition(' ')
        if sha:
            names.setdefault(sha, path)
    if not names:
        return None
    read = runner(base + ['cat-file', '--batch'], input=''.join(sha + '\n' for sha in names).encode(),
                  capture_output=True)
    if read.returncode or not isinstance(read.stdout, bytes):
        return 'secret scan could not read the outgoing objects (git cat-file exit %d)' % read.returncode
    data, at, seen = read.stdout, 0, 0
    while at < len(data):
        end = data.find(b'\n', at)
        header = data[at:end].split() if end >= 0 else []
        if len(header) != 3 or header[0].decode('ascii', 'replace') not in names or not header[2].isdigit():
            return 'secret scan could not read the outgoing objects (unexpected git cat-file answer)'
        sha, kind, size = header[0].decode('ascii'), header[1].decode('ascii'), int(header[2])
        body = data[end + 1:end + 1 + size]
        if len(body) != size or data[end + 1 + size:end + 2 + size] != b'\n':
            return 'secret scan could not read the outgoing objects (short git cat-file answer)'
        hit = secret_in(body)
        if hit:
            where = names[sha] or ('%s %s' % (kind, sha[:12]))
            return 'secret-looking value (%s) in %s' % (hit, where)
        at, seen = end + 2 + size, seen + 1
    if seen != len(names):
        return 'secret scan could not read the outgoing objects (%d of %d read)' % (seen, len(names))
    return None


def push_state(root, runner=subprocess.run, dry_run=False):
    """Commit and push state/ when it is its own git repo with a remote. Pull before push; never force.
    A secret-looking value in any outgoing object, or a scan that cannot read them, refuses the push
    and keeps the commit local."""
    folder = root / 'state'
    if folder.is_symlink() or not (folder / '.git').exists():
        print('State push: skip; state/ is not a git repo')
        return 0

    def git(*arguments):
        return runner(['git', '-C', str(folder)] + list(arguments), capture_output=True, text=True)

    if not git('remote').stdout.split():
        print('State push: skip; state/ has no remote')
        return 0
    changed = [line for line in git('status', '--porcelain', '--', '.').stdout.splitlines() if line.strip()]
    if dry_run:
        print('State push (dry run): %d changed files; nothing committed or pushed' % len(changed))
        return 0
    if changed:
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        for step in (('add', '-A', '--', '.'), ('commit', '-q', '-m', 'state: nightly export ' + stamp)):
            done = git(*step)
            if done.returncode:
                print('State push: FAIL git ' + step[0] + ': ' + (done.stderr or done.stdout).strip()[:200])
                return done.returncode
    pulled = git('pull', '--rebase', '--no-autostash', '-q')
    if pulled.returncode:
        git('rebase', '--abort')
        print('State push: FAIL pull: ' + (pulled.stderr or pulled.stdout).strip()[:200])
        return pulled.returncode
    # Scan what the push sends, after the pull: every outgoing object, text or binary. On a hit or a
    # scan that could not read the outgoing objects, keep the commits local and push nothing (T750 F04).
    refusal = scan_outgoing(folder, runner)
    if refusal:
        print('State push: REFUSED; ' + refusal + '; commit kept local, nothing pushed')
        return 1
    pushed = git('push', '-q', 'origin', 'HEAD')
    print('State push: exit %d; %d changed files%s' % (pushed.returncode, len(changed),
          ('; ' + pushed.stderr.strip()[:200]) if pushed.returncode else ''))
    return pushed.returncode


def deliver_failure_alert(receipt, notifier=subprocess.run):
    """Ask macOS to show one failure notification and keep its delivery result."""
    command = ['/usr/bin/osascript', '-e',
               'display notification "Open the nightly receipt for the failed memory job." with title "Foxrun memory job failed"']
    try:
        done = notifier(command, capture_output=True, text=True, timeout=10)
        delivered = done.returncode == 0
        detail = (done.stderr or '').strip()[:200]
    except (OSError, subprocess.TimeoutExpired) as error:
        delivered = False
        detail = type(error).__name__ + ': ' + str(error)[:160]
    row = {'mode': 'live', 'channel': 'macOS', 'delivered': delivered,
           'checked_at': datetime.now(timezone.utc).isoformat(),
           'source': 'nightly', 'detail': detail}
    (receipt / 'alert.json').write_text(json.dumps(row, indent=2) + '\n')
    return row


# A local, unshipped setting (T801). Only an install that has it sends a message; others send none.
MESSAGE_SETTINGS = 'config/nightly.local.json'


def bot_post(token, chat, text, timeout=20):
    """Call the Telegram Bot API sendMessage once. Return its JSON answer; never raise for an HTTP error."""
    body = urllib.parse.urlencode({'chat_id': chat, 'text': text}).encode()
    request = urllib.request.Request('https://api.telegram.org/bot' + token + '/sendMessage', data=body)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read().decode('utf-8'))
        except ValueError:
            return {'ok': False, 'description': 'HTTP %d' % error.code}


def send_message(root, exit_code, at, reader=subprocess.run, post=None):
    """Send one short nightly message through the bot named in config/nightly.local.json.

    The file holds only references, never values:
    {"telegram": {"sender": "<bot name>", "reader": "<secret reader>", "token_ref": "op://...", "chat_ref": "op://..."}}.
    The reader prints one value for one reference. The values stay in memory: never printed, logged, or stored.
    No file: return None and send nothing.
    """
    path = root / MESSAGE_SETTINGS
    if path.is_symlink() or not path.is_file():
        return None
    row = {'channel': 'telegram', 'sent': False, 'checked_at': datetime.now(timezone.utc).isoformat()}
    try:
        settings = json.loads(path.read_text(encoding='utf-8'))['telegram']
        names = [settings[key] for key in ('sender', 'reader', 'token_ref', 'chat_ref')]
        if not all(isinstance(name, str) and name for name in names) or not all(
                settings[key].startswith('op://') for key in ('token_ref', 'chat_ref')):
            raise ValueError('sender, reader, token_ref, and chat_ref must be set; refs start with op://')
    except (OSError, ValueError, KeyError, TypeError) as error:
        row['detail'] = 'invalid ' + MESSAGE_SETTINGS + ': ' + str(error)[:160]
        return row
    row['sender'] = settings['sender']
    sys.path.insert(0, str(ROOT))
    from memory import state
    text = 'Foxrun nightly: ' + state.format_nightly({
        'result': 'ok' if exit_code == 0 else 'failed', 'at': at.astimezone(),
        'backup': state.nightly_status(root)['backup']})
    row['text'] = text
    values = []
    try:
        for key in ('token_ref', 'chat_ref'):
            done = reader([settings['reader'], settings[key]], capture_output=True, text=True, timeout=60)
            value = (done.stdout or '').strip()
            if done.returncode or not value:
                # The reader's own output is not kept: it could hold a value.
                raise ValueError('secret read failed for ' + key + ': exit %d' % done.returncode)
            values.append(value)
        answer = (post or bot_post)(values[0], values[1], text)
        row['sent'] = isinstance(answer, dict) and answer.get('ok') is True
        result = answer.get('result') if isinstance(answer, dict) else None
        row['message_id'] = result.get('message_id') if isinstance(result, dict) else None
        detail = '' if row['sent'] else str(answer.get('description') if isinstance(answer, dict) else answer)
    except (OSError, ValueError, subprocess.SubprocessError, urllib.error.URLError) as error:
        detail = type(error).__name__ + ': ' + str(error)
    # Keep no value in the receipt, even when an error repeats one.
    for value in values:
        detail = detail.replace(value, '[REDACTED]')
    bot_url_token = ('telegram-bot-token-in-url', re.compile(r'[0-9]{8,10}:[A-Za-z0-9_-]{35}'))
    for name, pattern in STATE_SECRETS + (bot_url_token,):
        detail = pattern.sub('[REDACTED]', detail)
    row['detail'] = detail[:200]
    print('Nightly message: %s through %s' % ('sent' if row['sent'] else 'FAIL not sent', row['sender']))
    return row


def sequence(root, dream_args=(), check_args=(), runner=subprocess.run, portfolio=None, dry_run=False,
             notifier=subprocess.run, reader=subprocess.run, post=None):
    scripts = [root / 'memory/dream.py', root / 'memory/check.py']
    for script in scripts:
        if not script.is_file() or script.is_symlink():
            raise ValueError('missing installed command: ' + str(script))
    environment = os.environ.copy()
    environment.setdefault('FOXRUN_HOME', str(root))
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    if not portfolio:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import schedule
        portfolio = schedule.portfolio_of(root)
    portfolio = Path(portfolio)
    # Findings are reported, not failures (T293). Only a step that crashed or a failed push sets the exit.
    steps = {}
    failed, findings = run_lint(root, portfolio, runner)
    steps['lint'] = {'failed': failed, 'findings': findings}
    dream = runner([sys.executable, '-B', str(scripts[0])] + list(dream_args), cwd=str(root), env=environment)
    steps['dream'] = {'failed': bool(dream.returncode), 'exit': dream.returncode}
    failed, findings = run_check(scripts[1], check_args, root, environment, runner)
    steps['check'] = {'failed': failed, 'findings': findings}
    # After dream.py wrote state/: rebuild the workspaces view, then push state/ (g-state-travels-as-jsonl).
    status = build_workspaces_view(root, portfolio, runner, dry_run)
    steps['workspaces_view'] = {'failed': bool(status), 'exit': status}
    status = push_state(root, runner, dry_run)
    steps['push'] = {'failed': bool(status), 'exit': status}
    exit_code = int(any(step['failed'] for step in steps.values()))
    moment = datetime.now(timezone.utc)
    stamp = moment.strftime('%Y%m%dT%H%M%S%fZ')
    # T755: nightly receipts live in runs/nightly/.
    receipt = root / 'runs' / 'nightly' / (stamp + '-nightly')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.mkdir(mode=0o700)
    alert = deliver_failure_alert(receipt, notifier) if exit_code else None
    # A message never changes the exit; its result stays in the receipt. A dry run sends none.
    message = None if dry_run else send_message(root, exit_code, moment, reader, post)
    (receipt / 'receipt.json').write_text(json.dumps({
        'owner': 'keeper', 'at': stamp, 'exit': exit_code, 'dry_run': dry_run, 'steps': steps,
        'alert': alert, 'message': message}, indent=2) + '\n')
    print('Nightly: exit %d; lint %d findings; check %d failed checks; failed steps: %s; %s' % (
        exit_code, steps['lint']['findings'], steps['check']['findings'],
        ', '.join(name for name, step in steps.items() if step['failed']) or 'none', receipt))
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Pass --dry-run to dream.py.')
    parser.add_argument('--workspace', help='Workspace for the subsequent memory check.')
    parser.add_argument('--transcript', help='Installed transcript path for the subsequent handoff check.')
    parser.add_argument('--handoff', help='Installed handoff path for the subsequent handoff check.')
    parser.add_argument('--schedule', action='store_true', help='Print the launchd job from its template and config/dream.json; load nothing.')
    parser.add_argument("--workspaces", type=Path, help="Portfolio home for the lint scan.")
    args = parser.parse_args(argv)
    try:
        if args.schedule:
            # One renderer for the installer and this preview: cron/schedule.py and its template.
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import plistlib
            import schedule
            job = schedule.render(ROOT, args.workspaces or schedule.portfolio_of(ROOT))
            if args.workspaces:
                job['ProgramArguments'].extend(['--workspaces', str(args.workspaces)])
            sys.stdout.buffer.write(plistlib.dumps(job))
            return 0
        # One sequential nightly job; child checks inherit this lower priority.
        os.nice(10)
        if sys.platform=='darwin':
            subprocess.run(['/usr/sbin/taskpolicy','-b','-p',str(os.getpid())],check=True)
        check_args = ['--readonly'] if args.dry_run else []
        for key in ['workspace', 'transcript', 'handoff']:
            value = getattr(args, key)
            if value:
                check_args.extend(['--' + key, value])
        return sequence(ROOT, ['--dry-run'] if args.dry_run else [], check_args, portfolio=args.workspaces,
                        dry_run=args.dry_run)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('FAIL nightly: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
