"""Shipped code reads the person's names from config/person.json; it holds no person's names.

Rerun: python3 -m unittest base.tests.test_person_names
"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent))
import lint  # noqa: E402
import make_workspaces_view  # noqa: E402
import page_indexes  # noqa: E402
import workspace_pages  # noqa: E402
from base import migrate_capabilities, paths  # noqa: E402

PERSON = {'name': 'person', 'workspaces': ['cedar-shop', 'cedar-money'],
          'workspace_settings': {'cedar-wiki': {'move_only': True}, 'cedar-shop': {'move_only': False}},
          'tool_uses': ['cedar shop data']}


class PersonNames(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fresh, self.home = Path(temp.name) / 'fresh', Path(temp.name) / 'home'
        self.fresh.mkdir()
        (self.home / 'config').mkdir(parents=True)
        (self.home / 'config/person.json').write_text(json.dumps(PERSON))

    def test_workspace_database_reads_local_setting(self):
        configured = dict(PERSON)
        configured['workspace_settings'] = {'cedar-shop': {'database': str(self.root_database)}}
        (self.home / 'config/person.json').write_text(json.dumps(configured))
        with patch.dict('os.environ', {'FOXRUN_HOME': str(self.home)}):
            self.assertEqual(self.root_database.resolve(), paths.workspace_database('cedar-shop'))
            with self.assertRaisesRegex(ValueError, 'workspace_settings.cedar-money.database'):
                paths.workspace_database('cedar-money')

    @property
    def root_database(self):
        return self.home / 'shop-tracker.db'

    def test_fresh_home_has_no_person_names(self):
        self.assertEqual(page_indexes.move_only(self.fresh), set())
        self.assertEqual(workspace_pages.uses(self.fresh), workspace_pages.USES)
        self.assertEqual(migrate_capabilities.workspaces(self.fresh), {'foxrun-dev'})

    def test_configured_home_uses_its_names(self):
        self.assertEqual(page_indexes.move_only(self.home), {'cedar-wiki'})
        self.assertEqual(workspace_pages.uses(self.home)[-1], 'cedar shop data')
        self.assertEqual(migrate_capabilities.workspaces(self.home), {'foxrun-dev', 'cedar-shop', 'cedar-money'})

    def test_code_names_no_sample_or_owner_workspace(self):
        for name in ('page_indexes.py', 'workspace_pages.py', 'migrate_capabilities.py'):
            text = (BASE / name).read_text()
            for word in ('sample-project', 'sample-shop', 'sample-finance'):
                self.assertNotIn(word, text, name)

    def test_own_local_tool_page_wins_over_the_shipped_page(self):
        cli = self.home / 'tools/cli'
        cli.mkdir(parents=True)
        page = '---\ntype: tool\nname: gh\nstatus: %s\n---\n# gh\n\nGitHub command-line tool.\n'
        (cli / 'gh.md').write_text(page % 'candidate')
        (cli / 'gh.local.md').write_text(page % 'live')
        (cli / 'pdftotext.md').write_text(page.replace('gh', 'pdftotext') % 'candidate')
        found = make_workspaces_view.tool_inventory(self.fresh, self.home)
        self.assertEqual(found['gh'][0].name, 'gh.local.md')
        self.assertEqual(found['pdftotext'][0].name, 'pdftotext.md')
        self.assertNotIn('gh.local', found)

    def test_lint_reads_the_local_page_name(self):
        self.assertEqual(lint.page_stem(Path('tools/cli/gh.local.md')), 'gh')
        self.assertEqual(lint.page_stem(Path('tools/cli/gh.md')), 'gh')


if __name__ == '__main__':
    unittest.main()
