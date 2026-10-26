#!/usr/bin/env python3
"""Render the nightly launchd job from its template and turn it on. Standard library only.

The template is cron/launchd/session-nightly.plist.template. The clock comes from
config/dream.json. The job file goes to ~/Library/LaunchAgents/com.foxrun.session-nightly.plist.
FOXRUN_LAUNCHCTL names a different launchctl program, for tests.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
LABEL = 'com.foxrun.session-nightly'
WATCHDOG_LABEL = 'com.foxrun.session-nightly-watchdog'
TEMPLATE = HERE / 'launchd' / 'session-nightly.plist.template'
PLACEHOLDER = re.compile(r'@[A-Z_]+@')


def clock(home):
    """Return the launchd schedule keys from config/dream.json."""
    settings = Path(home) / 'config/dream.json'
    if settings.is_symlink():
        raise ValueError('config/dream.json must not be a link')
    schedule = json.loads(settings.read_text()) if settings.is_file() else {}
    if not isinstance(schedule, dict):
        raise ValueError('config/dream.json must hold an object')
    interval = schedule.get('interval_seconds')
    if interval is not None:
        if type(interval) is not int or interval < 60:
            raise ValueError('interval_seconds must be an integer of at least 60')
        return {'StartInterval': interval}
    hour, minute = schedule.get('hour', 2), schedule.get('minute', 30)
    if type(hour) is not int or type(minute) is not int or not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError('hour and minute are outside the clock')
    return {'StartCalendarInterval': {'Hour': hour, 'Minute': minute}}


def portfolio_of(home):
    """The rule of base/paths.py portfolio(), for this home: FOXRUN_PORTFOLIO, config/person.json, ~/foxrun."""
    if os.environ.get('FOXRUN_PORTFOLIO'):
        return Path(os.environ['FOXRUN_PORTFOLIO']).expanduser().resolve()
    config = Path(home) / 'config/person.json'
    if config.is_file() and not config.is_symlink():
        value = json.loads(config.read_text()).get('portfolio')
        if isinstance(value, str) and value:
            return (Path(home) / value).expanduser().resolve()
    return (Path.home() / 'foxrun').resolve()


def default_log_dir(user_home):
    return Path(user_home) / '.local/state/foxrun/session-nightly'


def render(home, portfolio, user_home=None, python=None, log_dir=None, template=TEMPLATE):
    """Return the job as a dict, with the person's paths in place of each placeholder."""
    user_home = Path(user_home or Path.home())
    values = {'@USER_HOME@': str(user_home), '@FOXRUN_HOME@': str(home),
              '@FOXRUN_PORTFOLIO@': str(portfolio), '@PYTHON@': str(python or sys.executable),
              '@LOG_DIR@': str(log_dir or default_log_dir(user_home))}

    def fill(value):
        if isinstance(value, str):
            for key, text in values.items():
                value = value.replace(key, text)
            if PLACEHOLDER.search(value):
                raise ValueError('template placeholder left unfilled: ' + value)
            return value
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return value

    job = fill(plistlib.loads(Path(template).read_bytes()))
    if job.get('Label') != LABEL:
        raise ValueError('template label must be ' + LABEL)
    job.pop('StartCalendarInterval', None)
    job.pop('StartInterval', None)
    job.update(clock(home))
    return job


def render_watchdog(home, user_home=None, python=None, log_dir=None):
    """Build the independent five-minute watchdog job."""
    user_home = Path(user_home or Path.home())
    logs = Path(log_dir or default_log_dir(user_home))
    return {'Label': WATCHDOG_LABEL,
            'ProgramArguments': [str(python or sys.executable), '-B', str(Path(home) / 'cron/watchdog.py'),
                                 '--home', str(home)],
            'EnvironmentVariables': {'HOME': str(user_home), 'PYTHONDONTWRITEBYTECODE': '1',
                                     'FOXRUN_HOME': str(home)},
            'StartInterval': 300, 'RunAtLoad': True,
            'StandardOutPath': str(logs / 'watchdog-stdout.log'),
            'StandardErrorPath': str(logs / 'watchdog-stderr.log'),
            'WorkingDirectory': str(home)}


def target_watchdog(user_home=None):
    return Path(user_home or Path.home()) / 'Library/LaunchAgents' / (WATCHDOG_LABEL + '.plist')


def turn_on_watchdog(home, user_home=None, python=None, log_dir=None, uid=None):
    """Install the watcher under a separate launchd label."""
    job = render_watchdog(home, user_home, python, log_dir)
    path = target_watchdog(user_home)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('watchdog launch agent path must not be a link: ' + str(path))
    if path.is_file():
        try:
            if plistlib.loads(path.read_bytes()) == job:
                return 'unchanged'
        except Exception:
            pass
        stamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
        new_private_file(path.with_name(path.name + '.bak-' + stamp), path.read_bytes())
        subprocess.run([launchctl(), 'bootout', 'gui/%d/%s' % (os.getuid() if uid is None else uid, WATCHDOG_LABEL)],
                       capture_output=True, text=True)
        state = 'replaced'
    else:
        state = 'written'
    if not os.environ.get('FOXRUN_LAUNCHCTL') and sys.platform != 'darwin':
        raise ValueError('launchd runs on macOS only; use --no-schedule here')
    Path(job['StandardOutPath']).parent.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_bytes(path, plistlib.dumps(job), 0o644)
    domain = 'gui/' + str(os.getuid() if uid is None else uid)
    result = subprocess.run([launchctl(), 'bootstrap', domain, str(path)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('watchdog launchctl bootstrap failed: ' + (result.stderr.strip() or result.stdout.strip()))
    return state


def replace_bytes(path, raw, mode=0o600):
    """Write path through a new private temporary file beside it, then rename it into place.
    mkstemp makes the file 0600 with O_EXCL, so a link planted at a temporary name is never followed.
    The finished file gets mode."""
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        os.chmod(temporary, mode)
        os.replace(temporary, str(path))
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def new_private_file(path, raw):
    """Write a new file that only this user can read. Refuse a name that exists, or a link there."""
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)


def target(user_home=None):
    return Path(user_home or Path.home()) / 'Library/LaunchAgents' / (LABEL + '.plist')


def launchctl():
    return os.environ.get('FOXRUN_LAUNCHCTL') or '/bin/launchctl'


def turn_on(home, portfolio, user_home=None, python=None, log_dir=None, uid=None):
    """Write and load the job. Return 'unchanged', 'written', or 'replaced'."""
    job = render(home, portfolio, user_home, python, log_dir)
    path = target(user_home)
    for part in (path, path.parent):
        if part.is_symlink():
            raise ValueError('launch agent path must not be a link: ' + str(part))
    state = 'written'
    if path.exists():
        try:
            current = plistlib.loads(path.read_bytes())
        except Exception:
            current = None
        if current == job:
            turn_on_watchdog(home, user_home, python, log_dir, uid)
            return 'unchanged'
        stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
        new_private_file(path.with_name(path.name + '.bak-' + stamp), path.read_bytes())
        state = 'replaced'
    if not os.environ.get('FOXRUN_LAUNCHCTL') and sys.platform != 'darwin':
        raise ValueError('launchd runs on macOS only; use --no-schedule here')
    Path(job['StandardOutPath']).parent.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_bytes(path, plistlib.dumps(job), 0o644)
    domain = 'gui/' + str(os.getuid() if uid is None else uid)
    if state == 'replaced':
        # A loaded job with the same label blocks bootstrap. Its absence is fine.
        subprocess.run([launchctl(), 'bootout', domain + '/' + LABEL], capture_output=True, text=True)
    result = subprocess.run([launchctl(), 'bootstrap', domain, str(path)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('launchctl bootstrap failed: ' + (result.stderr.strip() or result.stdout.strip()))
    turn_on_watchdog(home, user_home, python, log_dir, uid)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--home', default=os.environ.get('FOXRUN_HOME') or str(HERE.parent))
    parser.add_argument('--portfolio', help='Default: FOXRUN_PORTFOLIO, else the portfolio in config/person.json.')
    parser.add_argument('--python', help='Python program for the job; default is this one.')
    parser.add_argument('--compare', help='Compare the rendered job with this plist file; write nothing.')
    parser.add_argument('--on', action='store_true', help='Write and load the job.')
    args = parser.parse_args(argv)
    try:
        args.portfolio = args.portfolio or portfolio_of(args.home)
        if args.on:
            print('Nightly job: ' + turn_on(args.home, args.portfolio, python=args.python) + ' ' + str(target()))
            return 0
        job = render(args.home, args.portfolio, python=args.python)
        if args.compare:
            other = plistlib.loads(Path(args.compare).read_bytes())
            keys = sorted(set(job) | set(other))
            diff = [key for key in keys if job.get(key) != other.get(key)]
            for key in diff:
                print('differs ' + key + ': rendered=' + json.dumps(job.get(key)) + ' file=' + json.dumps(other.get(key)))
            print('same' if not diff else 'different: ' + ', '.join(diff))
            return 0 if not diff else 1
        sys.stdout.buffer.write(plistlib.dumps(job))
        return 0
    except (OSError, ValueError) as error:
        print('FAIL schedule: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
