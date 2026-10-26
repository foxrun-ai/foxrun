#!/usr/bin/env python3
"""List old-name dependencies and test a rename in an offline scratch copy."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import ast
import base64
import binascii
import csv
from datetime import datetime, timezone
import fnmatch
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import warnings

SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist',
             'build', '.next', '.cache', 'target', 'coverage', 'vendor',
             'site-packages', 'sessions', 'logs', 'raw', '.wrangler-dry-run'}
CONFIRM_SKIP_DIRS = {'logs', 'sessions', 'raw', 'build', 'dist', 'target', 'vendor', 'coverage'}
SETTINGS = {'settings.json', 'config.toml', 'config.yaml', 'config.yml'}
DATA_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.png', '.jpg', '.jpeg', '.pdf',
                 '.zip', '.gz', '.pyc', '.woff', '.woff2', '.lock', '.map'}
FIELDS = ['thing', 'path', 'line', 'access', 'program', 'test', 'how_found', 'sure',
          'confirmation_decision', 'confirmation_by', 'confirmation_at', 'confirmation_reason']
PRIVATE_WORDS = re.compile(r'(?:^|[^a-z0-9])(?:secrets?|credentials?|tokens?|auth|oauth|keys?|passwords?)(?:$|[^a-z0-9])', re.I)
SOURCE_SUFFIXES = {'.py', '.go', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rb', '.rs',
                   '.java', '.kt', '.swift', '.c', '.h', '.cpp', '.cs', '.php', '.sh', '.zsh',
                   '.bash', '.sql', '.lua'}
KEY_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.keystore', '.jks', '.crt', '.cer'}
PRIVATE_DIRS = {'.ssh', '.gnupg', '.aws', '.credentials', 'secrets', 'mcp', '.codex'}
PRIVATE_KEY_NAME = re.compile(r'^id_(?:rsa|dsa|ecdsa|ed25519|ed448)', re.I)
SQL_SHAPE = re.compile(r'\b(?:SELECT\s+(?:\*|[^;\n]*\bFROM\b)|DELETE\s+FROM\b|'
                       r'(?:INSERT|REPLACE)(?:\s+OR\s+\w+)?\s+INTO\b|UPDATE\s+[^;\n]*\bSET\b|'
                       r'(?:CREATE|ALTER|DROP)\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW|INDEX|TRIGGER)\b|'
                       r'WITH\s+\w+\s+AS\b|PRAGMA\s+\w+)', re.I)
SQL_IDENTIFIER = re.compile(r'(?:^|_)(?:sql|query|stmt|statement)(?:$|_)', re.I)
JS_SQL_CALL = re.compile(r'\.(?:execute|executemany|executescript|prepare|query)\s*\(')
JS_SHARED_CALL = re.compile(r'\.(?:run|exec|get|all)\s*\(')
JS_BUILT_PART = re.compile(r'\$\{|\+|\.(?:join|format)\s*\(')


class InvalidPlan(ValueError):
    pass


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def private_tree(path: Path) -> bool:
    parts = path.parts
    return (any(p.lower() in PRIVATE_DIRS or p.lower().startswith('.env') for p in parts) or
            ('.claude' in parts and 'mcp' in parts))


def private_named_path(path: Path) -> bool:
    return (private_tree(path) or any(PRIVATE_WORDS.search(p) for p in path.parts) or
            key_file_name(path) or bool(PRIVATE_KEY_NAME.match(path.name)))


def key_file_name(path: Path) -> bool:
    return path.name.lower() in KEY_SUFFIXES or any(s.lower() in KEY_SUFFIXES for s in path.suffixes)


def private_path(path: Path) -> bool:
    """A source extension permits scanning, but cannot override a protected tree/key."""
    if private_tree(path) or key_file_name(path) or PRIVATE_KEY_NAME.match(path.name):
        return True
    if path.is_dir():
        return False
    return private_named_path(path) and (path.suffix.lower() not in SOURCE_SUFFIXES or
                                         path.resolve().suffix.lower() not in SOURCE_SUFFIXES)


def gitignored_path(path: Path, cache: dict | None = None) -> bool:
    """Use Git's own ignore answer in repositories; keep every value out of output."""
    cache = {} if cache is None else cache
    folders = []
    repository = None
    for folder in path.absolute().parents:
        folders.append(folder)
        if (folder/'.git').exists():
            repository = folder
            break
    if repository is not None:
        key = ('git-answer', path.absolute())
        if key not in cache:
            try:
                result = subprocess.run(['git', '-C', str(repository), 'check-ignore', '--no-index',
                                         '--quiet', '--', str(path.absolute())],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                # A failed ignore check cannot authorize a source open.
                cache[key] = result.returncode != 1
            except (OSError, subprocess.TimeoutExpired):
                cache[key] = True
        return cache[key]
    relative_path = path.absolute()
    for folder in reversed(folders):
        ignore = folder/'.gitignore'
        if ignore not in cache:
            if not ignore.exists():
                cache[ignore] = []
            elif ignore.is_symlink() or private_tree(ignore):
                cache[ignore] = None
            else:
                try: cache[ignore] = ignore.read_text(encoding='utf-8').splitlines()
                except (OSError, UnicodeError): cache[ignore] = None
        rules = cache[ignore]
        if rules is None:
            return True
        relative = relative_path.relative_to(folder).as_posix()
        parts = relative.split('/')
        prefixes = ['/'.join(parts[:i]) for i in range(1, len(parts)+1)]
        for rule in rules:
            rule = rule.rstrip()
            if not rule or rule.startswith(('#', '!')):
                continue
            anchored = rule.startswith('/')
            rule = rule.lstrip('/').rstrip('/')
            rule = re.sub(r'\\([ #!\\])', r'\1', rule)
            if '/' not in rule and not anchored:
                if any(fnmatch.fnmatchcase(part, rule) for part in parts):
                    return True
            elif any(ignore_glob(rule.split('/'), prefix.split('/')) for prefix in prefixes):
                return True
    return False


def ignore_glob(pattern: list[str], parts: list[str]) -> bool:
    """Git's slash-separated ** spans zero or more folders; * stays in one folder."""
    if not pattern:
        return not parts
    if pattern[0] == '**':
        if len(pattern) == 1:
            return bool(parts)  # A trailing /** matches contents, not the parent itself.
        return any(ignore_glob(pattern[1:], parts[index:]) for index in range(len(parts)+1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pattern[0]) and ignore_glob(pattern[1:], parts[1:])


PEM_HEADER = re.compile(rb'^\s*-----BEGIN [A-Z0-9 ][A-Z0-9 -]*-----')
CODE_LINE = re.compile(r'^\s*(?:[#]|//|/\*|\*|--|<!--|(?:import|from|package|use|using|namespace|'
                       r'export|const|let|var|def|class|func|function|return|if|else|for|while|'
                       r'try|except|catch|finally|raise|throw|public|private|protected|async|await|'
                       r'select|insert|update|delete|create|alter|drop|pragma)\b)|'
                       r'[(){}\[\];]|(?:^|\s)[A-Za-z_$][\w.$]*(?:\s*:[^=]{1,80})?\s*(?:=|:=)', re.I)
ENCODED_LINE = re.compile(r'^[A-Za-z0-9+/_=-]{48,}$')
QUOTED_TEXT = re.compile(r"'([^'\r\n]*)'|\"([^\"\r\n]*)\"|`([^`\r\n]*)`")
BASE64_LITERAL = re.compile(r'(?<![A-Za-z0-9+/_=-])([A-Za-z0-9+/_-]{40,}={0,2})(?![A-Za-z0-9+/_=-])')
SHA256_HEX = re.compile(r'^[0-9a-fA-F]{64}$')


def assigned_encoded_material(line: str) -> bool:
    """Close long canonical base64 literals, including data URIs; retain SHA-256 hex constants."""
    for quoted in QUOTED_TEXT.finditer(line):
        value = next(part for part in quoted.groups() if part is not None)
        for candidate in BASE64_LITERAL.finditer(value):
            encoded = candidate[1]
            if SHA256_HEX.fullmatch(encoded):
                continue
            normalized = encoded.replace('-', '+').replace('_', '/')
            try:
                decoded = base64.b64decode(normalized+'='*(-len(normalized)%4), validate=True)
            except (ValueError, binascii.Error):
                continue
            canonical = base64.b64encode(decoded).decode('ascii')
            if (canonical.rstrip('=') == normalized.rstrip('=') and
                    (not normalized.endswith('=') or normalized == canonical)):
                return True
            del decoded, canonical
    return False


def source_first_look(path: Path) -> bool:
    """Classify source in memory without retaining bytes, searching identifiers, or copying it."""
    try:
        with path.open('rb') as handle:
            first = handle.read(256).removeprefix(b'\xef\xbb\xbf')
            if PEM_HEADER.match(first):
                return False
            del first
            handle.seek(0)
            total = code = 0
            for raw in handle:
                if PEM_HEADER.match(raw.removeprefix(b'\xef\xbb\xbf')):
                    return False
                if b'\0' in raw:
                    return False
                line = raw.decode('utf-8-sig').strip()
                if not line:
                    continue
                if assigned_encoded_material(line):
                    return False
                total += 1
                if not ENCODED_LINE.fullmatch(line) and (
                        CODE_LINE.search(line) or
                        (path.suffix.lower() in {'.sh', '.zsh', '.bash'} and
                         re.match(r'^[\w./-]+\s+\S', line))):
                    code += 1
                del raw, line
            return total == 0 or code > total/2
    except (OSError, UnicodeError):
        # Let the normal read record its existing unreadable-source gap.
        return True


def closed_file_paths(path: Path) -> set[str]:
    """Count excluded files by path metadata only, without following directory links."""
    if not path.is_dir():
        return {str(path)} if path.is_file() or path.is_symlink() else set()
    return {str(Path(folder)/name) for folder, _, files in os.walk(path, followlinks=False) for name in files}


def is_settings(path: Path) -> bool:
    if path.suffix.lower() in SOURCE_SUFFIXES:
        return False
    name = path.name.lower()
    return (name in SETTINGS or name == '.claude.json' or name.startswith('settings.') or
            (name.startswith('config.') and path.suffix not in {'.py', '.js', '.ts'}))


def boundary(name: str) -> re.Pattern:
    return re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])', re.I)


def strings(node, bindings) -> set[str]:
    """Bounded static expansion; unknown expressions cannot imply clearance."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return bindings.get(node.id, set())
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return set().union(*(strings(n, bindings) for n in node.elts))
    if isinstance(node, ast.IfExp):
        return strings(node.body, bindings) | strings(node.orelse, bindings)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = strings(node.left, bindings), strings(node.right, bindings)
        return {a + b for a, b in itertools.islice(itertools.product(left, right), 64)}
    if isinstance(node, ast.JoinedStr):
        choices = [strings(n.value, bindings) if isinstance(n, ast.FormattedValue)
                   else strings(n, bindings) for n in node.values]
        if any(not choice for choice in choices):
            return set()
        return {''.join(values) for values in itertools.islice(itertools.product(*choices), 64)}
    return set()


def complete_strings(node, bindings, uncertain) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.Name):
        return bool(bindings.get(node.id)) and node.id not in uncertain
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(complete_strings(n, bindings, uncertain) for n in node.elts)
    if isinstance(node, ast.IfExp):
        return complete_strings(node.body, bindings, uncertain) and complete_strings(node.orelse, bindings, uncertain)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return complete_strings(node.left, bindings, uncertain) and complete_strings(node.right, bindings, uncertain)
    if isinstance(node, ast.JoinedStr):
        return all(complete_strings(n.value if isinstance(n, ast.FormattedValue) else n, bindings, uncertain)
                   for n in node.values)
    return False


def sql_access(text: str, name: str) -> str | None:
    quoted = r'["`\[]?' + re.escape(name) + r'(?:["`\]]|\b)'
    writes = re.search(r'\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM|'
                       r'(?:CREATE|ALTER|DROP)\s+TABLE(?:\s+IF\s+(?:NOT\s+)?EXISTS)?)\s+' + quoted, text, re.I)
    reads = re.search(r'\b(?:FROM|JOIN|REFERENCES)\s+' + quoted, text, re.I)
    if writes and reads and not re.search(r'\bDELETE\s+FROM\s+' + quoted, text, re.I):
        return 'both'
    if writes:
        return 'write'
    if reads:
        return 'read'
    return None


def python_sql_context(call, bindings, expressions) -> bool:
    """Follow SQL arguments, including incomplete bindings, without naming receivers."""
    if call.func.attr in {'executemany', 'executescript', 'read_sql', 'read_sql_query', 'read_sql_table'}:
        return True
    pending = [call.args[0]]; visited = set()
    while pending:
        expression = pending.pop()
        if any(SQL_SHAPE.search(value) for value in strings(expression, bindings)):
            return True
        for node in ast.walk(expression):
            if isinstance(node, ast.Name):
                if SQL_IDENTIFIER.search(node.id):
                    return True
                if node.id not in visited:
                    visited.add(node.id)
                    pending.extend(expressions.get(node.id, []))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL_SHAPE.search(node.value):
                return True
    # Unknown execute arguments can hide readers. Bare, unbound task/job calls
    # are the generic executor controls; SQL evidence above takes precedence.
    argument = call.args[0]
    return not (isinstance(argument, ast.Name) and argument.id in {'task', 'job'}
                and argument.id not in expressions and argument.id not in bindings)


def javascript_dynamic_sql(line: str) -> bool:
    calls = list(JS_SQL_CALL.finditer(line))
    # Shared methods also serve Maps, regular expressions and job runners.
    # A SQL argument identifies their database use without a receiver whitelist.
    for call in JS_SHARED_CALL.finditer(line):
        argument = line[call.end():].lstrip()
        identifier = re.match(r'[A-Za-z_$][\w$]*', argument)
        if (identifier and SQL_IDENTIFIER.search(identifier.group())) or SQL_SHAPE.search(argument):
            calls.append(call)
    # A SQL call with an unknown argument remains a review location.
    for call in calls:
        argument = line[call.end():].lstrip()
        if argument and argument[0] not in {'"', "'", '`', ')'}:
            return True
    for built in JS_BUILT_PART.finditer(line):
        before = line[:built.start()]
        if SQL_SHAPE.search(before) or any(call.end() <= built.start() for call in calls):
            return True
    return False


def python_sql(text: str, name: str) -> list[tuple[int, str, bool]]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            tree = ast.parse(text)
    except SyntaxError:
        return []
    bindings = {}; uncertain = set(); expressions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    expressions.setdefault(target.id, []).append(node.value)
    # Repeat to resolve constants defined after another binding or loop alias.
    for _ in range(3):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                values = strings(node.value, bindings)
                for target in targets:
                    if isinstance(target, ast.Name) and values:
                        bindings.setdefault(target.id, set()).update(values)
                    if isinstance(target, ast.Name) and not complete_strings(node.value, bindings, uncertain):
                        uncertain.add(target.id)
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                values = strings(node.iter, bindings)
                if values:
                    bindings.setdefault(node.target.id, set()).update(values)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {'execute', 'executemany', 'executescript', 'read_sql',
                                  'read_sql_query', 'read_sql_table'} or not node.args:
            continue
        expression = node.args[0]
        values = strings(expression, bindings)
        unresolved = not values or len(values) >= 64 or not complete_strings(expression, bindings, uncertain)
        if unresolved and python_sql_context(node, bindings, expressions):
            found.add((expression.lineno, 'reference', False))
        for value in values:
            access = sql_access(value, name)
            if access:
                line = node.args[0].lineno
                if isinstance(node.args[0], (ast.Constant, ast.JoinedStr)):
                    match = boundary(name).search(value)
                    if match:
                        line += value[:match.start()].count('\n')
                found.add((line, access, not unresolved))
    return sorted(found)


def settings_locations(path: Path, patterns: list) -> tuple[list, str]:
    """Python fallback: keep only identifier locations and a byte hash, never values."""
    digest = hashlib.sha256(); locations = []
    with path.open('rb') as handle:
        for number, data in enumerate(handle, 1):
            digest.update(data)
            text = data.decode('utf-8')
            if '\0' in text:
                raise UnicodeError('binary settings')
            if any(p.search(text) for p in patterns):
                locations.append((number, 'reference', 'identifier-only settings search', 'needs a look'))
    return locations, digest.hexdigest()


def valid_confirmation(confirmation: dict, plan: dict) -> bool:
    if (confirmation.get('decision') not in {'reader', 'unrelated'} or
            not isinstance(confirmation.get('reason'), str) or not confirmation['reason'].strip() or
            not isinstance(plan.get('work_lead'), str) or not plan['work_lead'].strip() or
            confirmation.get('by') != plan['work_lead']):
        return False
    try:
        return datetime.fromisoformat(confirmation['at'].replace('Z', '+00:00')).tzinfo is not None
    except (KeyError, AttributeError, TypeError, ValueError):
        return False


def load_plan(plan: dict, out: Path, scratch: Path) -> dict:
    if inside(out.resolve(), scratch.resolve()):
        raise InvalidPlan('reports cannot be inside disposable scratch')
    if any((parent/'.git').exists() for parent in [scratch.resolve(), *scratch.resolve().parents]):
        raise InvalidPlan('scratch cannot be inside a repository')
    thing = plan.get('thing', {})
    if thing.get('kind') not in {'table', 'file', 'folder', 'program'} or not thing.get('name'):
        raise InvalidPlan('thing requires kind and name')
    if thing['kind'] == 'table' and not thing.get('database'):
        raise InvalidPlan('table requires database')
    if not plan.get('roots'):
        raise InvalidPlan('at least one search root is required')
    roots = []
    for raw in plan['roots']:
        root = {'path': raw} if isinstance(raw, str) else {k: raw[k] for k in ('path', 'program', 'database', 'role') if k in raw}
        root['path'] = str(Path(root['path']).expanduser().absolute())
        root.setdefault('program', Path(root['path']).name)
        roots.append(root)
    plan = {**plan, 'roots': roots}
    sources = [Path(r['path']).resolve() for r in roots]
    sources += [Path(r['workspace']).expanduser().resolve() for r in plan.get('readers', []) if r.get('workspace')]
    if thing.get('path'):
        sources.append(Path(thing['path']).expanduser().resolve())
    if thing.get('database'):
        sources.append(Path(thing['database']).expanduser().resolve().parent)
    # Follow metadata only, so a report cannot overwrite a checked link destination.
    for root in roots:
        root_path = Path(root['path'])
        if private_path(root_path) or private_path(root_path.resolve()):
            continue
        for path in walk_root(Path(root['path']), [], []):
            if path.is_symlink():
                sources.append(path.resolve())
        for folder, dirs, files in os.walk(root['path'], followlinks=False):
            for name in dirs + files:
                path = Path(folder)/name
                if path.is_symlink():
                    sources.append(path.resolve())
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not private_path(Path(folder)/d)]
    protected = [Path.home()/name for name in ['.small-talk', '.agents', '.claude', '.codex', '.hermes',
                 'Code', 'bin', 'Library/LaunchAgents']]
    from base import paths as configured_paths
    protected += [configured_paths.system_home(), configured_paths.portfolio(), configured_paths.state()]
    destinations = [out.resolve(), scratch.resolve()]
    for filename in ['readers.csv', 'verdict.json', 'scan.json', 'test-results.json']:
        target = out/filename
        if target.is_symlink():
            raise InvalidPlan('report files cannot be symbolic links')
        destinations.append(target.resolve())
    for dest in destinations:
        if any(inside(dest, p) or inside(p, dest) for p in sources):
            raise InvalidPlan('output and scratch must be disjoint from sources')
        if any(inside(dest, p.resolve()) or inside(p.resolve(), dest) for p in protected):
            raise InvalidPlan('output and scratch cannot enter live runtime state')
    return plan


def skip_place(skipped: list, path: Path, reason: str, category: str, requires_confirmation: bool):
    skipped.append({'path': str(path), 'reason': reason, 'category': category,
                    'requires_confirmation': requires_confirmation})


def walk_root(root: Path, gaps: list, skipped: list):
    if private_path(root) or private_path(root.resolve()):
        parents = [root.parent, root.resolve().parent]
        under_private = any(private_tree(p) for p in parents)
        reason = ('root is under a protected private folder; not searched; work lead must confirm'
                  if under_private else 'root has a private name; not searched; work lead must confirm')
        skip_place(skipped, root, reason, 'private root', True)
        return
    if root.is_dir() and root.name in SKIP_DIRS:
        required = root.name in CONFIRM_SKIP_DIRS
        skip_place(skipped, root, 'excluded unsearched tree' if required else 'excluded dependency tree',
                   'unsearched tree' if required else 'dependency', required)
        return
    if not root.exists():
        gaps.append({'path': str(root), 'reason': 'missing root or broken link'})
        return
    if root.is_file():
        yield root
        return
    seen = set()
    def onerror(error):
        gaps.append({'path': str(error.filename), 'reason': 'unreadable directory'})
    for folder, dirs, files in os.walk(root, followlinks=True, onerror=onerror):
        here = Path(folder)
        try:
            key = (here.stat().st_dev, here.stat().st_ino)
        except OSError:
            gaps.append({'path': str(here), 'reason': 'unreadable directory'})
            dirs[:] = []
            continue
        if key in seen:
            dirs[:] = []
            continue
        seen.add(key)
        keep = []
        for d in dirs:
            p = here/d
            if private_path(p) or private_path(p.resolve()):
                skip_place(skipped, p, 'excluded private tree', 'private', True)
            elif d in SKIP_DIRS:
                required = d in CONFIRM_SKIP_DIRS
                skip_place(skipped, p, 'excluded unsearched tree' if required else 'excluded dependency tree',
                           'unsearched tree' if required else 'dependency', required)
            else:
                keep.append(d)
        dirs[:] = keep
        for filename in files:
            yield here/filename


def scan(plan: dict) -> tuple[list, dict]:
    thing = plan['thing']; name = thing['name']
    names = list(dict.fromkeys([name, *thing.get('aliases', [])]))
    if thing['kind'] in {'file', 'folder'}:
        names += [Path(name).name]
    if thing['kind'] == 'program':
        names += [Path(name).name.replace('-', '_')]
    if thing.get('path'):
        names += [thing['path']]
    database = str(Path(thing['database']).expanduser().resolve()) if thing.get('database') else None
    if database:
        db_path = Path(database)
        names += [database, db_path.name, db_path.stem, db_path.stem.replace('-', '_')]
        if db_path.parent.name.startswith('.'):
            names += [db_path.parent.name]
        if '_' in name:
            orm = ''.join(part.capitalize() for part in name.split('_'))
            names += [orm, orm[:-1] if orm.endswith('s') else orm]
    names = list(dict.fromkeys(names))
    patterns = [boundary(n) for n in names]
    confirmations = {(str(Path(c['path']).expanduser().absolute()), int(c['line'])): c
                     for c in plan.get('confirmations', [])}
    reader_programs = {r['program'] for r in plan.get('readers', [])}
    rows = {}; gaps = []; skipped = []; files_read = 0; digests = {}; applied = []
    private_searched = set(); ignore_cache = {}
    for root in plan['roots']:
        for path in walk_root(Path(root['path']), gaps, skipped):
            if private_path(path) or private_path(path.resolve()):
                skip_place(skipped, path, 'excluded private file', 'private', True)
                continue
            if gitignored_path(path, ignore_cache) or gitignored_path(path.resolve(), ignore_cache):
                skip_place(skipped, path, 'excluded Git-ignored file; contents closed', 'private', True)
                continue
            if path.suffix.lower() in DATA_SUFFIXES or path.name.endswith(('-wal', '-shm')):
                skip_place(skipped, path, 'excluded data file', 'data', False)
                continue
            if is_settings(path):
                try:
                    candidates, digest = settings_locations(path, patterns)
                    files_read += 1
                except (OSError, UnicodeError):
                    gaps.append({'path': str(path), 'reason': 'identifier-only settings search failed'})
                    continue
            else:
                if path.suffix.lower() in SOURCE_SUFFIXES and not source_first_look(path):
                    skip_place(skipped, path, 'source first look rejected key or non-code content; not searched', 'private', True)
                    continue
                try:
                    content = path.read_bytes()
                    if b'\0' in content:
                        skip_place(skipped, path, 'binary file', 'binary', True)
                        continue
                    text = content.decode('utf-8')
                except (OSError, UnicodeError):
                    gaps.append({'path': str(path), 'reason': 'unreadable text or broken link'})
                    if private_named_path(path) or private_named_path(path.resolve()):
                        skip_place(skipped, path, 'unreadable private-named source; contents suppressed', 'private', True)
                    continue
                files_read += 1
                if private_named_path(path) or private_named_path(path.resolve()):
                    private_searched.add(str(path))
                digest = hashlib.sha256(content).hexdigest()
                db_context = (database is not None and (root.get('database') and
                              str(Path(root['database']).expanduser().resolve()) == database))
                if database and (database in text or (Path(database).name in text and Path(database).parent.name in text)):
                    db_context = True
                candidates = []
                for number, line in enumerate(text.splitlines(), 1):
                    if any(p.search(line) for p in patterns):
                        access = sql_access(line, name) if thing['kind'] == 'table' else 'reference'
                        sure = 'yes' if (thing['kind'] != 'table' and boundary(name).search(line)) else 'needs a look'
                        if thing['kind'] == 'table' and access and db_context:
                            sure = 'yes'
                        if root.get('role') in {'skill', 'contract'} and db_context:
                            sure = 'yes'
                        how = 'identifier search'+('; SQL '+access if access else '')
                        if thing['kind']=='table' and not boundary(name).search(line) and not access:
                            how = 'database/module/ORM reference; table access needs confirmation'
                        candidates.append((number, access or 'reference', how, sure))
                if thing['kind'] == 'table' and path.suffix == '.py':
                    for number, access, proven in python_sql(text, name):
                        candidates.append((number, access,
                                           'Python SQL constants/list/concatenation/f-string' if proven else 'unresolved Python SQL construction',
                                           'yes' if db_context and proven else 'needs a look'))
                if thing['kind'] == 'table' and path.suffix in {'.js', '.ts', '.mjs', '.cjs', '.jsx', '.tsx'}:
                    for number, line in enumerate(text.splitlines(), 1):
                        if javascript_dynamic_sql(line):
                            candidates.append((number, 'reference', 'unresolved JavaScript SQL construction', 'needs a look'))
                if path.suffix == '.plist':
                    # A plist is a dependency contract. Match locations only; never expose argument values.
                    candidates = [(n, a, 'LaunchAgent executable/contract identifier', s) for n, a, _, s in candidates]
                del content, text
            digests[str(path)] = digest
            for number, access, how, sure in candidates:
                private_source = path.suffix.lower() in SOURCE_SUFFIXES and private_named_path(path)
                row = dict(thing=name, path=str(path), line=number, access=access,
                           program=root['program'], test=('found; not dry-tested: private-named file' if private_source else
                                                          'configured' if root['program'] in reader_programs else 'not supplied'),
                           how_found=how, sure=sure)
                key = (str(path), number)
                previous = rows.get(key)
                if previous and (previous['access'] != 'reference' and access == 'reference' or
                                 previous['sure']=='yes' and sure!='yes'):
                    continue
                rows[key] = row
    # Dependency trees/data stay listed in the scan. Only required skips become lead review rows.
    skipped = list({s['path']: s for s in skipped}.values())
    private_closed = set().union(*(closed_file_paths(Path(s['path'])) for s in skipped
                                  if s['category'] in {'private', 'private root'} or
                                  (s['category']=='binary' and private_named_path(Path(s['path'])))))
    for place in skipped:
        if not place['requires_confirmation']:
            place['sure'] = 'not searched'
            continue
        root = next((r for r in plan['roots'] if inside(Path(place['path']), Path(r['path']))), plan['roots'][0])
        rows[(place['path'], 0)] = dict(thing=name, path=place['path'], line=0, access='unsearched',
                                      program=root['program'], test='not supplied',
                                      how_found=place['reason']+'; path-only lead review required', sure='needs a look')
    for key, row in rows.items():
        for field in FIELDS[8:]:
            row[field] = ''
        private_source = row['test']=='found; not dry-tested: private-named file'
        confirmation = confirmations.get((row['path'], 0) if private_source else key)
        if not confirmation:
            continue
        for field in ['decision', 'by', 'at', 'reason']:
            row['confirmation_'+field] = confirmation.get(field, '')
        valid = valid_confirmation(confirmation, plan)
        if row['line'] and not private_source:
            valid = valid and confirmation.get('sha256') == digests.get(row['path'])
        proven_sql = row['sure']=='yes' and row['access'] in {'read', 'write', 'both'}
        if proven_sql and confirmation.get('decision')=='unrelated':
            valid = False
            reason = 'unrelated confirmation cannot clear proven SQL reader'
        else:
            reason = 'invalid, non-lead, or stale confirmation'
        applied.append({'path': row['path'], 'line': row['line'],
                        **{f: confirmation.get(f, '') for f in ['decision', 'by', 'at', 'reason']}, 'accepted': valid})
        if not valid:
            gaps.append({'path': row['path'], 'line': row['line'], 'reason': reason})
        else:
            row['sure'] = 'yes' if confirmation['decision']=='reader' else 'no'
            row['how_found'] += '; lead confirmation'+(' against SHA-256' if row['line'] and not private_source else ' by path only')
    for place in skipped:
        if not place['requires_confirmation']:
            continue
        row = rows[(place['path'], 0)]
        place.update({k: row[k] for k in ['sure', *FIELDS[8:]]})
    return sorted(rows.values(), key=lambda r: (r['path'], r['line'])), {
        'roots': plan['roots'], 'words': names, 'files_read': files_read,
        'private_named_source_files_searched': len(private_searched),
        'private_named_files_closed': len(private_closed),
        'private_named_closed_rule': 'Closed files still require work lead confirmation by path; folder paths cover their closed files.',
        'gaps': gaps, 'skipped': skipped, 'confirmations': applied,
        'confirmation_hash': 'SHA-256 of current source bytes; private-named source and skipped paths use lead path attestation'}


def sandbox_command(argv: list[str], scratch: Path, cwd: Path, env: dict, timeout: int) -> int:
    executable = shutil.which('sandbox-exec')
    if sys.platform != 'darwin' or not executable:
        raise InvalidPlan('offline scratch tests require macOS sandbox-exec')
    allowed = json.dumps(str(scratch.resolve()))
    profile = ('(version 1) (allow default) (deny network*) (deny file-write*) '
               f'(allow file-write* (subpath {allowed})) '
               '(allow file-write* (literal "/dev/null"))')
    try:
        result = subprocess.run([executable, '-p', profile, *argv], cwd=cwd, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        return result.returncode
    except subprocess.TimeoutExpired:
        return 124
    except OSError:
        return 126


def backup(source: Path, destination: Path, scratch: Path):
    # Even SQLite's WAL helper files cannot be written outside scratch.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    os.close(descriptor)
    code = ('import sqlite3,sys; from pathlib import Path; '
            's=sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+"?mode=ro",uri=True); '
            'd=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()')
    rc = sandbox_command([sys.executable, '-c', code, str(source), str(destination)], scratch,
                         scratch, {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, 60)
    if rc:
        raise InvalidPlan('read-only SQLite backup failed; output suppressed')
    destination.chmod(0o700)


def copy_file(source: Path, target: Path):
    """Create a private copy without inheriting source permissions."""
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(descriptor, 'wb') as destination, source.open('rb') as origin:
        shutil.copyfileobj(origin, destination)


def copy_workspace(source: Path, target: Path):
    ignore_cache = {}
    def exclude(folder, names):
        return [name for name in names if name in SKIP_DIRS or private_named_path(Path(folder)/name)
                or gitignored_path(Path(folder)/name, ignore_cache)
                or (Path(folder)/name).is_symlink() or is_settings(Path(folder)/name)
                or ((Path(folder)/name).is_file() and (Path(folder)/name).suffix.lower() in SOURCE_SUFFIXES
                    and not source_first_look(Path(folder)/name))]
    def copy_folder(origin, destination):
        destination.mkdir(mode=0o700)
        names = list(origin.iterdir())
        excluded = set(exclude(origin, [p.name for p in names]))
        for path in names:
            if path.name in excluded:
                continue
            if path.is_dir():
                copy_folder(path, destination/path.name)
            else:
                copy_file(path, destination/path.name)
    copy_folder(source, target)


def copy_target(source: Path, target: Path):
    if private_named_path(source) or private_named_path(source.resolve()) or gitignored_path(source) or is_settings(source) or source.is_symlink():
        raise InvalidPlan('target is excluded from scratch copies')
    if source.is_file() and source.suffix.lower() in SOURCE_SUFFIXES and not source_first_look(source):
        raise InvalidPlan('target first look rejected key or non-code content; contents suppressed')
    if source.is_dir():
        copy_workspace(source, target)
    elif source.is_file():
        copy_file(source, target)
    else:
        raise InvalidPlan('target is missing or unreadable')


def run_tests(plan: dict, scratch: Path) -> list:
    thing = plan['thing']; results = []
    for index, reader in enumerate(plan.get('readers', [])):
        if not reader.get('offline') or not reader.get('workspace') or not reader.get('commands'):
            raise InvalidPlan('reader tests require offline=true, workspace, and command arrays')
        workspace = Path(reader['workspace']).expanduser().resolve()
        reader_root = Path(reader.get('root', reader['workspace'])).expanduser().absolute()
        if not inside(reader_root.resolve(), workspace):
            raise InvalidPlan('reader test root must be inside its source workspace')
        area = scratch/f'reader-{index}'
        area.mkdir(mode=0o700)
        frozen_workspace = area/'source'
        copy_workspace(Path(reader['workspace']).expanduser().resolve(), frozen_workspace)
        frozen_database = area/'source.db'
        external = False
        if thing['kind'] == 'table':
            backup(Path(thing['database']).expanduser().resolve(), frozen_database, scratch)
        else:
            if not thing.get('path'):
                raise InvalidPlan('file/folder/program tests require thing.path')
            if private_named_path(Path(thing['path']).expanduser()) or gitignored_path(Path(thing['path']).expanduser()) or is_settings(Path(thing['path'])):
                raise InvalidPlan('target is excluded from scratch copies')
            source = Path(thing['path']).expanduser().resolve()
            base = Path(reader['workspace']).expanduser().resolve()
            external = not inside(source, base)
            if external:
                frozen_target = area/'target-source'/source.name
                frozen_target.parent.mkdir(mode=0o700)
                copy_target(source, frozen_target)
        for mode in ['baseline', 'renamed']:
            work = area/mode
            copy_workspace(frozen_workspace, work)
            if thing['kind'] == 'table':
                copy = work/'reader-check-copy.db'
                backup(frozen_database, copy, scratch)
                if mode == 'renamed':
                    import sqlite3
                    with _fox_person.connect(copy) as conn:
                        old = '"'+thing['name'].replace('"', '""')+'"'
                        new = '"'+(thing['name']+'__moved').replace('"', '""')+'"'
                        conn.execute(f'ALTER TABLE {old} RENAME TO {new}')
            else:
                if external:
                    holder = work/'reader-check-target'; holder.mkdir(mode=0o700)
                    original = holder/source.name
                    copy_target(frozen_target, original)
                else:
                    original = work/source.relative_to(base)
                if not original.exists():
                    raise InvalidPlan('target was excluded from the scratch workspace')
                copy = original
                if mode == 'renamed':
                    copy = original.with_name(original.name+'__moved')
                    original.rename(copy)
            replacements = {'{copy}': str(copy), '{workspace}': str(work),
                            '{original}': str(original) if thing['kind']!='table' else str(copy)}
            def expand(value):
                for old, new in replacements.items():
                    value = value.replace(old, new)
                return value
            template_env = reader.get('env', {})
            env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
                   'TMPDIR': str(work), **{key: expand(value) for key, value in template_env.items()}}
            cwd = Path(expand(reader.get('cwd', '{workspace}'))).resolve()
            if not inside(cwd, work) or not cwd.is_dir():
                raise InvalidPlan('test cwd must be inside the copied workspace')
            for command_index, command in enumerate(reader['commands']):
                if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
                    raise InvalidPlan('test command must be a nonempty string array')
                if not any('{copy}' in v for v in command+list(template_env.values())):
                    raise InvalidPlan('each test must explicitly receive {copy}')
                rc = sandbox_command([expand(a) for a in command], scratch, cwd, env, int(reader.get('timeout', 60)))
                recreated = False
                if mode == 'renamed' and thing['kind'] == 'table':
                    import sqlite3
                    if copy.exists():
                        with _fox_person.connect(copy.as_uri()+'?mode=ro', uri=True) as conn:
                            recreated = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (thing['name'],)).fetchone())
                results.append({'program': reader['program'], 'workspace': str(Path(reader['workspace']).expanduser().resolve()),
                                'root': str(reader_root),
                                'mode': mode, 'command_index': command_index,
                                'exit_code': rc, 'old_table_recreated': recreated})
    return results


def dry_test_coverage(plan: dict, tests: list) -> tuple[list, list]:
    """A program name alone cannot prove that a checked root ran a dry test."""
    unproven = []; accepted = []
    for root in plan['roots']:
        path = Path(root['path']).resolve()
        modes = {}
        for test in tests:
            if (test['program'] == root['program'] and
                    Path(test['root']) == Path(root['path']) and
                    inside(path, Path(test['workspace']).resolve())):
                key = (test['workspace'], test['command_index'])
                modes.setdefault(key, set()).add(test['mode'])
        if any(value == {'baseline', 'renamed'} for value in modes.values()):
            continue
        exemption = next((c for c in plan.get('dry_test_exemptions', [])
                          if isinstance(c, dict) and isinstance(c.get('path'), str) and
                          Path(c['path']).expanduser().absolute() == Path(root['path']) and
                          valid_confirmation({**c, 'decision': 'unrelated'}, plan)), None)
        if exemption:
            accepted.append({k: exemption[k] for k in ['path', 'by', 'at', 'reason']})
        else:
            unproven.append({'path': root['path'], 'program': root['program']})
    return unproven, accepted


def check(plan: dict, out: Path, scratch: Path, execute_tests: bool = False,
          keep_copies: bool = False, keep_copies_by: str | None = None) -> tuple[int, dict]:
    out, scratch = out.resolve(), scratch.resolve()
    plan = load_plan(plan, out, scratch)
    if keep_copies and (not execute_tests or not isinstance(plan.get('work_lead'), str) or
                        not plan['work_lead'].strip() or keep_copies_by != plan['work_lead']):
        raise InvalidPlan('keeping copies requires the explicit named work lead')
    rows, scan_result = scan(plan)
    out.mkdir(parents=True, exist_ok=True)
    tests = []
    test_setup_failed = False
    owns_scratch = False
    cleanup_failed = False
    if execute_tests:
        try:
            scratch.mkdir(parents=True, exist_ok=False, mode=0o700)
            owns_scratch = True
            tests = run_tests(plan, scratch)
        except Exception:
            # Always save the scan and a refusal, even if preparing an external target fails.
            # Exception values and command output can hold private text.
            test_setup_failed = True
            scan_result['gaps'].append({'path': str(scratch), 'reason': 'offline test setup failed; details suppressed'})
        except (KeyboardInterrupt, SystemExit):
            if not keep_copies:
                raise
            # An explicit keep request still needs a saved path list on interruption.
            test_setup_failed = True
            scan_result['gaps'].append({'path': str(scratch), 'reason': 'offline tests interrupted; lead explicitly kept copies'})
        finally:
            # Remove only this run's newly created scratch, including partial copies.
            # BaseException (interrupt/SystemExit) also crosses this cleanup boundary.
            if owns_scratch and not keep_copies:
                try:
                    shutil.rmtree(scratch)
                except OSError:
                    cleanup_failed = True
                    scan_result['gaps'].append({'path': str(scratch), 'reason': 'scratch cleanup failed; copies remain private'})
    blockers = [r for r in rows if r['sure'] != 'no']
    reasons = []
    if blockers:
        reasons.append('old readers or unresolved common names remain')
    if scan_result['gaps']:
        reasons.append('search or confirmation is incomplete')
    unconfirmed_skipped = [s for s in scan_result['skipped'] if s['requires_confirmation'] and s['sure']!='no']
    if unconfirmed_skipped:
        reasons.append('skipped places require individual work lead confirmations')
    if plan.get('readers') and not execute_tests:
        reasons.append('configured reader tests were not run')
    if any(t['exit_code'] or t['old_table_recreated'] for t in tests):
        reasons.append('baseline/rename test failed or startup recreated the old table')
    unproven_roots, exemptions = dry_test_coverage(plan, tests)
    if unproven_roots:
        reasons.append('reader roots lack a dry test or named work lead exemption')
        if execute_tests and not tests:
            reasons.append('dry test ran no command; no rename evidence was produced')
    stamp = datetime.now(timezone.utc).isoformat()
    private_copies = sorted(str(p) for p in scratch.rglob('*') if p.is_file()) if owns_scratch and scratch.exists() else []
    cleared = [s for s in scan_result['skipped'] if s['requires_confirmation'] and s['sure']=='no']
    confirmed_by = sorted({s['confirmation_by'] for s in cleared})
    unsearched_roots = [{k: s[k] for k in ['path', 'reason', 'sure', 'confirmation_by']}
                        for s in scan_result['skipped'] if s['category']=='private root']
    unproven_only = (unproven_roots and not blockers and not scan_result['gaps'] and
                     not unconfirmed_skipped and not any(t['exit_code'] or t['old_table_recreated'] for t in tests))
    verdict = {'verdict': ('search found no reader; not proven by a dry test' if unproven_only else
                           'refused' if reasons else 'clear to move'),
               'unsearched_places_cleared': len(cleared), 'confirmed_by': confirmed_by,
               **{k: scan_result[k] for k in ['private_named_source_files_searched', 'private_named_files_closed', 'private_named_closed_rule']},
               'unsearched_roots': unsearched_roots, 'written_utc': stamp, 'thing': plan['thing'],
               'reasons': reasons, 'blocking_readers': blockers, 'scan_gaps': scan_result['gaps'],
               'unconfirmed_skipped': unconfirmed_skipped, 'confirmations': scan_result['confirmations'],
               'tests': tests, 'test_setup_failed': test_setup_failed,
               'unproven_reader_roots': unproven_roots, 'dry_test_exemptions': exemptions,
               'scratch': str(scratch) if execute_tests else None, 'private_scratch_copy_paths': private_copies,
               'private_scratch_copies': private_copies, 'scratch_cleanup_failed': cleanup_failed,
               'copies_kept_by': keep_copies_by if keep_copies else None,
               'cleanup_owner': plan.get('work_lead')}
    with (out/'readers.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)
    for name, value in [('verdict.json', verdict), ('scan.json', {'written_utc': stamp, **scan_result}),
                        ('test-results.json', {'written_utc': stamp, 'tests': tests})]:
        (out/name).write_text(json.dumps(value, indent=2)+'\n')
    return (1 if reasons else 0), verdict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--scratch', type=Path)
    parser.add_argument('--run-tests', action='store_true')
    parser.add_argument('--keep-copies', action='store_true', help='keep private test copies only at the named work lead request')
    parser.add_argument('--keep-copies-by', help='must match work_lead when --keep-copies is supplied')
    args = parser.parse_args(argv)
    previous_term = None
    def interrupt(signum, frame):
        raise KeyboardInterrupt()
    try:
        if threading.current_thread() is threading.main_thread():
            previous_term = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, interrupt)
        if private_path(args.plan):
            raise InvalidPlan('plan cannot be a secret or auth file')
        plan = json.loads(args.plan.read_text())
        code, verdict = check(plan, args.out, args.scratch or args.out/'scratch', args.run_tests,
                              args.keep_copies, args.keep_copies_by)
        print(json.dumps({'verdict': verdict['verdict'], 'unsearched_places_cleared': verdict['unsearched_places_cleared'],
                          **{k: verdict[k] for k in ['private_named_source_files_searched', 'private_named_files_closed', 'private_named_closed_rule']},
                          'confirmed_by': verdict['confirmed_by'], 'reasons': verdict['reasons'],
                          'reader_locations': len(verdict['blocking_readers']), 'written_utc': verdict['written_utc']}))
        return code
    except KeyboardInterrupt:
        print(json.dumps({'verdict': 'refused', 'error': 'run interrupted; clearance refused'}))
        return 130
    except Exception:
        # Path/exception values can contain private data. Print one constant error only.
        print(json.dumps({'verdict': 'refused', 'unsearched_places_cleared': 0, 'confirmed_by': [],
                          'error': 'invalid input, unsafe path, or unavailable offline test sandbox'}))
        return 2
    finally:
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)


if __name__ == '__main__':
    raise SystemExit(main())
