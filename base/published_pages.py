#!/usr/bin/env python3
"""Generate the glossary pages from word rows.

python3 -B base/published_pages.py --home HOME --portfolio PORTFOLIO [--check]
Words: HOME/config/words.tsv (shared); WORKSPACE/config/glossary-words.tsv (local).
GUIDE.md and INSTALL.md are hand-written product pages; this script does not build them.
Change rows, then regenerate. Python 3.9 stdlib. No runtime settings or agent start pages are written.
"""
import argparse
import sys
import csv
import json
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def cell(text):
    return text.replace('|', '\\|').replace('\n', ' ')


def words(path):
    values = rows(path)
    seen = set()
    for row in values:
        name = (row['group'].strip().casefold(), row['word'].strip().casefold())
        if not name[1] or name in seen or not row['meaning'].strip():
            raise ValueError('empty or duplicate word in ' + str(path))
        seen.add(name)
    return values


def approved_tags(folder):
    """Keep the existing owner and exact tag section as durable configuration."""
    source = folder / 'config/glossary-tags.json'
    if source.is_file():
        return json.loads(source.read_text(encoding='utf-8'))
    page = folder / 'GLOSSARY.md'
    old = page.read_text(encoding='utf-8') if page.is_file() else ''
    if '## Approved tags\n' not in old:
        # A workspace with no approved tags yet gets an empty section, not a failed build.
        return {'owner': 'Person approves; keeper maintains', 'section': '## Approved tags\n\nNone yet.\n'}
    section = old.split('## Approved tags\n', 1)[1].split('\n## ', 1)[0]
    return {'owner': 'Person approves; keeper maintains',
            'section': '## Approved tags\n' + section.rstrip() + '\n'}


def glossary(values, workspace, shared=None, tags=None):
    lines = ['---', 'type: glossary', 'workspace: ' + workspace, 'tags: []', '---',
             '# Glossary: ' + workspace, '', 'Generated from word rows. Change the rows, then run `base/published_pages.py`.', '']
    if shared:
        lines += ['[Shared setup words](' + shared + ') apply here. This page holds only this workspace’s own words.', '']
        lines += ['| Item | Owner |', '|---|---|',
                  '| Business words | Person defines; keeper proposes |',
                  '| Approved tags | ' + tags['owner'] + ' |', '']
    else:
        lines += ['Each word has one meaning. Each workspace keeps its own words in its own `GLOSSARY.md`.', '']
    groups = list(dict.fromkeys(row['group'] for row in values))
    for group in groups:
        lines += ['## ' + group, '', '| Word | Meaning | Source |', '|---|---|---|']
        for row in values:
            if row['group'] == group:
                lines.append('| **%s** | %s | %s |' % tuple(cell(row[k]) for k in ('word', 'meaning', 'source')))
        lines.append('')
    if not values:
        lines += ['## Business words', '', 'No business words are recorded yet.', '']
    if tags:
        lines += [tags['section'].rstrip(), '',
                  'Tag source: [`config/glossary-tags.json`](config/glossary-tags.json).',
                  'The person approves changes. The keeper updates this source after approval.', '']
    return '\n'.join(lines).rstrip() + '\n'


def pages(home, portfolio, word_rows=None, local_word_rows=None):
    all_words = rows(home / 'config/words.tsv') if word_rows is None else word_rows
    local_word_rows = local_word_rows or {}
    shared = [r for r in all_words if r['workspace'] == 'system']
    from base.generate_pages import glossary as canonical_glossary, strip_front_matter
    products = {home / 'GLOSSARY.md': canonical_glossary(all_words, 'system')}
    if portfolio.is_dir():
        paths = set(portfolio.glob('*/GLOSSARY.md'))
        paths.update(path.parent.parent / 'GLOSSARY.md' for path in portfolio.glob('*/config/glossary-words.tsv'))
        paths.update(portfolio / name / 'GLOSSARY.md' for name in local_word_rows)
        for path in sorted(paths):
            if path.parent.is_symlink():
                continue  # A linked workspace folder is another name for a real one; build the real one only.
            if path.is_symlink():
                raise ValueError('workspace glossary is a link: ' + str(path))
            local = path.parent / 'config/glossary-words.tsv'
            local_words = local_word_rows.get(path.parent.name)
            if local_words is None:
                local_words = words(local) if local.is_file() else []
            shared_names = {r['word'].casefold() for r in shared}
            if any(r['word'].casefold() in shared_names for r in local_words):
                raise ValueError('workspace repeats a shared word: ' + str(local))
            tags = approved_tags(path.parent)
            products[path.parent / 'config/glossary-tags.json'] = json.dumps(tags, indent=2) + '\n'
            context = path.parent / 'config/glossary-context.md'
            # Local words join the shared rows under this workspace, so the page shows them.
            local_rows = [{'workspace': path.parent.name, 'group': r['group'] or 'Business words', 'word': r['word'],
                           'meaning': r['meaning'], 'where': r.get('where') or '', 'source': r.get('source') or ''} for r in local_words]
            products[path] = canonical_glossary(all_words + local_rows, path.parent.name, strip_front_matter(context.read_text(encoding='utf-8')) if context.is_file() else '')
    # Each page carries SCHEMA front matter; the timestamp holds while the body is the same.
    from base.generate_pages import stamp
    for path, body in list(products.items()):
        if path.suffix == '.md' and not body.startswith('---\n'):
            kind = 'glossary' if path.name == 'GLOSSARY.md' else 'doc'
            workspace = 'system' if path.parent == home else path.parent.name
            products[path] = '---\ntype: %s\nworkspace: %s\ntimestamp: %s\n---\n%s' % (kind, workspace, stamp(path, body), body)
    return products


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path)
    parser.add_argument('--portfolio', required=True, type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    bad = 0
    for path, body in pages(args.home.resolve(), args.portfolio.resolve()).items():
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != body:
                print('differs: ' + str(path)); bad += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8', newline='\n') as stream:
                stream.write(body)
    print('published pages: %d problems' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
