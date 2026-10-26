#!/usr/bin/env python3
"""Checked glossary writes: provenance, scoped uniqueness, TSV integrity, and rebuilt pages."""
import contextlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import words, published_pages


class WordWriterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='word-writer-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home, self.portfolio = self.root / 'home', self.root / 'portfolio'
        (self.home / 'config').mkdir(parents=True)
        self.shop = self.portfolio / 'sample-shop'
        (self.shop / 'config').mkdir(parents=True)
        (self.home / 'config/words.tsv').write_text('\t'.join(words.FIELDS) + '\nsystem\tSetup\tBase\tBuilds things.\tbase/\tdecision-base\n')
        self.row = dict(workspace='system', group='Model words', word='Sample',
                        meaning='A sample word.', where='config/', source='decision-sample')

    def write(self, operation='add', **changes):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            words.write_word(self.home, self.portfolio, operation, dict(self.row, **changes))
        return output.getvalue()

    def test_add_and_change_rebuild_with_source_and_print_both_versions(self):
        output = self.write()
        self.assertIn('FROM: null', output)
        self.assertIn('Rebuilt: ' + str(self.home / 'GLOSSARY.md'), output)
        page = (self.home / 'GLOSSARY.md').read_text()
        self.assertIn('## Model words', page)
        self.assertIn('| Sample | A sample word. | config/ | decision-sample |', page)
        output = self.write('change', meaning='A changed sample.')
        self.assertIn('A sample word.', output)
        self.assertIn('A changed sample.', output)
        self.assertNotIn('A sample word.', (self.home / 'GLOSSARY.md').read_text())
        self.assertEqual(published_pages.pages(self.home, self.portfolio)[self.home / 'GLOSSARY.md'],
                         (self.home / 'GLOSSARY.md').read_text())

    def test_empty_source_duplicate_and_missing_change_leave_bytes_intact(self):
        self.write()
        paths = (self.home / 'config/words.tsv', self.home / 'GLOSSARY.md')
        before = [path.read_bytes() for path in paths]
        for operation, changes in (('add', {'source': ' '}), ('add', {'word': ' sample '}),
                                   ('change', {'word': 'missing'})):
            with self.subTest(operation=operation, changes=changes), self.assertRaises(ValueError):
                self.write(operation, **changes)
            self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_same_word_in_another_group_or_workspace_is_allowed(self):
        self.write()
        self.write(group='Other words')
        self.write(workspace='sample-shop', word='Local')
        self.write(workspace='sample-shop', word='Local', group='Other words')
        page = (self.shop / 'GLOSSARY.md').read_text()
        self.assertEqual(page.count('| Local |'), 2)
        self.assertEqual(page.count('## Model words'), 1)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.write(workspace='sample-shop', word='LOCAL')

    def test_workspace_cannot_redefine_a_system_word(self):
        with self.assertRaisesRegex(ValueError, 'shared word'):
            self.write(workspace='sample-shop', word='Base')
        self.assertFalse((self.shop / 'config/glossary-words.tsv').exists())

    def test_legacy_local_shape_is_upgraded_without_losing_rows_or_column_order(self):
        local = self.shop / 'config/glossary-words.tsv'
        local.write_text('word\tmeaning\tgroup\tsource\nLocal\tExisting.\tModel words\told-decision\n')
        self.write('change', workspace='sample-shop', word='Local', where='wiki/')
        with local.open(newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            values = list(reader)
            self.assertEqual(reader.fieldnames, ['word', 'meaning', 'group', 'source', 'workspace', 'where'])
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]['where'], 'wiki/')
        self.assertIn('| Local | A sample word. | wiki/ | decision-sample |', (self.shop / 'GLOSSARY.md').read_text())

    def test_malformed_shape_and_duplicate_existing_rows_are_refused(self):
        target = self.home / 'config/words.tsv'
        valid = target.read_text()
        for bad in (valid + 'short\trow\n', valid + valid.splitlines(True)[1],
                    valid.replace('workspace\tgroup', 'workspace\tunknown')):
            target.write_text(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.write()
            self.assertEqual(target.read_text(), bad)

    def test_control_characters_and_bad_workspace_are_refused(self):
        for changes in ({'meaning': 'first\nsecond'}, {'source': 'one\ttwo'},
                        {'workspace': '../escape'}, {'group': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.write(**changes)

    def test_generator_failure_and_linked_output_do_not_change_source(self):
        target = self.home / 'config/words.tsv'
        before = target.read_bytes()
        with mock.patch.object(published_pages, 'pages', side_effect=ValueError('bad generator')):
            with self.assertRaisesRegex(ValueError, 'bad generator'):
                self.write()
        outside = self.root / 'outside.md'
        outside.write_text('unchanged')
        (self.home / 'GLOSSARY.md').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'linked path'):
            self.write()
        self.assertEqual(before, target.read_bytes())
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_output_write_failure_restores_rows_and_page(self):
        self.write()
        target = self.home / 'config/words.tsv'
        page = self.home / 'GLOSSARY.md'
        before = target.read_bytes(), page.read_bytes()
        real = Path.write_text
        def fail_page(path, *args, **kwargs):
            if path == page:
                raise OSError('test page write failure')
            return real(path, *args, **kwargs)
        with mock.patch.object(Path, 'write_text', fail_page):
            with self.assertRaisesRegex(OSError, 'test page write failure'):
                self.write('change', meaning='Will not stay.')
        self.assertEqual(before, (target.read_bytes(), page.read_bytes()))

    def test_remove_prints_exact_from_and_reason_and_rebuilds_only_own_glossary(self):
        self.write()
        self.write(group='Other words')
        self.write(workspace='sample-shop', word='Local')
        local_paths = (self.shop / 'config/glossary-words.tsv', self.shop / 'GLOSSARY.md',
                       self.shop / 'config/glossary-tags.json')
        local_before = [path.read_bytes() for path in local_paths]
        output = self.write('remove', word=' sample ', group=' model WORDS ',
                            meaning='', where='', source='decision-remove')
        from_line = next(line for line in output.splitlines() if line.startswith('FROM: '))
        self.assertEqual(json.loads(from_line[6:]), self.row)
        self.assertIn('TO: null', output)
        self.assertIn('SOURCE: decision-remove', output)
        self.assertEqual(local_before, [path.read_bytes() for path in local_paths])
        _, values = words.read_rows(self.home / 'config/words.tsv', 'system')
        self.assertEqual([(r['group'], r['word']) for r in values],
                         [('Setup', 'Base'), ('Other words', 'Sample')])
        page = self.home / 'GLOSSARY.md'
        self.assertNotIn('## Model words', page.read_text())
        self.assertEqual(published_pages.pages(self.home, self.portfolio)[page], page.read_text())

    def test_remove_last_local_word_preserves_system_and_tags(self):
        self.write()
        self.write(workspace='sample-shop', word='Local')
        system_paths = (self.home / 'config/words.tsv', self.home / 'GLOSSARY.md')
        system_before = [path.read_bytes() for path in system_paths]
        tags = self.shop / 'config/glossary-tags.json'
        tags_before = tags.read_bytes()
        row = dict(workspace='sample-shop', group='Model words', word='Local', source='decision-remove')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(words.write_word(self.home, self.portfolio, 'remove', row))
        _, values = words.read_rows(self.shop / 'config/glossary-words.tsv', 'sample-shop')
        self.assertEqual(values, [])
        page = self.shop / 'GLOSSARY.md'
        self.assertNotIn('| Local |', page.read_text())
        self.assertEqual(published_pages.pages(self.home, self.portfolio)[page], page.read_text())
        self.assertEqual(system_before, [path.read_bytes() for path in system_paths])
        self.assertEqual(tags_before, tags.read_bytes())

    def test_remove_refuses_missing_identity_blank_source_and_bad_cells(self):
        self.write()
        paths = (self.home / 'config/words.tsv', self.home / 'GLOSSARY.md')
        before = [path.read_bytes() for path in paths]
        for changes in ({'source': ' '}, {'word': 'missing'}, {'group': 'missing'},
                        {'workspace': 'sample-shop'}, {'group': ''}, {'word': ''},
                        {'source': 'one\ntwo'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.write('remove', **changes)
            self.assertEqual(before, [path.read_bytes() for path in paths])
        self.assertFalse((self.shop / 'config/glossary-words.tsv').exists())

    def test_remove_generator_and_write_failures_restore_all_affected_bytes(self):
        for workspace, root in (('system', self.home), ('sample-shop', self.shop)):
            word = 'Sample' if workspace == 'system' else 'Local'
            self.write(workspace=workspace, word=word)
            target = root / ('config/words.tsv' if workspace == 'system' else 'config/glossary-words.tsv')
            paths = [target, root / 'GLOSSARY.md']
            if workspace != 'system':
                paths.append(root / 'config/glossary-tags.json')
            before = [path.read_bytes() for path in paths]
            with mock.patch.object(published_pages, 'pages', side_effect=ValueError('bad generator')):
                with self.assertRaisesRegex(ValueError, 'bad generator'):
                    self.write('remove', workspace=workspace, word=word)
            self.assertEqual(before, [path.read_bytes() for path in paths])
            real = Path.write_text
            for failed_path in paths:
                def fail_write(path, *args, **kwargs):
                    if path == failed_path:
                        real(path, 'partial write')
                        raise OSError('test remove write failure')
                    return real(path, *args, **kwargs)
                with self.subTest(workspace=workspace, path=failed_path):
                    with mock.patch.object(Path, 'write_text', fail_write):
                        with self.assertRaisesRegex(OSError, 'test remove write failure'):
                            self.write('remove', workspace=workspace, word=word)
                    self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_remove_cli_requires_source_but_not_meaning_or_where(self):
        self.write()
        paths = (self.home / 'config/words.tsv', self.home / 'GLOSSARY.md')
        before = [path.read_bytes() for path in paths]
        command = [sys.executable, '-B', str(Path(words.__file__)), '--home', str(self.home),
                   '--portfolio', str(self.portfolio), 'remove', '--workspace', 'system',
                   '--group', self.row['group'], '--word', self.row['word']]
        missing = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(missing.returncode, 2)
        self.assertIn('--source', missing.stderr)
        blank = subprocess.run(command + ['--source', ' '], text=True, capture_output=True)
        self.assertEqual(blank.returncode, 2)
        self.assertEqual(before, [path.read_bytes() for path in paths])
        removed = subprocess.run(command + ['--source', 'decision-remove'], text=True, capture_output=True)
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertIn('Removed:', removed.stdout)
        self.assertIn('TO: null', removed.stdout)
        after = [path.read_bytes() for path in paths]
        unknown = subprocess.run(command + ['--source', 'decision-remove'], text=True, capture_output=True)
        self.assertEqual(unknown.returncode, 2)
        self.assertIn('no word to remove', unknown.stderr)
        self.assertEqual(after, [path.read_bytes() for path in paths])

    def test_cli_requires_source_and_refuses_a_duplicate(self):
        command = [sys.executable, '-B', str(Path(words.__file__)), '--home', str(self.home),
                   '--portfolio', str(self.portfolio), 'add']
        for field, value in self.row.items():
            if field != 'source':
                command.extend(['--' + field, value])
        missing = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(missing.returncode, 2)
        self.assertIn('--source', missing.stderr)
        command.extend(['--source', self.row['source']])
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        duplicate = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn('duplicate word', duplicate.stderr)


if __name__ == '__main__':
    unittest.main()
