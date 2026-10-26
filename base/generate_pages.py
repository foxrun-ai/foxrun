#!/usr/bin/env python3
"""Build schema and glossary pages from dictionary and reviewed word rows."""
import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import sqlite3

def glossary(rows, workspace, context=''):
    selected = [row for row in rows if row['workspace'] == workspace]
    lines = ['# Glossary: ' + workspace, '', 'Generated from `config/words.tsv`. Change the rows, then rebuild.', '', context.strip(), '']
    group = None
    for row in selected:
        if group != row['group']:
            group = row['group']; lines.extend(['## ' + group, '', '| Word | Meaning | Where | Source |', '|---|---|---|---|'])
        lines.append('| ' + ' | '.join(row.get(k, '').replace('|', '\\|').replace('\n', '<br>') for k in ('word','meaning','where','source')) + ' |')
    return '\n'.join(lines) + '\n'

def strip_front_matter(text):
    # The rules file may carry its own front matter; the page has one block, at the top.
    if text.startswith('---\n'):
        end = text.find('\n---\n', 4)
        if end >= 0:
            return text[end + 5:]
    return text

def stamp(path, body):
    # Keep the old timestamp when the body is the same, so a rebuild with no change is a no-op.
    if path.is_file():
        old = path.read_text(encoding='utf-8')
        if old.startswith('---\n') and strip_front_matter(old) == body:
            for line in old.split('\n---\n', 1)[0].splitlines():
                if line.startswith('timestamp: '):
                    return line[len('timestamp: '):]
    return datetime.now().astimezone().isoformat(timespec='seconds')

def schema(home, timestamp=None):
    with sqlite3.connect('file:' + str(home/'data.db') + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        objects = [dict(r) for r in db.execute('SELECT * FROM object_types ORDER BY module,name')]
        fields = [dict(r) for r in db.execute('SELECT * FROM fields ORDER BY object_type,ordinal,field')]
    rules = strip_front_matter((home/'config/naming.md').read_text(encoding='utf-8')).strip()
    lines = ['# Schema: system', '', 'Built by `base/generate_pages.py` from `config/naming.md` and the `object_types` and `fields` rows of `data.db`. Change those, then rebuild.', '', rules, '', '## Tables and objects', '', '| Name | Module | Storage | Meaning |', '|---|---|---|---|']
    clean = lambda x: str(x or '').replace('|','\\|').replace('\n','<br>')
    for row in objects:
        lines.append('| ' + ' | '.join(clean(row.get(k)) for k in ('name','module','storage_name','description')) + ' |')
    lines.extend(['', '## Fields', '', '| Object | Field | Type | Required | Meaning |', '|---|---|---|---|---|'])
    for row in fields:
        lines.append('| ' + ' | '.join(clean(row.get(k)) for k in ('object_type','field','field_type','required','description')) + ' |')
    body = '\n'.join(lines) + '\n'
    when = timestamp or stamp(home/'SCHEMA.md', body)
    return '---\ntype: doc\nworkspace: system\ntimestamp: ' + when + '\n---\n' + body

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home', type=Path, required=True); p.add_argument('--portfolio', type=Path, required=True)
    p.add_argument('--check', action='store_true'); args = p.parse_args()
    rows = list(csv.DictReader((args.home/'config/words.tsv').open(encoding='utf-8', newline=''), delimiter='\t'))
    outputs = {args.home/'SCHEMA.md': schema(args.home)}
    workspaces = {row['workspace'] for row in rows} | {p.parent.parent.name for p in args.portfolio.glob('*/config/glossary-context.md')}
    for workspace in sorted(workspaces):
        if workspace != 'system' and (not workspace or '/' in workspace or workspace in ('.','..')):
            raise ValueError('invalid workspace: ' + workspace)
        root = args.home if workspace == 'system' else args.portfolio/workspace
        context = root/'config/glossary-context.md'
        outputs[root/'GLOSSARY.md'] = glossary(rows, workspace, context.read_text(encoding='utf-8') if context.exists() else '')
    differences = []
    for path, body in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != body: differences.append(str(path))
        else:
            with path.open('w', encoding='utf-8', newline='\n') as stream:
                stream.write(body)
    print(str(len(outputs)) + ' pages; ' + str(len(differences)) + ' differences')
    for path in differences: print(path)
    return 1 if differences else 0

if __name__ == '__main__':
    raise SystemExit(main())
