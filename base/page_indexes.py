#!/usr/bin/env python3
"""Keeper's file indexes. Read sources; stamp changed indexes from the machine clock; check without writes.

index.md takes its shape from base/templates/index.md; --check proves each page is fresh and has that shape (T697)."""
import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote, unquote

PROTECTED = re.compile(r'(^\.env|credential|secret|password|token|(^|[-_.])auth([-_.]|$)|\.(pem|key|p12|pfx)$)', re.I)
ORDER = 'team skills tools ops src config wiki history notes specs raw'.split()
TOP = 'AGENTS.md CLAUDE.md index.md STATE.md RESOLVER.md GLOSSARY.md'.split()
CAPS = 'TEAM.md CAPABILITIES.md DASHBOARD.md TOPICS.md LOG.md'.split()


def move_only(system):
    """Move-only workspaces get index.md; their wiki is never read or written.
    The person names them in config/person.json: "workspace_settings": {"<id>": {"move_only": true}}."""
    try: settings = json.loads((Path(system)/'config/person.json').read_text(encoding='utf-8')).get('workspace_settings') or {}
    except (OSError, ValueError): return set()
    return {ws for ws, v in settings.items() if isinstance(v, dict) and v.get('move_only') is True}

def safe(path):
    return not any(p.startswith('.') or PROTECTED.search(p) or p in ('node_modules', '__pycache__') for p in Path(path).parts)

def walk(root):
    if root.is_symlink() or not root.is_dir():
        return
    for directory, dirs, names in os.walk(str(root), followlinks=False):
        parent = Path(directory)
        dirs[:] = sorted(d for d in dirs if safe(d) and not (parent / d).is_symlink())
        for name in sorted(names):
            p = parent / name
            if safe(name) and not p.is_symlink() and p.is_file():
                yield p

def cell(text):
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('|', '&#124;').replace('[', '&#91;').replace(']', '&#93;').replace('\n', ' ')

def link(path, page, title=None):
    return '[%s](%s)' % (cell(title or path.name), quote(os.path.relpath(str(path), str(page.parent)), safe='/.-_'))

def front(path):
    text = path.read_text(encoding='utf-8', errors='replace')
    if text.startswith('<!-- Built by ') and '-->\n' in text:
        text=text.split('-->\n',1)[1]
    fields = {}
    body = text
    if text.startswith('---\n'):
        end = text.find('\n---', 4)
        if end >= 0:
            for line in text[4:end].splitlines():
                m = re.match(r'^([\w-]+):\s*(.*)', line)
                if m:
                    fields[m[1]] = m[2].strip().strip('"\'')
            body = text[end+4:].lstrip('\n')
    return fields, body

def words(path):
    _, body = front(path)
    lines = body.splitlines()
    index = next((i for i, s in enumerate(lines) if s.startswith('# ')), None)
    if index is None:
        return path.name
    title = lines[index][2:]
    first = next((s.strip() for s in lines[index+1:] if s.strip()), '')
    if re.match(r'^(#|\||[-*+] |\d+[.)] |>|```|~~~|\*\*|@|<!--)', first) or not first:
        return title
    sentence = re.split(r'(?<=[.!?])\s', first)[0]
    return sentence if len(sentence) <= 120 else sentence[:117].rsplit(' ', 1)[0] + '...'

NO_PURPOSE = 'no purpose yet'


def location_rows(path, section=None):
    """Read only location tables, with their purpose wording unchanged."""
    if not path.is_file() or path.is_symlink():
        return
    _, text = front(path)
    active = section is None
    headers = None
    fence = False
    for line in text.splitlines():
        if line.startswith(('```', '~~~')):
            fence = not fence
        if fence:
            continue
        heading = re.match(r'^#+ (.+)$', line)
        if heading:
            active = section is None or heading[1] == section
            headers = None
        if not active or not line.startswith('|'):
            headers = None
            continue
        cells = [part.strip() for part in re.split(r'(?<!\\)\|', line.strip('|'))]
        if all(re.fullmatch(r'[-: ]+', part) for part in cells):
            continue
        if headers is None:
            headers = cells
            continue
        if len(cells) == len(headers):
            yield dict(zip(headers, cells))


def location_purposes(ws, resolver, portfolio=False):
    """Exact folder paths: resolvers, personal rules, then folder-purposes.tsv.

    A file's destination does not define its parent folder. Children do not
    inherit wording from a parent. System rows never become workspace rows.
    """
    result = {}

    def add(place, purpose, base, workspace=None, pages=False):
        # A comma-separated list can name several destinations. A later
        # prose clause (such as "with its test in") is not a destination.
        for match in re.finditer(r'(?:^|,\s*)(?:`([^`]+)`|([^\s,]+))', place):
            name = (match[1] or match[2]).replace('<workspace>', workspace or '<workspace>')
            if (not name.endswith('/') and not (pages and name.endswith('.md'))) or '<' in name or '>' in name:
                continue
            path = Path(name).expanduser()
            if not path.is_absolute():
                path = base / path
            path = Path(os.path.abspath(path))
            if path == ws or ws in path.parents:
                result.setdefault(path, purpose)

    if not portfolio:
        for row in location_rows(ws / 'RESOLVER.md'):
            if 'The thing' in row and 'Its place' in row:
                add(row['Its place'], row['The thing'], ws)
            elif 'Information' in row and 'Authoritative home and format' in row:
                add(row['Authoritative home and format'], row['Information'], ws)
    if resolver is not None:
        rows = list(location_rows(resolver, 'Where Things Live'))
        # A named folder is more specific than the workspace placeholder.
        rows.sort(key=lambda row: '<workspace>' in row.get('Path', ''))
        for row in rows:
            if row.get('Home') != 'Portfolio' or not row.get('Thing') or not row.get('Path'):
                continue
            base = ws if portfolio else ws.parent
            # A workspace placeholder denotes each registered workspace,
            # never an arbitrary portfolio folder such as apps/.
            if portfolio and '<workspace>' in row['Path']:
                for folder in sorted(ws.iterdir()):
                    if folder.is_dir() and not folder.is_symlink() and (folder/'AGENTS.md').is_file():
                        add(row['Path'], row['Thing'], base, folder.name)
            else:
                add(row['Path'], row['Thing'], base, None if portfolio else ws.name)
        if not portfolio:
            for row in location_rows(resolver.parent / 'profile/AGENTS.md', 'Inside Every Workspace'):
                if row.get('You write') and row.get('It goes in'):
                    add(row['It goes in'], row['You write'], ws.parent, ws.name)
    if resolver is not None:
        table = resolver.parent / 'config/folder-purposes.tsv'
        if table.is_file() and not table.is_symlink():
            with table.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream, delimiter='\t'))
            workspace = 'portfolio' if portfolio else ws.name
            # Named rows precede defaults. Location tables above keep priority.
            rows.sort(key=lambda row: row.get('workspace') == '*')
            for row in rows:
                if row.get('workspace') == workspace or (not portfolio and row.get('workspace') == '*'):
                    if row.get('folder') and row.get('purpose'):
                        add(row['folder'], row['purpose'], ws, pages=True)
    return result


def declared_purpose(folder):
    """Read an explicit README purpose, then the folder's DOCUMENTATION row.

    An instruction or contract opener does not declare a folder's purpose.
    No wiki, payload, symlink, or recursive search supplies these words.
    """
    is_page = folder.is_file()
    for readme in ([folder] if is_page else [folder / name for name in ('README.md', 'readme.md')]):
        if not readme.is_file() or readme.is_symlink():
            continue
        fields, text = front(readme)
        if is_page and fields.get('purpose'):
            return fields['purpose']
        purpose_section = False
        fence = False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(('```', '~~~')):
                fence = not fence
                continue
            if fence:
                continue
            label = re.match(r'^(?:\*\*)?Purpose(?:\*\*)?\s*:(?:\*\*)?\s*(.+)$', line, re.I)
            if label:
                return label[1].strip()
            if line.startswith('#'):
                purpose_section = bool(re.fullmatch(r'#+\s+Purpose', line, re.I))
            elif purpose_section and line:
                if not re.match(r'^(\||[-*+] |>|<!--)', line):
                    return line
                purpose_section = False
        # A README can state its purpose as prose directly below its title.
        # Instructions, headings, tables, and labels are not a purpose sentence.
        lines = text.splitlines()
        title = next((i for i, line in enumerate(lines) if line.startswith('# ')), None)
        if title is not None:
            first = next((line.strip() for line in lines[title+1:] if line.strip()), '')
            if (first and not re.match(r'^(#|\||[-*+] |\d+[.)] |>|```|~~~|\*\*|@|<!--)', first)
                    and not re.match(r'^(Read|Run|Start|Open|See|Use|Follow|Install|Copy|Do|Please)\b', first, re.I)
                    and not re.match(r'^[A-Za-z -]{1,30}:', first)):
                return first
    document = folder.parent / 'DOCUMENTATION.md'
    if document.is_file() and not document.is_symlink():
        _, text = front(document)
        section_matches = True
        for line in text.splitlines():
            heading = re.match(r'^## (.+)$', line)
            if heading:
                name = heading[1].strip().strip('`').rstrip('/')
                if name.startswith(('~/', '/')):
                    section_matches = Path(name).expanduser() == folder.parent
                else:
                    section_matches = name in ('.', folder.parent.name, 'Folders', 'Files', 'Workspaces')
            if not section_matches or not line.startswith('|'):
                continue
            cells = [part.strip() for part in re.split(r'(?<!\\)\|', line.strip('|'))]
            if len(cells) < 2:
                continue
            entry = cells[0].strip('`')
            linked = re.fullmatch(r'\[.*?\]\((.*?)\)', entry)
            entry = unquote(linked[1]) if linked else entry
            if entry.rstrip('/') in (folder.name, './'+folder.name, str(folder)):
                purpose = cells[1].strip()
                if purpose and not re.fullmatch(r'[-: ]+', purpose):
                    return purpose
    return NO_PURPOSE


def header(kind, name, date):
    return ['---', 'type: index', 'workspace: '+name, 'timestamp: '+date+'T00:00:00Z', '---',
            '# '+kind+': '+name, '']

# index.md has one shape: base/templates/index.md (T697). The builder fills its slots; check_shape proves a page has it.
TEMPLATE = Path(__file__).resolve().parent / 'templates' / 'index.md'
SLOT = re.compile(r'\{\{(\w+)\}\}')
BLOCK = re.compile(r'\{\{#(\w+)\}\}\n(.*?)\{\{/\1\}\}\n', re.S)
# What one line of a many-line slot may hold. A slot never takes a heading, so a section cannot hide in it.
LINES = {'page_rows': r'\| [^\n]* \|', 'folder_rows': r'\| [^\n]* \|', 'tree': r'(?!```|#)[^\n]+',
         'extra_blocks': r'(?:|```|[A-Z][A-Z ]*  \(\d+\)|   [^\n]*)'}

def template(path=None):
    return (path or TEMPLATE).read_text(encoding='utf-8')

def fill(shape, values):
    """The template with its slots filled. A line that is one slot takes 0 or more lines; a block shows when its value is set."""
    shape = BLOCK.sub(lambda m: m[2] if values.get(m[1]) else '', shape)
    lines = []
    for line in shape.split('\n'):
        whole = SLOT.fullmatch(line)
        if whole:
            lines += values[whole[1]]
        else:
            lines.append(SLOT.sub(lambda m: str(values[m[1]]), line))
    return '\n'.join(lines)

def shape_pattern(shape):
    """The template as one pattern: fixed lines word for word, a slot line as 0 or more lines, a block as optional."""
    tokens = []
    for line in shape.split('\n')[:-1]:
        if re.fullmatch(r'\{\{#\w+\}\}', line):
            tokens.append('(?:')
        elif re.fullmatch(r'\{\{/\w+\}\}', line):
            tokens.append(')?')
        elif SLOT.fullmatch(line):
            tokens.append('(?:' + LINES.get(SLOT.fullmatch(line)[1], '(?!#|```)[^\n]*') + '\n)*?')
        else:
            parts = SLOT.split(line)
            tokens.append(''.join(re.escape(p) if i % 2 == 0 else '[^\n]*?' for i, p in enumerate(parts)) + '\n')
    return re.compile(''.join(tokens))

def check_shape(text, shape=None):
    """True when the page has the template's shape: every fixed line, in order, nothing else between them."""
    return shape_pattern(shape or template()).fullmatch(text) is not None

def index_page(ws, date, resolver, portfolio=False, shape=None, pending=(), built_at=None):
    """index.md of a workspace, or of the portfolio (portfolio=True): the same form, with workspaces as the folders.

    pending: pages this build writes that are not on disk yet; they count, so a second build gives the same page."""
    built_at = built_at or datetime.now().astimezone()
    page = ws / 'index.md'
    entries = [p for p in ws.iterdir() if safe(p.name) and not p.is_symlink()]
    folders = sorted((p for p in entries if p.is_dir()), key=lambda p: (ORDER.index(p.name) if p.name in ORDER and not portfolio else len(ORDER), p.name))
    pages = [p for p in entries if p.is_file() and p.suffix == '.md']
    pages = sorted(pages + ([] if page in pages else [page]), key=lambda p: (TOP.index(p.name) if p.name in TOP else len(TOP), p.name))
    pending = [q for q in pending if not q.is_file()]
    counts = {p: sum(1 for _ in walk(p)) + sum(p in q.parents for q in pending) for p in folders}
    purposes = location_purposes(ws, resolver, portfolio)
    descriptions = {p.name: purposes.get(p) or declared_purpose(p) for p in folders}
    page_rows = []
    for p in pages:
        purpose = purposes.get(p)
        if not purpose and p != page:
            declared = declared_purpose(p)
            purpose = declared if declared != NO_PURPOSE else words(p)
        page_rows.append('| '+link(p,page)+' | '+cell(purpose or 'This page.')+' |')
    folder_rows = []
    for p in folders:
        cap = (p/'index.md' if (p/'index.md').is_file() or p/'index.md' in pending else None) if portfolio else next((p/n for n in CAPS if (p/n).is_file()), None)
        folder_rows.append('| %s | %s | %d | %s |' % (link(p,page,p.name+'/'), cell(descriptions[p.name]), counts[p], link(cap,page) if cap else '—'))
    tree = []
    for p in folders:
        tree.append('%s/ (%d)' % (p.name,counts[p]))
        children = sorted(q for q in p.iterdir() if q.is_dir() and safe(q.name) and not q.is_symlink())
        if len(children)>8:
            tree.append('   %d folders' % len(children))
        else:
            for q in children:
                label = '   %s/ (%d)' % (q.name,sum(1 for _ in walk(q)))
                tree.append(label if len(label)<=78 else '   [folder name exceeds 78 characters]')
    extra = [p.name for p in pages if p.name not in TOP]
    other = [p.name for p in entries if p.is_file() and p.suffix != '.md']
    blocks = []
    for label,names in [('PAGES',extra),('OTHER FILES',sorted(other))]:
        if names:
            blocks += ['', '```', '%s  (%d)' % (label,len(names))]
            blocks += ['   '+name if len(name)<=75 else '   [file name exceeds 78 characters]' for name in names]
            blocks += ['```']
    name = 'portfolio' if portfolio else ws.name
    return fill(shape or template(), {
        'workspace': name, 'timestamp': built_at.isoformat(timespec='seconds'),
        'scope': 'the portfolio' if portfolio else 'this workspace', 'find': 'workspace' if portfolio else 'page',
        'pages_at_top': len(pages), 'folder_count': len(folders),
        'file_count': sum(counts.values())+sum(p.is_file() for p in entries)+int(not page.is_file()),
        'made': built_at.strftime('%Y-%m-%d %H:%M %z'), 'page_rows': page_rows, 'folder_rows': folder_rows, 'tree': tree,
        'extra': bool(blocks), 'extra_blocks': blocks})

def catalog(path):
    """Accept a small explicit topic list, not a Telegram router that also uses topics:."""
    if not path.is_file():
        return {}, ['topic catalog is missing: '+str(path)]
    text = path.read_text(encoding='utf-8')
    match=re.search(r'^wiki_topics:\s*(\{.*\})\s*$',text,re.M)
    if match:text=match[1]
    if not match and re.search(r'^(platform|coordinator|cross_topic):',text,re.M):
        return {}, ['config/topics.yaml is a Telegram router, not a wiki topic catalog']
    result = {}
    # The supported catalog shape is a JSON object (valid YAML), or topics: with scalar id/name rows.
    try:
        data = json.loads(text)
        for row in data.get('topics',[]):
            result[row['id']] = row.get('name',row['id'])
        if isinstance(data.get('topics'),list):return result,[]
    except (ValueError,TypeError,KeyError):
        pending = None
        for line in text.splitlines():
            m = re.match(r'\s*-\s*id:\s*([\w.-]+)\s*$',line)
            if m:
                pending=m[1]; result[pending]=pending
            m = re.match(r'\s+name:\s*(.+)',line)
            if m and pending:
                result[pending]=m[1].strip().strip('"\'')
    return result, ([] if result else ['topic catalog contains no supported topic rows'])

def wiki_roots(portfolio):
    for ws in sorted(portfolio.iterdir()):
        if ws.is_dir() and safe(ws.name) and not ws.is_symlink() and (ws/'AGENTS.md').is_file():
            if ws.name=='atlas':
                yield ws,ws
            elif (ws/'wiki').is_dir():
                yield ws,ws/'wiki'

def topic_pages(portfolio,date,moved=frozenset()):
    outputs,issues = {},[]
    for ws,root in wiki_roots(portfolio):
        if ws.name in moved:
            continue  # Move-only: its wiki is neither read for topic issues nor written.
        topics,errors=catalog(ws/'config/topics.yaml')
        issues += [{'workspace':ws.name,'page':'config/topics.yaml','why':e} for e in errors]
        rows=[]
        roots = [root/p for p in ('concepts','entities','comparisons','queries')] if ws.name=='atlas' else [root]
        for folder in roots:
            for p in walk(folder):
                if p.suffix!='.md' or p.name in ('TOPICS.md','SCHEMA.md','index.md','AGENTS.md','CLAUDE.md'):
                    continue
                fields,body=front(p)
                topic=fields.get('topic',''); subtopic=fields.get('subtopic','')
                title=next((s[2:] for s in body.splitlines() if s.startswith('# ')),p.stem)
                if topic not in topics:
                    issues.append({'workspace':ws.name,'page':str(p.relative_to(ws)), 'why':'page has no topic' if not topic else 'topic is outside the catalog: '+topic})
                    topic=''
                rows.append((topic,subtopic,p,title))
        page=root/'TOPICS.md'
        lines=header('Topics',ws.name,date)+['This page is built from the topic catalog and the wiki pages.', '', '## Contents','']
        groups=sorted(set(t for t,_,_,_ in rows if t))
        for topic in groups:
            title=topics[topic]; anchor=re.sub(r'[^\w -]','',title.lower()).replace(' ','-')
            lines.append('- [%s](#%s) (%d)'%(cell(title),anchor,sum(t==topic for t,_,_,_ in rows)))
            for sub in sorted(set(s for t,s,_,_ in rows if t==topic and s)):
                subanchor=re.sub(r'[^\w -]','',sub.lower()).replace(' ','-')
                lines.append('  - [%s](#%s) (%d)'%(cell(sub),subanchor,sum(t==topic and s==sub for t,s,_,_ in rows)))
        lines += ['', '```', 'TOPICS     '+str(len(groups)), 'SUBTOPICS  '+str(len(set((t,s) for t,s,_,_ in rows if t and s))), 'PAGES      '+str(len(rows)), 'MADE       '+date+' 00:00','```']
        for topic in groups+([''] if any(not r[0] for r in rows) else []):
            lines += ['', '## '+(topics[topic] if topic else 'Not placed yet'),'']
            subs=sorted(set(s for t,s,_,_ in rows if t==topic))
            for sub in subs:
                if sub:
                    lines += ['### '+cell(sub),'']
                for t,s,p,title in sorted(rows,key=lambda r:(r[3].lower(),str(r[2]))):
                    if t==topic and s==sub:
                        lines.append('- '+link(p,page,title))
        outputs[page]='\n'.join(lines)+'\n'
    # The library lives in Atlas (ruling g-library-md-lives-in-atlas-for-now).
    library=portfolio/'atlas'/'LIBRARY.md'
    # Parse the generated TOPICS.md bodies. The library's only source is those indexes.
    wikis=[]
    for ws,root in sorted(wiki_roots(portfolio),key=lambda pair:(pair[0].name!='atlas',pair[0].name)):
        if ws.name in moved:continue
        page=root/'TOPICS.md'; topic=''; subtopic=''; rows=[]
        for line in outputs[page].splitlines():
            if line.startswith('## '):topic=line[3:];subtopic=''
            elif line.startswith('### '):subtopic=line[4:]
            m=re.fullmatch(r'- \[(.*?)\]\((.*?)\)',line)
            if m and topic!='Contents' and not m[2].startswith('#'):
                rows.append((topic,subtopic,page.parent/unquote(m[2]),m[1]))
        wikis.append((ws.name,page,rows))
    lines=header('Library','portfolio',date)+['This page is built from every wiki topic index.', '', '```',
        'WIKIS       '+str(len(wikis)), 'WITH PAGES  '+str(sum(bool(r) for _,_,r in wikis)),
        'PAGES       '+str(sum(len(r) for _,_,r in wikis)), 'MADE        '+date+' 00:00','```','',
        '| Wiki | Topics page | Topics | Pages |','|---|---|---:|---:|']
    for name,page,rows in wikis:
        lines.append('| %s | %s | %d | %d |'%(name,link(page,library),len(set(t for t,_,_,_ in rows if t!='Not placed yet')),len(rows)))
    for name,page,rows in wikis:
        if not rows:continue
        lines += ['', '## '+name,'','| Topic | Subtopics | Pages |','|---|---|---:|']
        for topic in sorted(set(t for t,_,_,_ in rows)):
            anchor=re.sub(r'[^\w -]','',topic.lower()).replace(' ','-')
            target=quote(os.path.relpath(str(page),str(library.parent)),safe='/.-_')+'#'+anchor
            subs=sorted(set(s for t,s,_,_ in rows if t==topic and s))
            lines.append('| [%s](%s) | %s | %d |'%(cell(topic),target,cell(', '.join(subs) or 'None'),sum(t==topic for t,_,_,_ in rows)))
        lines += ['', '### Pages','']
        for topic,subtopic,path,title in rows:
            lines.append('- '+link(path,library,title))
    empty=[name for name,_,rows in wikis if not rows]
    if empty:
        lines += ['', '## Not placed yet','','```','WIKIS WITH NO PAGE  (%d)'%len(empty)]+['   '+n for n in empty]+['```']
    for name in sorted(moved):
        lines += ['', name.capitalize()+' is excluded. Its move-only ruling keeps its wiki files unchanged.']
    outputs[library]='\n'.join(lines)+'\n'
    return outputs,issues

def build(portfolio,system,date,kind):
    outputs,issues={},[]
    built_at = datetime.now().astimezone()
    if kind in ('index','all'):
        for ws in sorted(portfolio.iterdir()):
            if ws.is_dir() and safe(ws.name) and not ws.is_symlink() and (ws/'AGENTS.md').is_file():
                # Every workspace gets index.md, Atlas too (g-atlas-is-a-standard-workspace-with-its-wiki-at-the-top).
                # A move-only workspace still gets index.md; only its wiki stays unchanged (topic_pages skips it).
                outputs[ws/'index.md']=index_page(ws,date,system/'RESOLVER.md',built_at=built_at)
        # The top of the portfolio has the same form, with workspaces as the folders (spec-index.tsv).
        outputs[portfolio/'index.md']=index_page(portfolio,date,system/'RESOLVER.md',portfolio=True,pending=list(outputs),built_at=built_at)
    if kind in ('topics','all'):
        more,issues2=topic_pages(portfolio,date,move_only(system)); outputs.update(more); issues+=issues2
    return outputs,issues

def no_purpose_folders(outputs):
    """Report the exact folder rows flagged in the generated pages."""
    missing = set()
    for page, body in outputs.items():
        if page.name != 'index.md':
            continue
        for target in re.findall(r'^\| \[.*?/\]\((.*?)\) \| no purpose yet \|', body, re.M):
            missing.add(str(page.parent / unquote(target)))
    return sorted(missing)


def same_index(current, expected):
    """Keep an unchanged index's real build time; still check all other bytes."""
    stamp = re.search(r'^timestamp: (.+)$', current, re.M)
    wanted = re.search(r'^timestamp: (.+)$', expected, re.M)
    if not stamp or not wanted or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d', stamp[1]):
        return False
    try:
        made = datetime.fromisoformat(stamp[1]).strftime('%Y-%m-%d %H:%M %z')
        wanted_made = datetime.fromisoformat(wanted[1]).strftime('%Y-%m-%d %H:%M %z')
    except ValueError:
        return False
    current = current.replace('timestamp: '+stamp[1]+'\n', 'timestamp: '+wanted[1]+'\n', 1)
    current = re.sub(r'^(MADE +)'+re.escape(made)+r'$', lambda m: m[1]+wanted_made, current, count=1, flags=re.M)
    return current == expected


def write_outputs(outputs, portfolio, system):
    """Preflight every changed generated page, then write only changed bytes."""
    changed = []
    for path, body in outputs.items():
        if path.is_symlink():
            raise ValueError('linked output refused: '+str(path))
        if not path.is_file() or not (same_index(path.read_text(encoding='utf-8'), body) if path.name == 'index.md' else path.read_text(encoding='utf-8') == body):
            changed.append(path)
    gate = system / 'base/lint_gate.py'
    if gate.is_file():
        for path in changed:
            draft = tempfile.NamedTemporaryFile('w', suffix='.md', encoding='utf-8', newline='\n', delete=False)
            try:
                with draft:
                    draft.write(outputs[path])
                checked = subprocess.run([sys.executable, str(gate), '--mode', 'write',
                    '--home', str(system), '--workspaces', str(portfolio),
                    '--target', str(path), '--body', draft.name], capture_output=True, text=True)
            finally:
                Path(draft.name).unlink()
            if checked.returncode:
                raise ValueError('index write gate failed: '+str(path)+' '+checked.stdout+checked.stderr)
    for path in changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(outputs[path])
    return len(changed)


def refresh_indexes(portfolio, system, date=None):
    """The shape validator calls this after a folder add, archive, or move."""
    outputs, issues = build(portfolio, system, date or datetime.now().astimezone().date().isoformat(), 'index')
    if not all(check_shape(body) for body in outputs.values()):
        raise ValueError('the builder broke the index template shape')
    return {'pages': len(outputs), 'changed': write_outputs(outputs, portfolio, system),
            'no_purpose': no_purpose_folders(outputs), 'issues': issues}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--portfolio',type=Path,required=True);p.add_argument('--system-home',type=Path,required=True)
    p.add_argument('--as-of',required=True);p.add_argument('--kind',choices=('index','topics','all'),default='all')
    p.add_argument('--check',action='store_true',
                   help='write nothing; list pages that are stale or do not have the shape of base/templates/index.md')
    a=p.parse_args(); outputs,issues=build(a.portfolio,a.system_home,a.as_of,a.kind)
    stale=[]; shape=[]; changed=0
    for path,body in outputs.items():
        if path.name=='index.md' and not check_shape(body):
            raise ValueError('the builder broke the template shape: '+str(path))
        if not path.is_file() or not (same_index(path.read_text(encoding='utf-8'), body) if path.name == 'index.md' else path.read_text(encoding='utf-8') == body):
            if a.check:
                stale.append(str(path))
                if path.name=='index.md' and path.is_file() and not check_shape(path.read_text(encoding='utf-8')):
                    shape.append(str(path))
    if not a.check:
        changed = write_outputs(outputs, a.portfolio, a.system_home)
    print(json.dumps({'pages':len(outputs),'changed':changed,'stale':stale,'shape':shape,'issues':issues,
                      'no_purpose':no_purpose_folders(outputs)},ensure_ascii=False))
    return 1 if stale or shape or issues else 0

if __name__=='__main__':
    raise SystemExit(main())
