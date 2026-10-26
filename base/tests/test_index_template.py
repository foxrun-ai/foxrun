"""T697: base/templates/index.md is the shape of index.md, the builder fills it, and a check proves they match."""
import csv
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import page_indexes  # noqa: E402

SPEC = BASE.parent / 'config/lint/specs/v3/top-pages/spec-index.tsv'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def spec():
    rules = {}
    with SPEC.open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            rules.setdefault(row['rule'], []).append(row['value'])
    return rules


class IndexTemplate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.root = root
        self.portfolio, self.system = root / 'portfolio', root / 'system'
        write(self.system / 'RESOLVER.md', '| Settings | `<workspace>/config/` |\n')
        shop = self.portfolio / 'shop'
        write(shop / 'AGENTS.md', '# Shop\n\nThe contract for the shop.\n')
        write(shop / 'README.md', '# Shop\n\nPurpose: The contract for the shop.\n')
        write(shop / 'config/README.md', '# Config\n\nPurpose: Settings\n')
        write(shop / 'STATE.md', '# State: shop\n\nAn agent reads this page at the start.\n')
        write(shop / 'notes.txt', 'loose file\n')
        write(shop / 'EXTRA.md', '# Extra\n')
        write(shop / 'config/topics.yaml', '{"topics": []}\n')
        write(shop / 'team/TEAM.md', '# Team\n')
        write(self.portfolio / 'AGENTS.md', '# Portfolio\n\nThe front door.\n')
        write(self.portfolio / 'loose/readme.txt', 'no contract here\n')

    def build(self):
        outputs, _ = page_indexes.build(self.portfolio, self.system, '2026-10-18', 'index')
        return outputs

    def test_the_template_is_no_draft(self):
        text = page_indexes.template()
        for words in ('draft', 'template only', 'generation_status', '[['):
            self.assertNotIn(words, text)
        self.assertTrue(text.startswith('---\ntype: index\nworkspace: {{workspace}}\ntimestamp: {{timestamp}}\n---\n'))

    def test_the_template_has_the_reviewed_shape(self):
        rules, text = spec(), page_indexes.template()
        self.assertEqual(re.findall(r'^## (.+)$', text, re.M), rules['heading_order'][0].split(' > '))
        self.assertIn('# Index: {{workspace}}\n', text)
        labels = re.findall(r'^([A-Z][A-Z ]+[A-Z])  ', text, re.M)
        self.assertEqual(labels, rules['count_block_labels'][0].split('|'))
        for columns in rules['table_columns']:
            heading, names = columns.split('=')
            self.assertIn('| ' + ' | '.join(names.split('|')) + ' |', text, heading)
        intro = rules['intro'][0]
        filled = page_indexes.fill(text, dict.fromkeys(page_indexes.SLOT.findall(text), [])
                                   | {'scope': 'this workspace', 'find': 'page', 'workspace': 'x', 'timestamp': 't',
                                      'pages_at_top': 0, 'folder_count': 0, 'file_count': 0, 'made': 'm'})
        self.assertIn('\n' + intro + '\n', filled)

    def test_every_built_page_has_the_template_shape(self):
        outputs = self.build()
        self.assertEqual(set(outputs), {self.portfolio / 'index.md', self.portfolio / 'shop/index.md'})
        for path, body in outputs.items():
            self.assertTrue(page_indexes.check_shape(body), path)
        shop = outputs[self.portfolio / 'shop/index.md']
        self.assertIn('\n## Extra at the top\n', shop)
        self.assertIn('| [config/](config) | Settings | 2 | — |', shop)
        top = outputs[self.portfolio / 'index.md']
        self.assertIn('# Index: portfolio\n', top)
        self.assertIn('Start here to find a workspace.', top)
        # shop/index.md is written by the same build, so it counts and is linked.
        self.assertIn('| [shop/](shop) | The contract for the shop. | 9 | [index.md](shop/index.md) |', top)
        self.assertIn('| [loose/](loose) | no purpose yet | 1 | — |', top)

    def test_a_page_without_extra_files_drops_the_extra_section(self):
        (self.portfolio / 'shop/notes.txt').unlink()
        (self.portfolio / 'shop/EXTRA.md').unlink()
        (self.portfolio / 'shop/README.md').unlink()
        body = self.build()[self.portfolio / 'shop/index.md']
        self.assertNotIn('Extra at the top', body)
        self.assertTrue(page_indexes.check_shape(body))
        self.assertTrue(body.endswith('```\n'))

    def test_another_shape_fails_the_check(self):
        body = self.build()[self.portfolio / 'shop/index.md']
        for changed in (body.replace('## Folders', '## Folder list'),
                        body.replace('## Tree', '## Database\n\n| Type | Name |\n|---|---|\n\n## Tree'),
                        body.replace('A script makes it', 'The Keeper builds it'),
                        body + 'one more line\n'):
            self.assertFalse(page_indexes.check_shape(changed))

    def test_check_names_a_stale_page_and_a_page_of_another_shape(self):
        command = [sys.executable, '-B', str(BASE / 'page_indexes.py'), '--portfolio', str(self.portfolio),
                   '--system-home', str(self.system), '--as-of', '2026-10-18', '--kind', 'index']
        self.assertEqual(subprocess.run(command, capture_output=True, text=True).returncode, 0)
        fresh = subprocess.run(command + ['--check'], capture_output=True, text=True)
        self.assertEqual(fresh.returncode, 0, fresh.stdout)
        page = self.portfolio / 'shop/index.md'
        page.write_text(page.read_text().replace('## Tree', '## Folder tree'))
        result = subprocess.run(command + ['--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report['shape'], [str(page)])
        self.assertEqual(report['stale'], [str(page)])


    def test_purpose_uses_readme_label_after_instructions_not_contract_opener(self):
        shop = self.portfolio / 'shop'
        write(shop / 'README.md', '# Shop\n\nRead ../AGENTS.md first.\n\n**Purpose:** Keeps the shop work.\n')
        page = self.build()[self.portfolio / 'index.md']
        self.assertIn('| [shop/](shop) | Keeps the shop work. |', page)
        self.assertNotIn('| The contract for the shop. |', page)
        self.assertNotIn('| Read ../AGENTS.md first. |', page)

    def test_readme_declares_its_purpose_in_prose_after_frontmatter_and_title(self):
        shop = self.portfolio / 'shop'
        write(shop / 'README.md', '---\ntype: doc\n---\n# Shop\n\nShop holds the business work.\n')
        self.assertEqual(page_indexes.declared_purpose(shop), 'Shop holds the business work.')
        write(shop / 'README.md', '# Shop\n\n```sh\nPurpose: This is only a code sample.\n```\n')
        self.assertEqual(page_indexes.declared_purpose(shop), 'no purpose yet')

    def test_documentation_folder_row_and_missing_purpose_report(self):
        shop = self.portfolio / 'shop'
        write(shop / 'DOCUMENTATION.md', '# Documentation\n\n| File | Description |\n|---|---|\n| `team/` | Holds the shop team. |\n')
        outputs = self.build()
        self.assertIn('| [team/](team) | Holds the shop team. |', outputs[shop / 'index.md'])
        self.assertEqual(page_indexes.no_purpose_folders(outputs), [str(self.portfolio / 'loose')])
        write(shop / 'README.md', '# Shop\n\nRead ../AGENTS.md first.\n')
        outputs = self.build()
        self.assertIn('| [shop/](shop) | no purpose yet |', outputs[self.portfolio / 'index.md'])
        self.assertEqual(page_indexes.no_purpose_folders(outputs),
                         [str(self.portfolio / 'loose'), str(shop)])

    def test_documentation_sections_and_readme_purpose_section(self):
        folder = self.portfolio / 'shop/team'
        write(folder / 'README.md', '# Team\n\n## Purpose\n\nKeeps team assignments.\n')
        self.assertEqual(page_indexes.declared_purpose(folder), 'Keeps team assignments.')
        (folder / 'README.md').unlink()
        write(folder.parent / 'DOCUMENTATION.md',
              '## '+str(folder.parent)+'\n| `team/` | Correct purpose. |\n'
              '## /some/other/workspace\n| `team/` | Wrong purpose. |\n')
        self.assertEqual(page_indexes.declared_purpose(folder), 'Correct purpose.')

    def test_add_archive_move_and_new_workspace_refresh_without_nightly(self):
        shop = self.portfolio / 'shop'
        page_indexes.refresh_indexes(self.portfolio, self.system, '2026-10-20')
        added = shop / 'added'
        write(added / 'README.md', '# Added\n\nPurpose: Holds added work.\n')
        page_indexes.refresh_indexes(self.portfolio, self.system, '2026-10-20')
        self.assertIn('| [added/](added) | Holds added work. |', (shop / 'index.md').read_text())
        archive = self.root / 'archive'
        archive.mkdir()
        added.rename(archive / 'added')
        page_indexes.refresh_indexes(self.portfolio, self.system, '2026-10-20')
        self.assertNotIn('added/', (shop / 'index.md').read_text())
        write(shop / 'moved/README.md', '# Moved\n\nPurpose: Holds moved work.\n')
        (shop / 'moved').rename(shop / 'renamed')
        write(self.portfolio / 'new/AGENTS.md', '# New\n')
        write(self.portfolio / 'new/README.md', '# New\n\nPurpose: Holds new work.\n')
        page_indexes.refresh_indexes(self.portfolio, self.system, '2026-10-20')
        self.assertIn('| [renamed/](renamed) | Holds moved work. |', (shop / 'index.md').read_text())
        self.assertNotIn('[moved/]', (shop / 'index.md').read_text())
        self.assertIn('| [new/](new) | Holds new work. |', (self.portfolio / 'index.md').read_text())
        self.assertTrue((self.portfolio / 'new/index.md').is_file())
        (self.portfolio / 'new').rename(archive / 'new')
        page_indexes.refresh_indexes(self.portfolio, self.system, '2026-10-20')
        self.assertNotIn('[new/]', (self.portfolio / 'index.md').read_text())
        self.assertEqual(page_indexes.refresh_indexes(self.portfolio, self.system, '2026-10-20')['changed'], 0)

    def test_index_write_refuses_linked_output_before_other_writes(self):
        shop = self.portfolio / 'shop'
        target = self.root / 'unchanged.md'
        write(target, 'unchanged')
        (shop / 'index.md').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'linked output refused'):
            page_indexes.refresh_indexes(self.portfolio, self.system, '2026-10-20')
        self.assertEqual(target.read_text(), 'unchanged')
        self.assertFalse((self.portfolio / 'index.md').exists())


    def test_shared_location_table_precedes_readme_and_excludes_system_rows(self):
        write(self.system / 'RESOLVER.md',
              '### Where Things Live\n\n'
              '| Thing | Home | Path | Writer or owner |\n|---|---|---|---|\n'
              '| Shared settings | System | `config/` | Architect |\n'
              '| Workspace settings | Portfolio | `<workspace>/config/` | Local contract |\n')
        body = self.build()[self.portfolio / 'shop/index.md']
        self.assertIn('| [config/](config) | Workspace settings |', body)
        self.assertNotIn('| Shared settings |', body)
        self.assertNotIn('| Settings |', body)
        # The words come from the table each time, not a folder-name map.
        write(self.system / 'RESOLVER.md', (self.system / 'RESOLVER.md').read_text()
              .replace('Workspace settings', 'Shared settings'))
        self.assertIn('| [config/](config) | Shared settings |',
                      self.build()[self.portfolio / 'shop/index.md'])

    def test_local_resolver_overrides_shared_table_with_exact_wording(self):
        shop = self.portfolio / 'shop'
        write(self.system / 'RESOLVER.md',
              '### Where Things Live\n| Thing | Home | Path | Writer or owner |\n|---|---|---|---|\n'
              '| Living notes | Portfolio | `<workspace>/notes/` | Note author |\n')
        write(shop / 'RESOLVER.md',
              '| The thing | Its place |\n|---|---|\n'
              '| The reasoning behind a big decision row | `notes/` |\n'
              '| A meeting transcript | `'+str(shop)+'/raw/transcripts/` |\n')
        (shop / 'notes').mkdir()
        (shop / 'raw/transcripts').mkdir(parents=True)
        purposes = page_indexes.location_purposes(shop, self.system / 'RESOLVER.md')
        self.assertEqual(purposes[shop / 'notes'], 'The reasoning behind a big decision row')
        self.assertEqual(purposes[shop / 'raw/transcripts'], 'A meeting transcript')
        self.assertNotIn(shop / 'raw', purposes)
        self.assertIn('| [notes/](notes) | The reasoning behind a big decision row |',
                      self.build()[shop / 'index.md'])

    def test_personal_table_matches_history_and_children_without_inheritance(self):
        shop = self.portfolio / 'shop'
        write(self.system / 'profile/AGENTS.md',
              '## Inside Every Workspace\n| You write | It goes in |\n|---|---|\n'
              '| A handoff | `<workspace>/history/handoffs/` |\n'
              '| Something made for someone else | `<workspace>/history/outputs/` |\n'
              '## Other\n| You write | It goes in |\n|---|---|\n'
              '| A note | `<workspace>/unknown/` |\n')
        write(self.system / 'RESOLVER.md',
              '### Where Things Live\n| Thing | Home | Path | Writer or owner |\n|---|---|---|---|\n'
              '| Run reports | Portfolio | `<workspace>/history/runs/` | Run author |\n')
        purposes = page_indexes.location_purposes(shop, self.system / 'RESOLVER.md')
        self.assertEqual(purposes[shop / 'history/handoffs'], 'A handoff')
        self.assertEqual(purposes[shop / 'history/outputs'], 'Something made for someone else')
        self.assertEqual(purposes[shop / 'history/runs'], 'Run reports')
        self.assertNotIn(shop / 'history', purposes)
        self.assertNotIn(shop / 'history/runs/custom', purposes)
        self.assertNotIn(shop / 'unknown', purposes)

    def test_portfolio_table_distinguishes_registered_workspaces_and_named_folders(self):
        write(self.system / 'RESOLVER.md',
              '### Where Things Live\n| Thing | Home | Path | Writer or owner |\n|---|---|---|---|\n'
              '| Workspaces | Portfolio | `<workspace>/` | Local contract |\n'
              '| Default capture and library | Portfolio | `atlas/` | Capture and Keeper |\n')
        write(self.portfolio / 'atlas/AGENTS.md', '# Atlas\n')
        purposes = page_indexes.location_purposes(self.portfolio, self.system / 'RESOLVER.md', True)
        self.assertEqual(purposes[self.portfolio / 'shop'], 'Workspaces')
        self.assertEqual(purposes[self.portfolio / 'atlas'], 'Default capture and library')
        self.assertNotIn(self.portfolio / 'loose', purposes)
        self.assertIn('| [shop/](shop) | Workspaces |', self.build()[self.portfolio / 'index.md'])

    def test_location_table_ignores_file_links_code_samples_and_other_workspaces(self):
        shop = self.portfolio / 'shop'
        write(shop / 'RESOLVER.md',
              '| The thing | Its place |\n|---|---|\n'
              '| The intake form for a new agent | `history/outputs/agent-intake-form.md` |\n'
              '| A comparison of options | `'+str(self.portfolio)+'/other/wiki/comparisons/` |\n'
              '\n```md\n| The thing | Its place |\n|---|---|\n'
              '| A note | `unknown/` |\n```\n')
        self.assertEqual(page_indexes.location_purposes(shop, None), {})

    def test_folder_kind_from_tsv_supplies_purpose_after_location_tables(self):
        shop = self.portfolio / 'shop'
        for folder in ('history', 'tools', 'notes', 'specs'):
            write(shop / folder / 'README.md', '# Folder\n\nPurpose: README fallback.\n')
        write(shop / 'RESOLVER.md',
              '| The thing | Its place |\n|---|---|\n| Local settings | `config/` |\n')
        write(self.system / 'RESOLVER.md',
              '### Where Things Live\n| Thing | Home | Path | Writer or owner |\n|---|---|---|---|\n'
              '| Shared notes | Portfolio | `<workspace>/notes/` | Note author |\n')
        write(self.system / 'profile/AGENTS.md',
              '## Inside Every Workspace\n| You write | It goes in |\n|---|---|\n'
              '| Personal specs | `<workspace>/specs/` |\n')
        write(self.portfolio / 'apps/README.md', '# Apps\n\nPurpose: README fallback.\n')
        write(self.system / 'config/folder-purposes.tsv',
              'workspace\tfolder\tpurpose\tsource\n'
              '*\thistory/\tFrozen work.\truling\n'
              '*\ttools/\tWorkspace tools.\truling\n'
              '*\tconfig/\tTSV settings.\truling\n'
              '*\tnotes/\tTSV notes.\truling\n'
              '*\tspecs/\tTSV specs.\truling\n'
              '*\tloose/\tWorkspace only.\truling\n'
              'shop\thistory/\tShop run reports.\truling\n'
              'other\ttools/\tOther tools.\truling\n'
              'portfolio\tapps/\tApp repos.\truling\n')
        outputs = self.build()
        for folder, purpose in (('history', 'Shop run reports.'), ('tools', 'Workspace tools.'),
                                ('config', 'Local settings'), ('notes', 'Shared notes'),
                                ('specs', 'Personal specs')):
            self.assertIn('| ['+folder+'/]('+folder+') | '+purpose+' |', outputs[shop / 'index.md'])
        self.assertIn('| [apps/](apps) | App repos. |', outputs[self.portfolio / 'index.md'])
        self.assertIn('| [loose/](loose) | no purpose yet |', outputs[self.portfolio / 'index.md'])

    def test_legacy_local_location_table_uses_each_listed_destination(self):
        shop = self.portfolio / 'shop'
        write(shop / 'RESOLVER.md',
              '| Information | Authoritative home and format | Writer |\n|---|---|---|\n'
              '| Explanations | notes/, specs/, and installed wiki kit | Document author or keeper |\n')
        purposes = page_indexes.location_purposes(shop, None)
        self.assertEqual(purposes, {shop / 'notes': 'Explanations', shop / 'specs': 'Explanations'})

    def test_page_rows_use_tsv_before_declared_purpose_and_first_line(self):
        shop = self.portfolio / 'shop'
        write(shop / 'CLAUDE.md', '---\npurpose: Declared pointer.\n---\n# CLAUDE.md\n\nRead AGENTS.md.\n')
        write(shop / 'RESOLVER.md', '# Resolver\n\nShared rules: elsewhere.\n\nPurpose: Declared locations.\n')
        write(shop / 'EXTRA.md', '# Extra\n\nFirst line fallback.\n')
        write(self.system / 'config/folder-purposes.tsv',
              'workspace\tfolder\tpurpose\tsource\n'
              '*\tCLAUDE.md\tDefault pointer.\trule\n'
              'shop\tCLAUDE.md\tShop pointer.\trule\n'
              '*\tSTATE.md\tOpen work.\trule\n'
              'other\tRESOLVER.md\tWrong workspace.\trule\n'
              'portfolio\tAGENTS.md\tPortfolio contract.\trule\n')
        outputs = self.build()
        body = outputs[shop / 'index.md']
        for name, purpose in (('CLAUDE.md', 'Shop pointer.'), ('STATE.md', 'Open work.'),
                              ('RESOLVER.md', 'Declared locations.'), ('EXTRA.md', 'First line fallback.')):
            self.assertIn('| ['+name+']('+name+') | '+purpose+' |', body)
        self.assertIn('| [AGENTS.md](AGENTS.md) | Portfolio contract. |', outputs[self.portfolio / 'index.md'])
        (self.system / 'config/folder-purposes.tsv').unlink()
        self.assertIn('| [CLAUDE.md](CLAUDE.md) | Declared pointer. |', self.build()[shop / 'index.md'])

    def test_build_time_comes_from_local_machine_clock_not_as_of_date(self):
        instant = datetime(2031, 7, 9, 16, 23, 45, tzinfo=timezone(timedelta(hours=-4)))
        with patch.object(page_indexes, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = Mock()
            clock.now.return_value.astimezone.return_value = instant
            outputs = self.build()
        clock.now.assert_called_once_with()
        for body in outputs.values():
            self.assertIn('timestamp: 2031-07-09T16:23:45-04:00\n', body)
            self.assertRegex(body, r'(?m)^MADE +2031-07-09 16:23 -0400$')
            self.assertNotIn('2026-10-18T00:00:00Z', body)

    def test_unchanged_index_keeps_build_time_but_changed_index_gets_new_time(self):
        first = datetime(2031, 7, 9, 16, 23, 45, tzinfo=timezone(timedelta(hours=-4)))
        second = first + timedelta(days=1, seconds=17)
        with patch.object(page_indexes, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = Mock()
            clock.now.return_value.astimezone.return_value = first
            page_indexes.refresh_indexes(self.portfolio, self.system)
            page = self.portfolio / 'shop/index.md'
            original = page.read_text()
            clock.now.return_value.astimezone.return_value = second
            self.assertEqual(page_indexes.refresh_indexes(self.portfolio, self.system)['changed'], 0)
            self.assertEqual(page.read_text(), original)
            write(self.portfolio / 'shop/EXTRA.md', '# Extra\n\nChanged page purpose.\n')
            self.assertEqual(page_indexes.refresh_indexes(self.portfolio, self.system)['changed'], 1)
            self.assertIn('timestamp: '+second.isoformat()+'\n', page.read_text())
            self.assertIn('Changed page purpose.', page.read_text())

    def test_check_rejects_bad_build_time_and_still_detects_changed_content(self):
        body = self.build()[self.portfolio / 'shop/index.md']
        for changed in (re.sub(r'(?m)^timestamp: .+$', 'timestamp: 2026-10-20T00:00:00Z', body),
                        re.sub(r'(?m)^MADE .+$', 'MADE 2026-10-20 00:00', body),
                        body.replace('## Folders', '## Wrong'),
                        body.replace('An agent reads this page at the start.', 'Wrong purpose.')):
            self.assertFalse(page_indexes.same_index(changed, body))



if __name__ == '__main__':
    unittest.main()
