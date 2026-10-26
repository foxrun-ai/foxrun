#!/usr/bin/env python3
"""Read both Foxrun homes. Policy lives beside base/, in config/lint/."""
import argparse
import csv
import fnmatch
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from base.paths import resolve_portfolio_path, discover_workspaces, APP_FOLDERS

POLICY = Path(__file__).resolve().parents[1] / 'config' / 'lint'
SECRET = {'.env', '.ssh', '.netrc', 'auth', 'auth.json', 'credentials',
          'credentials.json', 'secrets', 'id_rsa', '.git-credentials',
          '.aws', 'tokens', 'token.json', 'oauth.json', 'keychain'}
KINDS = {'frontmatter', 'page_spec', 'allowed_top', 'empty_folder',
         'blank_page', 'state_tracker', 'required_pages', 'links',
         'no_business_name', 'database', 'forbidden_path', 'stale_contract', 'tracked_cache', 'tool_inventory', 'object_route', 'lint_growth', 'lint_gates', 'brand_page', 'runs'}
DONE = ('done', 'canceled', 'cancelled', 'superseded', 'complete', 'completed')


def protected(path):
    return any(p.lower() in SECRET or p.lower().startswith(('.env.', 'credentials.',
               'auth.', 'secrets.', 'id_rsa.', 'id_ed25519'))
               or p.lower().endswith(('.pem', '.key', '.p12', '.pfx'))
               for p in Path(path).parts)


def relative_text(path, root):
    """The relative POSIX text of a normalized absolute path, '.' for the root, or None."""
    if path == root:
        return '.'
    prefix = root if root.endswith('/') else root + '/'
    return path[len(prefix):] if path.startswith(prefix) else None


def inside(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


@lru_cache(maxsize=4096)
def pattern_form(pattern):
    """T692: most scope patterns are plain text, '**/' + plain text, or '**/*' + an ending."""
    plain = lambda text: not any(c in text for c in '*?[')
    if plain(pattern):
        return 'exact', pattern
    if pattern.startswith('**/') and plain(pattern[3:]):
        return 'tail', pattern[3:]
    if pattern.startswith('**/*') and pattern[4:] and plain(pattern[4:]) and '/' not in pattern[4:]:
        return 'ending', pattern[4:]
    return 'glob', pattern


def page_stem(path):
    """The page's name: <name>.local.md is the person's own page for <name> (config/*.local.md pattern)."""
    return path.stem[:-len('.local')] if path.stem.endswith('.local') else path.stem


def path_match(path, pattern):
    """Each * stays in one path segment. ** can match several segments."""
    form, text = pattern_form(pattern)
    if form == 'exact':
        return path == text
    if form == 'tail':
        return path == text or path.endswith('/' + text)
    if form == 'ending':
        return bool(path) and path.rpartition('/')[2].endswith(text)
    return glob_match(path, pattern)


@lru_cache(maxsize=131072)
def glob_match(path, pattern):
    """Each * stays in one path segment. ** can match several segments."""
    parts, patterns = path.split('/'), pattern.split('/')
    def match(i, j):
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == '**':
            return match(i, j + 1) or i < len(parts) and match(i + 1, j)
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], patterns[j]) and match(i + 1, j + 1)
    return match(0, 0)


def read_table(path, columns):
    if protected(path) or path.is_symlink():
        raise ValueError('Protected or linked policy file: ' + str(path))
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if not reader.fieldnames or not set(columns).issubset(reader.fieldnames):
            raise ValueError('Missing policy columns: ' + str(path))
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError('Malformed policy row: ' + str(path))
    return rows


def iso_time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.utcoffset() is not None
    except ValueError:
        return False


def scalar(value):
    value = value.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value.split(' #', 1)[0].strip()


def heading_order(value):
    """Separate headings without splitting angle-bracket placeholders."""
    return [part.strip() for part in re.split(r'\s+>\s+', value) if part.strip()]


def flow_delta(line):
    """Track opaque YAML flow containers without reading their nested keys as top-level fields."""
    quote, escaped, delta = None, False, 0
    for c in line:
        if escaped:
            escaped = False
        elif c == '\\' and quote:
            escaped = True
        elif quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in '[{':
            delta += 1
        elif c in ']}':
            delta -= 1
    return delta


class Page:
    def __init__(self, text):
        self.text = text
        self.lines = text.splitlines()
        self.fields, self.field_lines, self.fm_errors = {}, {}, []
        self.start = 0
        first = next((i for i, s in enumerate(self.lines) if s.strip('\ufeff \t')), 0)
        if self.lines and self.lines[first].startswith('<!-- Built by ') and self.lines[first].endswith(' -->'):
            first += 1
        if self.lines and self.lines[first].strip('\ufeff \t') == '---':
            end = next((i for i in range(first + 1, len(self.lines))
                        if self.lines[i].strip() in ('---', '...')), None)
            if end is None:
                self.fm_errors.append((first + 1, 'Front matter has no closing mark.'))
            else:
                self.start = end + 1
                sequence_key, flow_depth = None, 0
                for i in range(first + 1, end):
                    line = self.lines[i]
                    if not line.strip() or line.lstrip().startswith('#'):
                        continue
                    if flow_depth > 0:
                        flow_depth += flow_delta(line)
                        continue
                    m = re.match(r'^([A-Za-z_][\w-]*)[ \t]*:[ \t]*(.*)$', line)
                    if not m:
                        if sequence_key and re.match(r'^\s*-\s+', line):
                            continue
                        if not line.startswith((' ', '\t')):
                            self.fm_errors.append((i + 1, 'Invalid front matter key line.'))
                        continue
                    key, value = m.groups()
                    flow_depth = flow_delta(value) if value.strip().startswith(('{', '[')) else 0
                    sequence_key = key if not value.strip() else None
                    if key in self.fields:
                        self.fm_errors.append((i + 1, 'Duplicate front matter key: ' + key))
                    self.fields[key] = scalar(value)
                    self.field_lines[key] = i + 1
                    if not value.strip():
                        items = []
                        for tail in self.lines[i + 1:end]:
                            item = re.match(r'^\s*-\s+(.*)$', tail)
                            if item:
                                items.append(scalar(item.group(1)))
                            elif tail.strip():
                                break
                        if items:
                            self.fields[key] = items
                    elif value.startswith('[') and value.endswith(']'):
                        self.fields[key] = [scalar(v) for v in value[1:-1].split(',') if v.strip()]
        self.body = '\n'.join(self.lines[self.start:])
        self.headings, self.tables, self.code, self.fences = [], [], [], []
        self.visible = [''] * len(self.lines)
        fence, section = None, ''
        for i in range(self.start, len(self.lines)):
            line = self.lines[i]
            mark = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
            if mark:
                token = mark.group(1)
                if fence is None:
                    fence = token
                    self.fences.append((section, i + 1))
                elif token[0] == fence[0] and len(token) >= len(fence):
                    fence = None
                continue
            if fence:
                self.code.append((i + 1, line, section))
                continue
            self.visible[i] = line
            h = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*$', line)
            if h:
                self.headings.append((len(h.group(1)), h.group(2), i + 1))
                if len(h.group(1)) == 2:
                    section = h.group(2)
            if i + 1 < len(self.lines) and '|' in line and re.fullmatch(
                    r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*', self.lines[i + 1]):
                cells = [c.strip() for c in re.split(r'(?<!\\)\|', line.strip().strip('|'))]
                self.tables.append((section, cells, i + 1))
        if fence:
            self.fm_errors.append((len(self.lines), 'Code fence has no closing mark.'))


class Lint:
    def __init__(self, home, workspaces, policy=POLICY):
        self.home = Path(os.path.abspath(os.path.expanduser(str(home))))
        self.workspaces = Path(os.path.abspath(os.path.expanduser(str(workspaces))))
        self.policy = Path(policy)
        self.findings, self.files, self.dirs, self.links, self.cache = [], [], [], [], {}
        self.wiki_indexes = {}
        self.rules = read_table(self.policy / 'rules.tsv', ['id', 'words', 'kind', 'scope', 'level'])
        for rule in self.rules:
            if not rule['id'] or rule['kind'] not in KINDS or rule['level'] not in ('error', 'warning'):
                raise ValueError('Invalid rule: ' + rule['id'])
            rule.setdefault('write', 'warning')  # Legacy policies retain their save-time behavior.
            if rule['write'] not in ('blocking', 'warning'):
                raise ValueError('Invalid write disposition: ' + rule['id'])
            self.validate_scope(rule['scope'])
        self.data = {}
        for name, cols in (
                ('scan', ['kind', 'pattern', 'reason']), ('workspaces', ['id', 'kind', 'source']),
                ('allowed-top', ['scope', 'name', 'kind', 'source']), ('empty-ok', ['path', 'reason']),
                ('business-names', ['name', 'source']), ('frontmatter', ['key', 'required', 'format', 'values']),
                ('db', ['home', 'path', 'table', 'column', 'format']),
                ('db-reasons', ['home', 'table', 'row_id', 'column', 'case', 'reason']),
                ('required-pages', ['scope', 'path']), ('pages', ['home', 'pattern', 'spec'])):
            self.data[name] = read_table(self.policy / (name + '.tsv'), cols)
        self.excluded = {r['pattern'] for r in self.data['scan'] if r['kind'] == 'exclude_dir' and r['reason'].strip()}
        self.excluded_paths = {r['pattern'] for r in self.data['scan'] if r['kind'] == 'exclude_path' and r['reason'].strip()}
        for row in self.data['scan']:
            if row['kind'] not in ('exclude_dir', 'exclude_path') or not row['pattern'] or not row['reason'].strip():
                raise ValueError('Invalid scan boundary row.')
        self.names = discover_workspaces(self.workspaces, include_aliases=True) - APP_FOLDERS
        self.shared = {r['id'] for r in self.data['workspaces'] if r['kind'] == 'shared'}
        self.specs = {}
        for binding in self.data['pages']:
            p = self.policy / 'specs' / binding['spec']
            if not inside(p.resolve(), (self.policy / 'specs').resolve()):
                raise ValueError('Spec leaves policy folder.')
            if binding['spec'] not in self.specs:
                self.specs[binding['spec']] = read_table(p, ['rule', 'value'])
        for r in self.data['db']:
            if r['format'] not in ('text', 'integer', 'iso8601') or r['table'] != 'tasks':
                raise ValueError('Invalid database check.')
            if Path(r['path']).is_absolute() or '..' in Path(r['path']).parts or protected(r['path']):
                raise ValueError('Invalid database path.')
            if r['home'] not in self.names | APP_FOLDERS | {'system', 'workspace'}:
                raise ValueError('Unknown database owner: ' + r['home'])
            if r.get('database_home', '') not in ('', 'system', 'workspace'):
                raise ValueError('Invalid database home.')
            field = r.get('workspace_column', '')
            if field and (not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', field) or not r.get('workspace_value')):
                raise ValueError('Invalid database workspace filter.')
        self.parts = read_table(self.policy / 'parts.tsv', ['spec', 'kind', 'value'])
        for row in self.parts:
            if row['spec'] not in self.specs or row['kind'] not in ('optional_heading', 'required_pattern', 'h2_prefix'):
                raise ValueError('Invalid page part row.')
            if row['kind'] == 'required_pattern':
                re.compile(row['value'])

    def add(self, rule, path, line, wrong, fix):
        self.findings.append({'rule_id': rule['id'], 'level': rule['level'], 'path': str(path),
                              'write': rule.get('write', 'warning'), 'line': int(line), 'what': wrong, 'how_to_fix': fix})

    def context(self, path):
        # T692: one run asks this about each path once per rule; links on disk
        # do not change during a run, so keep each answer.
        cache = self.__dict__.setdefault('_contexts', {})
        key = (str(path), tuple(sorted(self.names)))
        if key not in cache:
            cache[key] = self._context(Path(path))
        return cache[key]

    def workspace_folders(self):
        """Resolve each configured workspace folder once per run (T692)."""
        key = tuple(sorted(self.names))
        cached = self.__dict__.get('_folders')
        if cached is None or cached[0] != key:
            folders = []
            for name in key:
                try:
                    folders.append((name, resolve_portfolio_path(self.workspaces / name, self.workspaces)))
                except ValueError:
                    continue
            cached = self._folders = (key, folders)
        return cached[1]

    def resolve(self, path):
        """resolve_portfolio_path with each folder's answer kept (T692).

        The folder above is resolved once; a plain leaf joins it. A linked
        leaf, or a folder that cannot resolve, takes the full check.
        """
        cache = self.__dict__.setdefault('_resolved', {})
        key = str(path)
        if key not in cache:
            path = Path(path)
            parent = path.parent
            result = None
            if parent != path and path.name not in ('', '.', '..') and not path.is_symlink():
                above = self.resolve(parent)
                if isinstance(above, Path):
                    result = above / path.name
            if result is None:
                try:
                    result = resolve_portfolio_path(path, self.workspaces)
                except ValueError as error:
                    result = error
            cache[key] = result
        if isinstance(cache[key], ValueError):
            raise ValueError(str(cache[key]))
        return cache[key]

    def _context(self, path):
        # T692: plain string tests; pathlib.relative_to was most of a run's time.
        text = str(path)
        rel = relative_text(text, str(self.home))
        if rel is not None:
            parts = rel.split('/') if rel != '.' else []
            name = parts[1] if len(parts) >= 3 and parts[0] == 'workspaces' else 'system'
            return 'system', rel, name
        # A configured workspace keeps its policy after its folder is renamed.
        try:
            resolved = str(self.resolve(path))
        except ValueError:
            resolved = text
        for name, folder in self.workspace_folders():
            inner = relative_text(resolved, str(folder))
            if inner is not None and inner != '.':
                return 'workspace', inner, name
        rel = relative_text(text, str(self.workspaces))
        if rel is None:
            path.relative_to(self.workspaces)  # The same error as before for a path outside both homes.
        parts = rel.split('/') if rel != '.' else []
        if len(parts) > 1 and parts[0] in self.names:
            return 'workspace', '/'.join(parts[1:]), parts[0]
        if len(parts) > 1 and parts[0] == 'atlas':
            return 'atlas', '/'.join(parts[1:]), 'atlas'
        return 'portfolio', rel, 'portfolio'

    @staticmethod
    def validate_scope(scope):
        legacy = {'pages', 'all', 'rollups', 'system-pages', 'system', 'workspace', 'portfolio'}
        includes = False
        for term in scope.split(';'):
            negative = term.startswith('!')
            term = term.lstrip('!')
            if term in legacy and not negative:
                includes = True
                continue
            if ':' not in term:
                raise ValueError('Unknown scope: ' + term)
            group, pattern = term.split(':', 1)
            if group not in ('*', 'system', 'workspace', 'portfolio', 'atlas') or not pattern or '..' in pattern.split('/'):
                raise ValueError('Invalid scoped path: ' + term)
            includes |= not negative
        if not includes:
            raise ValueError('Scope needs an included path.')

    @staticmethod
    @lru_cache(maxsize=256)
    def negative_terms(scope, home):
        """Split a scope's exclusions for one home: folder patterns and path patterns."""
        folders, paths = [], []
        for term in scope.split(';'):
            if not term.startswith('!'):
                continue
            group, pattern = term[1:].split(':', 1)
            if group not in ('*', home):
                continue
            if pattern.endswith('/'):
                folders.append(pattern.rstrip('/'))
            else:
                paths.append(pattern)
        return tuple(folders), tuple(paths)

    def folder_excluded(self, scope, home, rel):
        """True when rel, or a folder above it, matches a folder exclusion (cached per folder)."""
        cache = self.__dict__.setdefault('_folder_excluded', {})
        key = (scope, home, rel)
        if key not in cache:
            folders = self.negative_terms(scope, home)[0]
            parent = rel.rpartition('/')[0]
            cache[key] = bool(folders) and ((bool(parent) and self.folder_excluded(scope, home, parent))
                                            or any(path_match(rel, p) for p in folders))
        return cache[key]

    def excluded_by_scope(self, path, scope):
        home, rel, _ = self.context(path)
        folders, paths = self.negative_terms(scope, home)
        # A trailing slash excludes a directory and all its descendants (T692:
        # the same answer as before, with each folder's answer kept).
        parent = rel.rpartition('/')[0]
        if folders and parent and self.folder_excluded(scope, home, parent):
            return True
        if any(path_match(rel, p) for p in paths):
            return True
        if folders and (Path(path).is_dir() or Path(path).is_symlink()):
            return any(path_match(rel, p) for p in folders)
        return False

    def skipped_workspace(self, path):
        """Only immediate portfolio exceptions; nested folders keep their checks."""
        rel = relative_text(str(path), str(self.workspaces))
        return rel is not None and rel.split('/', 1)[0] in APP_FOLDERS

    def matches(self, path, scope):
        if self.skipped_workspace(path) or self.excluded_by_scope(path, scope):
            return False
        return any(self.matches_term(path, term) for term in scope.split(';') if not term.startswith('!'))

    def matches_term(self, path, scope):
        home, rel, name = self.context(path)
        if scope == 'all':
            return True
        if scope == 'pages':
            return path.suffix.lower() == '.md'
        if scope == 'system-pages':
            return home == 'system' and not rel.startswith('workspaces/') and path.suffix.lower() == '.md'
        if scope == 'rollups':
            return path.suffix.lower() == '.md' and ('/tools/' in str(path) or '/team/' in str(path)
                                                     or rel.startswith('workspaces/'))
        if ':' in scope:
            group, pattern = scope.split(':', 1)
            if pattern.endswith('/'):
                return group in ('*', home) and path.is_dir() and path_match(rel, pattern.rstrip('/'))
            return group in ('*', home) and path_match(rel, pattern)
        return home == scope

    def page(self, path):
        if inside(path, self.workspaces):
            path = self.resolve(path)
        if path not in self.cache:
            if protected(path) or path.is_symlink() or not any(inside(path.resolve(), r.resolve()) for r in (self.home, self.workspaces)):
                raise ValueError('Page leaves scan boundary or has a protected name.')
            self.cache[path] = Page(path.read_text(encoding='utf-8-sig'))
        return self.cache[path]

    def inventory(self, selected=None):
        selected = self.rules if selected is None else selected
        # Aggregate checks inspect their declared roots directly.
        selected = [rule for rule in selected if rule['kind'] not in
                    ('allowed_top', 'required_pages', 'database', 'tracked_cache', 'tool_inventory', 'lint_growth', 'lint_gates', 'runs')]
        # Only forbidden-path rules inspect regular non-Markdown files.
        # Links still inspect every symbolic link, regardless of its suffix.
        nonpage_rules = [r for r in selected if r['kind'] == 'forbidden_path' and any(
            not term.endswith('/') for term in r['scope'].split(';') if not term.startswith('!'))]
        for root in (self.home, self.workspaces):
            if protected(root) or root.is_symlink() or not root.is_dir():
                raise ValueError('Home is absent, protected, or linked: ' + str(root))
        for start in getattr(self, 'inventory_roots', (self.home, self.workspaces)):
            root = self.home if inside(start, self.home) else self.workspaces
            if not inside(start, root):raise ValueError('Inventory root leaves managed homes.')
            if self.skipped_workspace(start):continue
            for current, dirs, files in os.walk(start, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
                folder = Path(current)
                self.dirs.append(folder)
                kept = []
                for name in sorted(dirs):
                    child = folder / name
                    if protected(child) or self.skipped_workspace(child):
                        continue
                    if not selected or all(self.excluded_by_scope(child, r['scope']) for r in selected):
                        continue
                    if child.is_symlink():
                        self.links.append(child)
                    elif name in self.excluded or ('system/' if root == self.home else 'portfolio/') + child.relative_to(root).as_posix() in self.excluded_paths:
                        # A global safety exclusion never becomes a lint target.
                        pass
                    else:
                        kept.append(name)
                dirs[:] = kept
                for name in sorted(files):
                    path = folder / name
                    if protected(path) or name in {'.DS_Store', '.gitkeep'}:
                        continue
                    linked = path.is_symlink()
                    file_rules = selected if linked or path.suffix.lower() == '.md' else nonpage_rules
                    if not any(self.matches(path, r['scope']) for r in file_rules):
                        continue
                    if linked:
                        self.links.append(path)
                    else:
                        self.files.append(path)

    def bindings(self, path):
        home, rel, _ = self.context(path)
        matches = [r for r in self.data['pages'] if r['home'] == home
                   and path_match(rel, r['pattern'])
                   and not any(path_match(rel, p) for p in r.get('except_patterns', '').split('|') if p)]
        # Exact paths beat wildcard README bindings.
        exact = [r for r in matches if r['pattern'] == rel]
        return exact or matches

    def frontmatter(self, rule, path):
        page = self.page(path)
        for line, error in page.fm_errors:
            self.add(rule, path, line, error, 'Use the approved front matter and close each code fence.')
        for row in self.data['frontmatter']:
            key = row['key']; value = page.fields.get(key, '')
            line = page.field_lines.get(key, 1)
            if row['required'] == 'yes' and not value:
                self.add(rule, path, line, 'Required front matter key is absent or blank: ' + key,
                         'Add ' + key + ' from the page contract.')
                continue
            values = value if isinstance(value, list) else [value]
            for v in values:
                valid = (row['format'] != 'iso8601' or iso_time(v))
                if row['format'] == 'workspace':
                    valid = v in self.names | self.shared | {'system', 'portfolio', 'rules', 'people', 'archive'}
                if row['format'] == 'kebab':
                    valid = bool(re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', str(v)))
                if row['values'] and v not in row['values'].split('|'):
                    valid = False
                if not valid:
                    self.add(rule, path, line, 'Invalid front matter value: ' + key,
                             'Use the allowed value or ISO 8601 time with an offset.')
        for binding in self.bindings(path):
            spec = self.specs[binding['spec']]
            for r in spec:
                key, val = r['rule'], r['value']
                if key == 'frontmatter_key' and not page.fields.get(val):
                    self.add(rule, path, 1, 'Spec requires front matter key: ' + val, 'Add the key from ' + binding['spec'])
                elif key == 'frontmatter_keys_allowed':
                    for extra in set(page.fields) - set(val.split('|')):
                        self.add(rule, path, page.field_lines[extra], 'Front matter key is outside the spec: ' + extra,
                                 'Use only the keys in ' + binding['spec'])
                elif key in ('frontmatter_value', 'frontmatter_enum') and '=' in val:
                    field, expected = val.split('=', 1)
                    actual = page.fields.get(field)
                    if field == 'workspace' and ('folder name' in expected or expected.startswith('<')):
                        expected = self.context(path)[2]
                    if expected in ('system', 'portfolio') or key == 'frontmatter_enum' or not re.search(r'[ <>;]', expected):
                        if field == 'use' and self.context(path)[0] == 'workspace':
                            continue  # The approved spec permits local uses.
                        if actual not in expected.split('|'):
                            self.add(rule, path, page.field_lines.get(field, 1), 'Front matter differs from spec: ' + field,
                                     'Use ' + expected)
                elif key == 'frontmatter_key_order':
                    if list(page.fields) != [v.strip() for v in val.split('>')]:
                        self.add(rule, path, 1, 'Front matter keys have the wrong order.', 'Use key order in ' + binding['spec'])
                elif key == 'frontmatter_rule' and val.startswith(('name=', 'kind=')):
                    field = val.split('=', 1)[0]
                    expected = page_stem(path) if field == 'name' else path.parent.name
                    if page.fields.get(field) != expected:
                        self.add(rule, path, page.field_lines.get(field, 1), 'Front matter does not match its path: ' + field,
                                 'Set ' + field + ' to ' + expected)

    def page_spec(self, rule, path):
        if self.context(path)[2] == 'sample-project' and Path(path).name in ('CLAUDE.md', 'index.md', 'STATE.md', 'RESOLVER.md', 'GLOSSARY.md', 'TOPICS.md'):
            return  # g-sample-project-moved-nothing-else-changes; keep its existing forms.
        bindings = self.bindings(path)
        if not bindings:
            return  # No invented template for uncovered types.
        if len(bindings) != 1:
            self.add(rule, path, 1, 'Page matches more than one spec.', 'Keep one binding in pages.tsv.')
            return
        binding = bindings[0]; spec = self.specs[binding['spec']]; page = self.page(path)
        h1 = [(s, n) for depth, s, n in page.headings if depth == 1]
        h2 = [(s, n) for depth, s, n in page.headings if depth == 2]
        values = {}
        for row in spec:
            values.setdefault(row['rule'], []).append(row['value'])
        def fail(line, message):
            self.add(rule, path, line, message, 'Match ' + binding['spec'])
        def section_body(label):
            start = next((n for s, n in h2 if s == label), 0)
            end = next((n - 1 for _, n in h2 if n > start), len(page.lines))
            return start, '\n'.join(page.lines[start:end]) if start else ''
        title_required = 'h1' in values or 'block_order' in values
        if not title_required and binding['spec'].endswith('spec-CLAUDE.tsv') and h1:
            fail(h1[0][1], 'CLAUDE body has no title.')
        if title_required and len(h1) != 1:
            fail(1, 'Page needs exactly one title.')
        expected = values.get('h1', [''])[0]
        expected = expected.replace('<workspace>', self.context(path)[2]).replace('<name>', page_stem(path))
        expected = expected.split(';', 1)[0]
        if expected and '<' not in expected and not expected.startswith(('the name', 'what the reader')) and h1 and h1[0][0] != expected:
            fail(h1[0][1], 'Title differs from the spec: expected ' + expected)
        for key in ('headings_required', 'h2_first', 'h2_last'):
            for val in values.get(key, []):
                required = val.split('|') if key == 'headings_required' else [val]
                for heading in required:
                    if heading not in [s for s, _ in h2]:
                        fail(1, 'Required heading is absent: ' + heading)
                if h2 and key == 'h2_first' and h2[0][0] != val:
                    fail(h2[0][1], 'First section must be ' + val)
                if h2 and key == 'h2_last' and h2[-1][0] != val:
                    fail(h2[-1][1], 'Last section must be ' + val)
        for val in values.get('heading_order', []):
            order = heading_order(val)
            names = [s for s, _ in h2]
            fixed = [s for s in order if '<' not in s]
            positions = [names.index(s) for s in fixed if s in names]
            if positions != sorted(positions):
                fail(h2[0][1] if h2 else 1, 'Section headings have the wrong order.')
            optional = {r['value'] for r in self.parts if r['spec'] == binding['spec'] and r['kind'] == 'optional_heading'}
            flexible = '*' in optional
            explicitly_required = '|'.join(values.get('headings_required', [])).split('|')
            for s in fixed:
                may_omit = s in optional or flexible
                if s not in names and (s in explicitly_required or not may_omit):
                    fail(1, 'Required section is absent: ' + s)
            if 'headings_fixed' in values and names != fixed:
                fail(1, 'Fixed section headings differ from the spec.')
        for val in values.get('headings_allowed', []):
            for s, n in h2:
                if s not in val.split('|'):
                    fail(n, 'Section heading is outside the spec: ' + s)
        for key in ('forbidden_headings',):
            for val in values.get(key, []):
                for _, s, n in page.headings:
                    if s in val.split('|'):
                        fail(n, 'Forbidden heading: ' + s)
        for val in values.get('h2_count', []):
            if len(h2) != int(val):
                fail(1, 'Wrong number of sections: expected ' + val)
        width = int(values.get('max_code_line', ['78'])[0])
        for n, line, _ in page.code:
            if len(line) > width:
                fail(n, 'Code line exceeds ' + str(width) + ' characters.')
        for key in ('page_max_lines', 'body_max_lines'):
            for val in values.get(key, []):
                m = re.match(r'^\d+', val)
                count = len(page.lines) if key == 'page_max_lines' else len([s for s in page.lines[page.start:] if s.strip()])
                if m and count > int(m.group()):
                    fail(1, key + ' exceeds ' + m.group())
        expected_tables = []
        for key in ('table_columns', 'facts_table_columns'):
            for val in values.get(key, []):
                section, columns = val.split('=', 1) if '=' in val else ('' if key == 'facts_table_columns' else '*', val)
                expected_tables.append((section, columns.split('|')))
        for val in values.get('section', []):
            label, text = val.split('=', 1) if '=' in val else ('', val)
            match = re.search(r'then the table ([^|\n]+\|[^\n]+)$', text)
            if match:
                # Placeholder sections bind to their ordinal in heading_order.
                orders = heading_order(values.get('heading_order', [''])[0])
                placeholder = '<' + label + '>'
                if placeholder in orders and orders.index(placeholder) < len(h2):
                    label = h2[orders.index(placeholder)][0]
                expected_tables.append((label, match.group(1).split('|')))
        for section, cells, n in page.tables:
            choices = [cols for label, cols in expected_tables if label == section]
            if not choices:
                choices = [cols for label, cols in expected_tables if label == '*']
            if choices and cells not in choices:
                fail(n, 'Table columns differ from the spec.')
            if len(cells) > int(values.get('max_table_columns', ['4'])[0]):
                fail(n, 'Table has too many columns.')
        for label, columns in expected_tables:
            if label in ('*', ''):
                empty = [v.split('the sentence: ', 1)[-1] for v in values.get('table_when_empty', [])
                         if v.startswith('replace the table with the sentence: ')]
                if not any(cells == columns for _, cells, _ in page.tables) and not any(v in page.body for v in empty):
                    fail(1, 'Required table is absent: ' + '|'.join(columns))
                continue
            if label not in [s for s, _ in h2]:
                continue
            start = next(n for s, n in h2 if s == label)
            end = next((n - 1 for _, n in h2 if n > start), len(page.lines))
            content = '\n'.join(page.lines[start:end])
            empty = [v.split('the sentence: ', 1)[-1] for v in values.get('table_when_empty', [])
                     if v.startswith(label + '=')]
            if 'list_empty' in values:
                empty.append('None.')
            if not any(section == label for section, _, _ in page.tables) and not any(v in content for v in empty):
                fail(start, 'Required table is absent: ' + label)
        for val in values.get('required_table', []):
            label, columns = val.split('=', 1)
            if not any((label == '*' or section == label) and cells == columns.split('|')
                       for section, cells, _ in page.tables):
                fail(section_body(label)[0] or 1, 'Required table is absent: ' + label)
        for val in values.get('section_nonempty', []):
            for label in val.split('|'):
                start, content = section_body(label)
                content = re.sub(r'<!--.*?-->', '', content, flags=re.S).strip()
                if not content:
                    fail(start or 1, 'Required section body is empty: ' + label)
        for key, pattern in [('section_numbered_count', r'^\s*\d+\.\s+\S'),
                             ('section_bullet_count', r'^\s*[-*+]\s+\S')]:
            for val in values.get(key, []):
                label, count = val.rsplit('=', 1)
                start, content = section_body(label)
                if len(re.findall(pattern, content, re.M)) != int(count):
                    fail(start or 1, label + ' needs ' + count + ' list items.')
        for val in values.get('section_fence_count', []):
            label, count = val.rsplit('=', 1)
            start, _ = section_body(label)
            fences = [n for s, n in page.fences if s == label]
            if len(fences) != int(count) or not any(s == label and line.strip() for _, line, s in page.code):
                fail(start or 1, label + ' needs ' + count + ' non-empty code fences.')
        for val in values.get('section_code_labels', []):
            label, keys = val.split('=', 1)
            for key in keys.split('|'):
                if not any(s == label and re.match(r'^' + re.escape(key) + r'\s{2,}\S', line)
                           for _, line, s in page.code):
                    fail(section_body(label)[0] or 1, 'Required code label is absent in ' + label + ': ' + key)
        for val in values.get('section_command_count', []):
            label, count = val.rsplit('=', 1)
            numbers = [int(m.group(1)) for _, line, s in page.code if s == label
                       for m in [re.match(r'^#\s+(\d+)\.', line)] if m]
            if numbers != list(range(1, int(count) + 1)):
                fail(section_body(label)[0] or 1, label + ' needs ' + count + ' numbered commands.')
        if 'facts_table_columns' in values:
            if not any(cells == values['facts_table_columns'][0].split('|') for _, cells, _ in page.tables):
                fail(1, 'Required facts table is absent.')
            for key in '|'.join(values.get('facts_table_rows', [])).split('|'):
                if key and not re.search(r'^\|\s*' + re.escape(key) + r'\s*\|', page.body, re.M):
                    fail(1, 'Required facts row is absent: ' + key)
        labels = values.get('count_block_labels', []) + values.get('count_block_keys', [])
        for val in labels:
            for label in val.split('|'):
                if label.startswith('one line'):
                    continue
                if not any(re.match(r'^\s*' + re.escape(label) + r'\s{2,}\S', line) for _, line, _ in page.code):
                    fail(1, 'Required count label is absent: ' + label)
        for key in ('nav_line', 'go_to_line', 'notes_marks', 'needs_line', 'how_to_read'):
            for val in values.get(key, []):
                val = val.removeprefix('required, word for word: ')
                for literal in val.split('|') if key == 'notes_marks' else [val]:
                    if literal not in page.body:
                        fail(1, 'Required part is absent: ' + key)
        if 'contents' in values and not any(s == 'Contents' for s, _ in h2):
            fail(1, 'Required contents section is absent.')
        for row in self.parts:
            if row['spec'] != binding['spec']:
                continue
            if row['kind'] == 'required_pattern' and not re.search(row['value'], page.body, re.M):
                fail(1, 'Required page part is absent: ' + row['value'])
            elif row['kind'] == 'h2_prefix':
                for heading, line in h2:
                    if not heading.startswith(row['value']):
                        fail(line, 'Section heading needs the path prefix ' + row['value'])
        if 'count_block_keys' in values:
            expected_keys = values['count_block_keys'][0].split('|')
            actual_keys = []
            for line_number, line, _ in page.code:
                for label in expected_keys:
                    if re.match(r'^' + re.escape(label) + r'\s{2,}', line):
                        actual_keys.append(label)
                        if 'count_block_form' in values and len(line) - len(line.lstrip()) == 0:
                            m = re.match(r'^' + re.escape(label) + r'\s{2,}(\S.*)', line)
                            if m and m.start(1) != 20:
                                fail(line_number, 'Count value must start in column 21.')
            if actual_keys != expected_keys:
                fail(1, 'Count keys have the wrong order or repeat.')
        if 'first_paragraph' in values or 'what_it_is' in values or 'block_order' in values:
            if h1:
                tail = page.lines[h1[0][1]:]
                first = next((s for s in tail if s.strip()), '')
                if not first or re.match(r'^\s*(?:#|\||```|~~~)', first):
                    fail(h1[0][1], 'Required opening paragraph is absent.')
        for val in values.get('forbidden_text', []):
            for text in val.split('|'):
                for n, line in enumerate(page.lines, 1):
                    if text and (re.search(r'(?<![\w-])' + re.escape(text) + r'(?![\w-])', line) if text in ('TODO', 'TBD') else text.lower() in line.lower()):
                        fail(n, 'Forbidden text from the spec: ' + text)

    def rule_roots(self):
        return ([('system', self.home), ('portfolio', self.workspaces)] +
                [('workspace', self.workspaces / n) for n in sorted(self.names)] +
                [('atlas', self.workspaces / 'atlas')])

    def repository_roots(self):
        return [root for scope, root in self.rule_roots() if scope != 'atlas']

    def allowed_top(self, rule):
        roots = self.rule_roots()
        for scope, root in roots:
            try:
                checked = (resolve_portfolio_path(root, self.workspaces)
                           if inside(root, self.workspaces) else None if root.is_symlink() else root)
            except ValueError:
                checked = None
            if checked is None or not checked.is_dir():
                continue
            allowed = {r['name']: r['kind'] for r in self.data['allowed-top'] if r['scope'] == scope}
            for path in sorted(root.iterdir()):
                if protected(path) or not self.matches(path, rule['scope']):
                    continue
                kind = 'dir' if path.is_dir() else 'file'
                if path.name not in allowed:
                    self.add(rule, path, 0, 'Entry is outside the top list.', 'Remove the extra entry through a reviewed repair, or approve a policy row.')
                elif kind != allowed[path.name] and not path.is_symlink():
                    self.add(rule, path, 0, 'Top entry has the wrong kind.', 'Use the file or folder kind in allowed-top.tsv.')

    def empty_folder(self, rule, path):
        names = {p.name for p in path.iterdir()} - {'.git', '.gitignore', '.gitkeep', '.DS_Store'}
        if names:
            return
        scope, rel, name = self.context(path)
        label = ('system/' + rel) if scope == 'system' else ('portfolio/' + str(path.relative_to(self.workspaces)))
        for row in self.data['empty-ok']:
            pattern = row['path'].rstrip('/')
            if not row['reason'].strip():
                continue
            if pattern == label:
                return
            parts = pattern.split('/'); actual = label.split('/')
            if len(parts) == len(actual) and pattern.startswith('portfolio/*/') and parts.count('*') == 1:
                if name in self.names and all(p == '*' or p == a for p, a in zip(parts, actual)):
                    return
        self.add(rule, path, 0, 'Folder is empty without a listed reason.', 'Add an exact path and a real reason to empty-ok.tsv, or review removal.')

    def blank_page(self, rule, path):
        page = self.page(path)
        if page.fields.get('type') == 'template':
            return
        body = re.sub(r'<!--.*?-->', '', page.body, flags=re.S)
        meaningful = '\n'.join(s for s in body.splitlines() if not re.match(r'^\s*#{1,6}\s', s)).strip()
        if len(meaningful) < 40:
            self.add(rule, path, page.start + 1, 'Body without headings has fewer than 40 characters.', 'Write the source-backed body from its template; do not add filler.')

    def open_db(self, path):
        if protected(path) or path.is_symlink() or not path.is_file():
            raise ValueError('Database is absent, protected, or linked.')
        if not any(inside(path.resolve(), root.resolve()) for root in (self.home, self.workspaces)):
            raise ValueError('Database leaves scan boundary.')
        con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        return con

    def database_routes(self, owner):
        rows = [r for r in self.data['db'] if r['home'] == owner]
        if not rows and owner != 'system':
            rows = [r for r in self.data['db'] if r['home'] == 'workspace']
        routes = {}
        for row in rows:
            home = row.get('database_home') or ('system' if row['home'] == 'system' else 'workspace')
            root = self.home if home == 'system' else self.workspaces / owner
            path = root / row['path']
            key = (path, row.get('workspace_column', ''), row.get('workspace_value', ''))
            routes.setdefault(key, []).append(row)
        if len(routes) != 1:
            raise ValueError('Database routing is missing or conflicting for ' + owner)
        (path, column, value), checks = next(iter(routes.items()))
        return path, column, value, checks

    @staticmethod
    def database_filter(columns, column, value):
        if not column:
            return '', ()
        if column not in columns:
            raise ValueError('Shared task table lacks workspace filter column: ' + column)
        return '"' + column + '" = ?', (value,)

    def state_tracker(self, rule, path):
        home, rel, owner = self.context(path)
        if rel != 'STATE.md' or home not in ('system', 'workspace'):
            return
        page = self.page(path)
        claim = re.search(r'no work has started', page.body, re.I)
        count = re.search(r'^OPEN TASKS\s{2,}(\d+)\s*$', page.body, re.M)
        if not claim and not count:
            return
        db, workspace_column, workspace_value, declared_checks = self.database_routes('system' if home == 'system' else owner)
        con = self.open_db(db)
        try:
            # Reused gate logic: tasks and *_tasks, with the same terminal statuses.
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                      if r[0] == 'tasks' or r[0].endswith('_tasks')]
            if any(row.get('database_home') for row in declared_checks):
                declared = {row['table'] for row in declared_checks}
                tables = [table for table in tables if table in declared]
            if not tables:
                raise ValueError('No task table can prove STATE.')
            opened = 0
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                cols = {r[1] for r in con.execute('PRAGMA table_info(' + quoted + ')')}
                if 'status' not in cols:
                    raise ValueError('Task table has no status column.')
                filter_, parameters = self.database_filter(cols, workspace_column, workspace_value)
                opened += con.execute('SELECT COUNT(*) FROM ' + quoted +
                                      ' WHERE ' + (filter_ + ' AND ' if filter_ else '') +
                                      '(status IS NULL OR lower(trim(status)) NOT IN (' +
                                      ','.join('?' for _ in DONE) + '))', parameters + DONE).fetchone()[0]
            if count:
                view = con.execute("SELECT 1 FROM sqlite_master WHERE name='open_tasks' AND type='view'").fetchone()
                if view:
                    columns = {r[1] for r in con.execute('PRAGMA table_info(open_tasks)')}
                    if not workspace_column or workspace_column in columns:
                        filter_, parameters = self.database_filter(columns, workspace_column, workspace_value)
                        opened = con.execute('SELECT COUNT(*) FROM open_tasks' +
                                             (' WHERE ' + filter_ if filter_ else ''), parameters).fetchone()[0]
            if claim and opened or count and int(count.group(1)) != opened:
                match = claim or count
                self.add(rule, path, page.start + page.body[:match.start()].count('\n') + 1,
                         'STATE contradicts tracker: ' + str(opened) + ' open tasks.',
                         'Rebuild STATE from the tracker. Do not change tasks to match the page.')
        finally:
            con.close()

    def required_pages(self, rule):
        roots = self.rule_roots()
        for scope, root in roots:
            for row in self.data['required-pages']:
                if row['scope'] != scope:
                    continue
                if root.name in row.get('except_workspaces', '').split('|'):
                    continue
                path = root / row['path']
                if not self.matches(path, rule['scope']):
                    continue
                try:
                    checked = (resolve_portfolio_path(path, self.workspaces)
                               if inside(path, self.workspaces) else None if path.is_symlink() else path)
                except ValueError:
                    checked = None
                if checked is None or protected(checked) or not checked.is_file():
                    self.add(rule, path, 0, 'Required top page is absent or linked.', 'Build the required page from its approved source and spec.')
                elif self.bindings(path):
                    self.page_spec(rule, path)

    def no_business_name(self, rule, path):
        page = self.page(path)
        names = {r['name'] for r in self.data['business-names'] if r['name']}
        patterns = []
        for name in sorted(names):
            variants = {name, name.replace('-', ' ')}
            pattern = r'(?<![\w-])(?:' + '|'.join(re.escape(v) for v in sorted(variants)) + r')(?![\w-])'
            patterns.append((name, re.compile(pattern, re.I)))
        for n, line in enumerate(page.lines, 1):
            for name, pattern in patterns:
                if pattern.search(line):
                    self.add(rule, path, n, 'System page names a business: ' + name,
                             'Put workspace content on its workspace page. Keep system wording generic.')

    def forbidden_path(self, rule, path):
        self.add(rule, path, 0, 'Forbidden path exists: ' + self.context(path)[1],
                 'Review readers, then propose a move or exclusion. Preserve source files.')

    def stale_contract(self, rule, path):
        page = self.page(path)
        policy = read_table(self.policy / 'stale-names.tsv', ['literal', 'replacement', 'source'])
        for row in policy:
            for line, text in enumerate(page.lines, 1):
                if row['literal'] and row['literal'] in text:
                    self.add(rule, path, line, 'Contract names a retired place: ' + row['literal'],
                             'Use ' + row['replacement'] + '; check the owning resolver first.')

    def tracked_cache(self, rule):
        roots = self.repository_roots()
        for root in roots:
            if not (root / '.git').exists() or not self.matches(root, rule['scope']):
                continue
            if (root / '.git').is_symlink():
                self.add(rule, root, 0, 'Git cache check cannot use a linked repository.',
                         'Check the repository in its own source workspace.')
                continue
            result = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '-z'],
                                    capture_output=True)
            if result.returncode:
                self.add(rule, root, 0, 'Git cache check cannot complete.',
                         'Restore the repository metadata and rerun this check.')
                continue
            for raw in result.stdout.split(b'\0'):
                if not raw:
                    continue
                relative = os.fsdecode(raw)
                if '__pycache__' in Path(relative).parts or relative.endswith(('.pyc', '.pyo')):
                    self.add(rule, root / relative, 0, 'Git tracks a Python cache.',
                             'Remove the cache from the product list and Git index through a reviewed change.')

    def wiki_pages(self):
        """Pages a wiki name can resolve to. A one-page write check adds its listed pool."""
        return self.files

    def links_check(self, rule, path):
        if path.is_symlink():
            try:
                checked = resolve_portfolio_path(path, self.workspaces)
            except ValueError:
                self.add(rule, path, 0, 'Symbolic link leaves its allowed boundary.', 'Keep each link hop inside the portfolio.')
                return
            if protected(checked) or not checked.exists():
                self.add(rule, path, 0, 'Symbolic link target is absent or protected.', 'Restore a safe target inside the portfolio.')
            return
        if path.suffix.lower() != '.md':
            return
        page = self.page(path)
        text = '\n'.join(page.visible)
        # Inline examples are code, too. Preserve offsets for source line numbers.
        text = re.sub(r'(`+)([^`]*?)\1', lambda m: re.sub(r'[^\n]', ' ', m.group()), text)
        refs = []
        for m in re.finditer(r'!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[\'\"][^\n]*?[\'\"])?\s*\)', text):
            refs.append((m.start(), m.group(1), False))
        for m in re.finditer(r'\[\[([^\]\n]+)\]\]', text):
            refs.append((m.start(), m.group(1).split('|', 1)[0], True))
        for m in re.finditer(r'(?m)^\s*\[(?!\^)[^\]\n]+\]:\s*(<[^>]+>|[^\s\[\]]+)', text):
            refs.append((m.start(), m.group(1), False))
        for pos, literal, wiki in refs:
            literal = literal.strip('<>')
            coordinate = re.fullmatch(r'(.+\.[A-Za-z0-9]+):[1-9]\d*(?::[1-9]\d*)?', literal)
            if coordinate:
                literal = coordinate.group(1)
            if re.match(r'^[A-Za-z][\w+.-]*:', literal) or literal.startswith('//'):
                continue  # No network. External URL schemes are outside coverage.
            if any(c in literal for c in ('{', '}', '*', '$', '\\')):
                continue  # Templates are not literal links.
            parsed = urlsplit(literal)
            target_text, fragment = unquote(parsed.path), unquote(parsed.fragment)
            if target_text.startswith('~/.foxrun'):
                target = self.home / target_text[len('~/.foxrun'):].lstrip('/')
            elif target_text.startswith('~/foxrun'):
                target = self.workspaces / target_text[len('~/foxrun'):].lstrip('/')
            elif target_text.startswith(('~', '/')):
                target = Path(os.path.expanduser(target_text))
            else:
                target = path.parent / target_text if target_text else path
            target = Path(os.path.abspath(str(target)))
            n = text[:pos].count('\n') + 1
            candidates = [target, target.with_suffix('.md')] if wiki and not target.suffix else [target]
            if wiki and target_text and not target_text.startswith(('~', '/')):
                home, _, name = self.context(path)
                roots = [self.workspaces / name] if home in ('workspace', 'atlas') else []
                roots += [self.home, self.workspaces]
                for root in roots:
                    candidate = Path(os.path.abspath(str(root / target_text)))
                    candidates += [candidate, candidate.with_suffix('.md')] if not candidate.suffix else [candidate]
            found = next((p for p in candidates if p.exists()), None)
            if found is None and wiki and target_text and not target_text.startswith(('~', '/', '.')):
                suffix = target_text if Path(target_text).suffix else target_text + '.md'
                if rule['scope'] not in self.wiki_indexes:
                    index = {}
                    for p in self.wiki_pages():
                        if p.suffix.lower() != '.md' or not self.matches(p, rule['scope']):
                            continue
                        parts = self.context(p)[1].split('/')
                        for i in range(len(parts)):
                            index.setdefault('/'.join(parts[i:]), []).append(p)
                    self.wiki_indexes[rule['scope']] = index
                matches = self.wiki_indexes[rule['scope']].get(suffix, [])
                if len(matches) == 1:
                    found = matches[0]
                elif len(matches) > 1:
                    self.add(rule, path, n, 'Wiki link target is ambiguous: ' + target_text,
                             'Use the path of one intended page in the link.')
                    continue
            if found is None:
                self.add(rule, path, n, 'Local link target is absent: ' + str(candidates[-1]), 'Restore the target or correct the link.')
            elif fragment and not self.skipped_workspace(found.resolve()) and found.suffix.lower() == '.md' and not protected(found) and not found.is_symlink() and any(inside(found.resolve(), root.resolve()) for root in (self.home, self.workspaces)) and self.matches(found, rule['scope']):
                anchors, repeats = set(), {}
                for _, heading, _ in self.page(found).headings:
                    anchor = re.sub(r'[^\w -]', '', heading.lower()).replace(' ', '-')
                    repeated = repeats.get(anchor, 0); repeats[anchor] = repeated + 1
                    anchors.add(anchor + ('-' + str(repeated) if repeated else ''))
                if fragment not in anchors and not fragment.startswith('^'):
                    self.add(rule, path, n, 'Link section is absent: ' + fragment, 'Use an existing heading anchor.')

    def database(self, rule):
        groups = {}
        for owner in [root.name if scope == 'workspace' else scope
                      for scope, root in self.rule_roots() if scope in ('system', 'workspace')]:
            try:
                path, column, value, checks = self.database_routes(owner)
                if self.matches(path, rule['scope']):
                    groups[(path, owner, column, value)] = checks
            except ValueError as error:
                self.add(rule, self.home if owner == 'system' else self.workspaces / owner, 0,
                         'Database check cannot complete: ' + str(error), 'Supply one resolver-backed tracker route.')
        for (path, scope, workspace_column, workspace_value), checks in sorted(groups.items()):
            try:
                con = self.open_db(path)
                try:
                    columns = {r[1] for r in con.execute('PRAGMA table_info(tasks)')}
                    if not columns or 'id' not in columns:
                        raise ValueError('tasks or its id column is absent.')
                    filter_, parameters = self.database_filter(columns, workspace_column, workspace_value)
                    def query(selection, condition=''):
                        terms = [term for term in (filter_, condition) if term]
                        return con.execute('SELECT ' + selection + ' FROM tasks' +
                                           (' WHERE ' + ' AND '.join('(' + term + ')' for term in terms) if terms else ''),
                                           parameters)
                    empty_reason = any(r['home'] == scope and r['table'] == 'tasks' and r['case'] == 'empty-table'
                                       and r['reason'].strip() for r in self.data['db-reasons'])
                    if query('COUNT(*)').fetchone()[0] == 0 and not empty_reason:
                        self.add(rule, path, 0, 'tasks is empty without a listed table reason. Owner: ' + scope,
                                 'Explain the empty table in db-reasons.tsv, or restore its source rows.')
                    for row in checks:
                        column = row['column']
                        if column not in columns:
                            self.add(rule, path, 0, 'tasks column is absent: ' + column, 'Use the declared tasks schema or correct db.tsv after review.')
                            continue
                        q = '"' + column.replace('"', '""') + '"'
                        # Fetch only row ids for blanks/nulls. Never print cell payloads.
                        for case, condition in [('null', q + ' IS NULL'), ('blank', 'typeof(' + q + ")='text' AND trim(" + q + ")=''" )]:
                            for (key,) in query('id', condition):
                                permitted = any(r['home'] == scope and r['table'] == 'tasks' and r['row_id'] == str(key)
                                                and r['column'] == column and r['case'] == case and r['reason'].strip()
                                                for r in self.data['db-reasons'])
                                if not permitted:
                                    self.add(rule, path, 0, 'tasks row ' + str(key) + ': ' + column + ' is ' + case + ' without a reason.',
                                             'Record the exact reason in db-reasons.tsv, or repair the source value.')
                        condition = q + ' IS NOT NULL AND NOT (typeof(' + q + ")='text' AND trim(" + q + ")='')"
                        if row['format'] == 'iso8601':
                            for key, value in query('id, ' + q, condition):
                                if not iso_time(value):
                                    self.add(rule, path, 0, 'tasks row ' + str(key) + ': ' + column + ' is not an ISO 8601 time with offset.',
                                             'Recover the correct source time. Never invent a missing time.')
                        else:
                            for (key,) in query('id', condition + " AND typeof(" + q + ") != '" + row['format'] + "'"):
                                self.add(rule, path, 0, 'tasks row ' + str(key) + ': ' + column + ' has the wrong stored type.', 'Use the declared column type in db.tsv.')
                finally:
                    con.close()
            except (OSError, ValueError, sqlite3.Error) as error:
                self.add(rule, path, 0, 'Database check cannot complete for ' + scope + ': ' + str(error), 'Restore the database or its declared schema. Missing checks never pass.')

    def completion_table(self, name, columns):
        return read_table(self.policy / (name + '.tsv'), columns)

    def safe_entry(self, root, relative):
        """Policy paths never escape a home or traverse linked directories."""
        path = root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or protected(path):
            raise ValueError('Unsafe policy path: ' + relative)
        if inside(path, self.workspaces):
            path = resolve_portfolio_path(path, self.workspaces)
            if protected(path):
                raise ValueError('Protected policy path: ' + relative)
            return path
        if not inside(path.resolve(), root.resolve()):
            raise ValueError('Policy path leaves its home: ' + relative)
        cursor = path
        while cursor != root:
            if cursor.is_symlink():
                raise ValueError('Policy path traverses a link: ' + relative)
            cursor = cursor.parent
        return path

    def tool_inventory(self, rule):
        roots = self.completion_table('tool-roots', ['home', 'path'])
        declared = self.completion_table('tools', ['home', 'page', 'runtime', 'source'])
        exemptions = self.completion_table('tool-exceptions', ['home', 'path', 'reason'])
        for home, root in [(root.name if scope == 'workspace' else scope, root)
                           for scope, root in self.rule_roots() if scope in ('system', 'workspace')]:
            candidates = [r for r in roots if r['home'] in (home, 'workspace' if home != 'system' else 'system')]
            registered = [r for r in declared if r['home'] == home]
            mapped = set()
            for row in registered:
                if not row['source'].strip():
                    raise ValueError('Tool registration lacks source evidence.')
                page = self.safe_entry(root, row['page'])
                if not self.matches(page, rule['scope']):
                    continue
                runtime = Path(os.path.expanduser(row['runtime']))
                if not runtime.is_absolute():
                    runtime = self.safe_entry(root, row['runtime'])
                if protected(runtime):
                    raise ValueError('Protected tool location.')
                mapped.add(runtime)
                if runtime == page:
                    self.add(rule, page, 0, 'A tool page cannot be its executable.', 'Map the actual tool separately in tools.tsv.')
                if not page.is_file():
                    self.add(rule, page, 0, 'Registered tool page is absent.', 'Restore its source page.')
                if not runtime.exists():
                    self.add(rule, page, 0, 'Registered tool runtime is absent.', 'Restore the tool or record its installation gap.')
            for row in candidates:
                folder = self.safe_entry(root, row['path'])
                if not folder.is_dir():
                    continue
                children = sorted(folder.iterdir())
                for path in children:
                    if protected(path) or not self.matches(path, rule['scope']):
                        continue
                    rel = path.relative_to(root).as_posix()
                    if any(r['home'] in (home, '*') and r['path'] == rel and r['reason'].strip() for r in exemptions):
                        continue
                    if path.suffix == '.md':
                        if any(root / r['page'] == path for r in registered):
                            continue
                        siblings = [p for p in children if p != path and (p.name == page_stem(path) or p.stem == page_stem(path))
                                    and (p.is_dir() or p.suffix in ('.py', '.sh', '.js', '.mjs') or os.access(p, os.X_OK))]
                        if not siblings:
                            self.add(rule, path, 1, 'Tool page has no separately identified runtime.', 'Add the real runtime and source to tools.tsv.')
                    elif path.is_dir() or path.suffix in ('.py', '.sh', '.js', '.mjs') or os.access(path, os.X_OK):
                        if path not in mapped and not (folder / (path.stem + '.md')).is_file():
                            self.add(rule, path, 0, 'Tool payload has no page beside it.', 'Add its source-backed page or an exact reason in tool-exceptions.tsv.')

    def object_route(self, rule, path):
        page = self.page(path)
        kind = page.fields.get('type')
        if not isinstance(kind, str) or not kind:
            self.add(rule, path, 1, 'Cannot route a page without a type.', 'Set its source-defined front matter type.')
            return
        home, relative, owner = self.context(path)
        routes = self.completion_table('routes', ['home', 'type', 'pattern', 'source', 'quote'])
        rows = [r for r in routes if r['home'] in (home, owner, '*') and kind in r['type'].split('|')]
        if not rows or not any(path_match(relative, r['pattern']) and not any(
                path_match(relative, pattern) for pattern in r.get('except_patterns', '').split('|') if pattern)
                for r in rows):
            self.add(rule, path, 1, 'Page is outside the coded home for type ' + kind + '.',
                     'Use routes.tsv and its resolver source; an unknown route blocks a write.')
        for row in rows:
            if not row['source'] or not row['quote']:
                raise ValueError('Route lacks source evidence.')

    def lint_growth(self, rule):
        for relative in ('skillwright/skills/lint-rule/SKILL.md', 'base/lint_rule.py'):
            path = self.safe_entry(self.home, relative)
            if not path.is_file():
                self.add(rule, path, 0, 'Lint-growth entry is absent.', 'Restore the skill and its tested rule command.')
        records = self.completion_table('rule-evidence', ['id', 'task', 'evidence', 'sha256', 'good', 'bad'])
        for row in records:
            if not all(row[k].strip() for k in row):
                self.add(rule, self.policy / 'rule-evidence.tsv', 0, 'Rule evidence is incomplete.', 'Keep the finding, task, and passing and failing fixture proof.')
            if row['id'] not in {r['id'] for r in self.rules}:
                self.add(rule, self.policy / 'rule-evidence.tsv', 0, 'Evidence names an absent rule.', 'Restore the rule or retain the finding as unresolved.')
            import hashlib
            source = self.safe_entry(self.policy, row['evidence'])
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
                self.add(rule, self.policy / 'rule-evidence.tsv', 0, 'Retained rule evidence is absent or changed.', 'Restore the exact finding copy from its source.')

    def runs(self, rule):
        """T755: runs live in ~/.foxrun/runs/<date>/<task>-<seat>-<what>/ with brief.md, result.md, heavy/, in budget.
        A run written anywhere else or off-shape is an error at the rule's level; budget notes and older runs warn."""
        from memory import runs as run_home
        for row in run_home.check(self.home, self.workspaces):
            level = 'error' if row['level'] == 'error' and rule['level'] == 'error' else 'warning'
            self.findings.append({'rule_id': rule['id'], 'level': level, 'path': row['path'],
                                  'write': rule.get('write', 'warning'), 'line': 0,
                                  'what': row['what'], 'how_to_fix': row['how_to_fix']})

    def lint_gates(self, rule):
        rows = self.completion_table('gates', ['stage', 'path', 'required_text'])
        # T742: the write and commit gates (config/hooks, config/githooks) were never wired; they are archived.
        # T738: skill_ship.py no longer runs the system lint before a ship, so the release gate left this table.
        if set(r['stage'] for r in rows) != {'nightly'}:
            raise ValueError('The nightly gate is required.')
        for row in rows:
            path = self.safe_entry(self.home, row['path'])
            if not path.is_file() or row['required_text'] not in path.read_text():
                self.add(rule, path, 0, 'Lint gate is absent or disconnected: ' + row['stage'],
                         'Restore the gate entry that invokes this lint command. Runtime activation is separate.')

    def brand_page(self, rule, path):
        rows = self.completion_table('brand', ['check', 'value', 'source'])
        values = {r['check']: r['value'] for r in rows}
        if not all(r['source'].strip() for r in rows):
            raise ValueError('Brand rules require sources.')
        page = self.page(path)
        for depth, title, line in page.headings:
            visible = re.sub(r'[`*_~]', '', title)
            first = next((c for c in visible if c.isalpha()), '')
            if first and not first.isupper():
                self.add(rule, path, line, 'Heading starts with a lowercase letter.', 'Capitalize the heading under the brand rule.')
        for i, line in enumerate(page.visible, 1):
            for phrase in values['forbidden_phrases'].split('|'):
                if phrase.casefold() in line.casefold():
                    self.add(rule, path, i, 'Copy contains a prohibited brand phrase.', 'Use a specific, supported claim.')
        for section, cells, line in page.tables:
            if len(cells) > int(values['max_table_columns']):
                self.add(rule, path, line, 'Table is too wide for the page contract.', 'Split the table into smaller tables.')
        for line, text, section in page.code:
            if len(text) > int(values['max_code_line']):
                self.add(rule, path, line, 'Code exceeds the branded page width.', 'Split the command at a safe boundary.')
        # A stored visual review must bind to the exact current source, renderer, and screenshots.
        receipts = self.completion_table('visual-reviews', ['home', 'page', 'source_sha256', 'renderer_sha256',
            'width', 'overflow', 'status', 'reviewer', 'image', 'image_sha256'])
        home, relative, owner = self.context(path)
        matches = [r for r in receipts if r['home'] == owner and r['page'] == relative]
        renderer = self.safe_entry(self.home, 'base/lint_render.py')
        css = self.safe_entry(self.home, 'config/lint/brand.css')
        import hashlib
        renderer_hash = hashlib.sha256(renderer.read_bytes() + css.read_bytes()).hexdigest() if renderer.is_file() and css.is_file() else ''
        current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for width in (390, 1440):
            valid = False
            for row in matches:
                if row['width'] != str(width):
                    continue
                image = self.safe_entry(self.home, row['image'])
                valid |= bool(row['source_sha256'] == current_hash and row['renderer_sha256'] == renderer_hash
                    and row['overflow'] == '0' and row['status'] == 'pass' and row['reviewer'].strip()
                    and image.is_file() and row['image_sha256'] == hashlib.sha256(image.read_bytes()).hexdigest())
            if not valid:
                self.add(rule, path, 0, 'Missing current visual review at width ' + str(width) + '.',
                         'Render with lint_render.py; record real screenshot hashes, overflow, and reviewer in visual-reviews.tsv.')

    def run(self, rule_id=None, progress=None):
        selected = [r for r in self.rules if rule_id is None or r['id'] == rule_id]
        if not selected:
            raise ValueError('Unknown rule id: ' + str(rule_id))
        self.inventory(selected)
        for rule in selected:
            kind = rule['kind']
            if progress:
                progress(rule)
            try:
                if kind in ('allowed_top', 'required_pages', 'database', 'tracked_cache', 'tool_inventory', 'lint_growth', 'lint_gates', 'runs'):
                    getattr(self, kind)(rule)
                    continue
                paths = self.dirs + self.files + self.links if kind == 'forbidden_path' else self.dirs if kind == 'empty_folder' else self.files + (self.links if kind == 'links' else [])
                for path in paths:
                    if not self.matches(path, rule['scope']):
                        continue
                    if kind not in ('empty_folder', 'links', 'forbidden_path') and path.suffix.lower() != '.md':
                        continue
                    try:
                        getattr(self, 'links_check' if kind == 'links' else kind)(rule, path)
                    except (OSError, UnicodeError, ValueError, sqlite3.Error) as error:
                        self.add(rule, path, 0, 'Check cannot complete: ' + str(error), 'Restore readable, valid source data within the scan boundary.')
            except (OSError, UnicodeError, ValueError, sqlite3.Error) as error:
                self.add(rule, self.home, 0, 'Check cannot complete: ' + str(error), 'Correct the input or policy. A failed check never passes.')
        unique = {tuple(r.values()): r for r in self.findings}
        return sorted(unique.values(), key=lambda r: (r['rule_id'], r['path'], r['line'], r['what']))


def lint(path,blueprint):
    # Preserve the shipped database API. Import dependencies only for that API.
    from core import connect, EVENTS, load, Q
    db=connect(path,readonly=True)
    targets,columns=load(blueprint);errors=[]
    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':errors.append('SQLite quick_check')
    if list(db.execute('PRAGMA foreign_key_check')):errors.append('foreign keys')
    seqs=[]
    for table in EVENTS:
        for row in db.execute('SELECT * FROM '+Q(table)):
            r=dict(row);seqs.append(r['seq'])
            for name in ('workspace','subject_type','subject_id','action','actor','occurred_at','recorded_at'):
                if r[name] is None or r[name]=='':errors.append(table+' seq '+str(r['seq'])+' lacks '+name)
            if not r.get('session') and not r.get('source'):errors.append(table+' lacks session or source')
            if table=='work_changes' and r['field'] is not None and r['old_value']==r['new_value']:errors.append('echo change seq '+str(r['seq']))
            if table=='work_changes' and r['field']=='status' and r['new_value']=='canceled' and not r.get('summary'):errors.append('canceled without reason')
    if len(seqs)!=len(set(seqs)):errors.append('duplicate seq')
    high=db.execute('SELECT value FROM _foxrun_sequence WHERE id=1').fetchone()[0]
    if sorted(seqs)!=list(range(1,high+1)):errors.append('missing or out-of-order seq')
    for t in targets:
        if t['kind']!='table' or t['name'] in EVENTS:continue
        actual={r[1] for r in db.execute('PRAGMA table_info('+Q(t['name'])+')')}
        states=set(t.get('state_write_columns',[]))&actual
        for field in states:
            for row in db.execute('SELECT * FROM '+Q(t['name'])):
                scope=row['workspace'] if 'workspace' in actual else None
                query="SELECT * FROM work_changes WHERE subject_type=? AND subject_id=? AND field=?"
                args=[t['object_type'],row['id'],field]
                if scope is not None:query+=' AND workspace=?';args.append(scope)
                changes=list(db.execute(query+' ORDER BY seq',args))
                current=None if row[field] is None else str(row[field])
                if not changes:
                    created=db.execute("SELECT refs FROM work_changes WHERE subject_type=? AND subject_id=? AND action IN ('created','imported','decided') AND json_type(refs,'$[0].initial')='object' ORDER BY seq LIMIT 1",(t['object_type'],row['id'])).fetchone()
                    if not created and t.get('database_type') not in ('mirror','trend') and t['name'] not in ('base_modules','base_object_types','base_fields'):errors.append(t['name']+' lacks creation baseline')
                    elif created and (json.loads(created['refs'] or '[]') or [{}])[0].get('initial',{}).get(field)!=current:errors.append(t['name']+'.'+field+' differs from creation baseline')
                elif changes[-1]['new_value']!=current:errors.append(t['name']+'.'+field+' differs from newest event')
                for previous,next_row in zip(changes,changes[1:]):
                    if previous['new_value']!=next_row['old_value']:errors.append(t['name']+'.'+field+' has a missing change')
                if any(c['table']==t['name'] and c['column']=='version' and c['sqlite_type']=='INTEGER' for c in columns):
                    versions=[int(r['subject_version']) for r in changes if r['subject_version'] is not None]
                    if not t.get('version_columns') and len(versions)!=len(set(versions)):errors.append(t['name']+'.'+field+' has duplicate version events')
                    if any(v>row['version'] for v in versions):errors.append(t['name']+'.'+field+' has a future event version')
        if any(c['table']==t['name'] and c['column']=='version' and c['sqlite_type']=='INTEGER' for c in columns):
            for row in db.execute('SELECT id,version FROM '+Q(t['name'])):
                versions={int(r[0]) for r in db.execute('SELECT DISTINCT subject_version FROM work_changes WHERE subject_type=? AND subject_id=? AND subject_version IS NOT NULL',(t['object_type'],row['id']))}
                if t.get('version_family'):
                    # The version is the number of the text in its family (Model row 4046). The row's newest event carries the row's number.
                    if versions and max(versions)!=row['version']:errors.append(t['name']+' has a missing record version')
                elif versions and versions!=set(range(1,row['version']+1)):errors.append(t['name']+' has a missing record version')
    # A yes covers the exact text and facts of its version, and a proof of send keeps its platform id.
    # A load of old history can still write either state; the lint reports it.
    present={r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type IN ('table','view')")}
    if {'people_drafts','people_draft_facts','people_messages','base_approvals'}<=present:
        protected={'people_draft_facts': ('draft-fact', ('text','source_type','source_id','source_ref','draft','checked_at')),
                   'people_drafts': ('draft', ('text','content_hash')),
                   'people_messages': ('message', ('source_message_id',))}
        for table,(kind,fields) in protected.items():
            for row in db.execute('SELECT * FROM '+Q(table)):
                if table=='people_messages' and not db.execute("SELECT 1 FROM people_drafts WHERE status='sent' AND sent_message=?",(row['id'],)).fetchone():continue
                for field in fields:
                    event=db.execute("SELECT new_value FROM work_changes WHERE subject_type=? AND subject_id=? AND field=? ORDER BY seq DESC LIMIT 1",(kind,row['id'],field)).fetchone()
                    current=None if row[field] is None else str(row[field])
                    if event and event['new_value']!=current:errors.append(table+'.'+field+' differs from newest event')
        # Replacing a fact can remove it from the current parent join. Its repeated creation is still in history.
        if db.execute("SELECT 1 FROM work_changes WHERE subject_type='draft-fact' AND action='created' GROUP BY subject_id HAVING count(*)>1 LIMIT 1").fetchone():
            errors.append('people_draft_facts has a fact line created more than once')
        # Use the version at his yes, not the row's version after a later write. Missing events remain a separate weakness.
        version_at_yes="SELECT x.subject_version FROM work_changes x WHERE x.subject_type='draft' AND x.subject_id=a.subject_id AND x.subject_version IS NOT NULL AND x.seq<a.seq ORDER BY x.seq DESC LIMIT 1"
        if db.execute("SELECT 1 FROM base_approvals a WHERE a.subject_type='draft' AND a.authorization_valid=1 AND EXISTS("+version_at_yes+") AND a.version IS NOT CAST(("+version_at_yes+") AS INTEGER) LIMIT 1").fetchone():
            errors.append('base_approvals has a draft approval for a version that was not current at his yes')
        newer="x.seq>d.approval"
        text="EXISTS(SELECT 1 FROM work_changes x WHERE x.subject_type='draft' AND x.subject_id=d.id AND x.field IN ('text','content_hash') AND "+newer+")"
        fact="EXISTS(SELECT 1 FROM work_changes x JOIN people_draft_facts f ON f.id=x.subject_id WHERE x.subject_type='draft-fact' AND f.draft=d.id AND "+newer+" AND NOT (x.field='reviewed_by' AND lower(trim(coalesce(x.new_value,'')))='@person@'))"
        if db.execute("SELECT count(*) FROM people_drafts d WHERE d.status IN ('approved','sent') AND d.approval IS NOT NULL AND ("+text+" OR "+fact+")").fetchone()[0]:
            errors.append('people_drafts has a draft approved or sent whose text or facts changed after his yes')
        if db.execute("SELECT 1 FROM people_drafts d WHERE d.status='sent' AND NOT EXISTS(SELECT 1 FROM people_messages m WHERE m.id=d.sent_message AND m.conversation=d.conversation AND m.direction='outbound' AND m.text=d.text AND coalesce(length(trim(m.source_message_id)),0)>0) LIMIT 1").fetchone():
            errors.append('people_drafts has a sent draft whose read-back does not prove its exact send')
        since="coalesce((SELECT max(s.seq) FROM work_changes s WHERE s.subject_type='draft' AND s.subject_id=d.id AND (s.action='created' OR (s.field='status' AND s.new_value='sent'))),0)"
        if db.execute("SELECT count(*) FROM people_drafts d WHERE d.status='sent' AND EXISTS(SELECT 1 FROM work_changes x WHERE x.subject_type='message' AND x.subject_id=d.sent_message AND x.field='source_message_id' AND x.seq>"+since+")").fetchone()[0]:
            errors.append('people_messages has a proof of send whose platform id changed')
    db.close();return sorted(set(errors))


def legacy_main(argv):
    parser = argparse.ArgumentParser(description='Read the shipped database and event checks.')
    parser.add_argument('--db', required=True)
    parser.add_argument('--blueprint', default=str(Path(__file__).resolve().parent / 'blueprint'))
    args = parser.parse_args(argv)
    errors = lint(args.db, args.blueprint)
    for error in errors:
        print('FAIL ' + error)
    if not errors:
        print('PASS nightly lint')
    return int(bool(errors))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a == "--db" or a.startswith("--db=") for a in argv):
        return legacy_main(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home() / '.foxrun')
    parser.add_argument('--workspaces', type=Path, default=Path.home() / 'foxrun')
    parser.add_argument('--rule', metavar='ID')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        findings = Lint(args.home, args.workspaces).run(args.rule)
    except (OSError, UnicodeError, ValueError, sqlite3.Error) as error:
        findings = [{'rule_id': 'CONFIG', 'level': 'error', 'path': str(POLICY), 'line': 0,
                     'what': 'Lint cannot complete: ' + str(error), 'how_to_fix': 'Correct the policy or scan roots.'}]
        status = 2
    else:
        status = 1 if any(r['level'] == 'error' for r in findings) else 0
    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=['rule_id', 'level', 'path', 'line', 'what', 'how_to_fix'], delimiter='\t', lineterminator='\n')
        writer.writeheader(); writer.writerows(findings)
    return status


if __name__ == '__main__':
    sys.exit(main())
