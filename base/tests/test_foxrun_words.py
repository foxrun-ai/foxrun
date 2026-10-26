#!/usr/bin/env python3
"""Tests for the launcher words status, where, glossary, and for the two lists doctor reads in base/.

Each test makes a small home with only the files it needs.
Run from the system home: python3 -m unittest base.tests.test_foxrun_words
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else 'python3'
NEEDED = ('foxrun.py', 'base/paths.py', 'base/person.py', 'base/tracker.py', 'work/program.py',
          'base/agent_catalog.py', 'base/simple_yaml.py')
RESOLVER = '''# RESOLVER.md

## Where things live

| Thing | Home | Path | Writer or owner |
|---|---|---|---|
| Run trails | System | `runs/` | Chief of Staff |
| Shared settings | System | `config/` | Architect |
'''


class LauncherWordTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('FOXRUN_TEST_ROOT') or None
        self.temp = tempfile.TemporaryDirectory(prefix='words-home-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.home, self.portfolio = root / 'system', root / 'portfolio'
        for name in NEEDED:
            (self.home / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, self.home / name)
        for folder in ('config', 'runs'):
            (self.home / folder).mkdir()
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery', 'default_workspace': 'cedar-shop'}))
        shutil.copyfile(ROOT / 'config/models.yaml', self.home / 'config/models.yaml')
        (self.home / 'VERSION').write_text('0.1.0\n')
        (self.home / 'RESOLVER.md').write_text(RESOLVER)
        (self.home / 'GLOSSARY.md').write_text('# GLOSSARY.md\n\nWorkspace: A place for one business or body of work.\n')
        (self.portfolio / 'cedar-shop').mkdir(parents=True)
        (self.portfolio / 'cedar-shop/GLOSSARY.md').write_text('| Word | Meaning |\n|---|---|\n| Crown | The watch part you turn. |\n')
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            db.executescript("CREATE TABLE object_types (name TEXT, description TEXT, storage_name TEXT);"
                             "INSERT INTO object_types VALUES ('tasks','A task is one unit of work.','tasks');"
                             "INSERT INTO object_types VALUES ('agent-soul','An agent soul holds one character.','agents/<agent>.md');")
        self.lists()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('FOXRUN_')}
        self.env.update(FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio), PYTHONDONTWRITEBYTECODE='1')

    def table(self, name, header, entries):
        with (self.home / name).open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(header)
            writer.writerows(entries)

    def lists(self, folder='base/'):
        body = (self.home / 'foxrun.py').read_bytes()
        self.table(folder + 'product-manifest.tsv', ('path', 'bytes', 'sha256'),
                   [('foxrun.py', len(body), hashlib.sha256(body).hexdigest())])
        self.table(folder + 'made-at-install.tsv', ('path', 'kind'),
                   [('config/person.json', 'file'), ('runs', 'folder'), ('portfolio/cedar-shop', 'folder')])

    def launcher(self, *args, expected=0):
        result = subprocess.run([PYTHON, '-B', str(self.home / 'foxrun.py')] + list(args), cwd=str(self.home),
                                env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, expected, result.stdout)
        return result.stdout

    def test_doctor_passes_with_both_lists_in_base_and_no_installer_in_the_home(self):
        self.assertFalse((self.home / 'install.py').exists())
        output = self.launcher('doctor')
        for line in ('PASS required list base/product-manifest.tsv', 'PASS required list base/made-at-install.tsv',
                     'PASS shipped foxrun.py', 'PASS made portfolio/cedar-shop', 'Doctor: 0 failed'):
            self.assertIn(line, output)

    def test_doctor_fails_when_both_lists_are_missing(self):
        (self.home / 'base/product-manifest.tsv').unlink()
        (self.home / 'base/made-at-install.tsv').unlink()
        output = self.launcher('doctor', expected=1)
        self.assertIn('FAIL required list base/product-manifest.tsv: missing file', output)
        self.assertIn('FAIL required list base/made-at-install.tsv: missing file', output)

    def test_doctor_fails_when_one_list_is_missing(self):
        (self.home / 'base/made-at-install.tsv').unlink()
        output = self.launcher('doctor', expected=1)
        self.assertIn('PASS required list base/product-manifest.tsv', output)
        self.assertIn('FAIL required list base/made-at-install.tsv: missing file', output)
        self.assertIn('PASS shipped foxrun.py', output)

    def test_doctor_does_not_read_a_list_at_the_old_place(self):
        (self.home / 'base/product-manifest.tsv').unlink()
        (self.home / 'base/made-at-install.tsv').unlink()
        self.lists(folder='')
        output = self.launcher('doctor', expected=1)
        self.assertIn('FAIL required list base/product-manifest.tsv', output)
        self.assertNotIn('PASS shipped foxrun.py', output)

    def test_doctor_refuses_a_list_that_is_a_symbolic_link(self):
        real = self.home / 'runs/list.tsv'
        (self.home / 'base/product-manifest.tsv').rename(real)
        (self.home / 'base/product-manifest.tsv').symlink_to(real)
        output = self.launcher('doctor', expected=1)
        self.assertIn('symbolic link', output)

    def test_doctor_finds_a_changed_shipped_file(self):
        with (self.home / 'foxrun.py').open('a') as stream:
            stream.write('\n# changed\n')
        self.assertIn('FAIL shipped foxrun.py: bytes differ', self.launcher('doctor', expected=1))

    def test_status_names_the_homes_the_version_and_the_lists(self):
        output = self.launcher('status')
        for line in ('System: ' + str(self.home), 'Workspaces: ' + str(self.portfolio), 'Version: 0.1.0',
                     'System database: present', 'List: base/product-manifest.tsv | present',
                     'List: base/made-at-install.tsv | present', 'Workspace: cedar-shop | database: uses system database'):
            self.assertIn(line, output)

    def test_glossary_reads_the_dictionary_rows_and_the_page(self):
        self.assertIn('tasks: A task is one unit of work.', self.launcher('glossary', 'task'))
        output = self.launcher('glossary', 'Workspace')
        self.assertIn('Workspace: A place for one business or body of work.', output)
        self.assertIn(str(self.home / 'GLOSSARY.md'), output)
        self.assertIn('Crown: The watch part you turn.', self.launcher('glossary', 'crown', '--workspace', 'cedar-shop'))
        self.assertIn('no word: crown', self.launcher('glossary', 'crown', expected=1))
        self.assertIn('Near: agent-soul', self.launcher('glossary', 'soul', expected=1))
        self.assertEqual(self.launcher('glossary').count('\n  '), 3)

    def test_glossary_skips_the_front_matter(self):
        page = self.home / 'GLOSSARY.md'
        page.write_text('---\ntype: glossary\nworkspace: system\ntimestamp: 2026-10-19T19:35:51-04:00\n---\n' + page.read_text())
        self.assertIn('Workspace: A place for one business or body of work.', self.launcher('glossary', 'Workspace'))
        self.assertIn('no word: timestamp', self.launcher('glossary', 'timestamp', expected=1))
        self.assertEqual(self.launcher('glossary').count('\n  '), 3)

    def test_where_answers_with_a_path_a_resolver_row_or_a_dictionary_row(self):
        self.assertEqual(self.launcher('where').splitlines(), [str(self.home), str(self.portfolio)])
        self.assertEqual(self.launcher('where', 'config/person.json').strip(), str(self.home / 'config/person.json'))
        self.assertEqual(self.launcher('where', 'runs').strip(), str(self.home / 'runs'))
        self.assertIn('Run trails: System | runs/ | Chief of Staff  (RESOLVER.md)', self.launcher('where', 'run trails'))
        self.assertIn('tasks: tasks  (dictionary row)', self.launcher('where', 'task'))
        self.assertEqual(self.launcher('where', '--workspace', 'cedar-shop').strip(), str(self.portfolio / 'cedar-shop'))
        self.assertIn('no home found for: nothing-such', self.launcher('where', 'nothing-such', expected=1))
        self.assertIn('installed path does not exist', self.launcher('where', 'config/none.json', expected=1))
        self.assertIn('unsafe path', self.launcher('where', '../outside', expected=1))
        self.assertIn('Unknown workspace', self.launcher('where', '--workspace', 'nowhere', expected=2))

    def test_the_four_drawn_words_exist(self):
        output = self.launcher('--help')
        for word in ('start', 'status', 'where', 'glossary', 'rulings'):
            self.assertIn(word, output)

    def rulings_table(self, extra=()):
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            db.executescript('CREATE TABLE decisions (id TEXT PRIMARY KEY, name TEXT, statement TEXT, person_words TEXT,'
                             ' status TEXT, replaces TEXT, decided_on TEXT);')
            db.executemany('INSERT INTO decisions VALUES (?,?,?,?,?,?,?)', [
                ('g-old-library', 'Library at the top', 'The library page lives at the top, not in Atlas.', 'Put the library up top.',
                 'soft', 'none', '2026-10-12'),
                ('g-library-in-atlas', 'Library in Atlas', 'The library page lives in Atlas.', "Move library.md to Atlas.",
                 'ruled', 'g-old-library', '2026-10-18'),
                ('g-atlas-soft', 'Atlas library idea', 'Atlas holds a library index.', None, 'soft', None, '2026-10-19'),
                ('g-stock', 'Stock rule', 'Restocks start in the warehouse.', 'Start there.', 'ruled', None, '2026-10-17'),
            ] + list(extra))

    def test_rulings_match_every_word_ruled_first_and_mark_replaced_rows(self):
        self.rulings_table()
        database = self.home / 'data.db'
        before = hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns
        lines = self.launcher('rulings', 'Library', 'atlas').splitlines()
        heads = [line for line in lines if not line.startswith('  ')]
        self.assertEqual(heads, ['g-library-in-atlas | ruled | 2026-10-18',
                                 'g-atlas-soft | soft | 2026-10-19',
                                 'g-old-library | soft | 2026-10-12 | REPLACED by g-library-in-atlas'])
        self.assertIn('  The library page lives in Atlas.', lines)
        self.assertIn('  His words: Move library.md to Atlas.', lines)
        self.assertNotIn('Restocks', '\n'.join(lines))
        self.assertEqual(before, (hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns))
        self.assertIn('No ruling yet for: library warehouse', self.launcher('rulings', 'library', 'warehouse'))
        self.assertIn('the following arguments are required: words', self.launcher('rulings', expected=2))

    def test_rulings_show_ten_and_count_the_rest(self):
        self.rulings_table([('g-many-' + str(n), 'Many ' + str(n), 'Rule ' + str(n) + ' on many things.', None, 'ruled',
                             None, '2026-09-' + str(10 + n)) for n in range(12)])
        lines = self.launcher('rulings', 'many').splitlines()
        heads = [line for line in lines if not line.startswith('  ') and line.startswith('g-')]
        self.assertEqual(len(heads), 10)
        self.assertEqual(heads[0], 'g-many-11 | ruled | 2026-09-21')
        self.assertEqual(lines[-1], '2 more rulings match. Add a word to narrow them.')


    def test_scoped_rows_select_one_workspace_and_leave_other_rows(self):
        # fbf6a7c: full start now needs the row-built state modules; this small home checks its scope helper.
        (self.home / 'AGENTS.md').write_text('# Rules\n')
        (self.portfolio / 'oak-studio').mkdir()
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            db.executescript("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, tags TEXT);"
                             "CREATE VIEW open_tasks AS SELECT id,title,status FROM tasks WHERE status != 'done';"
                             "INSERT INTO tasks VALUES ('T1','Check stock','todo',NULL);"
                             "INSERT INTO tasks VALUES ('T2','Pack the order','todo','workspace:cedar-shop');"
                             "INSERT INTO tasks VALUES ('T3','Sand the table','todo','workspace:oak-studio');")
        code = ('import json; from pathlib import Path; from foxrun import open_rows, scoped_rows; '
                'rows=open_rows(Path("' + str(self.home / 'data.db') + '")); '
                'print(json.dumps([[r["id"] for r in scoped_rows(rows, name)] '
                'for name in ("cedar-shop", "oak-studio")]))')
        result = subprocess.run([PYTHON, '-B', '-c', code], cwd=self.home, env=self.env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), [['T1', 'T2'], ['T3']])

if __name__ == '__main__':
    unittest.main()
