#!/usr/bin/env python3
"""Freeze one kept reply, then link it by topic. Never change a frozen reply.

python3 -B memory/kept.py keep --workspace NAME --input RELATIVE_PATH [--topic wiki/concepts/TOPIC.md]
python3 -B memory/kept.py link [--workspace NAME]
Topics are existing note paths relative to the workspace. Missing topics need a person's review.
"""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
from base import paths
from base.tracker import local_path, tracker
from memory import state

BAD = {'.env', '.ssh', '.netrc', 'auth.json', 'credentials', 'credentials.json', 'secrets', 'id_rsa', '.git-credentials'}


def safe(root, relative):
    path = local_path(root, relative)
    if any(p.lower() in BAD or p.lower().startswith('.env.') for p in path.parts):
        raise ValueError('protected path refused')
    return path


def topic_path(folder, topic):
    path = safe(folder, topic)
    if not topic.startswith(('wiki/concepts/', 'wiki/entities/', 'wiki/queries/', 'wiki/comparisons/')) or path.suffix != '.md':
        raise ValueError('topic must name an existing wiki note')
    if not path.is_file():
        raise ValueError('topic note does not exist; review the topic first')
    return path


def freeze(workspace, text, topic=None, identifier=None):
    folder = safe(paths.portfolio(), workspace)
    if workspace not in state.workspaces():
        raise ValueError('unknown workspace')
    if not text.strip():
        raise ValueError('reply is empty')
    if topic:
        topic_path(folder, topic)
    text = text if text.endswith('\n') else text+'\n'
    digest = hashlib.sha256((workspace+'\n'+(topic or '')+'\n'+text).encode()).hexdigest()
    identifier = identifier or digest[:24]
    if not identifier or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identifier):
        raise ValueError('invalid snapshot id')
    target = safe(folder, 'history/snapshots/'+identifier+'.md')
    target.parent.mkdir(parents=True, exist_ok=True)
    body = '---\ntype: snapshot\nworkspace: '+workspace+'\ncreated_at: '+datetime.now().astimezone().isoformat(timespec='seconds')+'\ntopic: '+json.dumps(topic)+'\nsha256: '+digest+'\n---\n'+text
    if not body.endswith('\n'):
        body += '\n'
    fd, temporary = tempfile.mkstemp(prefix='.kept-', dir=str(target.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, str(target))
        except FileExistsError:
            old = target.read_text(encoding='utf-8')
            if '\nsha256: '+digest+'\n' not in old:
                raise ValueError('snapshot exists with different content; original kept')
    finally:
        os.unlink(temporary)
    return target


def fields(file):
    text = file.read_text(encoding='utf-8')
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        raise ValueError('snapshot has no metadata: '+file.name)
    header = text.split('\n---\n', 1)[0][4:]
    return dict(line.split(': ', 1) for line in header.splitlines() if ': ' in line)


def inbox(workspace, snapshot, runner=subprocess.run):
    database = tracker(workspace)
    note = 'Choose a topic for kept reply in '+workspace+': history/snapshots/'+snapshot.name
    with closing(state.readonly(database)) as db:
        if 'note' not in state.columns(db, 'tasks'):
            raise ValueError('tracker needs the tasks.note column')
        if db.execute('SELECT 1 FROM tasks WHERE note=?', (note,)).fetchone():
            return False
    command = [sys.executable, '-B', str(paths.system_home()/'work/work.py'), '--workspace', workspace,
               '--db', str(database), '--receipt-root', str(paths.workspace(workspace)),
               'create', '--title', 'Choose topic for kept reply '+snapshot.stem, '--note', note,
               # Every task carries six fields of its own (T718).
               '--problem', 'A kept reply in '+workspace+' has no topic, so nobody can find it from a topic page.',
               '--job-when', 'When a kept reply has no topic', '--job-want', 'I want to choose the topic note it belongs to',
               '--job-so', 'So I can find the reply from that topic later',
               '--body', 'Choose one existing topic note for the kept reply; kept.py link then links it.',
               '--acceptance', 'The kept reply links to one existing topic note',
               '--context', 'kept.py link made this task because the frozen reply names no topic.',
               '--where', str(snapshot),
               '--tags', 'workspace:'+workspace, '--by', 'keeper']
    result = runner(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('inbox command failed; snapshot kept for retry')
    return True


def link_all(moment=None, workspace=None, inbox_fn=inbox):
    moment = moment or datetime.now().astimezone()
    linked, queued = 0, 0
    legacy, invalid = [], []
    for name in ([workspace] if workspace else state.workspaces()):
        if name not in state.workspaces():
            raise ValueError('unknown workspace')
        folder = safe(paths.portfolio(), name)
        snapshots = safe(folder, 'history/snapshots')
        if not snapshots.is_dir():
            continue
        lock = safe(folder, 'history/.kept-link.lock')
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise ValueError('kept reply linking is locked; review before retry')
        os.close(fd)
        try:
            for candidate in sorted(snapshots.glob('*.md')):
                snapshot = safe(folder, str(candidate.relative_to(folder)))
                try:
                    metadata = fields(snapshot)
                except ValueError:
                    # Historical documents are never rewritten or guessed into a topic.
                    legacy.append({'workspace': name, 'file': snapshot.name, 'reason': 'historical document; no kept-reply metadata'})
                    continue
                if not {'created_at', 'topic', 'sha256'} <= set(metadata):
                    legacy.append({'workspace': name, 'file': snapshot.name, 'reason': 'legacy snapshot; review for migration'})
                    continue
                if metadata.get('type') != 'snapshot' or metadata.get('workspace') != name:
                    invalid.append({'workspace': name, 'file': snapshot.name, 'reason': 'kept-reply metadata mismatch'})
                    continue
                topic = json.loads(metadata.get('topic', 'null'))
                text = snapshot.read_text(encoding='utf-8').split('\n---\n',1)[1]
                digest = hashlib.sha256((name+'\n'+(topic or '')+'\n'+text).encode()).hexdigest()
                if digest != metadata.get('sha256'):
                    raise ValueError('frozen snapshot hash differs; original needs review')
                if topic is None or topic == '':
                    queued += bool(inbox_fn(name, snapshot))
                    continue
                page = topic_path(folder, topic)
                href = os.path.relpath(str(snapshot), str(page.parent)).replace(os.sep, '/')
                entry = '- '+metadata['created_at'][:10]+' · [Kept reply]('+href+')'
                before = page.read_text(encoding='utf-8')
                if ']('+href+')' in before:
                    continue
                state.write_once(page, before.rstrip()+'\n\n'+entry+'\n')
                linked += 1
        finally:
            lock.unlink()
    report = safe(paths.system_home(), 'runs/kept-link-review.json')
    report.parent.mkdir(parents=True, exist_ok=True)
    state.write_once(report, json.dumps({'checked_at': state.stamp(moment), 'legacy': legacy, 'invalid': invalid}, indent=2)+'\n')
    if invalid:
        raise ValueError('invalid kept replies need review; valid replies were processed; see runs/kept-link-review.json')
    return linked, queued


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('keep', 'link'))
    parser.add_argument('--workspace')
    parser.add_argument('--input')
    parser.add_argument('--topic')
    args = parser.parse_args()
    try:
        if args.command == 'keep':
            if not args.workspace or not args.input:
                raise ValueError('keep needs --workspace and --input')
            source = safe(paths.workspace(args.workspace), args.input)
            print(freeze(args.workspace, source.read_text(encoding='utf-8'), args.topic))
        else:
            linked, inbox_count = link_all(workspace=args.workspace)
            print('{} topic links, {} inbox rows'.format(linked, inbox_count))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print('FAIL kept: '+str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
