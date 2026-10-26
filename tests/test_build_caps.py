"""The system tool map uses only the local catalog and tool front matter."""
from pathlib import Path
import tempfile
import unittest

from base.build_caps import build


class BuildCaps(unittest.TestCase):
    def test_groups_catalog_tools_and_ignores_page_body_and_unlisted_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / 'config').mkdir()
            (home / 'tools/cli').mkdir(parents=True)
            (home / 'skills/log').mkdir(parents=True)
            (home / 'skills/log/SKILL.md').write_text('# Log\n')
            (home / 'config/tools.yaml').write_text('''tools:
  - name: local-tool
    kind: cli
    page: tools/cli/local-tool.md
  - name: absent
    kind: cli
    page: tools/cli/absent.md
''')
            (home / 'tools/cli/local-tool.md').write_text('''---
name: local-tool
what: Search | local pages
use: vault & search
---
Private name in page body: Wren Example
''')
            (home / 'tools/cli/unlisted.md').write_text('''---
name: unlisted
what: secret
use: vault & search
---
''')
            page = build(home, '2026-01-02T00:00:00Z')
            self.assertIn('[vault & search](#vault--search)', page)
            self.assertIn('| local-tool | cli | Search \\| local pages | [local-tool](cli/local-tool.md) |', page)
            self.assertIn('absent: tools/cli/absent.md is missing', page)
            self.assertIn('| log | [log](../skills/log/SKILL.md) |', page)
            self.assertNotIn('Wren Example', page)
            self.assertNotIn('unlisted', page)


    def test_off_and_workspace_picks_do_not_enter_global_guide(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / 'config').mkdir()
            (home / 'tools/cli').mkdir(parents=True)
            (home / 'config/tools.yaml').write_text("""tools:
  - name: public-tool
    kind: cli
    page: tools/cli/public-tool.md
    applies_to: global
  - name: disabled-tool
    kind: cli
    page: tools/cli/disabled-tool.md
    applies_to: off
  - name: studio-tool
    kind: cli
    page: tools/cli/studio-tool.md
    applies_to: [studio]
  - name: retired-page
    kind: cli
    page: tools/cli/retired-page.md
    applies_to: global
""")
            for name in ('public-tool', 'disabled-tool', 'studio-tool', 'retired-page'):
                status = 'off' if name == 'retired-page' else 'live'
                (home / 'tools/cli' / (name + '.md')).write_text(
                    '---\nname: ' + name + '\nwhat: A test tool\nuse: checks\nstatus: ' + status + '\n---\n')
            page = build(home, '2026-01-02T00:00:00Z')
            self.assertIn('public-tool', page)
            for name in ('disabled-tool', 'studio-tool', 'retired-page'):
                self.assertNotIn(name, page)
                self.assertTrue((home / 'tools/cli' / (name + '.md')).exists())


if __name__ == '__main__':
    unittest.main()
