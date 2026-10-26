"""Read explicit workspace sources. Generated pages own no source facts."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
from base.paths import resolve_portfolio_path

from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, unquote, urlsplit

GROUPS = ('contracts', 'team', 'business', 'knowledge', 'build', 'trail', 'history')
CONTRACTS = {'AGENTS.md', 'CLAUDE.md', 'RESOLVER.md', 'SCHEMA.md', 'CONCEPTS.md', 'DESIGN.md', 'BRAND.md'}
TEAM = {'CAPABILITIES.md', 'TOOLS.md', 'index.md', 'modules', 'tools', 'scripts', 'tests', 'state'}
KNOWLEDGE = {'wiki'}
BUILD = {'specs', 'design'}
TRAIL = {'notes', 'snapshots', 'handoffs', 'outputs', 'sources'}
SPEC_PAGES = 'specs'
SENTENCE_MAX = 300
NOT_PROSE = re.compile(r'#{1,6}(\s|$)|[-*+]\s|\d+[.)]\s|[|><]|!\[|(?:[-*_]\s*){3,}$')
TOP_HEADING = re.compile(r'#(?:\s+(.*?))?(?:\s+#+)?')
TABLE_RULE = re.compile(r'\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?')
CODE_SPAN = re.compile(r'(?<![`\\])(`+)(?!`)(.+?)(?<!`)\1(?!`)')
SENTENCE_END = re.compile(r'(?<!\.)[.?!]["\')\]”’]*(?=\s|$)')
BARE_ADDRESS = re.compile(r'(?:https?://|www\.)\S*', re.I)
SHORT_FORMS = {'e.g.', 'i.e.', 'vs.', 'cf.', 'mr.', 'mrs.', 'ms.', 'dr.', 'approx.'}
LABEL = re.compile(r'[*_]{0,2}[^\W\d_][\w-]*(?: [\w-]+)?[*_]{0,2}:[*_]{0,2}(?:\s|$)')
BOLD_START = re.compile(r'(\*\*|__)(.+?)(?:\1|$)')
PROTECTED = re.compile(r'(?:secret|credential|password|private[-_]?key|(?:^|[-_.])(?:auth|token|settings)(?:$|[-_.]))', re.I)


def blocked(name):
    return (name.startswith('.') or name in {'archive', 'System', 'node_modules', '__pycache__', 'venv', 'env'}
            or bool(PROTECTED.search(name)) or Path(name).suffix.lower() in {'.pem', '.key', '.p12', '.pfx'})


def safe_path(path):
    return resolve_portfolio_path(path)


def files(root):
    for directory, dirs, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        dirs[:] = sorted(n for n in dirs if not blocked(n) and not (parent / n).is_symlink())
        for name in sorted(names):
            path = parent / name
            if not blocked(name) and not path.is_symlink() and path.is_file():
                yield path


def group(path):
    first = path.parts[0]
    if first in CONTRACTS:
        return 'contracts'
    if first in TEAM:
        return 'team'
    if first in KNOWLEDGE:
        return 'knowledge'
    if first in BUILD:
        return 'build'
    if first in TRAIL:
        return 'trail'
    if first in {'log.md', 'log.jsonl'}:
        return 'history'
    return 'business'


def cell(value):
    if value is None or value == '':
        return 'Not set'
    return html.escape(' '.join(str(value).split()), quote=True).replace('|', '&#124;').replace('[', '&#91;').replace(']', '&#93;').replace('`', '&#96;')


def link(path, page, label=None):
    path = safe_path(Path(path))
    if not path.exists():
        raise ValueError(f'Link target missing: {path}')
    relative = os.path.relpath(path, page.parent)
    return f'[{cell(label or relative)}]({quote(relative, safe="/.-_")})'


def page_words(value):
    """Return one table cell in the page's own characters, guarded so it adds no link, embed, or HTML to the map."""
    text = ' '.join(str(value).split())
    # The guard is the same inside a code span and beside an address. A renderer can read a code span or an address
    # where this program reads none, and the other way round, and then the words there go live.
    # Every | [ ] gets an odd count of backslashes before it. Then no table rule splits the row there,
    # and no engine reads a link or an embed.
    text = re.sub(r'(\\*)([|\[\]])', lambda m: m[1] + ('' if len(m[1]) % 2 else '\\') + m[2], text)
    text = text.replace('](', ']\\(')
    # A backslash does not hold a < that follows an address: the address takes the backslash. An entity holds it.
    # A page's own backslash before the < goes, or it would turn the entity into plain letters.
    # A < before a space or = cannot open a tag and stays as the page has it.
    return re.sub(r'(\\*)<(?![\s=]|$)', lambda m: m[1][len(m[1]) % 2:] + '&lt;', text)


def address_guarded(value):
    """Say whether the guard changes a bare address in these words: bracket words or a tag touch it."""
    # A renderer takes the words that touch a bare address into the address, and the guard with them.
    # A pipe does not count: the table takes its backslash away before the address is read.
    text = ' '.join(str(value).split())
    return any(re.search(r'[\[\]]|<(?![\s=]|$)', address[0]) for address in BARE_ADDRESS.finditer(text))


def unlisted_spec_pages(workspace):
    """Yield (path, is a folder, why) for each page under specs/ that gets no line. Names only: no page is opened."""
    directory = workspace / SPEC_PAGES
    if directory.is_symlink() or directory.parent.is_symlink():
        yield directory, True, 'symlink'
        return

    def why(name, folder):
        if name.startswith('.'):
            return 'hidden name'
        if PROTECTED.search(name):
            return 'protected word in a folder name' if folder else 'protected word in the file name'
        return f'folder named {name}' if folder else 'file kind left out'

    def walk(parent, inherited):
        try:
            entries = sorted(parent.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for path in entries:
            folder = path.is_dir()
            if path.is_symlink():
                # A link is named and not followed.
                if folder or path.suffix.lower() == '.md':
                    yield path, folder, inherited or 'symlink'
            elif folder:
                reason = inherited or (why(path.name, True) if blocked(path.name) else None)
                if path.name.startswith('.'):
                    # A hidden folder is named and not walked.
                    yield path, True, reason
                else:
                    yield from walk(path, reason)
            elif path.suffix.lower() == '.md':
                reason = inherited or (why(path.name, False) if blocked(path.name) else None)
                if reason:
                    yield path, False, reason

    if directory.is_dir():
        yield from walk(directory, None)


def page_blocks(text):
    """Label each body line as blank, top (a top heading), prose, or other."""
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == '---'), None)
        lines = lines[end + 1:] if end else []
    blocks, fence, table = [], None, False
    for raw in lines:
        raw = raw.expandtabs(4)
        text = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        last = blocks[-1][0] if blocks else 'blank'
        opened = re.match(r'`{3,}|~{3,}', text) if indent < 4 else None
        if fence:
            fence = None if re.fullmatch(re.escape(fence[0]) + '{%d,}' % len(fence), text) else fence
            kind = 'other'
        elif not text:
            kind, table = 'blank', False
        elif opened:
            kind, fence = 'other', opened[0]
        elif table or (indent >= 4 and last != 'prose'):
            # A row of a table, or an indented code line.
            kind = 'other'
        elif last == 'prose' and '|' in text and '|' in blocks[-1][1] and TABLE_RULE.fullmatch(text):
            # A table with no edge pipes: the line above was its header row.
            blocks[-1] = ('other', blocks[-1][1])
            kind, table = 'other', True
        elif last == 'prose' and re.fullmatch(r'=+|-+', text):
            # A heading made with a line of = or - under its words. The = form is a top heading.
            start = len(blocks)
            while start and blocks[start - 1][0] == 'prose':
                start -= 1
            words = ' '.join(block[1] for block in blocks[start:])
            blocks[start:] = [('top' if text[0] == '=' else 'other', words)]
            continue
        else:
            top = TOP_HEADING.fullmatch(text)
            kind = 'top' if top else 'other' if NOT_PROSE.match(text) else 'prose'
            text = (top[1] or '') if top else text
        blocks.append((kind, text))
    return blocks


def first_sentence(words):
    # A full stop inside a code span, in an ellipsis, or after a short form does not end the sentence.
    masked = CODE_SPAN.sub(lambda m: 'x' * len(m[0]), words)
    for end in SENTENCE_END.finditer(masked):
        if masked[:end.start() + 1].split()[-1].lstrip('("\'[“‘').lower() not in SHORT_FORMS:
            return words[:end.end()]
    return words


def label_line(words):
    """Say whether a paragraph starts as a label, not as a sentence about the page."""
    # A key of one or two words and a colon: Created: 2026-07-13. Or bold words that hold a colon or end with a stop.
    bold = BOLD_START.match(words)
    return bool(LABEL.match(words) or (bold and (':' in bold[2] or bold[2].rstrip()[-1:] in ('.', '!'))))


def page_line(path):
    """Return (title, sentence) in the page's own words. Either is None when the page has none."""
    blocks = page_blocks(path.read_text(encoding='utf-8-sig', errors='replace'))
    top = next((i for i, block in enumerate(blocks) if block[0] == 'top'), None)
    title = blocks[top][1] if top is not None else None
    paragraph = []
    # The sentence sits directly under the top heading. Anything else there first means no sentence.
    for kind, text in blocks[0 if top is None else top + 1:]:
        if kind == 'prose':
            paragraph.append(text)
        elif kind != 'blank' or paragraph:
            break
    words = ' '.join(' '.join(paragraph).split())
    sentence = None if label_line(words) else first_sentence(words)
    # A longer text does not fit one line of the map. The caller shows the next shorter thing and flags the page.
    return tuple(value if value and len(value) <= SENTENCE_MAX else None for value in (title, sentence))


def spec_pages(workspace):
    """Yield (path, title, sentence) for each page under specs/, folders inside it included."""
    directory = workspace / SPEC_PAGES
    if directory.is_symlink() or directory.parent.is_symlink() or not directory.is_dir():
        return
    # The same walk as the file counts: hidden, protected, archive, and symlink paths are left out,
    # and a folder that cannot be listed gives no lines.
    for path in sorted(files(directory), key=lambda p: p.relative_to(directory).parts):
        if path.suffix.lower() == '.md':
            try:
                title, sentence = page_line(path)
            except OSError:
                # One page that cannot be read must not stop the map. It is listed by its file name and flagged.
                title, sentence = None, None
            yield path, title, sentence


def heading(kind, workspace, title, date):
    return ['---', f'type: {kind}', f'workspace: {workspace.name}', f'timestamp: {date}T00:00:00Z',
            '---', '', f'# {title}', '', 'Generated from sources. In review, ready for your yes.', '']


def write_pages(pages):
    # Validate every target before the first write. Never follow a symlink.
    for path in pages:
        safe_path(path)
    changed = []
    for path, content in pages.items():
        payload = content.encode('utf-8')
        if path.exists() and path.read_bytes() == payload:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        changed.append(str(path))
    return changed


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def q(name):
    return '"' + name.replace('"', '""') + '"'


class Source:
    def __init__(self, path, workspace):
        self.path = safe_path(Path(path))
        if not self.path.is_file() or blocked(self.path.name):
            raise ValueError('Database must be an existing unprotected file')
        self.workspace = workspace
        self.connection = _fox_person.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA query_only=ON')
        self.connection.execute('BEGIN')
        self.clock_connection = _fox_person.connect(':memory:')
        self.objects = {r['name']: dict(r) for r in self.connection.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")
            if not blocked(r['name']) and not r['name'].startswith('_')}

    def close(self):
        self.connection.close()
        self.clock_connection.close()

    def freeze_clock(self, date):
        # Source views keep their SQL. Only their SQLite clock reads use the report date.
        for name in ('date', 'time', 'datetime', 'julianday', 'unixepoch', 'strftime'):
            def function(*args, function_name=name):
                values = list(args)
                offset = 1 if function_name == 'strftime' else 0
                if len(values) == offset:
                    values.append(date + 'T00:00:00Z')
                elif len(values) > offset and str(values[offset]).lower() == 'now':
                    values[offset] = date + 'T00:00:00Z'
                placeholders = ','.join('?' for _ in values)
                return self.clock_connection.execute(f'SELECT {function_name}({placeholders})', values).fetchone()[0]
            self.connection.create_function(name, -1, function, deterministic=True)
        for name, value in (('current_date', date), ('current_time', '00:00:00'), ('current_timestamp', date + ' 00:00:00')):
            self.connection.create_function(name, 0, lambda value=value: value, deterministic=True)

    def columns(self, name):
        return [r['name'] for r in self.connection.execute(f'PRAGMA table_info({q(name)})')]

    def where(self, name):
        columns = self.columns(name)
        if 'workspace' in columns:
            return ' WHERE workspace=?', [self.workspace]
        if name == 'functions' and 'organization' in columns:
            organization = _fox_person.workspace_setting(self.workspace, 'organization', self.workspace)
            return ' WHERE organization=?', [organization]
        return '', []

    def rows(self, name):
        if name not in self.objects:
            return []
        where, args = self.where(name)
        rows = [dict(r) for r in self.connection.execute(f'SELECT * FROM {q(name)}{where}', args)]
        return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))

    def inventory(self, date):
        self.freeze_clock(date)
        result = []
        definitions = self.rows('object_types') or self.rows('base_object_types')
        modules = {r['id']: r.get('name') for r in self.rows('base_modules')}
        for name, obj in self.objects.items():
            columns = self.columns(name)
            where, args = self.where(name)
            count = self.connection.execute(f'SELECT count(*) FROM {q(name)}{where}', args).fetchone()[0]
            definitions_for_name = [r for r in definitions if r.get('storage_name') == name or r.get('location') == name]
            definition = definitions_for_name[0] if len(definitions_for_name) == 1 else {}
            newest = None
            age = 'Unknown'
            age_field = next((c for c in ('fetched_at', 'pulled_at', 'as_of', 'updated_at', 'created_at', 'created_on', 'at') if c in columns), None)
            if obj['type'] == 'table' and age_field:
                dates = []
                for (value,) in self.connection.execute(f'SELECT {q(age_field)} FROM {q(name)}{where}', args):
                    if value:
                        try:
                            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                            if parsed.tzinfo is not None or len(str(value)) == 10:
                                dates.append(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc))
                        except ValueError:
                            pass
                if dates:
                    newest = max(dates)
                    days = (datetime.fromisoformat(date).replace(tzinfo=timezone.utc) - newest).days
                    age = f'{days} days' if days >= 0 else f'Future: {abs(days)} days'
            if count == 0:
                age = 'No rows'
            result.append({'name': name, 'type': definition.get('database_type') or obj['type'],
                           'object_type': definition.get('name'), 'module': modules.get(definition.get('module'), definition.get('module')),
                           'scope': 'workspace' if 'workspace' in columns else 'database',
                           'rows': count, 'age': age, 'age_field': age_field, 'newest': newest.isoformat() if newest else None})
        return result


REFERENCE_DEFINITION = re.compile(r'^( {0,3}\[([^\]\n]+)\]:[ \t]*)(?:<([^>\n]+)>|((?:\\.|[^\s])+))([^\n]*)$', re.M)


def reference_label(value):
    return ' '.join(value.split()).casefold()


def markdown_prose(text):
    # Links inside code examples do not create Markdown links.
    text = re.sub(r'^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[ \t]*$', '', text, flags=re.M | re.S)
    return re.sub(r'(`+)[^\n]*?\1', '', text)


def check_links(pages):
    errors = []
    for page in pages:
        text = markdown_prose(page.read_text())
        definitions = {reference_label(m[2]): m[3] or m[4] for m in REFERENCE_DEFINITION.finditer(text)}
        targets = list(definitions.values())
        for raw in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', text):
            match = re.match(r'\s*(?:<([^>]+)>|(\S+))', raw)
            if match:
                targets.append(match[1] or match[2])
        for match in re.finditer(r'!?\[([^\]\n]+)\]\[([^\]\n]*)\]', text):
            label = reference_label(match[2] or match[1])
            if label not in definitions:
                errors.append(f'{page}: undefined reference [{label}]')
        for target in targets:
            if urlsplit(target).scheme:
                continue
            path = unquote(urlsplit(target).path)
            if path and not (page.parent / path).exists():
                errors.append(f'{page}: {target}')
    return errors


def date_arg(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Report date must be YYYY-MM-DD')
    datetime.fromisoformat(value)
    return value
