#!/usr/bin/env python3
"""Start check: load the Foxrun rules into every Claude and Codex session.

Claude and Codex both run this on SessionStart and pass JSON on stdin with
`cwd`. In every folder, ~/foxrun and ~/.foxrun included, it prints the soul,
the system rules, and the person's rules as SessionStart additionalContext.
Inside ~/foxrun the CLAUDE.md imports do not load them reliably: the
`@../.foxrun/CLAUDE.md` import is outside the project and needs an approval
per project, and Codex does not follow imports. Where Claude does load the
imports (~/.foxrun, or a project with the approval), the rules come twice.
That is accepted: a duplicate is better than a session without the rules.

Both runtimes cap one hook's context near 10,000 characters (Claude saves the
rest to a file, Codex cuts the middle). So the text is cut at line ends into
parts of at most LIMIT characters, and the runtime config runs this once per
part: `start-rules.py 1`, `start-rules.py 2`, ... up to PARTS. With no part
number it prints the whole text, for a manual check.

Hermes runs it as a pre_llm_call shell hook, every turn. On the first turn it
prints the whole text as {"context": ...}; on later turns it prints {}.

The rules are read from the Foxrun home this script is installed in
(FOXRUN_HOME, else the folder above hooks/), so an install in any folder works.

It must never block a session: on any error it exits 0 and prints nothing.
"""
import json
import os
import sys

HOME = os.path.expanduser('~')
ROOT = os.environ.get('FOXRUN_HOME') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = ('agents/soul.md', 'profile/AGENTS.md')


def shown(name):
    """The path as the reader sees it: ~/.foxrun/profile/AGENTS.md for the usual home."""
    path = os.path.join(ROOT, name)
    inside = os.path.relpath(path, HOME)
    return path if inside.startswith('..') else '~/' + inside
LIMIT = 8000  # characters per part, under both runtime caps
PARTS = 4     # parts the runtime configs run; keep in step with them


def split(files):
    """Cut [(name, text)] into parts. A part that starts inside a file opens
    with that file's name, so each part reads alone: Claude can join the
    parts in any order."""
    parts, current, name = [], '', ''
    for name, text in files:
        for line in text.splitlines(keepends=True):
            while line:
                if current and len(current) + len(line) > LIMIT:
                    parts.append(current)
                    current = ''
                if not current and not line.startswith('===== '):
                    current = f'===== {shown(name)} (continued) =====\n\n'
                room = LIMIT - len(current)
                current += line[:room]
                line = line[room:]
    if current:
        parts.append(current)
    return parts


def main():
    part = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    raw = sys.stdin.read() if not sys.stdin.isatty() else ''
    payload = json.loads(raw) if raw.strip() else {}
    payload = payload if isinstance(payload, dict) else {}
    hermes = payload.get('hook_event_name') == 'pre_llm_call'
    if hermes and not (payload.get('extra') or {}).get('is_first_turn'):
        print('{}')
        return
    cwd = payload.get('cwd') or os.getcwd()
    files = []
    for name in RULES:
        if not os.path.isfile(os.path.join(ROOT, name)):
            continue  # A new install has no profile/AGENTS.md until the person writes one.
        with open(os.path.join(ROOT, name), encoding='utf-8') as handle:
            files.append((name, f'===== {shown(name)} =====\n\n{handle.read().strip()}\n\n'))
    if not files:
        return
    body = [text for _, text in files]
    chunks = split(files)
    total = len(chunks)
    head = f'Foxrun rules loaded by the start check: this session started in {cwd}.'
    if part == 0 or hermes:
        text = head + '\n\n' + ''.join(body)
    elif part > total:
        return
    else:
        text = f'{head} Part {part} of {total}.\n\n' + chunks[part - 1]
        if part == PARTS and total > PARTS:
            text += ('\n\nThe start check carries only part of the rules. Read in full before '
                     'your first reply: ' + ', '.join(shown(name) for name, _ in files))
    if hermes:
        print(json.dumps({'context': text}))
        return
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': text}}))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
