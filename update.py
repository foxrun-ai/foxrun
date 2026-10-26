#!/usr/bin/env python3
"""Refresh product files in an existing home without reinstalling personal state."""
from __future__ import annotations

import argparse
import csv
from contextlib import ExitStack, closing, contextmanager, redirect_stdout
from datetime import datetime, timezone
import functools
import hashlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

try:
    import grp
    import pwd
except ImportError:  # Windows has neither, so there no group counts as private.
    grp = pwd = None


HERE = Path(__file__).resolve().parent
# Install and update write the product folder they ran from here; personal state, never a product row.
SOURCE_RECORD = 'config/product-source.json'
# A home manifest row whose sha256 starts with this marker is a retired product file. It stays on
# disk and in the list, so a later release may ship the same path again. Doctor skips these rows.
RETIRED = 'retired:'
LOCK = '.update.lock'
# skill-ship turns this folder into a link to a frozen release under skillwright/skill-releases/.
SHELF = 'skills'
# ReleaseShelf.ship stages a new release in a tempfile.mkdtemp folder with this name, then renames it.
STAGING = re.compile(r'\.update-[a-z0-9_]{8}')
# Update keeps this many backups/update-* folders, the one it just made included.
KEEP_BACKUPS = 3
# A product file the person changed is kept beside the new one with this suffix and a time.
LOCAL_EDIT = '.local-edit-'
ROUTES = '\n'.join((
    'Run the update for your install route.',
    'Clone: open the product folder, then run:',
    '  git pull',
    '  python3 foxrun.py update --home "$HOME/.foxrun"',
    'uv:',
    '  uv tool upgrade foxrun',
    '  foxrun update --home "$HOME/.foxrun"',
    'Plugin: run setup after a plugin upgrade, then run the two uv commands above.',
    'Another product folder:',
    '  python3 "$HOME/.foxrun/foxrun.py" update --source /absolute/path/to/foxrun --home "$HOME/.foxrun"'))


def source_record(tree):
    return (json.dumps({'version': 1, 'source': str(Path(tree).resolve())}, indent=2) + '\n').encode('utf-8')


def is_source(folder):
    return all((folder / name).is_file() for name in ('install.py', 'update.py', 'product-manifest.tsv'))


def find_source(home):
    """With no --source: this product folder (uv package or clone), then the recorded one, else refuse."""
    if is_source(HERE):
        # This folder's code is already running, but update still imports its install.py and base/.
        unsafe = source_unsafe(HERE)
        if unsafe:
            raise ValueError('This product folder ' + str(HERE) + ' is not safe to run: ' + unsafe + '.')
        return HERE
    home = Path(home).expanduser()
    record = regular(home, SOURCE_RECORD)
    problem = 'No --source was given, and ' + str(record) + ' does not exist.'
    unsafe = record.is_file() and writable_by_others(record)
    if unsafe:
        problem = 'The source record is not safe to use: ' + unsafe + '.'
    elif record.is_file():
        try:
            data = json.loads(record.read_text(encoding='utf-8'))
            recorded = Path(data['source'])
        except (ValueError, KeyError, TypeError):
            problem = 'The source record ' + str(record) + ' is not valid.'
        else:
            if recorded.is_absolute() and is_source(recorded):
                # Update runs this folder's code as this user, so no one else may change it.
                # Return the exact real path that passed the checks, never the recorded string.
                real = Path(os.path.realpath(str(recorded)))
                unsafe = source_unsafe(real)
                if unsafe:
                    problem = 'The recorded source ' + str(recorded) + ' is not safe to run: ' + unsafe + '.'
                else:
                    return real
            else:
                problem = 'The recorded source ' + str(recorded) + ' is not a product folder now.'
    routes = ROUTES
    if home.resolve() != (Path.home() / '.foxrun').resolve():
        routes = routes.replace('"$HOME/.foxrun/foxrun.py"', shlex.quote(str(home / 'foxrun.py')))
        routes = routes.replace('"$HOME/.foxrun"', shlex.quote(str(home)))
    raise ValueError('Update needs the product source. ' + problem + '\n' + routes)


def writable_by_others(path):
    """Name the reason another local user could change this path, or return None."""
    real = Path(os.path.realpath(str(path)))
    info = real.stat()
    # Windows has no os.getuid, so there the owner check is skipped; the write-bit checks still run.
    getuid = getattr(os, 'getuid', None)
    if getuid is not None and info.st_uid != getuid():
        return str(real) + ' is not owned by the current user'
    if info.st_mode & stat.S_IWOTH:
        return str(real) + ' is world-writable'
    # A group-writable path passes only when its group is this user's own private group.
    if info.st_mode & stat.S_IWGRP and not private_group(info.st_gid):
        return str(real) + ' is group-writable (fix: chmod g-w ' + shlex.quote(str(real)) + ')'
    return None


# private_group reads these local account files itself. Directory sources such as LDAP are not trusted.
PASSWD_FILE = '/etc/passwd'
GROUP_FILE = '/etc/group'


def local_entries(path, width):
    """The rows of a local colon-separated account file, or None when one line is not a plain entry."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return None
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        fields = line.split(':')
        # A + or - line pulls entries from NIS, so the file alone cannot name every member.
        if len(fields) != width or not fields[0] or fields[0][0] in '+-':
            return None
        rows.append(fields)
    return rows


@functools.lru_cache(maxsize=None)
def private_group(gid):
    """True when this user is the only possible member of group gid, as OpenSSH StrictModes allows.
    Ubuntu and most Linux systems give each user a group of their own and umask 002, so git clone
    and install make 0775 folders. Fail closed: the user and the group must both be in the local
    /etc/passwd and /etc/group. gid must be the user's primary group and no other local account's.
    Every group entry with gid, local or from the system lookup, must have the user's name and no
    other member. macOS keeps its users outside /etc/passwd and gives them the shared group staff,
    so there a group-writable path is still refused."""
    getuid = getattr(os, 'getuid', None)
    if pwd is None or grp is None or getuid is None:
        return False
    uid = getuid()
    users, groups = local_entries(PASSWD_FILE, 7), local_entries(GROUP_FILE, 4)
    if users is None or groups is None:
        return False
    try:
        users = [(name, int(number), int(primary)) for name, _password, number, primary, _gecos, _dir, _shell in users]
        groups = [(name, int(number), [member for member in members.split(',') if member])
                  for name, _password, number, members in groups]
    except ValueError:
        return False
    mine = [user for user in users if user[1] == uid]
    if len(mine) != 1 or mine[0][2] != gid:
        return False
    name = mine[0][0]
    # An account whose primary group is gid is in the group without a gr_mem line.
    if any(primary == gid and number != uid for _name, number, primary in users):
        return False
    local = [group for group in groups if group[1] == gid]
    if not local or any(group != name or any(m != name for m in members) for group, _gid, members in local):
        return False
    # The system lookup also sees directory sources. Each entry it gives for gid must agree too,
    # and no account it knows but this user may have gid as its primary group.
    try:
        if pwd.getpwuid(uid).pw_name != name:
            return False
        if any(user.pw_gid == gid and user.pw_uid != uid for user in pwd.getpwall()):
            return False
        entries = grp.getgrall()
    except Exception:  # Any lookup failure fails closed.
        return False
    return all(entry.gr_name == name and all(m == name for m in entry.gr_mem)
               for entry in entries if entry.gr_gid == gid)

def source_unsafe(source):
    """Name the first source folder, file, or parent folder another user could change."""
    real = Path(os.path.realpath(str(source)))
    seen = set()
    # update.py imports base/ from this tree, and it copies hooks, commands with no
    # extension, and SQL that later run. So check every folder and every file.
    for folder, folders, names in os.walk(str(real), followlinks=True):
        seen.add(os.path.realpath(folder))
        # Follow linked folders once each, so a link loop cannot walk forever.
        folders[:] = [name for name in folders if os.path.realpath(os.path.join(folder, name)) not in seen]
        for path in [folder] + [os.path.join(folder, name) for name in sorted(names)]:
            unsafe = writable_by_others(path)
            if unsafe:
                return unsafe
    # A writable parent lets another user swap the whole folder. The sticky bit blocks that swap.
    getuid = getattr(os, 'getuid', None)
    for parent in real.parents:
        info = parent.stat()
        # Any parent owned by another user except root is refused, so a writable parent
        # passes only with the sticky bit and an owner of root or this user.
        if getuid is not None and info.st_uid not in (getuid(), 0):
            return str(parent) + ' is owned by another user'
        # This user's private group cannot let another user in, so its write bit is safe here too.
        shared = info.st_mode & stat.S_IWGRP and not private_group(info.st_gid)
        if (info.st_mode & stat.S_IWOTH or shared) and not info.st_mode & stat.S_ISVTX:
            kind = 'world-writable' if info.st_mode & stat.S_IWOTH else 'group-writable'
            fix = ' (fix: chmod g-w ' + shlex.quote(str(parent)) + ')' if kind == 'group-writable' else ''
            return str(parent) + ' is ' + kind + ' without the sticky bit' + fix
    return None


def regular(root, name):
    """Validate every path component before reading or replacing a file."""
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Unsafe product path: ' + name)
    target = root
    for part in relative.parts:
        target /= part
        if target.is_symlink():
            raise ValueError('Linked update path: ' + str(target))
    if target.exists() and (not target.is_file() or target.stat().st_nlink != 1):
        raise ValueError('Update path must be a regular, unshared file: ' + str(target))
    return target


def manifest(root, name):
    with regular(root, name).open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    if not rows or not {'path', 'bytes', 'sha256'} <= set(rows[0]):
        raise ValueError('Invalid product manifest: ' + name)
    if len({row['path'] for row in rows}) != len(rows):
        raise ValueError('Duplicate product paths: ' + name)
    return rows


@contextmanager
def skill_env(home):
    """Point Skillwright's paths at this home while its code runs, then restore the caller's values."""
    values = {'SKILLS_DOJO_ROOT': home / 'skillwright', 'SKILL_RELEASES_ROOT': home / 'skillwright/skill-releases',
              'SKILL_STATE_ROOT': home / 'skillwright/skill-state', 'SKILLS_ACTIVE_PATH': home / SHELF,
              'SKILLS_LOCK_PATH': home / 'skillwright/skill-state/lifecycle.lock',
              'SKILLS_PIN_PATH': home / 'agents/execution/skills.yaml'}
    before = {key: os.environ.get(key) for key in values}
    os.environ.update({key: str(value) for key, value in values.items()})
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def load_skillwright(tree, home):
    """Load the source's skill-ship code, so update moves the shelf the way skill-ship does."""
    tools = tree / 'skillwright/tools'
    modules = []
    sys.path.insert(0, str(tools))
    try:
        with skill_env(home):
            for name in ('skill_ship', 'skill_scoped'):
                spec = importlib.util.spec_from_file_location('update_' + name, str(tools / (name + '.py')))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules.append(module)
    finally:
        sys.path.remove(str(tools))
    return modules


class ReleaseShelf:
    """The home's skills/ is a skill-ship release link. Update never writes through it.
    It makes a new release from the active one with the new product skill files, then moves the link."""

    def __init__(self, tree, home):
        self.home = home
        self.link = home / SHELF
        releases = self.releases = home / 'skillwright/skill-releases'
        regular(home, 'skillwright/skill-state/release-state.json')
        regular(home, 'skillwright/manifests/shipped.yaml')
        regular(home, 'agents/execution/skills.yaml')
        if releases.is_symlink() or not releases.is_dir():
            self.refuse('the release folder is not a regular folder')
        target = Path(os.path.realpath(str(self.link)))
        if target.parent != Path(os.path.realpath(str(releases))) or not target.is_dir():
            self.refuse('the link does not point at a release in ' + str(releases))
        try:
            self.tool, self.scoped = load_skillwright(tree, home)
        except (RuntimeError, OSError, ImportError, AttributeError) as error:
            self.refuse('the source cannot load skill-ship: ' + str(error))
        self.target = target
        self.record = self.agree()
        self.files = {}
        self.locked = None
        self.receipt = None
        self.candidate = None

    def refuse(self, reason):
        raise ValueError('Linked update path: ' + str(self.link) + ' (' + reason + ')')

    def guard(self):
        """Refuse when another local user could change the releases, the linked release, or skill-state.
        Update runs and records these bytes as this user, so it holds them to the bar of find_source."""
        # The skillwright parent too: another user who can write it could swap the whole releases folder.
        for path in (self.home / 'skillwright', self.releases, self.target, self.home / 'skillwright/skill-state'):
            unsafe = writable_by_others(path)
            if unsafe:
                self.refuse(unsafe + '; only you may write the skill releases')

    def agree(self):
        """Return the linked release's record when skill-ship left the shelf whole; else refuse."""
        tool, scoped = self.tool, self.scoped
        self.guard()
        try:
            with skill_env(self.home):
                for name in ('scoped-transaction.json', 'workspace-transaction.json', 'release-transaction.json'):
                    if (tool.STATE / name).exists():
                        self.refuse('a skill-ship transaction is open; run skill-ship recover first')
                if Path(os.path.realpath(str(self.link))) != self.target:
                    self.refuse('the link moved during the update')
                record = scoped.validate_record(tool, self.link)
                state = tool.load_json(tool.STATE_FILE) if tool.STATE_FILE.is_file() else {}
                current = Path((state.get('current') or {}).get('path', ''))
                if not state.get('scoped') or os.path.realpath(str(current)) != str(self.target):
                    self.refuse('the release state does not name the linked release')
                if (tool.load_json(tool.DIST) != record
                        or tool.load_json(scoped.pin_path()).get('release') != record['release_id']):
                    self.refuse('the shelf, shipped list, and pin do not agree')
        except (RuntimeError, OSError, KeyError, TypeError, AttributeError) as error:
            self.refuse(str(error))
        return record

    def owner(self, skill):
        entry = self.record['skills'][skill]
        return entry.get('owner') or self.tool.skill_owner(skill)

    def plan(self, name, raw, mode):
        """Return the bytes the home list records for this product file, or None when no file lands."""
        parts = Path(name).parts
        if len(parts) < 3 or not self.tool.SAFE_ID.fullmatch(parts[1]):
            raise ValueError('Product path is not inside one skill: ' + name)
        skill, inside = parts[1], Path(*parts[2:])
        if skill in self.record['skills'] and self.owner(skill) == 'person':
            # The person's own skill stays as it is. The list records the bytes it holds.
            held = self.target / skill / inside
            return held.read_bytes() if held.is_file() and not held.is_symlink() else None
        if skill not in self.record['skills'] and (skill in self.record.get('excluded', {})
                                                   or skill in self.record.get('removed', [])):
            return None
        self.files.setdefault(skill, {})[inside] = (raw, mode)
        return raw

    def check(self):
        for skill, files in self.files.items():
            if skill not in self.record['skills'] and Path('SKILL.md') not in files:
                raise ValueError('Product skill has no SKILL.md for the release: ' + skill)

    def lock(self):
        with skill_env(self.home):
            stack = ExitStack()
            try:
                stack.enter_context(self.tool.lifecycle_lock())
            except RuntimeError as error:
                raise ValueError(str(error) + '. Wait for skill-ship to end, then run the update again.')
            self.locked = stack
        # Skill-ship may have run before the lock; check the shelf again under it.
        if self.agree() != self.record:
            raise ValueError('The skill shelf changed during the update')
        self.remove_stale()

    def remove_stale(self):
        """Remove staging folders a killed update left. Only update makes .update-* folders here,
        and the update lock plus the lifecycle lock keep every other writer out."""
        for folder in self.releases.iterdir():
            if not STAGING.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
                continue
            # The copy is read-only like a frozen release; open its folders, never through a link.
            for inside, _folders, _names in os.walk(str(folder)):
                os.chmod(inside, 0o700)
            shutil.rmtree(str(folder))
            print('Removed a staging folder a stopped update left: ' + str(folder), flush=True)

    def close(self):
        if self.locked is not None:
            self.locked.close()
            self.locked = None

    def ship(self):
        """Make and activate the new release. Return its id, or None when the product skills are current."""
        tool, scoped = self.tool, self.scoped
        changed = [skill for skill, files in sorted(self.files.items()) if any(
            not (self.target / skill / inside).is_file() or (self.target / skill / inside).read_bytes() != raw
            or os.stat(str(self.target / skill / inside)).st_mode & 0o100 != mode & 0o100
            for inside, (raw, mode) in files.items())]
        if not changed:
            return None
        with skill_env(self.home):
            if scoped.validate_record(tool, self.link) != self.record:
                raise ValueError('The skill shelf changed during the update')
            release_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-update'
            candidate = tool.RELEASES / release_id
            staging = Path(tempfile.mkdtemp(prefix='.update-', dir=str(tool.RELEASES)))
            self.candidate = staging
            record = json.loads(json.dumps(self.record))
            record.update(kind='product_update', release_id=release_id, runtime_canaries='pending')
            # Copy only the skills the checked record names. A new product skill starts empty.
            checked = {}
            for skill in sorted(record['skills']):
                shutil.copytree(str(self.target / skill), str(staging / skill), symlinks=True,
                                ignore=shutil.ignore_patterns(*tool.EXCLUDED_PARTS))
                # copytree keeps each mode; a group- or world-writable file stays so. Close it at once.
                closed(staging / skill)
                # Prove the copy holds the checked bytes before any new file goes in.
                # Else bytes swapped after the check would get a fresh, valid digest below.
                scoped.safe_tree(staging / skill)
                checked[skill] = tool.file_records(staging / skill)
                entry = self.record['skills'][skill]
                if tool.digest_tree(staging / skill) != (entry['digest'], entry['file_count']):
                    raise ValueError('The active release changed after its check: ' + skill +
                                     '. Run skill-ship to check the shelf, then run the update again.')
            # The copy keeps the frozen release's read-only folders; open them for the new files.
            # The staging root stays 0700 until the rename, so no other user reaches inside.
            for folder, _folders, _names in os.walk(str(staging)):
                os.chmod(folder, 0o700 if folder == str(staging) else 0o755)
            for skill in changed:
                for inside, (raw, mode) in self.files[skill].items():
                    path = staging / skill / inside
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Replace the copied file; never write through what the copy holds.
                    if path.is_symlink() or path.exists():
                        path.unlink()
                    path.write_bytes(raw)
                    path.chmod(mode)
                digest, count = tool.digest_tree(staging / skill)
                record['skills'][skill] = dict(source='skills_dojo', digest=digest, file_count=count, owner='product')
            record['digest'] = scoped.record_digest(record['skills'])
            tool.write_json(staging / scoped.RECORD, record)
            tool.make_read_only(staging)
            os.chmod(str(staging), 0o700)
            # Confirm the frozen copy: each changed skill holds the checked copy plus the product files, nothing else.
            # Else a write between the copy and the new digest would be blessed by that digest.
            for skill in changed:
                expected = {row[0]: row for row in checked.get(skill, [])}
                for inside, (raw, mode) in self.files[skill].items():
                    if not any(part in tool.EXCLUDED_PARTS for part in inside.parts):
                        expected[inside.as_posix()] = (inside.as_posix(), '100755' if mode & 0o100 else '100644',
                                                       hashlib.sha256(raw).hexdigest())
                if sorted(tool.file_records(staging / skill)) != sorted(expected.values()):
                    raise ValueError('The new release changed while update made it: ' + skill +
                                     '. Run the update again.')
            scoped.validate_record(tool, staging)
            os.rename(str(staging), str(candidate))
            self.candidate = candidate
            os.chmod(str(candidate), 0o555)
            previous = dict(kind='release', path=str(self.target))
            # The same receipt skill-ship writes, so `skill-ship rollback` and `recover` work on this release.
            self.receipt = dict(version=1, kind='product_update', release_id=release_id, result='running', skill=None,
                                skills=changed, previous_release_id=self.record['release_id'], previous=previous,
                                candidate=str(candidate), links_created=[], removed=[],
                                distribution_before=scoped.json_snapshot(tool.DIST),
                                pin_before=scoped.json_snapshot(scoped.pin_path()),
                                state_before=scoped.json_snapshot(tool.STATE_FILE))
            tool.write_json(tool.SHIPS / (release_id + '.json'), self.receipt)
            tool.write_json(tool.STATE / 'scoped-transaction.json', self.receipt)
            tool.switch_link(candidate)
            tool.write_json(tool.DIST, record)
            tool.write_json(scoped.pin_path(), dict(gaps=[], release=release_id))
            tool.write_json(tool.STATE_FILE, dict(version=1, scoped=True, release_id=release_id,
                            current=dict(kind='release', path=str(candidate)), previous=previous))
        return release_id

    def finish(self):
        if self.receipt is None:
            return
        with skill_env(self.home):
            self.receipt['result'] = 'shipped'
            self.tool.write_json(self.tool.SHIPS / (self.receipt['release_id'] + '.json'), self.receipt)
            (self.tool.STATE / 'scoped-transaction.json').unlink()

    def rollback(self):
        """Restore the previous release link and Skillwright records, then remove the new release."""
        with skill_env(self.home):
            if self.receipt is not None:
                self.receipt['result'] = 'running'
                self.tool.write_json(self.tool.STATE / 'scoped-transaction.json', self.receipt)
                self.scoped.read_transaction(self.tool)
                self.receipt.update(result='failed', rollback='restored')
                self.tool.write_json(self.tool.SHIPS / (self.receipt['release_id'] + '.json'), self.receipt)
            if self.candidate is not None and self.candidate.is_dir() and not self.candidate.is_symlink():
                for folder, _folders, _names in os.walk(str(self.candidate)):
                    os.chmod(folder, 0o700)
                shutil.rmtree(str(self.candidate))


def closed(root):
    """Clear the group and other write bits on every folder and file under root. Links stay as they are."""
    for folder, folders, names in os.walk(str(root), followlinks=False):
        for path in [folder] + [os.path.join(folder, name) for name in folders + names]:
            info = os.lstat(path)
            if not stat.S_ISLNK(info.st_mode) and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                os.chmod(path, stat.S_IMODE(info.st_mode) & ~(stat.S_IWGRP | stat.S_IWOTH))


def personal(name, starters):
    return (name in starters or name in {'GLOSSARY.md', 'SCHEMA.md', 'STATE.md', 'data.db', 'health.json'}
            or name.startswith(('profile/', 'workspaces/', 'runs/', 'backups/', 'state/', 'raw/', 'archive/'))
            or any(part == '.local' or part.endswith('.local') or '.local.' in part for part in Path(name).parts))


def table_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, ('path', 'bytes', 'sha256'), delimiter='\t', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def file_row(name, raw):
    return dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def keep_local_edit(target, raw, stamp):
    """Write the person's bytes next to the product file, owner-only, and never over a file."""
    for count in range(1, 100):
        copy = target.with_name(target.name + LOCAL_EDIT + stamp + ('' if count == 1 else '-' + str(count)))
        try:
            descriptor = os.open(str(copy), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        os.chmod(str(copy), 0o600)
        return copy
    raise ValueError('Could not keep the changed copy of ' + str(target))


def prune_backups(backup_root, backup):
    """Keep the newest update backups. Never remove the one just made or anything else in backups/."""
    made = re.compile(r'update-\d{8}T\d{6}Z-')
    older = [folder for folder in backup_root.iterdir()
             if made.match(folder.name) and not folder.is_symlink() and folder.is_dir() and folder != backup]
    # The name starts with the time to the second; the folder time orders two updates in one second.
    older.sort(key=lambda folder: (folder.name[:len('update-YYYYMMDDTHHMMSSZ')], folder.stat().st_mtime_ns))
    for folder in older[:max(len(older) - (KEEP_BACKUPS - 1), 0)]:
        try:
            shutil.rmtree(str(folder))
        except OSError as error:
            print('Could not remove an old update backup: ' + str(error), file=sys.stderr)


def lock_holder(path):
    """The process id written in the lock file, or None."""
    try:
        text = path.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


def acquire_lock(home):
    """Hold the update lock and write this process id into it.
    With flock the system drops the lock when its holder dies, so a killed update never blocks the next one."""
    path = regular(home, LOCK)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is None:
        try:
            descriptor = os.open(str(path), flags | os.O_EXCL, 0o600)
        except FileExistsError:
            holder = lock_holder(path)
            raise ValueError('The update lock ' + str(path) + ' exists' +
                             (' (process ' + str(holder) + ')' if holder else '') +
                             '. Another update may be running. If none is running, delete that file, then run the update again.')
        os.write(descriptor, (str(os.getpid()) + '\n').encode())
        return path, descriptor, False
    for _ in range(5):
        descriptor = os.open(str(path), flags, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            holder = lock_holder(path)
            raise ValueError('Another update is running' + (' (process ' + str(holder) + ')' if holder else '') +
                             ' and holds ' + str(path) + '. Wait for it to end, then run the update again.')
        # An update that just ended removes its lock file. Hold the file that is at the path now.
        opened = os.fstat(descriptor)
        try:
            current = os.stat(str(path))
        except FileNotFoundError:
            current = None
        if current is not None and (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino):
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                os.close(descriptor)
                raise ValueError('Update path must be a regular, unshared file: ' + str(path))
            os.ftruncate(descriptor, 0)
            os.write(descriptor, (str(os.getpid()) + '\n').encode())
            return path, descriptor, True
        os.close(descriptor)
    raise ValueError('Could not take the update lock: ' + str(path))


def release_lock(lock):
    path, descriptor, flocked = lock
    if not flocked:
        os.close(descriptor)
        path.unlink()
        return
    # Remove the file while the lock is held, so no other update holds a removed file.
    try:
        path.unlink()
    finally:
        os.close(descriptor)


def replace(target, raw, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.update-', dir=str(target.parent))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_migration(db, sql):
    """Keep the script inside the caller's transaction, including its final checks."""
    statements = []
    pending = ''
    for character in sql:
        pending += character
        if character == ';' and sqlite3.complete_statement(pending):
            statements.append(pending)
            pending = ''
    clean = lambda text: re.sub(r'/\*.*?\*/|--[^\n]*', '', text, flags=re.S).strip()
    if clean(pending) or len(statements) < 2:
        raise ValueError('Migration must be a complete transaction')
    if clean(statements[0]).upper() != 'BEGIN IMMEDIATE;' or clean(statements[-1]).upper() != 'COMMIT;':
        raise ValueError('Migration must start with BEGIN IMMEDIATE and end with COMMIT')
    # A future migration must not release the writer lock before Doctor finishes.
    db.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY
                      if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT)
                      else sqlite3.SQLITE_OK)
    try:
        for statement in statements[1:-1]:
            db.execute(statement)
    finally:
        # set_authorizer(None) clears the callback only on Python 3.11 and later.
        # On 3.9 and 3.10 it keeps None as the callback, and SQLite then denies every statement.
        db.set_authorizer(lambda *args: sqlite3.SQLITE_OK)
    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise ValueError('Updated database failed its integrity check')
    if db.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('Updated database has invalid references')


def migrate(database, sql):
    from base import person
    with closing(person.connect(str(database))) as db:
        db.execute('PRAGMA foreign_keys = ON')
        with db:
            db.execute('BEGIN IMMEDIATE')
            apply_migration(db, sql)


def update(tree, home):
    tree = tree.expanduser().resolve()
    # Only the source installer supplies shipment exclusions. Never use the old home's code.
    spec = importlib.util.spec_from_file_location('update_install', str(tree / 'install.py'))
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    home = installer.destination(str(home), 'home', tree, empty=False)
    database = regular(home, 'data.db')
    for suffix in ('-wal', '-shm', '-journal'):
        regular(home, 'data.db' + suffix)
    config = json.loads(regular(home, 'config/person.json').read_text(encoding='utf-8'))
    if not database.is_file() or not isinstance(config.get('name'), str) or not config['name']:
        raise ValueError('Update needs an existing Foxrun home; use install for a new home')
    # Database checks use the target's configured workspace roster, never the caller's home.
    for key in list(os.environ):
        if key.startswith('FOXRUN_'):
            del os.environ[key]
    os.environ['FOXRUN_HOME'] = str(home)
    old_rows = manifest(home, 'base/product-manifest.tsv')
    # Retired rows count too: a file that ships again is still a product file, not the person's.
    old_names = {row['path'] for row in old_rows}
    source_rows = manifest(tree, 'product-manifest.tsv')
    files = {}
    modes = {}
    listed = []
    # Only these files are checked for the person's changes: product rows, never starters or .local files.
    product = set()
    workflow_record = regular(home, 'skillwright/workflows/.release-manifest.json')
    workflows = json.loads(workflow_record.read_text()) if workflow_record.exists() else {'version': 1, 'workflows': {}}
    if workflows.get('version') != 1 or not isinstance(workflows.get('workflows'), dict):
        raise ValueError('Invalid workflow release record')
    workflow_names = {Path(row['path']).stem for row in source_rows
                      if row['path'].startswith('skillwright/workflows/') and row['path'].endswith('.yaml')}
    workflow_files = {}
    # A skill-ship release link is checked here; any other link on an update path still refuses.
    shelf = ReleaseShelf(tree, home) if (home / SHELF).is_symlink() else None
    for row in source_rows:
        name = row['path']
        if name in installer.BUILD_ONLY or personal(name, set(installer.STARTERS)):
            continue
        source = regular(tree, name)
        raw = source.read_bytes()
        if shelf is not None and Path(name).parts[0] == SHELF:
            held = shelf.plan(name, raw, source.stat().st_mode & 0o777)
            if held is not None:
                listed.append(file_row(name, held))
            continue
        # Match install.py: the transport list selects files; hash the bytes actually copied.
        target = regular(home, name)
        if (name.startswith('skillwright/workflows/') and Path(name).stem in workflow_names
                and Path(name).suffix in ('.yaml', '.md')):
            snapshot = 'skillwright/workflows/.product/' + Path(name).name
            regular(home, snapshot)
            files[snapshot], modes[snapshot] = raw, source.stat().st_mode & 0o777
            workflow_files.setdefault(Path(name).stem, {})[Path(name).name] = dict(
                bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            record = workflows['workflows'].get(Path(name).stem, {})
            if record.get('owner') == 'person':
                raw = target.read_bytes()
                listed.append(file_row(name, raw))
                continue
        files[name] = raw
        modes[name] = source.stat().st_mode & 0o777
        listed.append(file_row(name, raw))
        product.add(name)
    if shelf is not None:
        shelf.check()
    for stem, rows in workflow_files.items():
        if workflows['workflows'].get(stem, {}).get('owner') != 'person':
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            workflows['workflows'][stem] = dict(owner='product', source='product:' + stem + '.yaml',
                release_id='installed-' + digest[:12], digest=digest, files=rows)
    files['skillwright/workflows/.release-manifest.json'] = (json.dumps(workflows, indent=2, sort_keys=True) + '\n').encode()
    modes['skillwright/workflows/.release-manifest.json'] = 0o644
    # The next update without --source finds this product folder here.
    files[SOURCE_RECORD], modes[SOURCE_RECORD] = source_record(tree), 0o644
    # Retired product files stay on disk. Their rows stay in the home list with the retired marker,
    # so a release that ships the path again replaces the file. A path that is now personal leaves the list.
    # Never walk the portfolio or rebuild starter settings, seats, pages, or release shelves.
    current = {row['path'] for row in listed}
    for row in old_rows:
        name = row['path']
        if name in current or name in installer.BUILD_ONLY or personal(name, set(installer.STARTERS)):
            continue
        sha = row['sha256'] if row['sha256'].startswith(RETIRED) else RETIRED + row['sha256']
        listed.append(dict(path=name, bytes=row['bytes'], sha256=sha))
    raw_manifest = table_bytes(sorted(listed, key=lambda row: row['path']))
    for name in ('product-manifest.tsv', 'base/product-manifest.tsv'):
        regular(home, name)
        files[name], modes[name] = raw_manifest, 0o644
    # Update writes these itself, so they are never the person's changes.
    product -= {'skillwright/workflows/.release-manifest.json', SOURCE_RECORD,
                'product-manifest.tsv', 'base/product-manifest.tsv'}
    installed = {row['path']: row['sha256'][len(RETIRED):] if row['sha256'].startswith(RETIRED) else row['sha256']
                 for row in old_rows}
    migration = files.get('work/apply.sql')
    if migration is None:
        raise ValueError('Source has no work/apply.sql migration')
    backup_root = home / 'backups'
    if backup_root.is_symlink() or (backup_root.exists() and not backup_root.is_dir()):
        raise ValueError('Backup folder must be a regular folder')
    lock = acquire_lock(home)
    released = None
    try:
        if shelf is not None:
            shelf.lock()
        backup_root.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = Path(tempfile.mkdtemp(prefix='update-' + stamp + '-', dir=str(backup_root)))
        print('Update backup: ' + str(backup), flush=True)
        from base import person
        with closing(person.connect(str(database))) as original:
            original.execute('PRAGMA foreign_keys = ON')
            # SQLite itself excludes every writer, including tools from older installs.
            # Hold this transaction until files and the database pass Doctor together.
            original.execute('BEGIN IMMEDIATE')
            try:
                with closing(sqlite3.connect(str(database))) as reader, closing(sqlite3.connect(str(backup / 'data.db'))) as saved:
                    reader.backup(saved)
                trial = backup / 'migration-check.db'
                shutil.copy2(backup / 'data.db', trial)
                migrate(trial, migration.decode('utf-8'))
                previous = {}
                for name in files:
                    target = regular(home, name)
                    previous[name] = (target.read_bytes(), target.stat().st_mode & 0o777) if target.exists() else None
                    if previous[name] is not None:
                        saved = backup / 'files' / name
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, saved)
                (backup / 'new-files.json').write_text(json.dumps([name for name, old in previous.items() if old is None]) + '\n')
                # A product file whose bytes differ from the home list was changed by the person.
                # A new product path the home already holds is adopted when its bytes match the release; else it is kept.
                edited = sorted(name for name in product if previous[name] is not None and (
                    hashlib.sha256(previous[name][0]).hexdigest() != installed[name] if name in installed
                    else previous[name][0] != files[name]))
                changed = []
                kept = []
                try:
                    apply_migration(original, migration.decode('utf-8'))
                    for name in edited:
                        kept.append(keep_local_edit(home / name, previous[name][0], stamp))
                    for name, raw in files.items():
                        replace(home / name, raw, modes[name])
                        changed.append(name)
                    if shelf is not None:
                        try:
                            released = shelf.ship()
                        except RuntimeError as error:
                            raise ValueError('Skill release failed: ' + str(error))
                    # Use the refreshed Doctor and the same connection. It sees the
                    # uncommitted migration while competing writers remain excluded.
                    spec = importlib.util.spec_from_file_location('update_doctor', str(home / 'foxrun.py'))
                    doctor = importlib.util.module_from_spec(spec)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        spec.loader.exec_module(doctor)
                        result = doctor.doctor(connection=original)
                    if result:
                        print(output.getvalue(), end='')
                        raise ValueError('Updated doctor failed')
                    if shelf is not None:
                        shelf.finish()
                    original.commit()
                except BaseException:
                    for name in reversed(changed):
                        if previous[name] is None:
                            (home / name).unlink()
                        else:
                            replace(home / name, *previous[name])
                    # The person's file is back at its own path. A copy that is already gone must not stop the rollback.
                    for copy in kept:
                        try:
                            copy.unlink()
                        except OSError:
                            pass
                    if shelf is not None:
                        try:
                            shelf.rollback()
                        except Exception as error:
                            print('Skill shelf rollback failed; run skill-ship recover: ' + str(error), file=sys.stderr)
                    print('Update rolled back; backup: ' + str(backup), file=sys.stderr)
                    raise
            finally:
                # Roll back before releasing the writer lock. Never restore an old
                # snapshot over changes that another task writer has committed.
                original.rollback()
        if kept:
            print('You changed these product files, or had your own file at a product path. Update kept your copy beside each new file:')
            for copy in kept:
                print('  ' + str(copy))
            print('Move your change into a .local file.')
        if released:
            print('Skill shelf: ' + str(home / SHELF) + ' now links to release ' + released +
                  '. The previous release stays for rollback: ' + str(shelf.target))
        prune_backups(backup_root, backup)
        print(output.getvalue(), end='')
        return 0
    finally:
        if shelf is not None:
            shelf.close()
        release_lock(lock)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('FOXRUN_HOME', Path.home() / '.foxrun')))
    parser.add_argument('--source', type=Path, help='product folder; default: this one, then the recorded one')
    args = parser.parse_args(argv)
    try:
        source = args.source
        if source is not None:
            # An explicit source passes the same checks as a recorded one before any of its code runs.
            source = Path(os.path.realpath(str(source.expanduser())))
            if not is_source(source):
                raise ValueError('The source ' + str(args.source) + ' is not a product folder.')
            unsafe = source_unsafe(source)
            if unsafe:
                raise ValueError('The source ' + str(args.source) + ' is not safe to run: ' + unsafe + '.')
        else:
            source = find_source(args.home)
        if source != HERE:
            # Run the checked source's own update code, never this installed copy.
            # -I keeps PYTHON* settings, the user site, and the working folder out of its imports.
            return subprocess.run([sys.executable, '-I', '-B', str(source / 'update.py'),
                                   '--source', str(source), '--home', str(args.home)]).returncode
        return update(source, args.home)
    except (OSError, ValueError, sqlite3.Error, ImportError) as error:
        print('Update refused or failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    # Isolated mode (-I) leaves this folder off sys.path; base/ comes from this checked tree.
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    raise SystemExit(main())
