#!/usr/bin/env python3
"""Compile saved sources into cited topic pages and research answers."""

from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote, urlsplit

sys.path.insert(0, str((Path(__file__).resolve().parent / '../base')))
from pages_common import blocked, cell, date_arg, files, heading, link, safe_path, sha, write_pages
sys.path.insert(0, str((Path(__file__).resolve().parent)))
from markdown_links import LINE_END, rewrite, scan
from base import paths as _fox_paths


def split_frontmatter(text):
    match = re.match(r'\A---\r?\n(.*?)\r?\n---\r?\n', text, re.S)
    if match:
        return match[1], text[match.end():]
    return '', text


def scalar(value):
    value = value.strip()
    if value.startswith('"'):
        try:
            return json.loads(value)
        except ValueError:
            return value.strip('"')
    return value.strip("'")


def metadata(header):
    result = {}
    key = None
    for line in header.splitlines():
        match = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', line)
        if match:
            key, value = match.groups()
            if value.startswith('[') and value.endswith(']'):
                try:
                    result[key] = json.loads(value)
                except ValueError:
                    result[key] = [scalar(v) for v in value[1:-1].split(',') if v.strip()]
            else:
                result[key] = scalar(value)
        elif key and re.match(r'^\s*-\s+', line):
            if not isinstance(result.get(key), list):
                result[key] = []
            result[key].append(scalar(re.sub(r'^\s*-\s+', '', line)))
    return result


def slug(value):
    result = re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-')[:90]
    return result or 'source-' + hashlib.sha256(str(value).encode()).hexdigest()[:12]


def expand(paths):
    result = set()
    for argument in paths:
        path = safe_path(argument)
        if blocked(path.name):
            raise ValueError(f'Protected source refused: {path}')
        if not path.exists():
            raise ValueError(f'Source missing: {path}')
        entries = files(path) if path.is_dir() else [path]
        for entry in entries:
            if entry.suffix == '.md' and not any(blocked(p) for p in entry.relative_to(path if path.is_dir() else path.parent).parts):
                if not entry.name.startswith('wp-source-'):
                    result.add(entry)
    return sorted(result)


def read_source(path, workspace, date):
    payload = path.read_bytes()
    text = payload.decode('utf-8')
    header, body = split_frontmatter(text)
    outer = metadata(header)
    already_raw = path.is_relative_to(workspace / 'wiki/raw') and bool(outer.get('sha256'))
    if already_raw:
        digest = hashlib.sha256(body.encode()).hexdigest()
        if outer['sha256'] != digest:
            raise ValueError(f'Raw body hash differs: {path}')
        original_header, original_body = split_frontmatter(body)
        details = {**outer, **metadata(original_header)}
        content = original_body
        raw = path
        raw_payload = None
        home = Path(os.path.normpath(workspace / str(outer['source_path']))).parent if outer.get('source_path') else None
    else:
        home = None
        digest = hashlib.sha256(payload).hexdigest()
        details = outer
        content = body
        raw = workspace / 'wiki/raw/documents' / f'wp-source-{slug(path.stem)}-{digest[:16]}.md'
        relative = os.path.relpath(path, workspace)
        raw_payload = ('---\ningested: ' + json.dumps(date) + '\nsha256: ' + digest + '\nsource_path: ' + json.dumps(relative) + '\n---\n').encode() + payload
    title_match = re.search(r'^#\s+(.+)$', content, re.M)
    title = details.get('title') or details.get('name') or (title_match[1] if title_match else path.stem)
    topics = details.get('topics') or details.get('topic') or details.get('topic_id') or details.get('tags') or [title]
    if not isinstance(topics, list):
        topics = [topics]
    topics = sorted({str(v).strip() for v in topics if str(v).strip()}) or [str(title)]
    original = details.get('source_url') or details.get('url') or details.get('original_url')
    who = details.get('author') or details.get('by') or details.get('agent') or 'Not set'
    return {'path': path, 'raw': raw, 'raw_payload': raw_payload, 'hash': digest, 'file_hash': hashlib.sha256(payload).hexdigest(),
            'title': str(title), 'topics': topics, 'subtopic': details.get('subtopic') or details.get('use_case') or details.get('use-case'),
            'who': who, 'original': original, 'home': home, 'body': content, 'body_line': len(LINE_END.findall(text[:len(text) - len(content)])), 'date': details.get('timestamp') or details.get('created') or details.get('source_document_timestamp')}


def planned_link(path, page, title):
    return '[' + cell(title) + '](' + quote(os.path.relpath(path, page.parent), safe='/.-_') + ')'


def original_link(record, page):
    target = str(record.get('original') or '')
    if urlsplit(target).scheme in ('http', 'https') and not any(v in target for v in ('\n', '\r', ')')):
        return '[Original](' + target + ')'
    return link(record['path'], page, 'Saved source')


def plain_title(title):
    """Return a title with no live link. A link in a page heading would point from the wrong folder."""
    for _ in range(4):
        found = scan(title, frontmatter=False).links
        links = [v for v in found if v.kind in ('inline', 'image', 'wikilink', 'embed')]
        if not links:
            if any(v.kind == 'html' for v in found):
                title = title.replace('<', '&lt;')
            break
        for found in sorted(links, key=lambda v: v.start, reverse=True):
            title = title[:found.start] + found.label + title[found.end:]
    return title


def vault_files(vault):
    """Index the vault's files by lower-case name, for wikilinks that name a note with no folder."""
    index = defaultdict(list)
    for directory, folders, names in os.walk(vault, followlinks=False):
        folders[:] = sorted(n for n in folders if not n.startswith('.') and not (Path(directory) / n).is_symlink())
        for name in sorted(names):
            if not (Path(directory) / name).is_symlink():
                index[name.lower()].append(Path(directory) / name)
    return index


def answer_body(record, page, workspace, lookup=None, gone=(), coming=()):
    """Keep the answer text. Move each relative link from the source's folder to the page's folder.

    Returns the text and one outcome for each destination. A link whose target does not exist
    stays as written and is reported. The scanner changes only the path of a destination.
    """
    # A frozen raw copy keeps the links of its original home. Try that home first, then the file's own folder.
    origins = list(dict.fromkeys(folder for folder in (record.get('home'), record['path'].parent) if folder))
    origin = origins[0]
    vault = workspace.parent

    def symlinked(path):
        return any(p.is_symlink() for p in (path, *path.parents))

    def present(path):
        # Judge a target as it is when the compile ends: a page this compile writes is there,
        # and a generated page this compile archives is gone. A second run then gives the same answer.
        return (os.path.lexists(path) or path in coming) and path not in gone

    def relocated(target, mode):
        if mode == 'wiki':
            return wiki_relocated(target)
        # A Markdown link in a vault can also start at the vault root, or leave out the .md of a note.
        # The answer is the folder prefix to put before the written path. The written path stays.
        folders = origins if mode == 'plain' else [*origins, vault]
        for folder in folders:
            for text in dict.fromkeys((unquote(target), target)):
                path = Path(os.path.normpath(folder / text))
                note = path.with_name(path.name + '.md')
                suffix = '' if present(path) else '.md' if mode == 'vault' and present(note) and not note.is_dir() else None
                if suffix is not None:
                    if symlinked(note if suffix else path):
                        return None, 'the target is a symlink'
                    return (os.path.relpath(folder, page.parent), suffix), None
        return None, 'the target does not exist'

    def wiki_relocated(target):
        # workspace notes's order: a path from the source's folder, a path from the vault root,
        # then the name anywhere in the vault, where the shortest path wins.
        candidates = [*(folder / target for folder in origins), vault / target]
        candidates += [p.with_name(p.name + '.md') for p in candidates]
        candidates = [Path(os.path.normpath(p)) for p in candidates]
        path = next((p for p in candidates if present(p) and not p.is_dir()), None)
        if path is None:
            index = dict(lookup() if lookup else vault_files(vault))
            for extra in coming:
                index[extra.name.lower()] = [*index.get(extra.name.lower(), []), *([] if extra.exists() else [extra])]
            wanted = target.replace('\\', '/').strip('/').lower()
            name = wanted.rsplit('/', 1)[-1]
            found = [p for p in index.get(name, []) + index.get(name + '.md', [])
                     if ('/' + p.as_posix().lower()).endswith(('/' + wanted, '/' + wanted + '.md')) and present(p)]
            found.sort(key=lambda p: (len(p.parts), str(p)))
            path = found[0] if found else None
        if path is None:
            return None, 'the target does not exist'
        if symlinked(path):
            return None, 'the target is a symlink'
        return os.path.relpath(path, page.parent), None

    return rewrite(record['body'], relocated)


def generate(workspace, sources, answers, date):
    inputs = expand([*sources, *answers])
    answer_paths = set(expand(answers))
    records = [read_source(path, workspace, date) for path in inputs]
    index_cache = []

    def lookup():
        if not index_cache:
            index_cache.append(vault_files(workspace.parent))
        return index_cache[0]
    # Native wiki pages can supply a title for a raw source with no title of its own.
    wiki = workspace / 'wiki'
    titles = {}
    if wiki.exists():
        for path in files(wiki):
            if path.suffix != '.md' or path.is_relative_to(wiki / 'raw'):
                continue
            text = path.read_text()
            if 'Generated from sources. In review, ready for your yes.' in text:
                continue
            header, _ = split_frontmatter(text)
            details = metadata(header)
            if details.get('title') and isinstance(details.get('sources'), list):
                for locator in details['sources']:
                    titles[(wiki / locator).resolve()] = details['title']
    for record in records:
        if record['title'] == record['path'].stem and record['raw'] in titles:
            record['title'] = titles[record['raw']]
    pages = {}
    raw_writes = {}
    for record in records:
        if record['raw_payload'] is not None:
            target = record['raw']
            safe_path(target)
            if target.exists():
                old_header, old_body = split_frontmatter(target.read_bytes().decode('utf-8'))
                if metadata(old_header).get('sha256') != record['hash'] or hashlib.sha256(old_body.encode()).hexdigest() != record['hash']:
                    raise ValueError(f'Frozen raw capture differs: {target}')
            else:
                raw_writes[target] = record['raw_payload']
    grouped = defaultdict(list)
    for record in records:
        for topic in record['topics']:
            grouped[topic].append(record)
    topic_paths = {}
    topic_slugs = defaultdict(list)
    for topic in grouped:
        topic_slugs[slug(topic)].append(topic)
    for topic, items in sorted(grouped.items()):
        stem = slug(topic)
        if len(topic_slugs[stem]) > 1:
            stem += '-' + hashlib.sha256(topic.encode()).hexdigest()[:12]
        page = workspace / 'wiki/concepts' / (stem + '-sources.md')
        topic_paths[topic] = page
        lines = heading('concept', workspace, plain_title(topic), date)
        lines.insert(4, 'sources: ' + json.dumps([os.path.relpath(r['raw'], workspace / 'wiki') for r in items]))
        lines += ['Saved sources for this topic. Source facts stay in their original records.', '',
                  '| Source | Who | Subtopic | Original | Capture | Raw source |', '| --- | --- | --- | --- | --- | --- |']
        for record in items:
            lines += ['| ' + ' | '.join([cell(record['title']), cell(record['who']), cell(record['subtopic']), original_link(record, page),
                       link(record['path'], page, 'Capture'), planned_link(record['raw'], page, 'Raw source')]) + ' |']
        pages[page] = '\n'.join(lines) + '\n'
    queries = []
    answered = []
    link_counts = {'rewritten': 0, 'untouched': 0, 'unresolved': []}
    index = workspace / 'wiki/index.md'
    previous_manifest = workspace / 'history/outputs/workspace-pages/wiki.json'
    previous = json.loads(previous_manifest.read_text()) if previous_manifest.exists() else {'pages': []}

    def query_page(record):
        return workspace / 'wiki/queries' / (slug(record['title']) + '-' + record['hash'][:12] + '.md')

    # Generated pages that this compile will archive. An answer must not link to one: it is gone when the compile ends.
    planned = set(pages) | {query_page(r) for r in records if r['path'] in answer_paths} | {index}
    gone = {workspace / p for p in previous['pages']} - planned
    for record in records:
        if record['path'] not in answer_paths:
            continue
        page = query_page(record)
        queries.append(page)
        lines = heading('query', workspace, plain_title(record['title']), date)
        lines.insert(4, 'sources: ' + json.dumps([os.path.relpath(record['raw'], workspace / 'wiki')]))
        lines += [f'Source date: {cell(record["date"])}. Who: {cell(record["who"])}.', '',
                  'This page preserves the saved research answer and its source date.', '',
                  'Source: ' + planned_link(record['raw'], page, 'Raw source') + '. ' + original_link(record, page) + '.', '',
                  '## Research answer', '']
        body, outcomes = answer_body(record, page, workspace, lookup, gone, planned | set(raw_writes))
        closer = scan(body, frontmatter=False).open_block
        if closer:
            body += '\n' + closer  # Close a code or HTML block the answer left open, so the citation below stays a link.
        answered.append({'page': os.path.relpath(page, workspace), 'source': os.path.relpath(record['path'], workspace),
                         'folders': [os.path.relpath(folder, workspace) for folder in dict.fromkeys(f for f in (record['home'], record['path'].parent) if f)]})
        for outcome in outcomes:
            if outcome['status'] == 'unresolved':
                link_counts['unresolved'].append({'page': os.path.relpath(page, workspace), 'line': len(lines) + outcome['line'],
                    'source': os.path.relpath(record['path'], workspace), 'source_line': record['body_line'] + outcome['line'],
                    'destination': outcome['destination'], 'reason': outcome['reason']})
            else:
                link_counts[outcome['status']] += 1
        lines += [body, '', '[S1] ' + planned_link(record['raw'], page, 'Raw source'), '']
        pages[page] = '\n'.join(lines) + '\n'
    obsolete = [workspace / p for p in previous['pages'] if workspace / p not in pages and workspace / p != index]
    lines = heading('index', workspace, 'Wiki Index', date)
    lines += ['## Topics', '']
    lines += ['- ' + planned_link(path, index, topic) for topic, path in sorted(topic_paths.items())]
    lines += ['', '## Queries', ''] + ['- ' + planned_link(path, index, path.stem) for path in sorted(queries)]
    lines += ['', '## Pages', '']
    existing = [p for p in files(workspace / 'wiki') if p.suffix == '.md' and not p.is_relative_to(workspace / 'wiki/raw') and p not in pages and p not in obsolete and p != index and p.name not in {'SCHEMA.md', 'log.md'}] if (workspace / 'wiki').exists() else []
    lines += ['- ' + link(path, index) for path in existing]
    lines += ['', '## Sources', ''] + ['- ' + planned_link(r['raw'], index, r['title']) for r in records] + ['']
    pages[index] = '\n'.join(lines) + '\n'
    manifest = {'workspace': workspace.name, 'source_count': len(records), 'topics': {t: os.path.relpath(p, workspace) for t, p in sorted(topic_paths.items())},
                'queries': [os.path.relpath(p, workspace) for p in queries], 'pages': [os.path.relpath(p, workspace) for p in sorted(pages)],
                'answers': answered, 'links': link_counts,
                'sources': [{k: (os.path.relpath(r[k], workspace) if k in {'path', 'raw'} else r[k]) for k in ('path', 'raw', 'hash', 'file_hash', 'topics')} for r in records]}
    pages[workspace / 'history/outputs/workspace-pages/wiki.json'] = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
    # Refuse handwritten collisions and all bad targets before preserving captures or writing pages.
    for page in pages:
        safe_path(page)
        if page.exists() and page.suffix == '.md' and page != index:
            if 'Generated from sources. In review, ready for your yes.' not in page.read_text():
                raise ValueError(f'Handwritten wiki page would change: {page}')
    archives = {}
    for path in obsolete:
        safe_path(path)
        if not path.is_relative_to(workspace / 'wiki') or path.is_relative_to(workspace / 'wiki/raw'):
            raise ValueError('Invalid generated page manifest')
        if path.exists():
            if 'Generated from sources. In review, ready for your yes.' not in path.read_text():
                raise ValueError(f'Handwritten obsolete page would change: {path}')
            archive = _fox_paths.system_home() / 'archive' / workspace.name / 'wiki-compile' / (path.stem + '-' + sha(path)[:16] + '.md')
            safe_path(archive)
            if archive.exists() and sha(archive) != sha(path):
                raise ValueError('Archive collision')
            archives[path] = archive
    for path, payload in raw_writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(payload)
    changed = write_pages(pages)
    for path, archive in archives.items():
        archive.parent.mkdir(parents=True, exist_ok=True)
        path.rename(archive)
    return {'sources': len(records), 'topics': len(topic_paths), 'queries': len(queries), 'changed': len(changed) + len(raw_writes) + len(archives),
            'links_rewritten': link_counts['rewritten'], 'links_untouched': link_counts['untouched'], 'links_unresolved': len(link_counts['unresolved'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=('run',), default='run',
                        help='run the existing memory command')
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--sources', action='append', default=[], type=Path)
    parser.add_argument('--answer', action='append', default=[], type=Path)
    parser.add_argument('--as-of', required=True, type=date_arg)
    args = parser.parse_args()
    if not args.sources and not args.answer:
        parser.error('Pass at least one source or research answer')
    workspace = safe_path(args.workspace)
    if not workspace.is_dir():
        parser.error('Workspace must exist')
    print(json.dumps(generate(workspace, args.sources, args.answer, args.as_of), sort_keys=True))


if __name__ == '__main__':
    main()
