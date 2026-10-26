"""Small synthetic homes prove lint behavior. No real home is copied."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from base.tests.support import shipped_paths

SOURCE = Path(__file__).resolve().parents[1] / 'lint.py'
spec = importlib.util.spec_from_file_location('foxrun_lint', SOURCE)
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


def rendered_policy(folder, fixture, workspace='sample-shop'):
    """Copy shipped policy bytes only, then name one fixture workspace."""
    target = Path(folder) / 'product-policy'
    shutil.copytree(fixture, target)
    root = SOURCE.parents[1]
    # T742: local lint settings belong to the person; fixture checks use shipped policy only.
    for path in shipped_paths(root):
        if path.is_file() and path.is_relative_to(root / 'config/lint'):
            output = target / path.relative_to(root / 'config/lint')
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output)
    # T742: these are fixture settings; the person's workspaces and top paths never enter tests.
    (target / 'workspaces.tsv').write_text('id\tkind\tsource\n' + workspace + '\tworkspace\tFixture.\n')
    allowed = [('system', 'VERSION', 'file'), ('system', 'sources', 'dir'),
               ('portfolio', 'atlas', 'dir'), ('portfolio', workspace, 'dir'),
               ('workspace', 'AGENTS.md', 'file'), ('workspace', '.agents', 'dir'), ('workspace', '.claude', 'dir'),
               ('workspace', '.codex', 'dir'), ('workspace', '.mcp.json', 'file')]
    allowed += [('atlas', name, 'dir') for name in
                ('comparisons', 'concepts', 'entities', 'queries', 'raw', 'history')]
    with (target / 'allowed-top.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(('scope', 'name', 'kind', 'source'))
        writer.writerows((*row, 'Fixture.') for row in allowed)
    # T742: these page bindings are local settings; use small explicit test specs.
    missing = {
        'v3/top-pages/spec-STATE.tsv': (
            'rule\tvalue\nsection_nonempty\tDo first|Limits\n'
            'section_numbered_count\tDo first=5\nsection_bullet_count\tLimits=4\n'
            'section_fence_count\tCommands=1\n'
            'section_code_labels\tLast 7 days=NEW TASKS|RUNS|DECISIONS\n'
            'required_table\tCommands=Question|View\n'),
        'v3/top-pages/spec-RESOLVER.tsv': 'rule\tvalue\n',
        'v2/capabilities/spec.tsv': 'rule\tvalue\n',
    }
    for name, body in missing.items():
        path = target / 'specs' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return target


RULES = [
    ('L01', 'page_spec', 'pages'), ('L02', 'allowed_top', 'all'),
    ('L03', 'empty_folder', 'all'), ('L04', 'blank_page', 'pages'),
    ('L04', 'state_tracker', 'pages'), ('L05', 'frontmatter', 'pages'),
    ('L06', 'database', 'all'), ('L07', 'required_pages', 'all'),
    ('L08', 'no_business_name', 'system-pages'), ('L09', 'links', 'all')]


APPROVED_FORMS = {'TEAM': "---\ntype: index\nworkspace: sample-shop\ntimestamp: 2026-10-13T18:20:43-04:00\n---\n# Team: sample-shop\n\nThe lead is [`lead-sample-shop`](lead-sample-shop.md). A script makes the table and the tree from the files in this folder. Write only in Notes.\n\n**Go to:** [State](../STATE.md) · [Capabilities](../tools/CAPABILITIES.md) · [Index](../index.md)\n\n```\nLEAD    lead-sample-shop\nSEATS   5\nMADE    2026-10-13 18:20\n```\n\n| Seat | What it does | Runs on |\n|---|---|---|\n| [`lead-sample-shop`](lead-sample-shop.md) · lead | Lead sample-shop and keep work clear. | claude · codex |\n| [`amazon-operator`](amazon-operator.md) | Keeps Sample Shop's Amazon listings correct and compliant. Audits, prepares the exact correction with evidence, and drafts support responses. Submits nothing without Person's yes. | hermes · claude · codex |\n| [`creative-strategist`](creative-strategist.md) | Finds the angle. Reads buyer language and past ad results, then writes one tight creative brief with required shots and claims the reviewer can check. | (not on disk) |\n| [`sample-shop`](sample-shop.md) | sample-shop business operations — ShipBob, Gmail, creators, Amazon FBA | (not on disk) |\n| [`ugc-producer`](ugc-producer.md) | Runs creator content from talent to delivered files — finds fits, drafts the deal, writes the shot list, chases delivery — and hands Mercer drafts, never sends. | (not on disk) |\n\nEach lead directs its own workers. Workers do not start other workers. This rule is in [`AGENTS.md`](../../../.foxrun/AGENTS.md).\n\nShared seats work for every workspace. They are in [`~/.foxrun/agents/`](../../../.foxrun/agents/).\n\n## Files\n\n```\nteam/\n├─ TEAM.md                  this page\n├─ lead-sample-shop.md        seat · lead\n├─ amazon-operator.md       seat\n├─ creative-strategist.md   Claude file, not a seat file\n├─ sample-shop.md             Claude file, not a seat file\n├─ ugc-producer.md          Claude file, not a seat file\n├─ claude/\n│  └─ lead-sample-shop.md     made from lead-sample-shop.md\n└─ codex/\n   ├─ amazon-operator.toml  made from amazon-operator.md\n   ├─ creative-strategist.tomlmade from creative-strategist.md\n   ├─ lead-sample-shop.toml   made from lead-sample-shop.md\n   ├─ mercer.toml           (not on disk)\n   ├─ sample-shop.toml        made from sample-shop.md\n   └─ ugc-producer.toml     made from ugc-producer.md\n```\n\n## Notes\n\nA new build keeps the lines between the two note marks.\n\n<!-- notes:start -->\n<!-- notes:end -->\n", 'STATE': '---\ntype: state\nworkspace: sample-shop\ntimestamp: 2026-10-13T18:44:52-04:00\n---\n# State: sample-shop\n\nAn agent reads this page first. A script makes it from the rows in `data.db`. Change a row, not this page.\n\n```\nWORKSPACE           sample-shop\nLEAD                lead-sample-shop\nDB                  path from config/person.json\nOPEN TASKS          72\nIN PROGRESS         25\nIN REVIEW           15\nBLOCKED             0\nNOT STARTED         32\nWAITING FOR person  0\nOPEN BUGS           51\nNEWEST CHANGE       2026-10-12T21:28:42-04:00\nMADE                2026-10-13T18:44:52-04:00\nFRESH               yes\n```\n\n## Do first\n\n1. Read the system [`AGENTS.md`](../../.foxrun/AGENTS.md).\n2. Read [`AGENTS.md`](AGENTS.md) of this workspace.\n3. Read [`RESOLVER.md`](RESOLVER.md) before you change a fact.\n4. When `FRESH` is `no`, the lists on this page are old. Read the views: command 4 under `Commands`.\n5. Before work, find your task row or make one. Then claim it: command 2 under `Commands`.\n\n## Limits\n\n- Get the person\'s explicit yes before money, sends, deletes, or actions that cannot be undone.\n- Show the exact action before you ask.\n- Workers do not start other workers.\n- Fix source rows before you rebuild generated pages.\n\nDo not act against these four lines. They are in the system [`AGENTS.md`](../../.foxrun/AGENTS.md), word for word. That page has the full rules.\n\n## Waiting for Person\n\nNone. The view `needs_me` has 0 rows.\n\n## Blocked\n\nNone. 0 open tasks have the status `blocked`.\n\n## In progress\n\n| Task | Title | Claimed by | Stream |\n|---|---|---|---|\n| T178 | Sample Creator Payment Request | opus | WS01 |\n| T177 | Sample Person Meeting Prep 10.9 | opus | WS01 |\n| T171 | Creator Reply Kit | opus | WS01 |\n| T162 | Ask Sample Person: Example Contact Payment Claimed | opus | WS01 |\n| T163 | Creator Sweep 10.8 | opus | WS01 |\n\n20 more. All 25: `select * from open_tasks where status=\'in-progress\'`.\n\n## In review\n\n| Task | Title | Stream |\n|---|---|---|\n| T153 | Creator Refresh 10.6 | WS01 |\n| T149 | TikTok One Creator Discovery Route | WS01 |\n| T144 | Creator Board Data Map | WS01 |\n| T139 | Safe Outreach Pacing Research | WS01 |\n| T136 | Prospect Review Carousel | WS01 |\n\n10 more. All 15: `select * from open_tasks where status=\'in-review\'`.\n\n## Open by stream\n\n| Stream | In progress | In review | Not started |\n|---|---|---|---|\n| WS01 Creators | 17 | 14 | 26 |\n| WS04 Amazon | 7 | 1 | 3 |\n| WS03 Strategy | 1 | 0 | 1 |\n| WS05 Data Feeds | 0 | 0 | 2 |\n\n## Last 7 days\n\nFrom 2026-10-06 to the time in `MADE`.\n\n```\nNEW TASKS           15\nRUNS                97\nDECISIONS           2\n```\n\n| Decision id | Name | Ruled |\n|---|---|---|\n| `d-ca-duties-paid-price-up-20` | Canada: duties paid, price up 20%, Sample Person agreed | 2026-10-09 |\n| `d-compliance-page1-marked-draft` | Compliance test copies carry a DRAFT mark | 2026-10-08 |\n\n## Commands\n\nRun each one from any folder. `<task>` is an id such as `T178`. `<you>` is your seat id.\n\n```sh\n# 1. print this page and the open tasks\npython3 ~/.foxrun/foxrun.py start --workspace sample-shop\n\n# 2. claim a task\npython3 ~/.foxrun/work/work.py --workspace sample-shop \\\n  --receipt-root ~/foxrun/sample-shop claim <task> --by <you>\n\n# 3. read one task\npython3 ~/.foxrun/work/work.py --workspace sample-shop \\\n  --receipt-root ~/foxrun/sample-shop show <task>\n\n# 4. read a view (read only)\nsqlite3 -readonly <tracker-from-config/person.json> \\\n  "select * from <view>"\n```\n\n| Question | View |\n|---|---|\n| What is open? | `open_tasks` |\n| What waits for Person? | `needs_me` |\n| What is in review, with subtasks? | `close_now` |\n| What is planned or due in the next 7 days? | `this_week` |\n| Which decisions are open? | `open_decisions` |\n| Which stock is at zero or less? | `v_low_stock` |\n| Which restocks are due? | `v_restock_due` |\n| How old is each mirror? | `v_mirror_age` |\n'}


class LintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'system'
        self.ws = self.root / 'portfolio'
        self.policy = self.root / 'policy'
        for p in (self.home, self.ws / 'shop', self.policy / 'specs'):
            p.mkdir(parents=True)
        self.write_page(self.ws / 'shop/AGENTS.md', 'shop', '# Contract\n\nThis labeled workspace contract registers one test workspace.\n')
        self.table('rules', ['id', 'words', 'kind', 'scope', 'level'],
                   [[id_, 'Fixture rule.', kind, scope, 'error'] for id_, kind, scope in RULES])
        self.table('scan', ['kind', 'pattern', 'reason'], [['exclude_dir', '.git', 'Git payload.']])
        self.table('workspaces', ['id', 'kind', 'source'], [['shop', 'workspace', 'Fixture contract.']])
        self.table('allowed-top', ['scope', 'name', 'kind', 'source'], [
            ['system', 'STATE.md', 'file', 'Fixture.'], ['system', 'data.db', 'file', 'Fixture.'],
            ['system', 'PAGE.md', 'file', 'Fixture.'], ['portfolio', 'shop', 'dir', 'Fixture.'],
            ['workspace', 'AGENTS.md', 'file', 'Fixture.'], ['workspace', 'STATE.md', 'file', 'Fixture.'], ['workspace', 'data.db', 'file', 'Fixture.']])
        self.table('empty-ok', ['path', 'reason'], [])
        self.table('business-names', ['name', 'source'], [['Acme', 'Fixture brand.']])
        self.table('frontmatter', ['key', 'required', 'format', 'values'], [
            ['type', 'yes', 'kebab', 'doc|state'], ['workspace', 'yes', 'workspace', ''],
            ['timestamp', 'yes', 'iso8601', '']])
        self.table('pages', ['home', 'pattern', 'spec'], [['system', 'PAGE.md', 'page.tsv']])
        self.table('parts', ['spec', 'kind', 'value'], [])
        self.table('specs/page', ['rule', 'value'], [
            ['frontmatter_key', 'type'], ['frontmatter_value', 'type=doc'],
            ['frontmatter_keys_allowed', 'type|workspace|timestamp'], ['h1', 'Fixture'],
            ['heading_order', 'First > Second'], ['headings_required', 'First|Second'],
            ['table_columns', 'First=Name|Meaning'], ['count_block_labels', 'ITEMS|MADE'],
            ['max_code_line', '78'], ['max_table_columns', '4']])
        self.table('required-pages', ['scope', 'path'], [['system', 'PAGE.md'], ['workspace', 'STATE.md']])
        self.table('db', ['home', 'path', 'table', 'column', 'format'], [
            [h, 'data.db', 'tasks', c, f] for h in ('system', 'workspace')
            for c, f in [('id', 'text'), ('title', 'text'), ('status', 'text'),
                         ('created_on', 'iso8601'), ('owner', 'text')]])
        self.table('db-reasons', ['home', 'table', 'row_id', 'column', 'case', 'reason'],
                   [[h, 'tasks', 'T1', 'owner', 'null', 'Task has no assigned owner.'] for h in ('system', 'shop')])
        self.write_page(self.home / 'PAGE.md', 'system', '''# Fixture

This page explains the fixture and links to its local task state.

```
ITEMS  1
MADE   2026-10-13T12:00:00-04:00
```

## First

| Name | Meaning |
|---|---|
| Example | A local fixture. |

## Second

Read [State](STATE.md) to see the current local work.
''')
        for root, name in ((self.home, 'system'), (self.ws / 'shop', 'shop')):
            self.write_page(root / 'STATE.md', name, '# State\n\nAn agent reads this local tracker count before work.\n\n```\nOPEN TASKS  1\n```\n', 'state')
            con = sqlite3.connect(str(root / 'data.db'))
            con.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, created_on TEXT, owner TEXT)')
            con.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, ?)', ('T1', 'Fixture task', 'todo', '2026-10-13T12:00:00-04:00', None))
            con.commit(); con.close()
        self.product = rendered_policy(self.root, self.policy)

    def table(self, name, columns, rows):
        with (self.policy / (name + '.tsv')).open('w', newline='') as f:
            w = csv.writer(f, delimiter='\t', lineterminator='\n')
            w.writerow(columns); w.writerows(rows)

    def write_page(self, path, workspace, body, type_='doc'):
        path.write_text('---\ntype: ' + type_ + '\nworkspace: ' + workspace +
                        '\ntimestamp: 2026-10-13T12:00:00-04:00\n---\n' + body)

    def replace(self, old, new, path=None):
        path = path or self.home / 'PAGE.md'
        path.write_text(path.read_text().replace(old, new))

    def run_lint(self, rule=None):
        return lint.Lint(self.home, self.ws, self.policy).run(rule)

    def assert_finding(self, rule, text):
        rows = self.run_lint(rule)
        self.assertTrue(any(text in r['what'] for r in rows), rows)
        for row in rows:
            self.assertEqual(set(row), {'rule_id', 'level', 'write', 'path', 'line', 'what', 'how_to_fix'})
            self.assertTrue(row['how_to_fix'])

    def sql(self, statement, root=None):
        con = sqlite3.connect(str((root or self.home) / 'data.db'))
        con.execute(statement); con.commit(); con.close()

    def test_good_home_all_kinds(self):
        self.assertEqual(self.run_lint(), [])

    def test_frontmatter_missing_key(self):
        self.replace('type: doc\n', '')
        self.assert_finding('L05', 'Required front matter key')

    def test_frontmatter_bad_workspace(self):
        self.replace('workspace: system', 'workspace: gone')
        self.assert_finding('L05', 'Invalid front matter value: workspace')

    def test_frontmatter_invalid_calendar_time(self):
        self.replace('2026-10-13T12:00:00-04:00', '2026-02-30T12:00:00-04:00')
        self.assert_finding('L05', 'Invalid front matter value: timestamp')

    def test_frontmatter_duplicate_key(self):
        self.replace('type: doc', 'type: doc\ntype: doc')
        self.assert_finding('L05', 'Duplicate front matter key')

    def test_frontmatter_spec_allowed_value(self):
        self.replace('type: doc', 'type: state')
        self.assert_finding('L05', 'Front matter differs from spec: type')

    def test_frontmatter_extra_key(self):
        self.replace('type: doc', 'type: doc\nextra: value')
        self.assert_finding('L05', 'outside the spec')

    def test_frontmatter_list_workspace(self):
        self.replace('workspace: system', 'workspace: [system, gone]')
        self.assert_finding('L05', 'Invalid front matter value: workspace')

    def test_frontmatter_unindented_yaml_list_is_valid(self):
        self.replace('workspace: system', 'workspace:\n- system')
        self.assertEqual(self.run_lint('L05'), [])

    def test_frontmatter_unindented_yaml_list_checks_values(self):
        self.replace('workspace: system', 'workspace:\n- system\n- gone')
        self.assert_finding('L05', 'Invalid front matter value: workspace')

    def test_frontmatter_multiline_flow_container_is_not_top_level(self):
        text = '---\ntype: doc\nworkspace: system\ntimestamp: 2026-10-13T12:00:00-04:00\nmcpServers: {\n"sample": {"type": "nested"}\n}\n---\n# Flow\n\nA synthetic page with an opaque runtime metadata object.'
        (self.home / 'FLOW.md').write_text(text)
        checker = lint.Lint(self.home, self.ws, self.policy)
        checker.frontmatter({'id':'L05','level':'error'}, self.home / 'FLOW.md')
        self.assertEqual(checker.findings, [])
        self.assertEqual(checker.page(self.home / 'FLOW.md').fields['type'], 'doc')

    def test_spec_heading_order(self):
        self.replace('## First', '## TEMP'); self.replace('## Second', '## First'); self.replace('## TEMP', '## Second')
        self.assert_finding('L01', 'wrong order')

    def test_spec_table_columns(self):
        self.replace('| Name | Meaning |', '| Wrong | Meaning |')
        self.assert_finding('L01', 'Table columns differ')

    def test_spec_table_missing(self):
        self.replace('| Name | Meaning |\n|---|---|\n| Example | A local fixture. |', 'A section with no required table.')
        self.assert_finding('L01', 'Required table is absent')

    def test_shipped_claude_shim_requires_only_the_workspace_import(self):
        self.table('pages', ['home', 'pattern', 'spec'],
                   [['workspace', 'CLAUDE.md', 'v3/top-pages/spec-CLAUDE.tsv']])
        checker = lint.Lint(self.home, self.ws, self.product)
        target = self.ws / 'shop/CLAUDE.md'
        self.write_page(target, 'shop', '@AGENTS.md\n', 'agents')
        checker.page_spec({'id': 'L01', 'level': 'error'}, target)
        self.assertEqual(checker.findings, [])
        self.write_page(target, 'shop', 'Read `AGENTS.md` in this folder first.\n', 'agents')
        checker = lint.Lint(self.home, self.ws, self.product)
        checker.page_spec({'id': 'L01', 'level': 'error'}, target)
        self.assertTrue(any('Required page part' in row['what'] for row in checker.findings), checker.findings)

    def test_spec_required_part(self):
        self.replace('ITEMS  1', 'COUNT  1')
        self.assert_finding('L01', 'Required count label is absent')

    def test_spec_code_line(self):
        self.replace('ITEMS  1', 'ITEMS  ' + '1' * 80)
        self.assert_finding('L01', 'Code line exceeds')

    def test_heading_inside_fence_is_not_section(self):
        self.replace('## First', '```\n## First\n```')
        self.assert_finding('L01', 'Required heading is absent')

    def test_top_unknown_file(self):
        (self.home / 'extra.txt').write_text('Extra fixture.')
        self.assert_finding('L02', 'outside the top list')

    def test_top_wrong_kind(self):
        (self.home / 'PAGE.md').unlink(); (self.home / 'PAGE.md').mkdir()
        self.assert_finding('L02', 'wrong kind')

    def test_empty_folder(self):
        (self.home / 'empty').mkdir()
        self.assert_finding('L03', 'empty without')

    def test_gitkeep_does_not_hide_empty_folder(self):
        (self.home / 'empty').mkdir(); (self.home / 'empty/.gitkeep').touch()
        self.assert_finding('L03', 'empty without')

    def test_empty_reason_requires_actual_reason(self):
        (self.home / 'empty').mkdir()
        self.table('empty-ok', ['path', 'reason'], [['system/empty', '']])
        self.assert_finding('L03', 'empty without')
        self.table('empty-ok', ['path', 'reason'], [['system/empty', 'Awaiting a fixture output.']])
        self.assertEqual(self.run_lint('L03'), [])

    def test_blank_page(self):
        self.write_page(self.home / 'PAGE.md', 'system', '# Empty\n')
        self.assert_finding('L04', 'fewer than 40')

    def test_state_false_no_work(self):
        self.replace('An agent reads this local tracker count before work.', 'No work has started yet.', self.ws / 'shop/STATE.md')
        self.assert_finding('L04', 'contradicts tracker')

    def test_state_wrong_count(self):
        self.replace('OPEN TASKS  1', 'OPEN TASKS  0', self.home / 'STATE.md')
        self.assert_finding('L04', 'contradicts tracker')

    def test_state_missing_database_is_failure(self):
        (self.ws / 'shop/data.db').unlink()
        self.assert_finding('L04', 'Check cannot complete')

    def test_nested_state_example_is_not_tracker_state(self):
        (self.home / 'templates').mkdir()
        self.write_page(self.home / 'templates/STATE.md', 'system',
                        '# Example\n\nNo work has started yet. This is only a template example.\n', 'state')
        self.assertEqual(self.run_lint('L04'), [])

    def test_database_null_requires_exact_reason(self):
        self.sql('UPDATE tasks SET title=NULL')
        self.assert_finding('L06', 'title is null without a reason')

    def test_database_blank(self):
        self.sql("UPDATE tasks SET title='  '")
        self.assert_finding('L06', 'title is blank without a reason')

    def test_database_bad_time(self):
        self.sql("UPDATE tasks SET created_on='2026-10-13'")
        self.assert_finding('L06', 'not an ISO 8601 time')

    def test_database_missing_column(self):
        with (self.policy / 'db.tsv').open('a') as f:
            f.write('system\tdata.db\ttasks\tmissing\ttext\n')
        self.assert_finding('L06', 'column is absent')

    def test_database_read_only(self):
        before = {p: p.read_bytes() for p in (self.home / 'data.db', self.ws / 'shop/data.db')}
        self.assertEqual(self.run_lint('L06'), [])
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)
        checker = lint.Lint(self.home, self.ws, self.policy)
        con = checker.open_db(self.home / 'data.db')
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("UPDATE tasks SET title='Changed'")
        finally:
            con.close()

    def test_required_top_page(self):
        (self.ws / 'shop/STATE.md').unlink()
        self.assert_finding('L07', 'Required top page is absent')

    def test_required_top_page_uses_spec(self):
        self.replace('## Second', '## Missing')
        self.assert_finding('L07', 'Required heading is absent')

    def test_business_name(self):
        self.replace('local task state', 'Acme task state')
        self.assert_finding('L08', 'System page names')

    def test_business_workspace_name(self):
        self.replace('local task state', 'SHOP task state')
        self.assertEqual(self.run_lint('L08'), [])

    def test_business_hyphen_and_space(self):
        self.table('business-names', ['name', 'source'], [['old-shop', 'Fixture business.']])
        self.replace('local task state', 'OLD SHOP task state')
        self.assert_finding('L08', 'System page names')
        self.replace('OLD SHOP', 'old-shop')
        self.assert_finding('L08', 'System page names')

    def test_empty_database_reason(self):
        self.sql('DELETE FROM tasks')
        self.assert_finding('L06', 'tasks is empty')
        self.table('db-reasons', ['home', 'table', 'row_id', 'column', 'case', 'reason'], [
            ['system', 'tasks', '', '', 'empty-table', 'Fixture has no tasks yet.'],
            ['shop', 'tasks', 'T1', 'owner', 'null', 'Task has no assigned owner.']])
        self.assertEqual(self.run_lint('L06'), [])

    def test_missing_link(self):
        self.replace('(STATE.md)', '(gone.md)')
        self.assert_finding('L09', 'Local link target is absent')

    def test_link_with_source_line_resolves_file(self):
        self.replace('(STATE.md)', '(STATE.md:12)')
        self.assertEqual(self.run_lint('L09'), [])

    def test_link_with_source_line_checks_missing_file(self):
        self.replace('(STATE.md)', '(gone.md:12)')
        self.assert_finding('L09', 'Local link target is absent')

    def test_inline_link_examples_are_not_links(self):
        self.replace('Read [State](STATE.md)', 'Read `[example](gone.md)` and `[[gone]]`. Read [State](STATE.md)')
        self.assertEqual(self.run_lint('L09'), [])

    def test_footnote_body_is_not_a_reference_url(self):
        self.replace('Read [State](STATE.md)', 'Read [State](STATE.md).\n\n[^source]: [[STATE]]; [[PAGE]]')
        self.assertEqual(self.run_lint('L09'), [])

    def test_reference_link_still_checks_target(self):
        self.replace('Read [State](STATE.md)', 'Read [State][state].\n\n[state]: gone.md')
        self.assert_finding('L09', 'Local link target is absent')

    def test_wiki_link_resolves_workspace_root(self):
        (self.ws / 'shop/notes').mkdir()
        self.write_page(self.ws / 'shop/notes/note.md', 'shop', '# Note\n\nRead [[shop/STATE]] for the task count.')
        self.assertEqual(self.run_lint('L09'), [])

    def test_wiki_link_resolves_unique_managed_basename(self):
        (self.home / 'notes').mkdir()
        self.write_page(self.home / 'notes/unique.md', 'system', '# Unique\n\nA source-backed page inside this synthetic home.')
        self.replace('(STATE.md)', '(STATE.md) and [[unique]]')
        self.assertEqual(self.run_lint('L09'), [])

    def test_wiki_link_ambiguity_requires_explicit_path(self):
        for folder in ('a', 'b'):
            (self.home / folder).mkdir()
            self.write_page(self.home / folder / 'duplicate.md', 'system', '# Duplicate\n\nA distinct synthetic page in this folder.')
        self.replace('(STATE.md)', '(STATE.md) and [[duplicate]]')
        self.assert_finding('L09', 'Wiki link target is ambiguous')

    def test_missing_section_link(self):
        self.replace('(STATE.md)', '(STATE.md#missing)')
        self.assert_finding('L09', 'Link section is absent')

    def test_links_keep_source_line(self):
        self.replace('(STATE.md)', '(gone.md)')
        path = self.home / 'PAGE.md'
        expected = next(i for i, s in enumerate(path.read_text().splitlines(), 1) if 'gone.md' in s)
        row = next(r for r in self.run_lint('L09') if r['path'] == str(path))
        self.assertEqual(row['line'], expected)

    def test_dead_symlink(self):
        (self.ws / 'shop/dead').symlink_to('missing')
        self.assert_finding('L09', 'Symbolic link target is absent')

    def test_external_symlink_payload_not_read(self):
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'BAD.md').write_bytes(b'\xff')
        (self.home / 'outside').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_lint('L05'), [])

    def test_secret_payload_not_read(self):
        (self.home / 'secrets').mkdir()
        (self.home / 'secrets/private.md').write_bytes(b'\xff')
        (self.home / '.env').write_bytes(b'\xff')
        (self.home / 'auth.json').write_bytes(b'\xff')
        self.assertEqual(self.run_lint(), [])

    def test_url_and_fence_links_are_not_checked(self):
        self.replace('Read [State](STATE.md)', 'Read [web](https://example.invalid)\n\n```\n[Example](gone.md)\n```\n\nRead [State](STATE.md)')
        self.assertEqual(self.run_lint('L09'), [])

    def test_rule_added_with_one_data_line(self):
        self.replace('type: doc\n', '')
        with (self.policy / 'rules.tsv').open('a') as f:
            f.write('NEW01\tSame shape for this page.\tfrontmatter\tsystem:PAGE.md\terror\n')
        rows = self.run_lint('NEW01')
        self.assertTrue(rows)
        self.assertTrue(all(r['rule_id'] == 'NEW01' and r['path'] == str(self.home / 'PAGE.md') for r in rows))

    def test_glob_star_stays_in_one_folder(self):
        self.assertTrue(lint.path_match('tools/cli/tool.md', 'tools/*/*.md'))
        self.assertFalse(lint.path_match('tools/cli/tool/nested.md', 'tools/*/*.md'))
        self.assertTrue(lint.path_match('base/README.md', '**/README.md'))
        self.assertTrue(lint.path_match('README.md', '**/README.md'))

    def test_bad_scope_is_failure(self):
        with (self.policy / 'rules.tsv').open('a') as f:
            f.write('BAD\tInvalid scope.\tfrontmatter\tmisspelled:*.md\terror\n')
        with self.assertRaises(ValueError):
            self.run_lint()

    def test_unknown_rule_does_not_pass(self):
        with self.assertRaises(ValueError):
            self.run_lint('MISSING')

    def test_unknown_kind_does_not_pass(self):
        with (self.policy / 'rules.tsv').open('a') as f:
            f.write('NEW02\tBad fixture.\tnot-built\tall\terror\n')
        with self.assertRaises(ValueError):
            self.run_lint()

    def test_cli_json_warning_exit(self):
        # A tiny package copy uses this fixture policy, never a copied home.
        package = self.root / 'package'; (package / 'base').mkdir(parents=True)
        (package / 'base/lint.py').write_bytes(SOURCE.read_bytes())
        (package / 'base/paths.py').write_bytes((SOURCE.parent / 'paths.py').read_bytes())
        (package / 'config').mkdir(); (package / 'config/lint').symlink_to(self.policy)
        self.replace('type: doc\n', '')
        self.table('rules', ['id', 'words', 'kind', 'scope', 'level'], [['W01', 'Fixture warning.', 'frontmatter', 'pages', 'warning']])
        result = subprocess.run([sys.executable, '-B', str(package / 'base/lint.py'), '--home', str(self.home),
                                 '--workspaces', str(self.ws), '--rule', 'W01', '--json'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout))

    def test_missing_home_does_not_pass(self):
        with self.assertRaises(ValueError):
            lint.Lint(self.root / 'gone', self.ws, self.policy).run()


    def production_page(self, name, text=None):
        path = self.ws / 'sample-shop' / ('team/TEAM.md' if name == 'TEAM' else 'STATE.md')
        path.parent.mkdir(parents=True, exist_ok=True)
        (self.ws/'sample-shop/AGENTS.md').write_text('# Contract\n')
        path.write_text(APPROVED_FORMS[name] if text is None else text)
        checker = lint.Lint(self.home, self.ws, self.product)
        checker.page_spec({'id': 'L01', 'level': 'error'}, path)
        return checker.findings

    def test_production_team_passes(self):
        self.assertEqual(self.production_page('TEAM'), [])

    def test_production_team_missing_seat_table(self):
        text = '\n'.join(s for s in APPROVED_FORMS['TEAM'].splitlines() if not s.startswith('|'))
        self.assertTrue(any('Required table is absent' in r['what'] for r in self.production_page('TEAM', text)))

    def test_production_team_missing_files_fence(self):
        import re
        text = re.sub(r'(?ms)(^## Files\n).*?(?=^## )', r'\1\n', APPROVED_FORMS['TEAM'])
        self.assertTrue(any('Files needs' in r['what'] for r in self.production_page('TEAM', text)))

    def test_production_state_passes(self):
        self.assertEqual(self.production_page('STATE'), [])

    def test_production_state_empty_startup_sections(self):
        import re
        text = re.sub(r'(?ms)(^## (?:Do first|Limits)\n).*?(?=^## )', r'\1\n', APPROVED_FORMS['STATE'])
        rows = self.production_page('STATE', text)
        self.assertTrue(any('Required section body is empty: Do first' in r['what'] for r in rows))
        self.assertTrue(any('Required section body is empty: Limits' in r['what'] for r in rows))

    def test_production_state_wrong_startup_list_count(self):
        text = APPROVED_FORMS['STATE'].replace('5. Before work', 'Before work')
        self.assertTrue(any('Do first needs 5 list items' in r['what'] for r in self.production_page('STATE', text)))

    def test_production_state_wrong_limits_count(self):
        text = APPROVED_FORMS['STATE'].replace('- Workers do not start', 'Workers do not start')
        self.assertTrue(any('Limits needs 4 list items' in r['what'] for r in self.production_page('STATE', text)))

    def test_production_state_missing_commands_fence(self):
        import re
        text = re.sub(r'(?ms)^```sh\n.*?^```', '', APPROVED_FORMS['STATE'])
        self.assertTrue(any('Commands needs 1 non-empty code fences' in r['what'] for r in self.production_page('STATE', text)))

    def test_production_state_missing_activity_count(self):
        text = APPROVED_FORMS['STATE'].replace('NEW TASKS           15', 'NEW ITEMS           15')
        self.assertTrue(any('Required code label' in r['what'] for r in self.production_page('STATE', text)))

    def test_production_state_missing_query_table(self):
        text = APPROVED_FORMS['STATE'].split('| Question | View |')[0]
        self.assertTrue(any('Required table is absent: Commands' in r['what'] for r in self.production_page('STATE', text)))

    def test_production_allowed_drawing_entries(self):
        home, ws = self.root / 'drawing-system', self.root / 'drawing-portfolio'
        home.mkdir(); ws.mkdir()
        for name in ('comparisons', 'concepts', 'entities', 'queries', 'raw', 'history'):
            (ws / 'atlas' / name).mkdir(parents=True)
        (home / 'sources').mkdir()
        (home / 'VERSION').write_text('1.0\n')
        for name in ('.agents', '.claude', '.codex'):
            (ws / 'sample-shop' / name).mkdir(parents=True)
        (ws / 'sample-shop/.mcp.json').write_text('{}\n')
        (ws / 'sample-shop/AGENTS.md').write_text('# Contract\n')
        checker = lint.Lint(home, ws, self.product)
        rule = next(r for r in checker.rules if r['kind'] == 'allowed_top')
        checker.allowed_top(rule)
        self.assertEqual(checker.findings, [])

    def test_production_all_rules_exclude_forbidden_payloads(self):
        (self.ws/'sample-shop').mkdir()
        (self.ws/'sample-shop/AGENTS.md').write_text('# Contract\n')
        checker = lint.Lint(self.home, self.ws, self.product)
        # Upkeep checks inspect path metadata and history presence, not payloads.
        rules = [row for row in checker.rules if not row['id'].startswith('UPKEEP')]
        paths = [self.home / rel for rel in (
            '.git/a.md', 'node_modules/a.md', 'sources/a.md', 'history/a.md',
            'archive/a.md', 'backups/a.md', 'raw/a.md', 'skillwright/skill-releases/r1/a.md',
            'skills/installed/a.md', 'skillwright/skill-state/skill-data/vendor/a.md',
            'tools/cli/vendor/a.md', 'modules/x/tools/mcp/vendor/a.md',
            'apps/example/.wrangler-dry-run/README.md', 'apps/example/dist/README.md')]
        paths += [self.ws / 'sample-shop' / rel for rel in ('src/a.md', 'history/a.md',
                   'tools/cli/vendor/a.md', 'skills/installed/a.md', 'node_modules/a.md')]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'\xff')
            for rule in rules:
                # L09 inspects immediate tool metadata; inventory still excludes its payloads.
                if rule['kind'] == 'tool_inventory' and '/tools/' in str(path):
                    continue
                self.assertTrue(checker.excluded_by_scope(path, rule['scope']), (path, rule))
                self.assertFalse(checker.matches(path, rule['scope']), (path, rule))
        checker.inventory(rules)
        self.assertFalse(set(paths) & set(checker.files))
        self.assertFalse(any(checker.excluded_by_scope(p, r['scope'])
                             for p in checker.dirs for r in rules))

    def test_production_tool_page_beside_vendor_is_in_scope(self):
        checker = lint.Lint(self.home, self.ws, self.product)
        rule = next(r for r in checker.rules if r['kind'] == 'frontmatter')
        self.assertTrue(checker.matches(self.home / 'tools/cli/vendor.md', rule['scope']))
        self.assertFalse(checker.matches(self.home / 'tools/cli/vendor/README.md', rule['scope']))

    def test_production_tool_catalog_is_not_a_tool_page(self):
        checker = lint.Lint(self.home, self.ws, self.product)
        self.assertEqual(checker.bindings(self.home / 'tools/cli/index.md'), [])
        self.assertEqual(checker.bindings(self.home / 'tools/cli/bin-inventory.md'), [])
        self.assertEqual(checker.bindings(self.home / 'tools/cli/mattpocock-skills.md'), [])
        bindings = checker.bindings(self.home / 'tools/cli/README.md')
        self.assertEqual([r['spec'] for r in bindings], ['v3/top-pages/spec-README.tsv'])

    def test_database_scope_selects_system_only(self):
        self.sql('UPDATE tasks SET title=NULL', self.ws / 'shop')
        self.table('rules', ['id', 'words', 'kind', 'scope', 'level'],
                   [['DB1', 'System only.', 'database', 'system:data.db', 'error']])
        self.assertEqual(self.run_lint('DB1'), [])

    def test_required_pages_scope_selects_system_only(self):
        (self.ws / 'shop/STATE.md').unlink()
        self.table('rules', ['id', 'words', 'kind', 'scope', 'level'],
                   [['TOP1', 'System only.', 'required_pages', 'system:*.md', 'error']])
        self.assertEqual(self.run_lint('TOP1'), [])

    def test_allowed_top_scope_selects_system_only(self):
        (self.ws / 'shop/extra.txt').write_text('Extra fixture.')
        self.table('rules', ['id', 'words', 'kind', 'scope', 'level'],
                   [['TOP1', 'System only.', 'allowed_top', 'system:**', 'error']])
        self.assertEqual(self.run_lint('TOP1'), [])

    def test_scope_excludes_empty_directory_without_read(self):
        (self.home / 'excluded').mkdir()
        self.table('rules', ['id', 'words', 'kind', 'scope', 'level'],
                   [['E1', 'Fixture scope.', 'empty_folder', '*:**;!system:excluded/', 'error']])
        from unittest.mock import patch
        original = Path.iterdir
        def guarded(path):
            if path == self.home / 'excluded':
                raise AssertionError('Excluded directory was read.')
            return original(path)
        with patch.object(Path, 'iterdir', guarded):
            self.assertEqual(self.run_lint('E1'), [])

    def test_link_anchor_does_not_open_excluded_payload(self):
        target = self.home / 'history/old.md'
        target.parent.mkdir(); target.write_bytes(b'\xff')
        self.replace('(STATE.md)', '(history/old.md#old)')
        self.table('rules', ['id', 'words', 'kind', 'scope', 'level'],
                   [['LINK1', 'Fixture scope.', 'links', '*:**;!*:**/history/', 'error']])
        self.assertEqual(self.run_lint('LINK1'), [])

    def test_selected_rule_scope_controls_inventory(self):
        excluded = self.home / 'excluded/a.md'
        excluded.parent.mkdir(); excluded.write_bytes(b'\xff')
        with (self.policy / 'rules.tsv').open('a') as f:
            f.write('NARROW\tOne new policy row.\tfrontmatter\tsystem:PAGE.md;!system:excluded/\terror\n')
        self.assertEqual(self.run_lint('NARROW'), [])

    def test_bad_exclusion_scope_is_configuration_error(self):
        with (self.policy / 'rules.tsv').open('a') as f:
            f.write('BAD\tBad exclusion.\tfrontmatter\tpages;!wrong:**\terror\n')
        with self.assertRaises(ValueError):
            self.run_lint()


    def test_named_sample_project_required_page_exception(self):
        (self.ws / 'sample-project').mkdir()
        (self.ws / 'sample-project/AGENTS.md').write_text('# Labeled workspace contract\n')
        self.table('workspaces', ['id', 'kind', 'source'], [['shop', 'workspace', 'Fixture.'], ['sample-project', 'workspace', 'Move-only ruling.']])
        self.table('required-pages', ['scope', 'path', 'except_workspaces'], [['system', 'PAGE.md', ''], ['workspace', 'STATE.md', 'sample-project'], ['workspace', 'index.md', 'sample-project'], ['workspace', 'RESOLVER.md', 'sample-project']])
        checker = lint.Lint(self.home, self.ws, self.policy)
        checker.required_pages({'id': 'L07', 'level': 'error', 'scope': 'all'})
        self.assertFalse(any('/sample-project/' in r['path'] for r in checker.findings))
        self.assertTrue(any('/shop/index.md' in r['path'] for r in checker.findings))

    def test_first_line_built_marker_preserves_metadata(self):
        page = lint.Page('<!-- Built by workspace_reports.py. Do not edit. -->\n---\ntype: log\nworkspace: shop\ntimestamp: 2026-10-14T00:00:00Z\n---\n# Log: shop\n')
        self.assertEqual(page.fields['type'], 'log')
        self.assertEqual(page.fields['workspace'], 'shop')
        self.assertEqual(page.headings[0][1], 'Log: shop')

    def test_source_todo_status_is_not_placeholder(self):
        checker = lint.Lint(self.home, self.ws, self.policy)
        checker.specs['page.tsv'].append({'rule': 'forbidden_text', 'value': 'TODO|TBD'})
        target = self.home / 'PAGE.md'
        checker.cache[target] = lint.Page(target.read_text() + '\nA task has status todo.\n')
        checker.page_spec({'id': 'L01', 'level': 'error'}, target)
        self.assertEqual(checker.findings, [])
        checker.cache[target] = lint.Page(target.read_text() + '\nTODO\n')
        checker.page_spec({'id': 'L01', 'level': 'error'}, target)
        self.assertTrue(any('Forbidden text' in r['what'] for r in checker.findings))


if __name__ == '__main__':
    unittest.main()
