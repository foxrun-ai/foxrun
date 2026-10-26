#!/usr/bin/env python3
"""Build two pages of one workspace from the files on disk: tools/CAPABILITIES.md and team/TEAM.md.

  python3 base/workspace_pages.py <workspace>            write the two pages
  python3 base/workspace_pages.py <workspace> --check    say which page differs from the files; write nothing

CAPABILITIES.md: every tool and skill the workspace uses, by use. A tool is a page
tools/<kind>/<name>.md with `type: tool`, in the workspace or in the system home. A skill
is a folder with SKILL.md. A workspace uses its own tools and skills, and what a seat
file in team/ loads. TEAM.md: one row for each seat file in team/. The lead is the name
on the line `lead:` of config/team.yaml in the workspace. A person changes the lead
there. A seat file named lead-<workspace>.md does not make a lead by itself. The lines
between the two note marks of TEAM.md are kept. Nobody edits the rest of these pages.
The time lines of a page (timestamp, MADE) are not compared by --check.
Python 3.9 standard library.
"""
import argparse, datetime, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402  the home's own path rules

KINDS = ('cli', 'mcp', 'plugin', 'service', 'external-app', 'schedule')
# The allowed words for the use of a tool. The person rules on this list; a page uses only a word on it.
USES = ['secrets', 'vault & search', 'tickets', 'comms', 'gmail', 'creator & content', 'data & docs', 'dev & repos',
        'sessions', 'browser control', 'computer use']


def uses(SYS):
    """USES plus the person's own words: "tool_uses": [...] in config/person.json of the system home."""
    try: extra = json.loads((Path(SYS) / 'config/person.json').read_text(encoding='utf-8')).get('tool_uses') or []
    except (OSError, ValueError): extra = []
    return USES + [w for w in extra if isinstance(w, str) and w not in USES]
NOTES = ('<!-- notes:start -->', '<!-- notes:end -->')

def front(path):
    """A small reader of front matter: top keys, one nested level, lists, and folded text."""
    try: text = Path(path).read_text(encoding='utf-8')
    except OSError: return {}, ''
    if text.startswith('<!-- Built by '): text = text.split('-->\n', 1)[1]
    if not text.startswith('---\n'): return {}, text
    end = text.find('\n---', 4)
    if end < 0: return {}, text
    if text[4:end].lstrip().startswith('{'):           # front matter written as JSON
        try: return json.loads(text[4:end]), text[end + 4:].lstrip('\n')
        except ValueError: return {}, text[end + 4:].lstrip('\n')
    data, lines, i = {}, text[4:end].split('\n'), 0
    while i < len(lines):
        m = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', lines[i])
        if not m: i += 1; continue
        key, val = m.group(1), m.group(2).strip()
        block = []
        j = i + 1
        while j < len(lines) and (lines[j].startswith((' ', '\t')) or not lines[j].strip()):
            block.append(lines[j]); j += 1
        if val in ('>-', '>', '|', '|-'):
            data[key] = ' '.join(b.strip() for b in block if b.strip())
        elif val == '' and block:
            if all(b.strip().startswith('- ') for b in block if b.strip()):
                data[key] = [b.strip()[2:].strip().strip('"\'') for b in block if b.strip()]
            else:
                sub = {}
                for b in block:
                    mm = re.match(r'^\s+([A-Za-z_][\w-]*):\s*(.*)$', b)
                    if mm: sub[mm.group(1)] = mm.group(2).strip().strip('"\'')
                data[key] = sub
        elif val.startswith('[') and val.endswith(']'):
            data[key] = [x.strip().strip('"\'') for x in val[1:-1].split(',') if x.strip()]
        else:
            if block and not val.startswith(('"', "'")):          # a plain value that goes on in the next lines
                val = ' '.join([val] + [b.strip() for b in block if b.strip()])
            data[key] = val.strip('"\'')
        i = j
    return data, text[end + 4:].lstrip('\n')


def first_sentence(text, cut=120):
    text = ' '.join(str(text).split())
    m = re.search(r'[.!?](?= |$)', text)
    s = text[:m.end()] if m else text
    if len(s) > cut:
        s = s[:cut].rsplit(' ', 1)[0] + ' …'
    return s.replace('|', '\\|')


def block(label, names):
    names = sorted(set(names), key=str.lower)
    if not names: return ''
    lines = []
    line, out = '', []
    for n in names:
        add = n if not line else line + '  ' + n
        if len('   ' + add) > 78 and line:
            out.append('   ' + line); line = n
        else:
            line = add
    if line: out.append('   ' + line)
    return '```\n%s  (%d)\n%s\n```\n' % (label, len(names), '\n'.join(out))


def anchor(heading):
    return '#' + re.sub(r'[^a-z0-9 -]', '', heading.lower()).replace(' ', '-')


def stamp():
    now = datetime.datetime.fromisoformat(os.environ['FOXRUN_PAGE_AS_OF'] + 'T00:00:00+00:00') if os.environ.get('FOXRUN_PAGE_AS_OF') else datetime.datetime.now().astimezone()
    return now.isoformat(timespec='seconds'), now.strftime('%Y-%m-%d %H:%M')


def legacy_capabilities(ws, SYS, WS, add=frozenset(), gone=frozenset(), staged=None, moved_from=None):
    staged, moved_from = staged or {}, moved_from or {}
    home = WS / ws

    def exists(p):
        return (p.exists() or p in add) and p not in gone

    def read(p):
        return staged.get(p, p)                      # a page this job moves or changes: read its new content

    # tool pages of the workspace and of the system home, as they are after the apply
    pages, not_tool = {}, []
    for root in (home / 'tools', SYS / 'tools'):
        cands = set(root.glob('*/*.md')) | {p for p in add if p.parent.parent == root and p.suffix == '.md'}
        for p in sorted(cands):
            if exists(p) and p.parent.name in KINDS:
                if front(moved_from.get(p, read(p)))[0].get('type') == 'tool':
                    # <name>.local.md is the person's own page; it wins over the shipped <name>.md beside it.
                    local = p.stem.endswith('.local')
                    key = p.stem[:-len('.local')] if local else p.stem
                    if key not in pages or (local and pages[key].parent == p.parent):
                        pages[key] = p
                elif root == home / 'tools':
                    not_tool.append(str(p.relative_to(root)))
    for p in sorted(set((home / 'tools').glob('*.md')) | {p for p in add if p.parent == home / 'tools' and p.suffix == '.md'}):
        if p.name != 'CAPABILITIES.md' and exists(p):
            not_tool.append(p.name)
    seats = [p for p in sorted((home / 'team').glob('*.md')) if p.name != 'TEAM.md']
    loaded_tools, loaded_skills = set(), set()
    for s in seats:
        d, _ = front(s)
        aslist = lambda v: v if isinstance(v, list) else []
        loaded_skills |= set(aslist(d.get('skills')))
        loaded_tools |= set(aslist(d.get('tools') if 'id' in d else d.get('mcpServers')))
    own_tools = {n: p for n, p in pages.items() if str(p).startswith(str(home))}
    tools = {}                                       # name -> (kind, use, what, page)
    allowed = uses(SYS)
    for name in sorted(set(own_tools) | loaded_tools):
        p = pages.get(name)
        if p is None:
            tools[name] = ('(not on disk)', '', '(not on disk)', None); continue
        d, body = front(moved_from.get(p, read(p)))
        h1 = re.search(r'^# .+\n+((?:(?!\n\n).)+)', body, re.S)
        tools[name] = (p.parent.name, d.get('use', '') if d.get('type') == 'tool' and d.get('use') in allowed else '',
                       first_sentence(h1.group(1)) if h1 else '(not on disk)', p)
    skills, missing = {}, set()                      # name -> (use, what, path)
    own = {p.parent.name: p for p in sorted((home / 'skills').glob('*/SKILL.md'))}
    for name in sorted(set(own) | loaded_skills):
        p = own.get(name) or next((q for q in (SYS / 'skills' / name / 'SKILL.md', SYS / 'skillwright/skills' / name / 'SKILL.md') if q.is_file()), None)
        if p is None:
            missing.add(name); continue
        d, _ = front(p)
        meta = d.get('metadata') if isinstance(d.get('metadata'), dict) else {}
        skills[name] = (d.get('use') or meta.get('category') or '', first_sentence(d.get('description', '')) or '(not on disk)', p)
    known = sorted(set(tools) | set(pages), key=len, reverse=True)

    def needs(path):
        text = path.read_text(encoding='utf-8', errors='replace')
        hit = [n for n in sorted(set(tools) | set(pages)) if len(n) > 2 and re.search(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])', text, re.I)]
        out = []
        for n in hit:
            p = pages.get(n)
            out.append('[`%s`](%s)' % (n, os.path.relpath(p, home / 'tools')) if p else '`%s`' % n)
        return ' · '.join(out) or '—'

    uses = {}
    for n, t in tools.items():
        if t[1]: uses.setdefault(t[1][:1].upper() + t[1][1:], [[], []])[0].append(n)
    for n, s in skills.items():
        if s[0]: uses.setdefault(s[0][:1].upper() + s[0][1:], [[], []])[1].append(n)
    iso, made = stamp()
    L = ['<!-- Built by workspace_pages.py. Do not edit. -->', '---', 'type: index', 'workspace: ' + ws, 'timestamp: ' + iso, '---', '# Capabilities: ' + ws, '',
         'Every tool and skill this workspace uses, by use. A script makes this page. Edit a tool page, a skill, or a seat file; then run the script.', '',
         '```', 'USES     %d' % len(uses),
         'TOOLS    %-4d with a use: %d' % (len(tools), sum(bool(t[1]) for t in tools.values())),
         'SKILLS   %-4d with a use: %d' % (len(skills), sum(bool(s[0]) for s in skills.values())),
         'MADE     ' + made, '```', '', '## Uses', '', '| Use | Tools | Skills |', '|---|---|---|']
    order = sorted(uses, key=str.lower)
    for u in order:
        L.append('| [%s](%s) | %s | %s |' % (u, anchor(u), len(uses[u][0]) or '—', len(uses[u][1]) or '—'))
    no_use_t = [n for n, t in tools.items() if not t[1]]
    no_use_s = [n for n, s in skills.items() if not s[0]]
    L.append('| [Not placed yet](#not-placed-yet) | %s | %s |' % (len(no_use_t) or '—', len(no_use_s) or '—'))
    L.append('')
    for u in order:
        L += ['## ' + u, '']
        ts, ss = uses[u]
        if ts:
            L += ['| Tool | Kind | What it is |', '|---|---|---|']
            for n in sorted(ts, key=lambda n: (KINDS.index(tools[n][0]) if tools[n][0] in KINDS else 9, n)):
                k, _, what, p = tools[n]
                L.append('| %s | %s | %s |' % ('[`%s`](%s)' % (n, os.path.relpath(p, home / 'tools')) if p else '`%s`' % n, k, what))
            L.append('')
        if ss:
            L += ['| Skill | What it does | Needs |', '|---|---|---|']
            for n in sorted(ss):
                _, what, p = skills[n]
                L.append('| [`%s`](%s) | %s | %s |' % (n, os.path.relpath(p, home / 'tools'), what, needs(p)))
            L.append('')
    L += ['## Not placed yet', '']
    blocks = [block('TOOLS WITH NO USE', no_use_t), block('SKILLS WITH NO USE', no_use_s),
              block('TOOLS WITH NO PAGE', [n for n, t in tools.items() if t[3] is None]),
              block('SKILLS A SEAT LOADS, NOT ON DISK', missing),
              block('PAGES IN tools/ THAT ARE NOT A TOOL PAGE', not_tool)]
    blocks = [b for b in blocks if b]
    L.append('Each name here is in use and has a gap. Give it a use, a page, or a folder; then it leaves this list.' if blocks
             else 'Every tool and skill has a use and a page.')
    for b in blocks: L += ['', b.rstrip('\n')]
    return '\n'.join(L).rstrip() + '\n', {'tools': len(tools), 'skills': len(skills), 'uses': len(uses), 'pages': len(pages)}


from workspace_capabilities import capabilities


def team(ws, SYS, WS, add=frozenset(), gone=frozenset(), settings_file=None):
    folder = WS / ws / 'team'
    files = [p for p in sorted(folder.glob('*.md')) if p.name != 'TEAM.md' and p not in gone]
    settings = settings_file or WS / ws / 'config/team.yaml'
    named = None                                   # the lead is a setting, not a guess from a file name
    if settings.is_file():
        m = re.search(r'^lead:[ \t]*["\']?([A-Za-z0-9][\w.-]*)["\']?[ \t]*(?:#.*)?$', settings.read_text(encoding='utf-8'), re.M)
        named = m.group(1) if m else None
    lead = folder / (named + '.md') if named else None
    shared = paths.resolve_seat(named, home=SYS) if named else None
    rows = ([lead] if lead in files else []) + [p for p in files if p != lead]
    iso, made = stamp()
    L = ['<!-- Built by workspace_pages.py. Do not edit. -->', '---', 'type: index', 'workspace: ' + ws, 'timestamp: ' + iso, '---', '# Team: ' + ws, '']
    if not named:
        first = 'This team has no lead in `config/team.yaml` yet. '
    elif lead in files:
        first = 'The lead is [`%s`](%s). ' % (named, lead.name)
    elif shared is not None:
        first = 'The lead is [`%s`](%s), a shared seat. ' % (named, os.path.relpath(shared, folder))
    else:
        first = 'The lead is `%s`. No seat file with that name is on disk. ' % named
    L.append(first + 'The lead is set in [`config/team.yaml`](../config/team.yaml). ' if settings.is_file() else first)
    L[-1] += 'A script makes the table and the tree from the files in this folder. Write only in Notes.'
    L += ['', '**Go to:** [State](../STATE.md) · [Capabilities](../tools/CAPABILITIES.md) · [Index](../index.md)', '', '```', 'LEAD    ' + (named or '(not on disk)'), 'SEATS   %d' % len(rows), 'MADE    ' + made, '```', '',
          '| Seat | What it does | Runs on |', '|---|---|---|']
    labels = {}
    for p in rows:
        d, _ = front(p)
        what = ' '.join(str(d.get('summary') or d.get('description') or '(not on disk)').split()).replace('|', '\\|')
        runs = ' · '.join(d['runtimes']) if isinstance(d.get('runtimes'), list) else '(not on disk)'
        L.append('| [`%s`](%s)%s | %s | %s |' % (p.stem, p.name, ' · lead' if p == lead else '', what, runs))
        labels[p.name] = ('seat' + (' · lead' if p == lead else '')) if 'id' in d else 'Claude file, not a seat file'
    agents_md = os.path.relpath(SYS / 'profile/AGENTS.md', folder)
    L += ['', 'Each lead directs its own workers. Workers do not start other workers. This rule is in the [global contract](%s).' % agents_md, '',
          'Shared seats work for every workspace. They are in [`~/%s/agents/`](%s).' % (SYS.name, os.path.relpath(SYS / 'agents', folder) + '/'),
          '', '## Files', '', '```', 'team/']
    entries = [('TEAM.md', 'this page')] + [(p.name, labels[p.name]) for p in rows]
    subs = [d for d in sorted(folder.iterdir()) if d.is_dir() and not d.name.startswith('.')]
    width = max([len(n) for n, _ in entries] + [len(k.name) + 3 for d in subs for k in d.iterdir()]) + 3
    for i, (n, lab) in enumerate(entries):
        last = i == len(entries) - 1 and not subs
        L.append('%s %s%s' % ('└─' if last else '├─', n.ljust(width), lab))
    for si, d in enumerate(subs):
        lastd = si == len(subs) - 1
        L.append('%s %s/' % ('└─' if lastd else '├─', d.name))
        kids = [k for k in sorted(d.iterdir()) if not k.name.startswith('.')]
        for ki, k in enumerate(kids):
            seat = folder / (k.stem + '.md')
            L.append('%s  %s %s%s' % (' ' if lastd else '│', '└─' if ki == len(kids) - 1 else '├─', k.name.ljust(width - 3),
                                     'made from %s' % seat.name if seat in files else '(not on disk)'))
    kept = []
    page = folder / 'TEAM.md'
    if page.is_file():
        old = page.read_text(encoding='utf-8')
        if NOTES[0] in old and NOTES[1] in old:
            kept = old.split(NOTES[0], 1)[1].split(NOTES[1], 1)[0].strip('\n').split('\n')
            kept = [k for k in kept if k.strip()]
    L += ['```', '', '## Notes', '', 'A new build keeps the lines between the two note marks.', '', NOTES[0]] + kept + [NOTES[1]]
    text = '\n'.join(L) + '\n'
    if page.is_file() and NOTES[0] in old and NOTES[1] in old:
        kept_text = old.split(NOTES[0], 1)[1].split(NOTES[1], 1)[0]
        text = text.split(NOTES[0], 1)[0] + NOTES[0] + kept_text + NOTES[1] + text.split(NOTES[1], 1)[1]
    return text, len(rows)


def same(a, b):
    drop = lambda t: [l for l in t.splitlines() if not l.startswith(('timestamp:', 'MADE'))]
    return drop(a) == drop(b)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build tools/CAPABILITIES.md and team/TEAM.md of one workspace from the files on disk.')
    ap.add_argument('workspace')
    ap.add_argument('--check', action='store_true', help='write nothing; exit 1 when a page differs from the files')
    ap.add_argument('--system-home', type=Path)
    ap.add_argument('--workspace-root', type=Path)
    ap.add_argument('--as-of')
    a = ap.parse_args(argv)
    if a.as_of: os.environ['FOXRUN_PAGE_AS_OF'] = a.as_of
    SYS, WS = a.system_home or paths.system_home(), a.workspace_root or paths.portfolio()
    home = WS / a.workspace
    if not home.is_dir():
        raise SystemExit('no workspace folder: %s' % home)
    made = {home / 'tools/CAPABILITIES.md': capabilities(a.workspace, SYS, WS)[0], home / 'team/TEAM.md': team(a.workspace, SYS, WS)[0]}
    bad = 0
    for page, text in made.items():
        old = page.read_text(encoding='utf-8') if page.is_file() else ''
        if a.check:
            if not same(old, text):
                bad += 1
                print('differs: %s' % page)
        elif not same(old, text):
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(text, encoding='utf-8')
            print('wrote: %s' % page)
    if a.check:
        print('workspace pages: %d problems' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
