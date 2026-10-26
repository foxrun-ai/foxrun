#!/usr/bin/env python3
"""Check that every relative destination in a page resolves from the page's own folder.

This check does not trust the scanner to find the links. It collects candidates with
deliberately broad patterns over the raw text: every "](", every "]:", every "[[...]]",
and every href= or src=. Each candidate must end one of these ways:

- The scanner saw it as a link. This module then reads the destination from the raw text
  by its own rules, and resolves it from the page's own folder.
- The scanner named it as not a link, with a reason (code, comment, refused bracket).
- Neither. That is a FAIL line. A link the scanner did not see cannot pass.

A refused candidate that names a real file in the source folder is a suspect.
A suspect passes only when an independent CommonMark parser (pandoc) renders no broken link.
A link that fails from the page and from its source folder was broken in the source.
It is listed, and it is not a FAIL.
"""

from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote

sys.path.insert(0, str((Path(__file__).resolve().parent)))
import markdown_links

BROAD_ATTRIBUTE = re.compile(r'(?:href|src)\s*=\s*(?:"([^"\r\n]*)"|\'([^\'\r\n]*)\'|([^\s"\'<>]+))', re.I)
BROAD_WIKI = re.compile(r'\[\[([^\[\]\r\n]*)\]\]')
ESCAPE = re.compile(r'\\([!-/:-@\[-`{-~])|&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});')
TAG_REASONS = ('HTML tag', 'HTML block text')


def read_destination(text, position):
    """Read a destination the broad way. Return (start, end) of its text."""
    size = len(text)
    if position < size and text[position] == '<':
        end = position + 1
        while end < size and text[end] not in '<>\r\n':
            end += 2 if text[end] == '\\' and text[end + 1:end + 2] not in ('', '\r', '\n') else 1
        if end < size and text[end] == '>':
            return position + 1, end
    end, depth = position, 0
    while end < size and text[end] > ' ' and text[end] != '\x7f':
        if text[end] == '\\' and text[end + 1:end + 2] > ' ':
            end += 2
            continue
        if text[end] == '(':
            depth += 1
        elif text[end] == ')':
            if not depth:
                break
            depth -= 1
        end += 1
    return position, end


def skip_to_destination(text, position):
    """Skip spaces, one line end, and the quote marks or indent that start the next line."""
    size = len(text)
    while position < size and text[position] in ' \t':
        position += 1
    if position < size and text[position] in '\r\n':
        position += 2 if text.startswith('\r\n', position) else 1
        while position < size and text[position] in ' \t>':
            position += 1
    return position


def candidates(text):
    """Return every place that could hold a destination: (form, trigger, start, end)."""
    found = []
    for match in re.finditer(r'\]\(', text):
        start, end = read_destination(text, skip_to_destination(text, match.end()))
        found.append(('inline', match.start(), start, end))
    for match in re.finditer(r'\]:', text):
        start, end = read_destination(text, skip_to_destination(text, match.end()))
        if end > start or text[start - 1:start] == '<':
            found.append(('definition', match.start(), start, end))
    for match in BROAD_WIKI.finditer(text):
        bar = re.search(r'\\?\|', match[1])
        found.append(('wiki', match.start(), match.start(1), match.start(1) + (bar.start() if bar else len(match[1]))))
    for match in BROAD_ATTRIBUTE.finditer(text):
        group = 1 if match[1] is not None else 2 if match[2] is not None else 3
        found.append(('html', match.start(), match.start(group), match.end(group)))
    return sorted(found, key=lambda item: (item[2], item[1]))


def reading(raw, form):
    """Return (kind, paths to try) for a destination as written. Written apart from the scanner's rules."""
    if form == 'html':
        text = html.unescape(raw)
    elif form == 'wiki':
        text = raw.strip()
    else:
        text = ESCAPE.sub(lambda m: m[1] if m[1] else html.unescape(m[0]), raw)
    if not text.strip():
        return 'empty', []
    if text[0] in '#?':
        return 'anchor', []
    if form != 'wiki' and (text.startswith(('//', '\\\\')) or re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', text)):
        return 'absolute', []
    if form != 'wiki' and text[0] == '/':
        return 'root', []
    cut = re.search(r'#' if form == 'wiki' else r'[#?]', text)
    path = text[:cut.start()] if cut else text
    if not path.strip():
        return 'anchor', []
    return 'relative', list(dict.fromkeys((unquote(path), path)))


def exists(folder, paths):
    return any(os.path.lexists(os.path.normpath(os.path.join(folder, path))) for path in paths)


def source_exists(form, origin, vault, paths):
    """Say whether a destination names a real file on the source side: beside the source,
    or for a Markdown link from the vault root, or as a note with its .md left out.
    origin is one folder, or the list of folders the source's links can start from."""
    folders = [origin] if isinstance(origin, str) else list(origin)
    if form != 'html' and vault:
        folders.append(vault)
    notes = [] if form == 'html' else [path + '.md' for path in paths]
    return any(exists(folder, paths) or any(os.path.isfile(os.path.normpath(os.path.join(folder, note))) for note in notes) for folder in folders)


def wiki_exists(paths, folders, vault):
    """Find a wikilink target the way workspace notes does: by path from a known folder, or by name anywhere."""
    for path in paths:
        for folder in folders:
            if os.path.isfile(os.path.join(folder, path)) or os.path.isfile(os.path.join(folder, path + '.md')):
                return True
        if vault:
            wanted = path.replace('\\', '/').strip('/').lower()
            for directory, names, files in os.walk(vault):
                names[:] = [name for name in names if not name.startswith('.') and not os.path.islink(os.path.join(directory, name))]
                for name in files:
                    full = '/' + os.path.join(directory, name).replace(os.sep, '/').lower()
                    if full.endswith(('/' + wanted, '/' + wanted + '.md')) and not os.path.islink(os.path.join(directory, name)):
                        return True
    return False


def line_of(text, offset):
    return len(re.findall(r'\r\n|\n|\r', text[:offset])) + 1


def check_text(text, folder, origin=None, vault=None, scanner=None):
    """Check one page's text. folder is the page's own folder; origin is its source's folder, when it has one."""
    found = (scanner or markdown_links.scan)(text)
    by_start = {}
    for link in found.links:
        if link.dest_start >= 0:
            by_start.setdefault(link.dest_start, link)
    result = {'resolved': 0, 'untouched': Counter(), 'not_links': Counter(), 'broken_in_source': [], 'failures': [], 'suspects': [], 'links': 0}
    seen = set()
    for form, trigger, start, end in candidates(text):
        raw = text[start:end]
        line = line_of(text, start)
        link = by_start.get(start)
        if link is not None and link.kind != 'autolink':
            seen.add(start)
            result['links'] += 1
            if link.raw != raw:
                result['failures'].append(f'line {line}: the check reads "{raw}" and the scanner reads "{link.raw}"')
                continue
            kind, paths = reading(raw, form)
            if link.alternate:
                form = 'html' if form != 'wiki' else form  # An alternate link counts only as a plain relative path.
            if link.alternate and (kind != 'relative' or not exists(folder, paths) and not source_exists(form, origin or folder, vault, paths)):
                result['links'] -= 1
                result['not_links']['footnote text'] += 1  # Only plain CommonMark reads this as a link. It names no real file.
            elif kind != 'relative':
                result['untouched'][kind] += 1
            elif form == 'wiki':
                folders = [folder, *([origin] if isinstance(origin, str) else origin or []), *([vault] if vault else [])]
                if wiki_exists(paths, folders, vault):
                    result['failures'].append(f'line {line}: wikilink "{raw}" names a real note and was not rewritten')
                else:
                    result['broken_in_source'].append({'line': line, 'destination': raw, 'paths': paths})
            elif exists(folder, paths):
                result['resolved'] += 1
            elif origin is None:
                result['failures'].append(f'line {line}: "{raw}" does not resolve from the page\'s folder')
            elif source_exists(form, origin, vault, paths):
                result['failures'].append(f'line {line}: "{raw}" names a real file on the source side and does not resolve from the page\'s folder')
            else:
                result['broken_in_source'].append({'line': line, 'destination': raw, 'paths': paths})
            continue
        region = found.region(trigger)
        if region in TAG_REASONS and form == 'html':
            region = None  # Attributes live in tags. A tag alone is no reason to skip one.
        reason = region or found.rejects.get(trigger)
        refused = region is None and trigger in found.rejects
        if reason is None:
            for other in found.links:
                if other.dest_start < 0 or other.dest_start == start:
                    continue
                if other.dest_start <= trigger < other.end:
                    reason = 'inside the destination or title of another link'
                elif other.kind == 'definition' and other.start <= trigger < other.dest_start:
                    reason = 'inside the label of a definition'
        if reason is None:
            result['failures'].append(f'line {line}: the scanner did not see "{raw}" ({form})')
            continue
        result['not_links'][reason] += 1
        if refused and origin is not None:
            kind, paths = reading(raw, form)
            if kind == 'relative' and form != 'wiki' and not exists(folder, paths) and source_exists(form, origin, vault, paths):
                result['suspects'].append(f'line {line}: "{raw}" is refused as a link ({reason}) and names a real file in the source folder')
    for link in found.links:
        if link.dest_start >= 0 and link.kind != 'autolink' and link.dest_start not in seen:
            result['failures'].append(f'line {link.line}: the broad patterns missed the scanner\'s link "{link.raw}"')
        if link.kind == 'autolink':
            result['untouched']['absolute'] += 1
        if link.kind == 'reference' and not link.defined:
            result['not_links']['reference with no definition'] += 1
    return result


class Rendered(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if 'footnote' in (values.get('class') or ''):
            return
        for name in ('href', 'src'):
            if values.get(name) is not None:
                self.links.append(values[name])


DIALECTS = ('commonmark', 'commonmark+footnotes+task_lists')  # Plain CommonMark, and the way a vault reads footnotes and task boxes.


def rendered_links(text, dialect=DIALECTS[0]):
    """Return the destinations an independent CommonMark parser renders, or None when pandoc is missing."""
    pandoc = shutil.which('pandoc')
    if not pandoc:
        return None
    body = re.sub(r'\A---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)', '', text)
    output = subprocess.run([pandoc, '--from=' + dialect, '--to=html', '--wrap=none', '--syntax-highlighting=none'],
                            input=body.encode('utf-8'), capture_output=True, check=True).stdout.decode('utf-8')
    parser = Rendered()
    parser.feed(output)
    return parser.links


def oracle_text(text, folder, excused=(), origin=None, vault=None):
    """Return the rendered relative links that fail from the folder, in either dialect. None when pandoc is missing.

    Plain CommonMark reads a one-word footnote text as a destination. With a known source folder,
    such a destination fails only when it names a real file on the source side.
    """
    known = {path for item in excused for path in item}
    failures = []
    for dialect in DIALECTS:
        links = rendered_links(text, dialect)
        if links is None:
            return None
        for value in links:
            kind, paths = reading(value, 'html')
            if kind != 'relative' or exists(folder, paths) or known.intersection(paths):
                continue
            if dialect == DIALECTS[0] and origin and not source_exists('html', origin, vault, paths):
                continue
            line = f'pandoc renders "{value}", which does not resolve from the page\'s folder'
            if line not in failures:
                failures.append(line)
    return failures


def check_page(page, origin=None, vault=None, oracle=True):
    """Check one page file. Suspects fail unless pandoc clears them."""
    text = page.read_bytes().decode('utf-8')
    origin = [str(folder) for folder in origin] if isinstance(origin, (list, tuple)) else str(origin) if origin else None
    result = check_text(text, str(page.parent), origin, str(vault) if vault else None)
    result['oracle'] = 'not run'
    if oracle:
        failures = oracle_text(text, str(page.parent), [item['paths'] for item in result['broken_in_source']],
                               origin, str(vault) if vault else None)
        result['oracle'] = 'pandoc is not installed' if failures is None else 'checked'
        result['failures'] += failures or []
    if result['suspects'] and result['oracle'] != 'checked':
        result['failures'] += [value + '; pandoc did not confirm it' for value in result['suspects']]
    return result


def check_workspace(workspace, oracle=True):
    """Check every page the wiki compile wrote for one workspace (else every wiki/*.md page). Return the totals."""
    compiled = workspace / 'history/outputs/workspace-pages/wiki.json'
    if compiled.is_file():
        manifest = json.loads(compiled.read_text())
    else:
        manifest = {'pages': sorted(p.relative_to(workspace).as_posix() for p in (workspace / 'wiki').rglob('*.md')),
                    'answers': []}
    origins = {item['page']: [workspace / folder for folder in item['folders']] for item in manifest.get('answers', [])}
    totals = {'pages': 0, 'links': 0, 'resolved': 0, 'untouched': Counter(), 'not_links': Counter(), 'broken': [], 'failures': [], 'oracle': Counter()}
    names = [name for name in manifest['pages'] if name.endswith('.md')]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda name: check_page(workspace / name, origins.get(name), workspace.parent, oracle), names))
    for name, result in zip(names, results):
        totals['pages'] += 1
        totals['links'] += result['links']
        totals['resolved'] += result['resolved']
        totals['untouched'] += result['untouched']
        totals['not_links'] += result['not_links']
        totals['oracle'][result['oracle']] += 1
        totals['broken'] += [f'{workspace.name}/{name} line {item["line"]}: "{item["destination"]}"' for item in result['broken_in_source']]
        totals['failures'] += [f'{workspace.name}/{name} {line}' for line in result['failures']]
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--workspace', required=True, type=Path, action='append')
    parser.add_argument('--no-oracle', action='store_true', help='skip the pandoc pass')
    args = parser.parse_args()
    failed = False
    for workspace in args.workspace:
        totals = check_workspace(workspace.resolve(), not args.no_oracle)
        print(f'{workspace.name}: {totals["pages"]} pages, {totals["links"]} links, {totals["resolved"]} relative links resolve, '
              f'{sum(totals["untouched"].values())} untouched {dict(sorted(totals["untouched"].items()))}, '
              f'{sum(totals["not_links"].values())} not links {dict(sorted(totals["not_links"].items()))}, '
              f'pandoc {dict(sorted(totals["oracle"].items()))}')
        for line in totals['broken']:
            print('broken in the source: ' + line)
        for line in totals['failures']:
            print('FAIL ' + line)
        failed = failed or bool(totals['failures'])
    print('FAIL links' if failed else 'PASS links')
    sys.exit(failed)


if __name__ == '__main__':
    main()
