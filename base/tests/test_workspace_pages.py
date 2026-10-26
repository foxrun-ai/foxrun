"""workspace_pages builds CAPABILITIES.md and TEAM.md from the files of one workspace."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'workspace_pages.py'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class WorkspacePages(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.system, self.portfolio = root / 'system', root / 'portfolio'
        shop = self.portfolio / 'shop'
        write(self.system / 'AGENTS.md', '# AGENTS.md\n')
        # Launch fix s5-cap (28405b5) and later: capabilities read config/catalog.yaml and
        # config/module-commands.json, which the install makes.
        write(self.system / 'config/catalog.yaml', '{"where": {}}\n')
        write(self.system / 'config/module-commands.json', '{"version": 1, "commands": {}}\n')
        (self.system / 'agents').mkdir()
        write(self.system / 'tools/cli/sender.md', '---\ntype: tool\nuse: comms\n---\n# sender\n\nsender sends one message. It has more text.\n')
        write(self.system / 'skills/shared-skill/SKILL.md', '---\nname: shared-skill\ndescription: Does a shared thing. More.\n---\n')
        write(shop / 'tools/cli/counter.md', '---\ntype: tool\n---\n# counter\n\ncounter counts stock.\n')
        write(shop / 'tools/cli/notes.md', '---\ntype: doc\n---\n# Notes\n\nNot a tool page.\n')
        write(shop / 'skills/restock/SKILL.md', '---\nname: restock\ndescription: >-\n  Rank the items to restock.\n  Uses counter.\nmetadata:\n  category: Inventory\n---\nRun counter first.\n')
        write(shop / 'team/lead-shop.md', '---\nid: lead-shop\nsummary: Leads the shop.\nruntimes: [claude, codex]\nskills: [shared-skill, missing-skill]\ntools: [sender, ghost]\n---\n# Lead\n')
        write(shop / 'team/helper.md', '---\nname: helper\ndescription: Helps the lead.\nmcpServers:\n- sender\n---\n')
        write(shop / 'config/team.yaml', '# The team settings.\nlead: lead-shop\n')
        self.shop = shop
        self.env = dict(os.environ, FOXRUN_HOME=str(self.system), FOXRUN_PORTFOLIO=str(self.portfolio))

    def tool(self, *extra):
        return subprocess.run([sys.executable, str(TOOL), 'shop', *extra], env=self.env, capture_output=True, text=True)

    def test_capabilities_counts_and_groups(self):
        # Launch fix s5-cap (28405b5): the page groups by use, counts in one block, and lists each gap
        # under its own heading. Fixture tool pages are not on the tool-page template, so they say so.
        self.assertEqual(self.tool().returncode, 0)
        page = (self.shop / 'tools/CAPABILITIES.md').read_text()
        self.assertIn('# Capabilities: shop', page)
        self.assertIn('USES    2', page)
        self.assertIn('TOOLS   3  with a use: 1', page)          # counter, sender, ghost
        self.assertIn('SKILLS  2  with a use: 1', page)          # restock, shared-skill
        self.assertIn('## Comms', page)
        self.assertIn('[sender](../../../system/tools/cli/sender.md) | cli |', page)
        self.assertIn('## Inventory', page)
        self.assertIn('[`restock`](../skills/restock/SKILL.md) | Rank the items to restock. |', page)
        self.assertIn('### Tools with no page\n\n```\nNAMES  (1)\n   ghost', page)
        self.assertIn('### Skills a seat loads, not on disk\n\n```\nNAMES  (1)\n   missing-skill', page)
        self.assertIn('### Pages in tools/ that are not a tool page\n\n```\nNAMES  (1)\n   cli/notes.md', page)

    def test_team_rows_and_notes_are_kept(self):
        self.tool()
        page = self.shop / 'team/TEAM.md'
        text = page.read_text()
        self.assertIn('The lead is [`lead-shop`](lead-shop.md). The lead is set in [`config/team.yaml`](../config/team.yaml).', text)
        self.assertIn('LEAD    lead-shop', text)
        self.assertIn('| [`lead-shop`](lead-shop.md) · lead | Leads the shop. | claude · codex |', text)
        self.assertIn('| [`helper`](helper.md) | Helps the lead. | (not on disk) |', text)
        self.assertIn('SEATS   2', text)
        self.assertIn('[global contract](../../../system/profile/AGENTS.md)', text)
        self.assertNotIn('](../../../system/AGENTS.md)', text)
        page.write_text(text.replace('<!-- notes:start -->', '<!-- notes:start -->\nA line the person wrote.'))
        write(self.shop / 'team/new-seat.md', '---\nid: new-seat\nsummary: A new seat.\nruntimes: [claude]\n---\n')
        self.assertEqual(self.tool().returncode, 0)
        text = page.read_text()
        self.assertIn('A line the person wrote.', text)
        self.assertIn('SEATS   3', text)

    def test_check_names_a_page_that_differs(self):
        self.tool()
        self.assertEqual(self.tool('--check').returncode, 0)
        write(self.shop / 'team/late.md', '---\nid: late\nsummary: Came late.\n---\n')
        done = self.tool('--check')
        self.assertEqual(done.returncode, 1)
        self.assertIn('TEAM.md', done.stdout)

    def test_a_lead_file_alone_does_not_make_a_lead(self):
        (self.shop / 'config/team.yaml').unlink()
        self.tool()
        text = (self.shop / 'team/TEAM.md').read_text()
        self.assertIn('This team has no lead in `config/team.yaml` yet.', text)
        self.assertIn('LEAD    (not on disk)', text)
        self.assertIn('| [`lead-shop`](lead-shop.md) | Leads the shop. |', text)      # a seat like the others
        self.assertNotIn('· lead', text)

    def test_the_person_changes_the_lead_in_one_place(self):
        write(self.shop / 'config/team.yaml', 'lead: helper   # changed by the person\n')
        self.tool()
        text = (self.shop / 'team/TEAM.md').read_text()
        self.assertIn('The lead is [`helper`](helper.md).', text)
        self.assertIn('| [`helper`](helper.md) · lead |', text)
        self.assertNotIn('lead-shop`](lead-shop.md) · lead', text)

    def test_a_shared_seat_can_lead(self):
        write(self.system / 'agents/operator.md', '---\nid: operator\nsummary: Runs things.\n---\n')
        write(self.shop / 'config/team.yaml', 'lead: operator\n')
        self.tool()
        text = (self.shop / 'team/TEAM.md').read_text()
        self.assertIn('The lead is [`operator`](../../../system/agents/operator.md), a shared seat.', text)

    def test_a_lead_with_no_seat_file_is_said_plainly(self):
        write(self.shop / 'config/team.yaml', 'lead: nobody\n')
        self.tool()
        self.assertIn('The lead is `nobody`. No seat file with that name is on disk.', (self.shop / 'team/TEAM.md').read_text())


    def test_tool_picks_override_seats_body_mentions_and_skill_dependencies(self):
        write(self.system / 'config/tools.yaml', """tools:
  - name: sender
    kind: cli
    page: tools/cli/sender.md
    applies_to: off
  - name: counter
    kind: cli
    applies_to: [other]
  - name: extra
    kind: cli
    page: tools/cli/extra.md
    applies_to: [shop]
""")
        write(self.system / 'tools/cli/extra.md',
              '---\ntype: tool\nname: extra\nkind: cli\nuse: checks\nwhat: An extra tool\nstatus: candidate\n---\n# extra\n')
        write(self.shop / 'skills/restock/SKILL.md',
              '---\nname: restock\ndescription: Rank items\nuse: Inventory\nrequires_tools: [sender, counter]\n---\nRun `sender draft`\n')
        result = self.tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = (self.shop / 'tools/CAPABILITIES.md').read_text()
        self.assertIn('[extra]', page)
        self.assertIn('[`restock`]', page)
        self.assertNotIn('sender', page)
        self.assertNotIn('counter', page)
        self.assertIn('ghost', page)  # A genuinely missing, unruled tool remains a gap.
        self.assertTrue((self.shop / 'tools/cli/counter.md').exists())


if __name__ == '__main__':
    unittest.main()
