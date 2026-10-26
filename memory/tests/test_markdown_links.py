"""Table-driven tests for the link scanner, the rewriter, and the independent link check.

Each case in link_cases.json has a source text and its exact expected output.
Run: TMPDIR=/a/safe/folder python3 -m unittest test_markdown_links.py
"""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('wiki_compile', (Path(__file__).resolve().parent / '../compile.py'))
compile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compile)
import link_check
import markdown_links

CASES = json.loads(((Path(__file__).resolve().parent / '../link_cases.json')).read_text(encoding='utf-8'))
DATE = '2026-10-05'
FILES = ['sources/evidence.md', 'sources/saved evidence.md', 'sources/nested(one).md', 'sources/evidence&more.md',
         'sources/diagram.svg', 'sources/café/naïve notes.md', 'sources/folder/deep.md', 'notes/elsewhere.md',
         'sources/notes #1.md', 'sources/near.md', 'notes/twin.md']
PANDOC = shutil.which('pandoc')
WRAPS = {'block quote': ('> ', '> '), 'list item': ('- ', '  '), 'ordered list': ('10. ', '    '), 'block quote in a list': ('- > ', '  > ')}


def wrapped(text, first, rest):
    lines = text.replace('\r\n', '\n').split('\n')
    return '\n'.join(((first if number == 0 else rest) + line) if line else (rest.rstrip() if '>' in rest else '') for number, line in enumerate(lines))


# Every CommonMark case of the table, placed again inside each container, with both line endings.
DOCUMENTS = [(case['name'] + ' in ' + name + (' CRLF' if end == '\r\n' else ''), wrapped(case['source'], *marks).replace('\n', end) + end)
             for case in CASES if case.get('commonmark', True) for name, marks in WRAPS.items() for end in ('\n', '\r\n')]
GENERATED = len(DOCUMENTS)


def blind(text, frontmatter=True):
    """A scanner that sees nothing. The check must fail every link it finds by itself."""
    return markdown_links.Scan('')


class LinkTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.vault = Path(cls.directory.name).resolve() / 'vault'
        cls.workspace = cls.vault / 'foxrun'
        for name in FILES:
            path = cls.workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# Proof\n\n## Saved Proof\n\nText. ^block-1\n')
        (cls.vault / 'people').mkdir()
        for name in ('ada-lovelace.md', 'twin.md', 'near.md'):
            (cls.vault / 'people' / name).write_text('# Person\n')
        cls.source = cls.workspace / 'sources/answer.md'
        cls.source.write_text('# Answer\n')
        cls.page = cls.workspace / 'wiki/queries/answer.md'
        cls.page.parent.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def rewrite(self, case):
        return compile.answer_body({'path': self.source, 'body': case['source']}, self.page, self.workspace)

    def check(self, text, origin=True, scanner=None):
        return link_check.check_text(text, str(self.page.parent), str(self.source.parent) if origin else None, str(self.vault), scanner)

    def test_table_covers_the_brief(self):
        names = [case['name'] for case in CASES]
        self.assertGreaterEqual(len(CASES), 60)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sorted(case['review'] for case in CASES if 'review' in case), [1, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4])
        for word in ('block quote', 'list item', 'nested list', 'table cell', 'footnote', 'HTML block', 'CRLF', 'unicode',
                     'parentheses', 'absolute URL', 'anchor', 'missing', 'wikilink', 'embed', 'autolink', 'angle',
                     'climb out', 'encoded characters', 'links to a folder', 'shortest path', 'fragment mark', 'query mark'):
            self.assertTrue(any(word in name for name in names), word)

    def test_each_case_gives_its_exact_output(self):
        for case in CASES:
            with self.subTest(case['name']):
                text, outcomes = self.rewrite(case)
                self.assertEqual(text, case['expected'])
                count = {status: sum(1 for outcome in outcomes if outcome['status'] == status) for status in ('rewritten', 'untouched', 'unresolved')}
                self.assertEqual(count, {'rewritten': case['rewritten'], 'untouched': case['untouched'], 'unresolved': case['unresolved']})

    def test_only_destination_paths_change(self):
        def without_paths(text):
            for link in sorted(markdown_links.scan(text, frontmatter=False).links, key=lambda v: v.dest_start, reverse=True):
                if link.dest_start >= 0 and link.syntax != 'wiki' and not link.alternate:
                    text = text[:link.dest_start] + text[link.dest_start + markdown_links.path_length(link.raw, link.syntax):]
            return text
        for case in CASES:
            if '[[' in case['source'] or case.get('footnote_text'):
                continue  # A wikilink becomes a Markdown link. Its exact output is in the table.
            with self.subTest(case['name']):
                self.assertEqual(without_paths(case['source']), without_paths(case['expected']))

    def test_scanner_spans_are_exact(self):
        for case in CASES:
            with self.subTest(case['name']):
                found = markdown_links.scan(case['source'], frontmatter=False)
                for link in found.links:
                    self.assertEqual(case['source'][link.dest_start:link.dest_end] if link.dest_start >= 0 else '', link.raw)
                    self.assertEqual(found.line(link.dest_start if link.dest_start >= 0 else link.start), link.line)
                    self.assertLessEqual(link.start, link.end)

    def test_check_accepts_each_expected_output(self):
        for case in CASES:
            with self.subTest(case['name']):
                result = self.check(case['expected'])
                self.assertEqual(result['failures'], [])
                self.assertEqual(len(result['broken_in_source']), case['unresolved'])
                self.assertEqual(bool(result['suspects']), bool(case.get('suspect')))

    def test_check_rejects_each_unrepaired_link(self):
        for case in CASES:
            if not case['rewritten']:
                continue
            with self.subTest(case['name']):
                self.assertTrue(self.check(case['source'])['failures'])
                if not case.get('footnote_text'):  # With no source folder known, footnote text is only text.
                    self.assertTrue(self.check(case['source'], origin=False)['failures'])

    def test_check_fails_what_a_blind_scanner_misses(self):
        for case in CASES:
            if not case['rewritten'] + case['unresolved']:
                continue
            with self.subTest(case['name']):
                for text in (case['source'], case['expected']):
                    failures = self.check(text, scanner=blind)['failures']
                    self.assertTrue(any('did not see' in line for line in failures), failures)

    def same_links(self, before, after, plain):
        """Each rendered link is unchanged, or it was relative to a real file and still reaches that file."""
        origin, folder = str(self.source.parent), str(self.page.parent)
        self.assertEqual(len(before), len(after))
        for old, new in zip(before, after):
            kind, paths = link_check.reading(old, 'html')
            if kind == 'relative' and link_check.exists(origin, paths):
                target = next(os.path.normpath(os.path.join(origin, p)) for p in paths if os.path.lexists(os.path.join(origin, p)))
                self.assertEqual(os.path.normpath(os.path.join(folder, unquote(new.split('#')[0].split('?')[0]))), target)
                self.assertEqual(old.partition('#')[2], new.partition('#')[2])
            elif plain and kind in ('relative', 'anchor') and old != new:
                # Plain CommonMark reads a whole footnote text as one destination. It named no file before, and names none now.
                self.assertFalse(link_check.exists(folder, link_check.reading(new, 'html')[1]))
            else:
                self.assertEqual(old, new)

    def no_broken_render(self, text):
        checked = self.check(text)
        self.assertEqual(checked['failures'], [])
        excused = [item['paths'] for item in checked['broken_in_source']]
        self.assertEqual(link_check.oracle_text(text, str(self.page.parent), excused, str(self.source.parent), str(self.vault)), [])

    @unittest.skipUnless(PANDOC, 'pandoc is not installed')
    def test_pandoc_agrees_on_each_case(self):
        for case in CASES:
            with self.subTest(case['name']):
                self.no_broken_render(case['expected'])
                if not case.get('commonmark', True):
                    continue  # CommonMark has no wikilinks. Their exact outputs are in the table.
                for dialect in link_check.DIALECTS:
                    self.same_links(link_check.rendered_links(case['source'], dialect), link_check.rendered_links(case['expected'], dialect), dialect == link_check.DIALECTS[0])

    @unittest.skipUnless(PANDOC, 'pandoc is not installed')
    def test_pandoc_agrees_on_generated_documents(self):
        def work(document):
            text, outcomes = compile.answer_body({'path': self.source, 'body': document[1]}, self.page, self.workspace)
            return text, outcomes, [(link_check.rendered_links(document[1], d), link_check.rendered_links(text, d), d == link_check.DIALECTS[0]) for d in link_check.DIALECTS]

        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(work, DOCUMENTS))
        self.assertGreaterEqual(len(results), 1000)
        for (name, document), (text, outcomes, rendered) in zip(DOCUMENTS, results):
            with self.subTest(name):
                for before, after, plain in rendered:
                    self.same_links(before, after, plain)
                self.no_broken_render(text)
                if any(outcome['status'] == 'rewritten' for outcome in outcomes):
                    self.assertTrue(self.check(document)['failures'])


class Compile(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        # Obsolete pages move to the system home's archive; keep that home in the temp folder, not the source tree.
        self.home = Path(self.directory.name).resolve() / 'home'
        home = mock.patch.dict(os.environ, {'FOXRUN_HOME': str(self.home)})
        home.start()
        self.addCleanup(home.stop)
        self.workspace = Path(self.directory.name).resolve() / 'vault/system-workspace'
        self.sources = self.workspace / 'sources'
        self.sources.mkdir(parents=True)
        (self.sources / 'evidence.md').write_text('# Evidence\nSource proof.\n')
        self.answer = self.sources / 'answer.md'

    def tearDown(self):
        self.directory.cleanup()

    def generate(self, body, title='Reference test'):
        self.answer.write_bytes(('---\ntitle: ' + title + '\ntags: [model]\n---\n# Answer\n\n' + body).encode('utf-8'))
        before = hashlib.sha256(self.answer.read_bytes()).hexdigest()
        result = compile.generate(self.workspace, [self.sources], [self.answer], DATE)
        manifest = json.loads((self.workspace / 'history/outputs/workspace-pages/wiki.json').read_text())
        query = self.workspace / manifest['queries'][0]
        self.assertEqual(hashlib.sha256(self.answer.read_bytes()).hexdigest(), before)
        self.assertEqual(compile.generate(self.workspace, [self.sources], [self.answer], DATE)['changed'], 0)
        return result, manifest, query

    def test_review_cases_compile_to_pages_whose_links_resolve(self):
        for case in CASES:
            if 'review' not in case:
                continue
            with self.subTest(case['name']):
                result, manifest, query = self.generate(case['source'])
                self.assertIn(case['expected'], query.read_bytes().decode('utf-8'))
                self.assertEqual(result['links_rewritten'], 1)
                self.assertEqual(result['links_unresolved'], 0)
                self.assertEqual(markdown_links.check_links([self.workspace / name for name in manifest['pages'] if name.endswith('.md')]), [])
                totals = link_check.check_workspace(self.workspace)
                self.assertEqual(totals['failures'], [])
                self.assertEqual(totals['broken'], [])
                # The unrepaired text, placed beside the page, must fail the check.
                broken = query.with_name('unrepaired.md')
                broken.write_text(case['source'])
                self.assertTrue(markdown_links.check_links([broken]))
                broken.unlink()

    def test_missing_target_is_reported_with_file_and_line(self):
        result, manifest, query = self.generate('Line one.\n\n> [Gone](missing.md) and [Proof](evidence.md)\n\n[[nowhere|Gone]]\n')
        self.assertEqual((result['links_rewritten'], result['links_unresolved']), (1, 2))
        page_lines = query.read_text().split('\n')
        source_lines = self.answer.read_text().split('\n')
        for item, destination in zip(manifest['links']['unresolved'], ('missing.md', 'nowhere')):
            self.assertEqual(item['destination'], destination)
            self.assertEqual(item['page'], os.path.relpath(query, self.workspace))
            self.assertIn(destination, page_lines[item['line'] - 1])
            self.assertIn(destination, source_lines[item['source_line'] - 1])
        totals = link_check.check_workspace(self.workspace)
        self.assertEqual(totals['failures'], [])
        self.assertEqual(len(totals['broken']), 2)

    def test_open_code_block_cannot_swallow_the_citation(self):
        for body in ('Text.\n\n```\n[Proof](evidence.md)\n', 'Text.\n\n<!--\n[Proof](evidence.md)\n'):
            with self.subTest(body):
                result, manifest, query = self.generate(body)
                found = markdown_links.scan(query.read_bytes().decode('utf-8'))
                self.assertEqual(found.open_block, None)
                citation = next(n for n, line in enumerate(query.read_text().split('\n'), 1) if line.startswith('[S1] '))
                self.assertTrue(any('wp-source-' in link.raw for link in found.links if link.line == citation))
                self.assertEqual(link_check.check_workspace(self.workspace)['failures'], [])

    def test_frozen_raw_copy_resolves_links_from_its_original_home(self):
        (self.workspace / 'outputs').mkdir()
        (self.workspace / 'outputs/result.md').write_text('# Result\n')
        raw = self.workspace / 'wiki/raw/documents/plan.md'
        raw.parent.mkdir(parents=True)
        (raw.parent / 'beside.md').write_text('# Beside\n')
        body = '---\ntitle: Plan\n---\n# Plan\n\n[Result](../outputs/result.md) [Beside](beside.md) [Gone](../outputs/gone.md)\n'
        raw.write_text('---\ningested: "2026-10-05"\nsha256: ' + hashlib.sha256(body.encode()).hexdigest() + '\nsource_path: "docs/plan.md"\n---\n' + body)
        result = compile.generate(self.workspace, [raw], [raw], DATE)
        manifest = json.loads((self.workspace / 'history/outputs/workspace-pages/wiki.json').read_text())
        text = (self.workspace / manifest['queries'][0]).read_text()
        self.assertIn('[Result](../../outputs/result.md) [Beside](../raw/documents/beside.md) [Gone](../outputs/gone.md)', text)
        self.assertEqual((result['links_rewritten'], result['links_unresolved']), (2, 1))
        self.assertEqual(manifest['answers'][0]['folders'], ['docs', 'wiki/raw/documents'])
        totals = link_check.check_workspace(self.workspace)
        self.assertEqual(totals['failures'], [])
        self.assertEqual(len(totals['broken']), 1)

    def test_link_to_a_page_the_same_compile_archives_is_not_rewritten(self):
        other = self.sources / 'other.md'
        other.write_text('---\ntitle: Other\ntags: [old-topic]\n---\n# Other\n')
        body = '[Topic](../wiki/concepts/old-topic-sources.md) and [[old-topic-sources|Topic]] and [Proof](evidence.md)\n'
        # The first compile writes the topic page in the same run. The answer can link to it at once.
        result, manifest, query = self.generate(body)
        self.assertIn('[Topic](../../wiki/concepts/old-topic-sources.md) and [Topic](../concepts/old-topic-sources.md) and [Proof](../../sources/evidence.md)', query.read_text())
        self.assertEqual((result['links_rewritten'], result['links_unresolved']), (3, 0))
        self.assertEqual(link_check.check_workspace(self.workspace)['failures'], [])
        other.write_text('---\ntitle: Other\ntags: [new-topic]\n---\n# Other\n')
        # The old topic page exists now. This compile archives it, so the answer must not point at it.
        self.assertTrue((self.workspace / 'wiki/concepts/old-topic-sources.md').is_file())
        result, manifest, query = self.generate(body)
        self.assertFalse((self.workspace / 'wiki/concepts/old-topic-sources.md').exists())
        archived = self.home / 'archive/system-workspace/wiki-compile'
        self.assertEqual(1, len(list(archived.glob('old-topic-sources-*.md'))))
        self.assertIn('[Topic](../wiki/concepts/old-topic-sources.md) and [[old-topic-sources|Topic]] and [Proof](../../sources/evidence.md)', query.read_text())
        self.assertEqual((result['links_rewritten'], result['links_unresolved']), (1, 2))
        totals = link_check.check_workspace(self.workspace)
        self.assertEqual(totals['failures'], [])
        self.assertEqual(len(totals['broken']), 2)

    def test_link_in_a_title_does_not_reach_a_heading(self):
        result, manifest, query = self.generate('[Proof](evidence.md)\n', title='"[Proof](evidence.md) and [[evidence|more]]"')
        self.assertIn('# Proof and more\n', query.read_text())
        self.assertEqual(link_check.check_workspace(self.workspace)['failures'], [])


if __name__ == '__main__':
    unittest.main()
