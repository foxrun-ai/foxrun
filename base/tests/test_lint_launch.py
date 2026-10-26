"""Approved page examples and launch upkeep regressions."""
import csv
import importlib.util
from pathlib import Path
import subprocess
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from base.tests.support import shipped_paths

SOURCE = Path(__file__).resolve().parents[1] / 'lint.py'
spec = importlib.util.spec_from_file_location('launch_lint', SOURCE)
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)
POLICY = SOURCE.parents[1] / 'config/lint'


def rendered_policy(folder, workspace='sample-shop'):
    """Copy shipped policy and use fixture settings, not a person's local settings."""
    target = Path(folder) / 'product-policy'
    target.mkdir()
    root = SOURCE.parents[1]
    for path in shipped_paths(root):
        if path.is_file() and path.is_relative_to(root / 'config/lint'):
            output = target / path.relative_to(root / 'config/lint')
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output)
    # T742: local lint settings belong to the person; these settings belong to this fixture.
    (target / 'workspaces.tsv').write_text('id\tkind\tsource\n' + workspace + '\tworkspace\tFixture.\n')
    allowed = [('system', 'VERSION', 'file'), ('system', 'sources', 'dir'),
               ('portfolio', 'atlas', 'dir'), ('portfolio', workspace, 'dir'),
               ('workspace', '.agents', 'dir'), ('workspace', '.claude', 'dir'),
               ('workspace', '.codex', 'dir'), ('workspace', '.mcp.json', 'file')]
    allowed += [('atlas', name, 'dir') for name in
                ('comparisons', 'concepts', 'entities', 'queries', 'raw', 'history')]
    with (target / 'allowed-top.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(('scope', 'name', 'kind', 'source'))
        writer.writerows((*row, 'Fixture.') for row in allowed)
    (target / 'business-names.tsv').write_text('name\tsource\n' + workspace + '\tFixture.\n')
    (target / 'db.tsv').write_text('home\tpath\ttable\tcolumn\tformat\tdatabase_home\tworkspace_column\tworkspace_value\tsource\n')
    (target / 'required-pages.tsv').write_text('scope\tpath\texcept_workspaces\nworkspace\thistory/LOG.md\t\n')
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
    # The contract fixture enters UPKEEP03; provide its real retired-name input.
    (target/'stale-names.tsv').write_text('literal\treplacement\tsource\nCONCEPTS.md\tGLOSSARY.md\tFixture.\n')
    return target
# Approved examples are frozen below by the proposal builder.
APPROVED = {'CLAUDE.md': '---\ntype: agents\nworkspace: system\ntimestamp: 2026-10-13T18:47:06-04:00\n---\n@AGENTS.md\n', 'README.md': '---\ntype: doc\nworkspace: system\ntimestamp: 2026-10-13T17:12:07-04:00\n---\n# Foxrun\n\nFoxrun is a framework for agents and your work. The system home holds shared code, settings, and the database. The portfolio holds your workspaces.\n\n| Field | Value |\n|---|---|\n| Version | 0.1.0 |\n| Needs | Python 3.9 or newer. The product uses the Python standard library. |\n| Runtimes | Claude and Codex on day one |\n\n## Start here\n\n| To | Open |\n|---|---|\n| Install Foxrun | [`INSTALL.md`](INSTALL.md) |\n| Learn the daily commands | [`GUIDE.md`](GUIDE.md) |\n| See what each file does | [`DOCUMENTATION.md`](DOCUMENTATION.md) |\n| Read the rules every agent follows | [`AGENTS.md`](AGENTS.md) |\n| See what changed in each version | [`CHANGELOG.md`](CHANGELOG.md) |\n\n## The two folders\n\n```text\n<home>/               the system home: code, settings, the database\n├─ AGENTS.md\n├─ config/\n└─ data.db\n<portfolio>/          your workspaces and your library\n├─ atlas/\n└─ <workspace>/\n```\n\n## The three commands\n\n```sh\npython3 install.py --home <dir> --portfolio <dir>\npython3 <home>/foxrun.py doctor\npython3 <home>/foxrun.py start --workspace <name>\n```\n\n| Command | What it does |\n|---|---|\n| `install.py` | Installs Foxrun into two empty folders. It asks your name, workspace name, and runtime. |\n| `doctor` | Checks shipped hashes, generated paths, database integrity, and person configuration. |\n| `start` | Prints your workspace state, its open tasks, and the three files to read first. |\n', 'portfolio/sample-shop/tools/CAPABILITIES.md': '---\ntype: index\nworkspace: sample-shop\ntimestamp: 2026-10-13T18:19:42-04:00\n---\n# Capabilities: sample-shop\n\nEvery tool and skill this workspace uses, by use. A script makes this page. Edit a tool page, a skill, or a seat file; then run the script.\n\n## Contents\n\n- **By use**\n  - [Account Health](#account-health) · 1 skill\n  - [Comms](#comms) · 4 tools\n  - [Creator & content](#creator--content) · 6 tools\n  - [Data & docs](#data--docs) · 3 tools\n  - [Dev & repos](#dev--repos) · 1 tool\n  - [Gmail](#gmail) · 1 tool\n  - [Inventory](#inventory) · 1 skill\n  - [Listings & Content](#listings--content) · 3 skills\n  - [Sample Shop data](#sample-shop-data) · 2 tools\n  - [PPC & Ads](#ppc--ads) · 3 skills\n  - [Profit & Finance](#profit--finance) · 3 skills\n  - [Reporting](#reporting) · 4 skills\n  - [Search & SEO](#search--seo) · 2 skills\n  - [Secrets](#secrets) · 1 tool\n  - [Sessions](#sessions) · 1 tool\n  - [Tickets](#tickets) · 1 tool\n  - [Vault & search](#vault--search) · 2 tools\n- **Not placed yet**\n  - [Tools with no use](#tools-with-no-use) · 6\n  - [Skills with no use](#skills-with-no-use) · 28\n  - [Tools with no page](#tools-with-no-page) · 21\n  - [Tool pages not on the template](#tool-pages-not-on-the-template) · 7\n  - [Skills a seat loads, not on disk](#skills-a-seat-loads-not-on-disk) · 1\n\n```\nUSES     17\nTOOLS    28   with a use: 22\nSKILLS   45   with a use: 17\nMADE     2026-10-13 18:19\n```\n\n**How to read a row.** A tool row says what the tool is. A skill row says what the skill does, and the tools it needs. A skill does not work when a tool it needs is not set up. Each name opens its own page.\n\n## Account Health\n\n| Skill | What it does | Tools it needs |\n|---|---|---|\n| [`daily-account-health-check`](../skills/daily-account-health-check/SKILL.md) | Run a daily Amazon account-health check: Account Health Rating (AHR), order-defect rate, late-shipment rate, … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n\n## Comms\n\n| Tool | Kind | What it is |\n|---|---|---|\n| imsg | cli | iMessage read/send; timed-out sends may still deliver — re-read the thread before retrying. |\n| telegram-files | cli | pull files out of Telegram chats. |\n| telegram-search | cli | search Telegram history. |\n| [tgcli](../../../.foxrun/tools/cli/tgcli.md) | cli | Telegram control (topics, groups, membership) via the hardened launcher. |\n\n## Creator & content\n\n| Tool | Kind | What it is |\n|---|---|---|\n| ffmpeg | cli | cut, convert, and inspect media. |\n| ig-read | cli | Instagram reads (profiles, DMs surface). |\n| link-read | cli | fetch and read a URL cleanly. |\n| safe-tweet-read | cli | X/Twitter reads without auth risk. |\n| [telecrawl](../../../.foxrun/tools/cli/telecrawl.md) | cli | Telegram-channel crawling for research. |\n| yt-dlp | cli | pull video/audio from platforms. |\n\n## Data & docs\n\n| Tool | Kind | What it is |\n|---|---|---|\n| pandoc | cli | document conversion (markdown → PDF/DOCX and back). |\n| poppler | cli | PDF text/image extraction (`pdftotext`); pairs with pandoc. |\n| sqlite-utils | cli | query and reshape SQLite/CSV data. |\n\n## Dev & repos\n\n| Tool | Kind | What it is |\n|---|---|---|\n| gh | cli | GitHub PRs, issues, API. |\n\n## Gmail\n\n| Tool | Kind | What it is |\n|---|---|---|\n| gogcli | cli | agent-driven Gmail; always name the account (`sample-shop` = person@example.invalid); default bounded read-only flags; … |\n\n## Inventory\n\n| Skill | What it does | Tools it needs |\n|---|---|---|\n| [`restock-priority-alert`](../skills/restock-priority-alert/SKILL.md) | Rank the Amazon FBA SKUs about to stock out by urgency - days of supply vs sales velocity, inbound-aware - with how … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n\n## Listings & Content\n\n| Skill | What it does | Tools it needs |\n|---|---|---|\n| [`amazon-listing-optimizer`](../skills/amazon-listing-optimizer/SKILL.md) | Optimize an Amazon listing from your own live data, tuned for 2026 Amazon (the 75-character title cap, the COSMO intent … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`buy-box-loss-root-cause`](../skills/buy-box-loss-root-cause/SKILL.md) | Find the Amazon SKUs losing the Buy Box (Featured Offer) and the most likely reason - price vs the featured offer, out … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`suppressed-inactive-listings-check`](../skills/suppressed-inactive-listings-check/SKILL.md) | Scan the whole catalog for listings that are silently not selling - suppressed, inactive, stranded (stock on hand but … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n\n## Sample Shop data\n\n| Tool | Kind | What it is |\n|---|---|---|\n| [dropbox-ugc](cli/dropbox-ugc.md) | cli | creator UGC cataloging into Dropbox. |\n| [sample-shop-shopify-export](cli/sample-shop-shopify-export.md) | cli | Shopify catalog/inventory exports. |\n\n## PPC & Ads\n\n| Skill | What it does | Tools it needs |\n|---|---|---|\n| [`ppc-bid-optimizer-apply`](../skills/ppc-bid-optimizer-apply/SKILL.md) | Recompute Sponsored Products keyword bids toward a target ACoS and apply them through DataDoe Actions - always a dryRun … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`ppc-negative-keyword-applier`](../skills/ppc-negative-keyword-applier/SKILL.md) | Find the exact Sponsored Products search terms burning budget with no sales, then add them as negative keywords through … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`ppc-wasted-spend-watchdog`](../skills/ppc-wasted-spend-watchdog/SKILL.md) | Find the exact Amazon Sponsored Products search terms wasting your ad budget - dead spend (clicks but no orders) and … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n\n## Profit & Finance\n\n| Skill | What it does | Tools it needs |\n|---|---|---|\n| [`net-profit-pl-analyzer`](../skills/net-profit-pl-analyzer/SKILL.md) | Break down your true Amazon net profit by SKU for any period - after Amazon fees, FBA, COGS and ad spend, not just … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`return-refund-analyzer`](../skills/return-refund-analyzer/SKILL.md) | Find the SKUs bleeding the most margin to returns, why they come back (the real return reasons, bucketed into product / … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`weekly-business-review`](../skills/weekly-business-review/SKILL.md) | Generate a weekly Amazon BUSINESS review - profit, margin, ad efficiency (TACoS) and inventory - comparing this week to … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n\n## Reporting\n\n| Skill | What it does | Tools it needs |\n|---|---|---|\n| [`create-amazon-reconciliation-dashboard`](../skills/create-amazon-reconciliation-dashboard/SKILL.md) | Build a self-contained, interactive Amazon Reconciliation Dashboard powered by the DataDoe MCP tools. | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`create-orders-manager`](../skills/create-orders-manager/SKILL.md) | Build a single-page Orders Manager application powered by the DataDoe REST API. | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`sales-movers-scanner`](../skills/sales-movers-scanner/SKILL.md) | Scan the whole catalog for the SKUs that moved the most this period - up and down - and decompose each move into its … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`weekly-sales-briefing`](../skills/weekly-sales-briefing/SKILL.md) | Generate a structured weekly Amazon sales briefing as an interactive HTML card. | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n\n## Search & SEO\n\n| Skill | What it does | Tools it needs |\n|---|---|---|\n| [`amazon-asin-search-auditor`](../skills/amazon-asin-search-auditor/SKILL.md) | Audit an Amazon seller\'s organic and sponsored search visibility by combining DataDoe search-term data, live Amazon … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n| [`keyword-rank-sqp-tracker`](../skills/keyword-rank-sqp-tracker/SKILL.md) | Track your money keywords week over week - organic rank and, more importantly, your share of the query (impressions, … | [DataDoe](mcp/datadoe.md): Amazon data and controlled action layer for Sample Shop. |\n\n## Secrets\n\n| Tool | Kind | What it is |\n|---|---|---|\n| [agent-secret-read](../../../.foxrun/tools/cli/agent-secret-read.md) | cli | the only secret path: `agent-secret-read \'op://Foxrun/Item/field\'`; never raw `op read`, never print values. |\n\n## Sessions\n\n| Tool | Kind | What it is |\n|---|---|---|\n| herdr | cli | spawn/steer agent sessions (Person\'s pick; use deliberately — orchestration consolidation pending, AOS-217). |\n\n## Tickets\n\n| Tool | Kind | What it is |\n|---|---|---|\n| linear-pp-cli | cli | the only Linear path. |\n\n## Vault & search\n\n| Tool | Kind | What it is |\n|---|---|---|\n| ob | cli | Obsidian services (open, links, Bases) when a note-level action needs the app. |\n| qmd | mcp | QMD rides as an MCP, not a CLI — "search my markdown anywhere, repos included." It is the search default. |\n\n## Not placed yet\n\nEach name here is in use and has a gap. Give it a use, a page, or a folder; then it leaves this list.\n\n### Tools with no use\n\n```\nNAMES  (6)\n   agentcentral  agentcentral-de  agentcentral-nl  context7  datadoe  shipbob\n```\n\n### Skills with no use\n\n```\nNAMES  (28)\n   amazon-eu-fba  amazon-image-classifier  amazon-listing-copy\n   create-creator-page  creator-collabs  creator-comms  creator-cycle-record\n   creator-drafting  decision-making  dropbox-creator-file-request\n   find-creator-email  instagram-read  last30days  log  sample-shop\n   sample-shop-email  sample-shop-outreach  sample-shop-payment\n   sample-shop-shopify-data  prompt-god  shipbob-order  shopify-to-amazon\n   store-resolver  telegram-files  tldr  to-tickets  wiki-upkeep  x-research\n```\n\n### Tools with no page\n\n```\nNAMES  (21)\n   agentcentral-de  agentcentral-nl  context7  ffmpeg  gh  gogcli  herdr\n   ig-read  imsg  linear-pp-cli  link-read  ob  pandoc  poppler  qmd\n   safe-tweet-read  shipbob  sqlite-utils  telegram-files  telegram-search\n   yt-dlp\n```\n\n### Tool pages not on the template\n\n```\nNAMES  (7)\n   agent-secret-read  agentcentral  datadoe  dropbox-ugc\n   sample-shop-shopify-export  telecrawl  tgcli\n```\n\n### Skills a seat loads, not on disk\n\n```\nNAMES  (1)\n   telegram-send\n```\n\n3 skills are here because their name or their line names this workspace.\n'}


class LaunchLintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'system'
        self.portfolio = Path(self.temp.name) / 'portfolio'
        self.home.mkdir()
        self.portfolio.mkdir()
        (self.portfolio/'sample-shop').mkdir()
        (self.portfolio/'sample-shop/AGENTS.md').write_text('# Labeled workspace contract\n')
        self.policy = rendered_policy(self.temp.name)

    def checker(self):
        return lint.Lint(self.home, self.portfolio, self.policy)

    def test_page_specs_state_rulings_plainly(self):
        import re
        for spec_file in sorted((POLICY / 'specs').rglob('*.tsv')):
            text = spec_file.read_text(encoding='utf-8')
            self.assertNotRegex(text, r'\bg-[a-z]+-[a-z]+-[a-z]', spec_file)
        made_by = next(line for line in (POLICY / 'specs/v3/top-pages/spec-SCHEMA.tsv').read_text().splitlines()
                       if line.startswith('made_by\t'))
        self.assertIn('a ruling says it is built from rows', made_by)

    def test_documentation_names_only_shipped_scripts(self):
        import re
        root = SOURCE.parents[1]
        with (root / 'product-manifest.tsv').open(encoding='utf-8') as stream:
            shipped = {line.split('\t', 1)[0] for line in stream if '\t' in line}
        text = (root / 'DOCUMENTATION.md').read_text(encoding='utf-8')
        missing = sorted({name for part in re.findall(r'(?:script|skill)s?: ([^;)]*)', text)
                          for name in re.findall(r'`([^`*<]+\.(?:py|sh|mjs))`', part)
                          if not any(path == name or path.endswith('/' + name) for path in shipped)})
        self.assertEqual([], missing)

    def test_approved_examples(self):
        for relative, text in APPROVED.items():
            checker = self.checker()
            target = self.portfolio / relative[10:] if relative.startswith('portfolio/') else self.home / relative
            checker.cache[target] = lint.Page(text)
            checker.page_spec({'id': 'L01', 'level': 'error'}, target)
            self.assertEqual(checker.findings, [], relative)

    def test_required_title_still_rejected(self):
        checker = self.checker()
        target = self.home / 'README.md'
        checker.cache[target] = lint.Page(APPROVED['README.md'].replace('# Foxrun\n', ''))
        checker.page_spec({'id': 'L01', 'level': 'error'}, target)
        self.assertTrue(any('one title' in row['what'] for row in checker.findings))

    def test_command_columns_still_rejected(self):
        checker = self.checker()
        target = self.home / 'README.md'
        checker.cache[target] = lint.Page(APPROVED['README.md'].replace('| Command | What it does |', '| Wrong | Columns |'))
        checker.page_spec({'id': 'L01', 'level': 'error'}, target)
        self.assertTrue(any('Table columns differ' in row['what'] for row in checker.findings))

    def test_every_workspace_name_fails_on_system_page(self):
        for row in self.checker().data['workspaces']:
            if row['kind'] != 'workspace':
                continue
            for name in (row['id'], row['id'].replace('-', ' ').upper()):
                checker = self.checker()
                target = self.home / 'tools/cli/example.md'
                checker.cache[target] = lint.Page('# Example\n\nTools for ' + name + '.\n')
                checker.no_business_name({'id': 'L08', 'level': 'error'}, target)
                self.assertTrue(checker.findings, name)

    def test_scratch_folder_is_found_but_source_copy_is_excluded(self):
        (self.portfolio / 'sample-shop/scratch').mkdir(parents=True)
        (self.portfolio / 'sample-shop/src/scratch').mkdir(parents=True)
        findings = self.checker().run('UPKEEP01')
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]['path'].endswith('sample-shop/scratch'))
        self.assertEqual(findings[0]['rule_id'],'UPKEEP01')

    def test_raw_type_child_folder_is_found(self):
        (self.portfolio / 'sample-shop/wiki/raw/articles/nested').mkdir(parents=True)
        findings = self.checker().run('UPKEEP02')
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]['path'].endswith('wiki/raw/articles/nested'))
        self.assertEqual(findings[0]['rule_id'],'UPKEEP02')

    def test_stale_contract_is_found(self):
        (self.home / 'AGENTS.md').write_text('# Rules\nRead CONCEPTS.md.\n')
        findings=self.checker().run('UPKEEP03')
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['what'],'Contract names a retired place: CONCEPTS.md')
        (self.home/'AGENTS.md').write_text('# Rules\nRead GLOSSARY.md.\n')
        self.assertEqual(self.checker().run('UPKEEP03'),[])

    def test_tracked_cache_uses_git_index_not_disk_presence(self):
        (self.home / '.git').mkdir()
        result = subprocess.CompletedProcess([], 0, b'base/__pycache__/x.pyc\0base/x.py\0', b'')
        with patch.object(lint.subprocess, 'run', return_value=result):
            findings = self.checker().run('UPKEEP04')
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]['path'].endswith('x.pyc'))

    def test_missing_history_is_found(self):
        (self.portfolio / 'sample-shop').mkdir(exist_ok=True)
        self.assertTrue(self.checker().run('UPKEEP05'))


class SharedDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'system'
        self.portfolio = self.root / 'portfolio'
        self.home.mkdir()
        self.policy = self.root / 'policy'
        shutil.copytree(POLICY, self.policy)
        for name in ('sample-home', 'sample-group', 'sample-shop'):
            (self.portfolio / name).mkdir(parents=True)
            (self.portfolio / name / 'AGENTS.md').write_text('# Contract\n')
        self.table('workspaces', ['id','kind','source'],
                   [[name,'workspace','Synthetic resolver.'] for name in ('sample-home','sample-group','sample-shop')])
        fields = ['home','path','table','column','format','database_home','workspace_column','workspace_value','source']
        rows = []
        for owner in ('system','sample-home','sample-group','sample-shop'):
            shared = owner in ('sample-home','sample-group')
            # The system fixture checks identity; workspace fixtures check their timestamps too.
            for column, format_ in [('id','text')] + ([] if owner=='system' else [('created_on','iso8601')]):
                rows.append([owner,'data.db','tasks',column,format_,'workspace' if owner=='sample-shop' else 'system',
                             'workspace' if shared else '',owner if shared else '', 'Synthetic resolver.'])
        self.table('db',fields,rows)
        self.table('db-reasons',['home','table','row_id','column','case','reason'],[])
        con=sqlite3.connect(str(self.home/'data.db'))
        con.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY,status TEXT,workspace TEXT,created_on TEXT)')
        con.executemany('INSERT INTO tasks VALUES (?,?,?,?)',[
            ('L1','todo','sample-home','2026-10-14T12:00:00-04:00'),
            ('L2','done','sample-home','2026-10-14T12:00:00-04:00'),
            ('N1','todo','sample-group','bad-time'),
            ('O1','todo','other-workspace',None)])
        con.execute("CREATE VIEW open_tasks AS SELECT * FROM tasks WHERE status != 'done'")
        con.commit();con.close()
        con=sqlite3.connect(str(self.portfolio/'sample-shop/data.db'))
        con.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY,status TEXT,created_on TEXT)')
        con.execute('INSERT INTO tasks VALUES (?,?,?)',('P1','todo','2026-10-14T12:00:00-04:00'))
        con.commit();con.close()

    def table(self,name,fields,rows):
        with (self.policy/(name+'.tsv')).open('w',newline='') as stream:
            writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
            writer.writerow(fields);writer.writerows(rows)

    def checker(self):
        return lint.Lint(self.home,self.portfolio,self.policy)

    def state(self,name,count):
        path=self.portfolio/name/'STATE.md'
        path.write_text('# State\n\n```\nOPEN TASKS  '+str(count)+'\n```\n')
        return path

    def test_shared_routes_need_no_local_databases(self):
        checker=self.checker()
        findings=checker.run('L06')
        self.assertFalse(any('absent, protected' in row['what'] for row in findings))
        self.assertTrue(any('N1' in row['what'] for row in findings))
        self.assertFalse(any('O1' in row['what'] for row in findings))
        self.assertFalse((self.portfolio/'sample-home/data.db').exists())

    def test_shared_state_uses_workspace_filtered_view(self):
        checker=self.checker()
        checker.state_tracker({'id':'L04','level':'error'},self.state('sample-home',1))
        checker.state_tracker({'id':'L04','level':'error'},self.state('sample-group',1))
        self.assertEqual(checker.findings,[])

    def test_shared_state_wrong_count_is_reported(self):
        checker=self.checker()
        checker.state_tracker({'id':'L04','level':'error'},self.state('sample-home',3))
        self.assertEqual(len(checker.findings),1)
        self.assertIn('1 open tasks',checker.findings[0]['what'])

    def test_shared_state_counts_only_declared_tracker_table(self):
        con=sqlite3.connect(str(self.home/'data.db'))
        con.execute('CREATE TABLE business_tasks (id TEXT,status TEXT)')
        con.execute("INSERT INTO business_tasks VALUES ('B1','todo')")
        con.commit();con.close()
        checker=self.checker()
        checker.state_tracker({'id':'L04','level':'error'},self.state('sample-home',1))
        self.assertEqual(checker.findings,[])

    def test_unfiltered_view_does_not_override_shared_scope(self):
        con=sqlite3.connect(str(self.home/'data.db'))
        con.execute('DROP VIEW open_tasks')
        con.execute("CREATE VIEW open_tasks AS SELECT id,status FROM tasks WHERE status != 'done'")
        con.close()
        checker=self.checker()
        checker.state_tracker({'id':'L04','level':'error'},self.state('sample-home',1))
        self.assertEqual(checker.findings,[])

    def test_local_sample_shop_tracker_is_preserved(self):
        checker=self.checker()
        checker.state_tracker({'id':'L04','level':'error'},self.state('sample-shop',1))
        self.assertEqual(checker.findings,[])
        self.assertEqual(checker.database_routes('sample-shop')[0],self.portfolio/'sample-shop/data.db')

    def test_shared_scope_empty_is_not_hidden_by_other_rows(self):
        con=sqlite3.connect(str(self.home/'data.db'))
        con.execute("DELETE FROM tasks WHERE workspace='sample-home'")
        con.commit();con.close()
        findings=self.checker().run('L06')
        self.assertTrue(any('empty' in row['what'] and 'sample-home' in row['what'] for row in findings))

    def test_null_reason_uses_workspace_owner(self):
        con=sqlite3.connect(str(self.home/'data.db'))
        con.execute("UPDATE tasks SET created_on=NULL WHERE id='L1'")
        con.commit();con.close()
        self.table('db-reasons',['home','table','row_id','column','case','reason'],[
            ['system','tasks','L1','created_on','null','Wrong owner cannot excuse a workspace fact.']])
        self.assertTrue(any('L1' in row['what'] for row in self.checker().run('L06')))
        self.table('db-reasons',['home','table','row_id','column','case','reason'],[
            ['sample-home','tasks','L1','created_on','null','Fixture time is unknown.']])
        self.assertFalse(any('L1' in row['what'] for row in self.checker().run('L06')))

    def test_missing_workspace_column_fails_closed(self):
        con=sqlite3.connect(str(self.home/'data.db'))
        con.execute('DROP VIEW open_tasks')
        con.execute('ALTER TABLE tasks RENAME COLUMN workspace TO old_scope')
        con.commit();con.close()
        checker=self.checker()
        findings=checker.run('L06')
        self.assertTrue(any('lacks workspace filter column' in row['what'] for row in findings))
        with self.assertRaisesRegex(ValueError,'lacks workspace filter column'):
            checker.state_tracker({'id':'L04','level':'error'},self.state('sample-home',1))

    def test_conflicting_route_is_refused(self):
        checker=self.checker()
        duplicate=dict(next(row for row in checker.data['db'] if row['home']=='sample-home'))
        duplicate['path']='other.db'
        checker.data['db'].append(duplicate)
        with self.assertRaisesRegex(ValueError,'routing is missing or conflicting'):
            checker.database_routes('sample-home')

    def test_shared_workspace_value_is_parameterized(self):
        checker=self.checker()
        for row in checker.data['db']:
            if row['home']=='sample-home': row['workspace_value']="sample-home' OR 1=1 --"
        findings=checker.run('L06')
        self.assertTrue(any('empty' in row['what'] and 'sample-home' in row['what'] for row in findings))


if __name__ == '__main__':
    unittest.main()
