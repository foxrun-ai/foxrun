"""T563: config/tools.yaml applies_to pushes shelf tools into each workspace's TOOLS.md."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[2]
TOOL = SRC / 'base/make_workspaces_view.py'
TEMPLATE = SRC / 'config/templates/tools.yaml'


class ToolShelf(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home, self.portfolio = root / 'home', root / 'portfolio'
        shutil.copytree(SRC / 'tools', self.home / 'tools')
        (self.home / 'config').mkdir(parents=True)
        for name in ('shop', 'other'):
            (self.portfolio / name / 'tools').mkdir(parents=True)
            (self.portfolio / name / 'AGENTS.md').write_text('# ' + name + '\n')

    def build(self, text):
        (self.home / 'config/tools.yaml').write_text(text)
        return subprocess.run([sys.executable, '-B', str(TOOL), '--system-home', str(self.home),
                               '--workspace-root', str(self.portfolio), '--as-of', '2026-10-18'],
                              text=True, capture_output=True)

    def page(self, name):
        return (self.home / 'workspaces' / name / 'TOOLS.md').read_text()

    def test_product_default_pushes_dependencies_everywhere(self):
        result = self.build(TEMPLATE.read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('shop', 'other'):
            text = self.page(name)
            self.assertIn('## From the shelf', text)
            self.assertIn('[yt-dlp](../../tools/cli/yt-dlp.md) | cli | Add-on: command-line audio/video downloader. Owner: product. Why: dependency', text)
            self.assertNotIn('printing-press', text)

    def test_list_pushes_to_named_workspaces_only(self):
        text = TEMPLATE.read_text().replace(
            'page: tools/cli/printing-press.md\n    owner: product\n    why: recommended\n    applies_to: off',
            'page: tools/cli/printing-press.md\n    owner: product\n    why: recommended\n    applies_to: [shop]')
        self.assertEqual(self.build(text).returncode, 0)
        self.assertIn('printing-press.md', self.page('shop'))
        self.assertNotIn('printing-press', self.page('other'))

    def test_absent_applies_to_changes_nothing(self):
        self.assertEqual(self.build('format: 1\ntools:\n  - name: gh\n    kind: cli\n').returncode, 0)
        self.assertNotIn('From the shelf', self.page('shop'))
        self.assertNotIn('FROM THE SHELF', self.page('shop'))

    def test_bad_applies_to_is_refused(self):
        result = self.build('format: 1\ntools:\n  - name: gh\n    kind: cli\n    applies_to: everywhere\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('applies_to must be global, off, or a workspace list', result.stderr)

    def test_every_product_page_has_a_shelf_row(self):
        # Product pages are the shipped rows; an installed shelf also holds the person's own pages.
        manifest = SRC / 'product-manifest.tsv'
        if not manifest.is_file():
            manifest = SRC / 'base/product-manifest.tsv'
        shipped = [line.split('\t', 1)[0] for line in manifest.read_text().splitlines()[1:]]
        pages = sorted(name for name in shipped if re.fullmatch(r'tools/[^/]+/[^/]+\.md', name))
        rows = [line.split('page: ', 1)[1].strip() for line in TEMPLATE.read_text().splitlines() if 'page: ' in line]
        self.assertEqual(pages, sorted(rows))
        for page in pages:
            text = (SRC / page).read_text()
            self.assertIn('| Owner | product', text)
            self.assertIn('| Why | ', text)


    def test_historical_pages_cannot_override_off_or_workspace_picks(self):
        sys.path.insert(0, str(SRC / 'base'))
        from make_workspaces_view import tool_inventory
        for workspace in ('shop', 'other'):
            folder = self.portfolio / workspace / 'tools/cli'
            folder.mkdir()
            for name in ('retired', 'scoped', 'page-off'):
                status = 'off' if name == 'page-off' else 'live'
                (folder / (name + '.md')).write_text(
                    '---\ntype: tool\nname: ' + name + '\nwhat: Test tool\nkind: cli\nuse: checks\nstatus: ' + status + '\n---\n# ' + name + '\n')
        catalog = """tools:
  - name: retired
    kind: cli
    page: tools/cli/retired.md
    applies_to: off
  - name: scoped
    kind: cli
    page: tools/cli/scoped.md
    applies_to: [shop]
"""
        done = self.build(catalog)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('scoped.md', self.page('shop'))
        self.assertNotIn('scoped.md', self.page('other'))
        for workspace in ('shop', 'other'):
            self.assertNotIn('retired.md', self.page(workspace))
            self.assertNotIn('page-off.md', self.page(workspace))
            known = tool_inventory(self.portfolio / workspace, self.home)
            self.assertNotIn('retired', known)
            self.assertNotIn('page-off', known)
            self.assertEqual('scoped' in known, workspace == 'shop')
            self.assertTrue((self.portfolio / workspace / 'tools/cli/retired.md').exists())


    def test_same_name_in_another_kind_does_not_hide_an_allowed_tool(self):
        sys.path.insert(0, str(SRC / 'base'))
        from make_workspaces_view import tool_inventory
        for kind in ('cli', 'mcp'):
            folder = self.home / 'tools' / kind
            (folder / 'shared-name.md').write_text(
                '---\ntype: tool\nname: shared-name\nstatus: live\n---\n# shared-name\n')
        (self.home / 'config/tools.yaml').write_text("""tools:
  - name: shared-name
    kind: cli
    applies_to: global
  - name: shared-name
    kind: mcp
    applies_to: [other]
""")
        known = tool_inventory(self.portfolio / 'shop', self.home)
        self.assertEqual(known['shared-name'][0].parent.name, 'cli')

    def test_off_local_override_does_not_resurrect_the_shipped_page(self):
        sys.path.insert(0, str(SRC / 'base'))
        from make_workspaces_view import tool_inventory
        folder = self.home / 'tools/cli'
        for name, status in (('local-example', 'live'), ('local-example.local', 'off')):
            (folder / (name + '.md')).write_text(
                '---\ntype: tool\nname: local-example\nstatus: ' + status + '\n---\n# local-example\n')
        self.assertNotIn('local-example', set(tool_inventory(self.portfolio / 'shop', self.home)))


    def test_personal_global_guide_only_tool_stays_out_of_workspaces(self):
        sys.path.insert(0, str(SRC / 'base'))
        from make_workspaces_view import tool_inventory
        text = """tools:
  - name: gh
    kind: cli
    page: tools/cli/gh.md
    applies_to: global
    guide_only: true
"""
        self.assertEqual(self.build(text).returncode, 0)
        for workspace in ('shop', 'other'):
            self.assertNotIn('gh.md', self.page(workspace))
            self.assertNotIn('gh', tool_inventory(self.portfolio / workspace, self.home))


if __name__ == '__main__':
    unittest.main()
