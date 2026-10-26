"""The compaction hook must show the handoff and live lessons, including on failure."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'hooks/after_compact.py'


class AfterCompactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / 'home'
        self.portfolio = root / 'portfolio'
        self.workspace = self.portfolio / 'cedar-shop'
        self.workspace.mkdir(parents=True)
        boot = self.home / 'skills/handoff/bin/handoff-boot'
        boot.parent.mkdir(parents=True)
        boot.write_text('''import json, os, sys
if '--json' in sys.argv:
    print(json.dumps({'picked': os.environ['TEST_HANDOFF'], 'seat': 'architect', 'workspace': 'cedar-shop'}))
else:
    print(json.dumps({'hookSpecificOutput': {'additionalContext':
        'Boot: read this handoff first.\\nFile 1 of 1: '+os.environ['TEST_HANDOFF']+'\\n\\n'
        '---\\ntags: [architect]\\n---\\n## Boot Order\\n1. Recheck task T704.\\n## Lessons\\nL handoff'}}))
''')
        self.handoff = self.workspace / 'history/handoffs/2026-10-20-001-architect-note.md'
        self.handoff.parent.mkdir(parents=True)
        self.handoff.write_text('handoff')
        self.start = self.home / 'foxrun.py'
        self.start.write_text('''import json, sys
assert sys.argv[1:] == ['start', '--workspace', 'cedar-shop', '--seat', 'architect', '--runtime', 'claude', '--hook-json']
assert json.load(sys.stdin)['session_id'] == 's1'
print(json.dumps({'hookSpecificOutput': {'additionalContext':
    'Person: Test\\nWorkspace: cedar-shop\\n\\n## Lessons\\nL1 live lesson\\n\\n---\\ntype: state\\nOPEN TASKS 1'}}))
''')

    def run_hook(self, cwd=None):
        env = dict(os.environ, FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio),
                   TEST_HANDOFF=str(self.handoff))
        env.pop('FOXRUN_SEAT', None)
        payload = json.dumps({'cwd': str(cwd or self.workspace), 'session_id': 's1',
                              'hook_event_name': 'SessionStart', 'source': 'compact'})
        result = subprocess.run([sys.executable, str(SCRIPT), 'claude'], input=payload,
                                text=True, capture_output=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['hookSpecificOutput']['additionalContext']

    def test_handoff_boot_order_and_live_lessons_fit_one_result(self):
        output = self.run_hook()
        self.assertIn('## Boot Order\n0. `python3 ~/.foxrun/foxrun.py start --workspace cedar-shop --seat architect`', output)
        self.assertIn('1. Recheck task T704.', output)
        self.assertIn('## Lessons\nL1 live lesson', output)
        self.assertIn(str(self.handoff), output)
        self.assertLessEqual(len(output), 8000)

    def test_next_action_and_all_open_items_survive_budget(self):
        items = [f'{number}. Open item {number} has a full task instruction.'
                 for number in range(1, 31)]
        self.handoff.write_text('''---
type: handoff
session: s1
seat: architect
timestamp: 2026-10-20T01:00:00-04:00
---
## Boot Order
0. Boot Foxrun.
1. Recheck tasks.
2. Read rows.
3. Read contracts.
4. Next action: finish T704 first.

## Open Items

''' + '\n'.join(items) + '\n\n## Context\n' + ('less useful context ' * 1000))
        output = self.run_hook()
        self.assertLessEqual(len(output), 8000)
        self.assertIn('4. Next action: finish T704 first.', output)
        self.assertLess(output.index('4. Next action'), output.index('## Open Items'))
        for item in items:
            self.assertIn(item, output)
        if '## Context' in output:
            self.assertLess(output.index(items[-1]), output.index('## Context'))

    def test_retry_when_another_start_holds_markers(self):
        counter = self.home / 'attempts'
        self.start.write_text("import json, pathlib, sys\ncounter = pathlib.Path(sys.argv[0]).with_name('attempts')\ntries = int(counter.read_text()) if counter.exists() else 0\ncounter.write_text(str(tries + 1))\nif tries == 0:\n    print('FAIL start: another start writes markers; retry after it ends', file=sys.stderr)\n    sys.exit(1)\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'Person: Test\\nWorkspace: cedar-shop\\n\\n## Lessons\\nL1 live lesson'}}))\n")
        output = self.run_hook()
        self.assertIn('## Lessons\nL1 live lesson', output)
        self.assertEqual(counter.read_text(), '2')

    def test_start_failure_names_error_and_handoff(self):
        self.start.write_text('import sys\nprint("broken start", file=sys.stderr)\nsys.exit(3)\n')
        output = self.run_hook()
        self.assertIn('foxrun.py start failed (3): broken start', output)
        self.assertIn(str(self.handoff), output)
        self.assertIn('Lessons unavailable', output)

    def test_session_outside_portfolio_uses_its_own_newest_handoff(self):
        outside = Path(self.temp.name) / 'Obsidian'
        outside.mkdir()
        self.handoff.write_text('''---
type: handoff
session: s1
seat: architect
timestamp: 2026-10-19T20:34:49-04:00
---
## Boot Order
1. Recheck the architect work.
''')
        other = self.workspace / 'history/handoffs/2026-10-20-002-architect-other.md'
        other.write_text('''---
type: handoff
session: other-session
seat: architect
timestamp: 2026-10-20T01:00:00-04:00
---
## Boot Order
1. Wrong session.
''')
        output = self.run_hook(outside)
        self.assertIn('Handoff path: ' + str(self.handoff), output)
        self.assertIn('1. Recheck the architect work.', output)
        self.assertNotIn('Wrong session.', output)
        self.assertIn('## Lessons\nL1 live lesson', output)

    def no_handoff_outside_portfolio(self):
        """A session outside the portfolio with no handoff: start gets the install's default workspace."""
        boot = self.home / 'skills/handoff/bin/handoff-boot'
        boot.write_text("import json, sys\nprint(json.dumps({} if '--json' in sys.argv else "
                        "{'hookSpecificOutput': {'additionalContext': ''}}))\n")
        self.start.write_text('''import json, pathlib, sys
pathlib.Path(sys.argv[0]).with_name('picked').write_text(sys.argv[3])
print(json.dumps({'hookSpecificOutput': {'additionalContext': 'Person: Test\\n\\n## Lessons\\nL1 live lesson'}}))
''')
        outside = Path(self.temp.name) / 'elsewhere'
        outside.mkdir()
        output = self.run_hook(outside)
        return output, (self.home / 'picked').read_text()

    def test_no_handoff_falls_back_to_the_configured_default_workspace(self):
        (self.home / 'config').mkdir()
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery', 'default_workspace': 'birch-studio'}))
        output, picked = self.no_handoff_outside_portfolio()
        self.assertEqual(picked, 'birch-studio')
        self.assertIn('--workspace birch-studio', output)
        self.assertNotIn('foxrun-hq', output)

    def test_no_handoff_and_no_default_uses_the_first_workspace(self):
        (self.workspace / 'AGENTS.md').write_text('rules')
        output, picked = self.no_handoff_outside_portfolio()
        self.assertEqual(picked, 'cedar-shop')
        self.assertNotIn('foxrun-hq', output)

    def test_precompact_writer_puts_start_before_recheck(self):
        from hooks.write_handoff import render
        ctx = {'now': datetime.now(timezone.utc), 'workspace': 'cedar-shop', 'db': '/tmp/test.db',
               'report': None, 'unpromoted': [], 'session': 's1', 'agent': 'codex',
               'seat': 'architect', 'supersedes': None, 'lead_handoff': None, 'trigger': 'auto',
               'open_ids': [], 'previous': None, 'earlier_notes': [], 'agent_runtime': 'codex',
               'path_hint': 'cedar-shop/history/handoffs/test.md', 'transcript': None,
               'since': None, 'check_error': 'fixture', 'tracker_error': None,
               'statuses': {}, 'export': None}
        handoff = render(ctx)
        self.assertIn('## Boot Order\n\n0. Boot Foxrun: `python3 ~/.foxrun/foxrun.py start --workspace cedar-shop --seat architect`\n1. Recheck first:', handoff)
        self.assertIn('Run its Boot Order step 0, then step 1', handoff)


if __name__ == '__main__':
    unittest.main()
