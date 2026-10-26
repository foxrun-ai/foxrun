from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.support import BIN, orchestrate

DISABLED = ('fleet', 'foxy', 'dex', 'codex', 'claude-code', 'claude-delegate',
            'kanban-codex-lane', 'cross-runtime-agent-orchestration', 'coding-agent-delegation')
RETIRED = (*DISABLED, 'herd', 'ce-sessions')
DOORS = ('orchestrate', 'herdr', 'runtime-session-search')
CODEX_INDEX_DOORS = ('orchestrate', 'runtime-session-search', 'herdr-help')
DOCS = ('sample-shop/AGENTS.md', 'runtime-workspace/AGENTS.md', 'sample-shop/wiki/entities/orchestrate.md')


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.vault = self.home / 'foxrun'
        self.shelf = self.home / '.foxrun/skills'
        self.hermes_shelf = self.home / '.hermes/skills'
        self.hermes_shelf.mkdir(parents=True)
        for name in (*DOORS, 'herdr-help'):
            self.write(self.shelf / name / 'SKILL.md', '# skill\n')
            if name in DOORS:
                self.write(self.shelf / name / 'bin' / name, '#!/bin/sh\nexit 99\n').chmod(0o755)
        for folder in (self.home / '.foxrun/tools/cli', self.home / '.foxrun/tools/mcp', self.vault / 'sample-shop/config'):
            folder.mkdir(parents=True)
        self.codex_skills = self.home / '.codex/skills'
        self.codex_skills.mkdir(parents=True)
        for name in CODEX_INDEX_DOORS:
            (self.codex_skills / name).symlink_to(self.shelf / name, target_is_directory=True)
        self.config = self.home / '.hermes/config.yaml'
        self.profile = self.home / '.hermes/profiles/alpha/config.yaml'
        self.local = self.home / '.claude/settings.local.json'
        self.settings = self.home / '.claude/settings.json'
        self.codex = self.home / '.codex/config.toml'
        self.write(self.config, self.yaml())
        self.write(self.profile, self.yaml())
        self.write(self.home / '.hermes/profiles/beta/config.yaml', self.yaml())
        self.write(self.home / '.hermes/profiles/gamma/config.yaml', self.yaml())
        self.write(self.local, '{}')
        self.write(self.settings, json.dumps({'permissions': {'deny': ['Skill(compound-engineering:ce-sessions)']}}))
        self.write(self.codex, '[projects."/code/example"]\ntrust_level = "trusted"\n')
        self.write(self.home / '.foxrun/config/orchestrate.local.json', json.dumps({'hermes_profiles': ['main', 'alpha', 'beta', 'gamma'], 'portfolio_reference_files': ['sample-shop/AGENTS.md', 'runtime-workspace/AGENTS.md'], 'portfolio_tool_dirs': ['sample-shop/wiki/entities', 'sample-shop/config']}))
        self.write(self.home / '.foxrun/AGENTS.md', 'Use orchestrate.\n')
        for relative in DOCS:
            self.write(self.vault / relative, 'Use orchestrate.\n')

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def yaml(self, names=DISABLED):
        return 'skills:\n  disabled:\n' + ''.join(f'    - {name}\n' for name in names)

    def findings(self):
        return [r for r in orchestrate.doctor(self.home, self.vault)['checks'] if r['status'] == 'finding']

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(BIN), 'doctor', '--home', str(self.home), *args],
                              capture_output=True, text=True)

    def test_clean_json_and_table_exit_zero(self):
        result = self.cli('--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'clean')
        self.assertEqual(payload['finding_count'], 0)
        self.assertTrue(all(r['status'] == 'pass' for r in payload['checks']))
        table = self.cli()
        self.assertEqual(table.returncode, 0)
        self.assertIn('| Runtime | Status |', table.stdout)

    def test_finding_json_and_table_exit_one(self):
        self.write(self.home / '.foxrun/AGENTS.md', 'Run fleet list.\n')
        result = self.cli('--json')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['finding_count'], 1)
        table = self.cli()
        self.assertEqual(table.returncode, 1)
        self.assertIn('live fleet reference at lines 1', table.stdout)

    def test_custom_vault_and_home_default_vault(self):
        self.assertEqual(self.cli('--json').returncode, 0)
        other = Path(self.temp.name) / 'separate vault'
        self.vault.rename(other)
        result = self.cli('--vault', str(other), '--json')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(self.home / '.claude/settings.local.json'), [r['path'] for r in json.loads(result.stdout)['checks']])
        self.assertEqual(self.cli('--json').returncode, 1)

    def test_missing_skill_docs_each_door(self):
        for name in (*DOORS, 'herdr-help'):
            with self.subTest(name=name):
                doc = self.shelf / name / 'SKILL.md'
                doc.unlink()
                rows = self.findings()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['check'], name)
                self.assertIn('SKILL.md', rows[0]['findings'][0])
                self.write(doc, '# skill\n')

    def test_missing_nonexecutable_and_broken_binaries(self):
        for name, state in itertools.product(DOORS, ('missing', 'nonexecutable', 'broken')):
            with self.subTest(name=name, state=state):
                binary = self.shelf / name / 'bin' / name
                binary.unlink()
                if state == 'nonexecutable':
                    self.write(binary, '#!/bin/sh\n').chmod(0o644)
                elif state == 'broken':
                    binary.symlink_to(self.home / 'absent')
                self.assertEqual(self.findings()[0]['check'], name)
                if binary.exists() or binary.is_symlink():
                    binary.unlink()
                self.write(binary, '#!/bin/sh\n').chmod(0o755)

    def test_resolvable_skill_and_binary_links(self):
        skill = self.shelf / 'orchestrate'
        target = self.home / 'release/orchestrate'
        target.parent.mkdir()
        skill.rename(target)
        skill.symlink_to(target, target_is_directory=True)
        binary = target / 'bin/orchestrate'
        executable = self.home / 'executable'
        binary.rename(executable)
        binary.symlink_to(executable)
        self.assertFalse(self.findings())

    def test_codex_index_links_resolve_to_home_shelf(self):
        rows = orchestrate.doctor(self.home, self.vault)['checks']
        indexed = [row for row in rows if row['runtime'] == 'Codex' and row['check'] in CODEX_INDEX_DOORS]
        self.assertEqual([row['check'] for row in indexed], list(CODEX_INDEX_DOORS))
        self.assertTrue(all(row['status'] == 'pass' for row in indexed))
        self.assertTrue(all(row['path'].startswith(str(self.home / '.codex/skills')) for row in indexed))

    def test_missing_codex_index_links_each_door(self):
        for name in CODEX_INDEX_DOORS:
            with self.subTest(name=name):
                link = self.codex_skills / name
                link.unlink()
                rows = self.findings()
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]['runtime'], rows[0]['check']), ('Codex', name))
                self.assertIn('missing symlink', rows[0]['findings'][0])
                link.symlink_to(self.shelf / name, target_is_directory=True)

    def test_dangling_codex_index_links_each_door(self):
        for name in CODEX_INDEX_DOORS:
            with self.subTest(name=name):
                link = self.codex_skills / name
                link.unlink()
                link.symlink_to(self.home / 'missing' / name, target_is_directory=True)
                rows = self.findings()
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]['runtime'], rows[0]['check']), ('Codex', name))
                self.assertIn('dangling symlink', rows[0]['findings'][0])
                link.unlink()
                link.symlink_to(self.shelf / name, target_is_directory=True)

    def test_codex_index_directory_or_other_target_is_a_finding(self):
        link = self.codex_skills / 'orchestrate'
        link.unlink()
        link.mkdir()
        self.assertIn('missing symlink', self.findings()[0]['findings'][0])
        link.rmdir()
        other = self.home / 'other-orchestrate'
        other.mkdir()
        link.symlink_to(other, target_is_directory=True)
        self.assertIn('does not point', self.findings()[0]['findings'][0])

    def test_broken_skill_link(self):
        skill = self.shelf / 'herdr-help'
        skill.rename(self.shelf / 'manual')
        skill.symlink_to(self.home / 'absent', target_is_directory=True)
        self.assertEqual(self.findings()[0]['check'], 'herdr-help')

    def test_every_retired_name_in_both_shelves(self):
        for root, name in itertools.product((self.shelf, self.hermes_shelf), RETIRED):
            with self.subTest(root=root, name=name):
                path = root / name
                path.mkdir()
                rows = self.findings()
                self.assertEqual(len(rows), 1)
                self.assertIn(name, rows[0]['findings'][0])
                path.rmdir()

    def test_nested_retired_and_broken_retired_links(self):
        for root in (self.shelf, self.hermes_shelf):
            category = root / 'autonomous-ai-agents'
            category.mkdir()
            retired = category / 'coding-agent-delegation'
            retired.symlink_to(self.home / 'missing')
            self.assertIn('autonomous-ai-agents/coding-agent-delegation', self.findings()[0]['findings'][0])
            retired.unlink()

    def test_follows_category_links_and_avoids_cycles(self):
        target = self.home / 'external-category'
        (target / 'codex').mkdir(parents=True)
        (self.shelf / 'gstack').symlink_to(target, target_is_directory=True)
        (self.shelf / 'loop').symlink_to(self.shelf, target_is_directory=True)
        self.assertIn('gstack/codex', self.findings()[0]['findings'][0])

    def test_archived_retired_entries_ignored_but_live_links_reported(self):
        for root, archive in itertools.product((self.shelf, self.hermes_shelf), ('.archive', 'archive', 'retired')):
            (root / archive / 'fleet').mkdir(parents=True)
        self.assertFalse(self.findings())
        (self.hermes_shelf / 'fleet').symlink_to(self.hermes_shelf / '.archive/fleet', target_is_directory=True)
        self.assertTrue(self.findings())

    def test_missing_shelves(self):
        for root in (self.shelf, self.hermes_shelf):
            moved = root.with_name('saved')
            root.rename(moved)
            self.assertTrue(any(r['check'] == 'retired doors' for r in self.findings()))
            moved.rename(root)

    def test_each_missing_disabled_name_per_profile(self):
        for path, name in itertools.product((self.config, self.profile), DISABLED):
            with self.subTest(path=path, name=name):
                self.write(path, self.yaml(n for n in DISABLED if n != name))
                rows = self.findings()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['path'], str(path))
                self.assertEqual(rows[0]['findings'], ['missing disabled: ' + name])
                self.write(path, self.yaml())

    def test_missing_profile_file_continues(self):
        (self.home / '.hermes/profiles/gamma/config.yaml').unlink()
        self.write(self.home / '.hermes/profiles/beta/config.yaml', 'skills: {}\n')
        result = self.cli('--json')
        self.assertEqual(result.returncode, 1)
        rows = json.loads(result.stdout)['checks']
        self.assertEqual({r['check'] for r in rows if r['status'] == 'finding'}, {'gamma disabled', 'beta disabled'})
        self.assertTrue(any(r['runtime'] == 'Codex' for r in rows))

    def test_default_profiles_skip_other_profiles_as_info(self):
        for name in ('ellie', 'sample-profile', 'sample-team'):
            self.write(self.home / f'.hermes/profiles/{name}/config.yaml', 'skills: {}\n')
        result = self.cli('--json')
        self.assertEqual(result.returncode, 0, result.stdout)
        rows = json.loads(result.stdout)['checks']
        skipped = [r for r in rows if r['status'] == 'info']
        self.assertEqual({r['check'] for r in skipped},
                         {'ellie disabled', 'sample-profile disabled', 'sample-team disabled'})
        self.assertTrue(all('skipped' in r['findings'][0] for r in skipped))

    def test_missing_local_settings_checks_main_only(self):
        (self.home / '.foxrun/config/orchestrate.local.json').unlink()
        result = self.cli('--json')
        self.assertEqual(result.returncode, 0, result.stdout)
        rows = json.loads(result.stdout)['checks']
        info = {row['check'] for row in rows if row['status'] == 'info'}
        self.assertEqual(info, {'alpha disabled', 'beta disabled', 'gamma disabled'})
        self.assertFalse(any(row['path'].startswith(str(self.vault)) for row in rows))

    def test_named_profiles_replace_default_scope(self):
        self.write(self.home / '.hermes/profiles/ellie/config.yaml', 'skills: {}\n')
        result = self.cli('--hermes-profiles', 'main,ellie', '--json')
        self.assertEqual(result.returncode, 1)
        rows = json.loads(result.stdout)['checks']
        findings = [r for r in rows if r['status'] == 'finding']
        self.assertEqual([r['check'] for r in findings], ['ellie disabled'])
        info = {r['check'] for r in rows if r['status'] == 'info'}
        self.assertEqual(info, {'gamma disabled', 'alpha disabled', 'beta disabled'})

    def test_profile_list_trims_deduplicates_and_rejects_paths(self):
        result = self.cli('--hermes-profiles', ' main, alpha,main ', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(r['check'] == 'alpha disabled' for r in json.loads(result.stdout)['checks']), 1)
        rejected = self.cli('--hermes-profiles', 'main,../ellie', '--json')
        self.assertEqual(rejected.returncode, 2)

    def test_yaml_block_flow_quotes_comments_and_other_sections(self):
        configs = [self.yaml() + 'other:\n  disabled: []\n',
                   'skills:\n  disabled: [' + ', '.join(DISABLED) + '] # comment\n',
                   'skills:\n  enabled: true\n  disabled: ' + json.dumps(list(DISABLED)) + '\n  other: true\n',
                   'skills:\n  disabled:\n' + ''.join(f"  - '{n}' # comment\n" for n in DISABLED),
                   'skills:\n  disabled: [\n' + ''.join(f'    "{n}",\n' for n in DISABLED) + '  ]\n',
                   self.yaml(('Q&A', *DISABLED))]
        for config in configs:
            with self.subTest(config=config):
                self.write(self.config, config)
                self.assertFalse(self.findings())

    def test_comments_and_other_sections_do_not_count(self):
        self.write(self.config, 'other:\n  disabled: ' + json.dumps(list(DISABLED)) + '\nskills:\n  disabled: []\n# ' + self.yaml().replace('\n', '\n# '))
        self.assertEqual(self.findings()[0]['findings'], ['missing disabled: ' + ', '.join(DISABLED)])

    def test_unknown_yaml_shapes_and_duplicates(self):
        for config in [self.yaml() + self.yaml(), self.yaml() + '  disabled: []\n',
                       self.yaml() + '    - *unknown\n',
                       *('skills:\n  disabled: ' + v + '\n' for v in ('*secret-marker', '{secret-marker: true}', '[secret-marker', 'secret-marker'))]:
            with self.subTest(config=config):
                self.write(self.config, config)
                result = self.cli('--json')
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('secret-marker', result.stdout + result.stderr)

    def test_claude_codex_allow(self):
        self.write(self.local, json.dumps({'permissions': {'allow': ['Skill(codex)']}}))
        self.assertEqual(self.findings()[0]['findings'], ['remove Skill(codex) allow'])
        self.write(self.local, json.dumps({'permissions': {'allow': ['Skill(codex:rescue)']}}))
        self.assertFalse(self.findings())

    def test_claude_deny_missing_unknown_and_supported(self):
        for deny in ([], ['Skill(other)'], ['Skill(compound-engineering:ce-session)'], {'skill': 'ce-sessions'}, [{'skill': 'ce-sessions'}], ['unknown:ce-sessions']):
            with self.subTest(deny=deny):
                self.write(self.settings, json.dumps({'permissions': {'deny': deny}}))
                self.assertEqual(self.findings()[0]['check'], 'ce-sessions deny')
        for rule in ('Skill(compound-engineering:ce-sessions)', 'Skill(ce-sessions)', 'Skill(compound-engineering:*)', 'Skill(*)', 'Skill'):
            self.write(self.settings, json.dumps({'permissions': {'deny': [rule]}}))
            self.assertFalse(self.findings())

    def test_codex_trust_not_comments_or_untrusted(self):
        self.write(self.codex, '[projects."/a/fleet/bin"]\ntrust_level = "trusted"\n[projects."/b/fleet-old"]\ntrust_level = "trusted"\n')
        self.assertEqual(self.findings()[0]['findings'], ['retired trust entries: /a/fleet/bin, /b/fleet-old'])
        self.write(self.codex, '# [projects."/fleet"]\n[projects."/a/fleet"]\ntrust_level = "untrusted"\nnote = "/fleet"\n')
        self.assertFalse(self.findings())

    def test_codex_trust_reads_the_same_without_tomllib(self):
        # Python 3.9 and 3.10 have no tomllib, so the doctor reads the projects tables itself.
        config = '\n'.join((
            'model = "fixture-model"',
            'approval_policy = "on-request"  # a comment with [brackets]',
            'notify = [',
            '  "python3",',
            '  "/path/[odd]/notify.py",',
            ']',
            'instructions = """',
            '[projects."/fleet/inside-a-string"]',
            'trust_level = "trusted"',
            '"""',
            '[mcp_servers.context7]',
            'command = "npx"',
            'args = ["-y", "@example/fixture-mcp"]',
            'env = { KEY = "value" }',
            '',
            '[projects."/a/fleet/bin"] # trusted below',
            'trust_level = "trusted"',
            "[projects.'/b/fleet-old']",
            "trust_level = 'trusted'",
            '[projects."/c/fleet-safe"]',
            'trust_level = "untrusted"',
            'note = "x # y"',
            '[projects."/code/example"]',
            'trust_level = "trusted"',
            '[[hooks.post]]',
            'command = "x"',
            ''))
        fallback = orchestrate._toml_projects(config)
        self.assertEqual(fallback, {'/a/fleet/bin': {'trust_level': 'trusted'}, '/b/fleet-old': {'trust_level': 'trusted'},
                                    '/c/fleet-safe': {'trust_level': 'untrusted'}, '/code/example': {'trust_level': 'trusted'}})
        try:
            import tomllib
        except ImportError:
            pass
        else:
            parsed = tomllib.loads(config)['projects']
            self.assertEqual(fallback, {name: {'trust_level': row['trust_level']} for name, row in parsed.items()})
        # A form the reader does not know refuses, so the check says it cannot verify.
        for unknown in ('projects = { "/fleet" = { trust_level = "trusted" } }\n',
                        '[projects]\n"/fleet".trust_level = "trusted"\n',
                        'projects."/fleet".trust_level = "trusted"\n',
                        '[projects."/fleet"]\ntrust_level = """trusted"""\n',
                        '[projects."/fleet"]\n[projects."/fleet"]\n',
                        '[[projects]]\nname = "/fleet"\n',
                        'instructions = """\nnever closed\n',
                        '\x00secret-marker{\n'):
            with self.subTest(unknown=unknown):
                with self.assertRaises(ValueError):
                    orchestrate._toml_projects(unknown)
        self.write(self.codex, config)
        with mock.patch.dict(sys.modules, {'tomllib': None}):
            rows = self.findings()
        self.assertEqual([row['findings'] for row in rows], [['retired trust entries: /a/fleet/bin, /b/fleet-old']])
        self.write(self.codex, 'projects."/fleet".trust_level = "trusted"\n')
        with mock.patch.dict(sys.modules, {'tomllib': None}):
            rows = self.findings()
        self.assertEqual(rows[0]['findings'], ['cannot verify (ValueError); missing, unreadable, or unknown format'])

    def test_each_live_vault_surface_and_line_numbers(self):
        for relative in DOCS:
            path = self.vault / relative
            self.write(path, 'Use orchestrate.\nRun fleet spawn.\nSee ~/.agents/skills/fleet/bin/fleet\n')
            rows = self.findings()
            self.assertEqual(rows[0]['path'], str(path))
            self.assertEqual(rows[0]['findings'], ['live fleet reference at lines 2, 3'])
            self.write(path, 'Use orchestrate.\n')

    def test_live_fleet_door_patterns(self):
        lines = ('skills/fleet', 'bin/fleet', 'the `fleet` skill', 'fleet spawn',
                 'fleet close 2', '`fleet list`')
        for line in lines:
            with self.subTest(line=line):
                self.write(self.home / '.foxrun/AGENTS.md', line + '\n')
                self.assertEqual(self.findings()[0]['findings'], ['live fleet reference at lines 1'])
        self.write(self.home / '.foxrun/config/orchestrate.local.json', json.dumps({'hermes_profiles': ['main', 'alpha', 'beta', 'gamma'], 'portfolio_reference_files': ['sample-shop/AGENTS.md', 'runtime-workspace/AGENTS.md'], 'portfolio_tool_dirs': ['sample-shop/wiki/entities', 'sample-shop/config']}))
        self.write(self.home / '.foxrun/AGENTS.md', 'Use orchestrate.\n')

    def test_history_replacements_and_third_party_names_are_not_live(self):
        text = ('It was `fleet` before the rename.\n'
                'Replaces fleet, foxy, and dex.\n'
                'State filenames remain from the fleet era.\n'
                'Watch the herdr-fleet third-party repository.\n'
                'The retired fleet skill is archived.\n'
                'The fleet skill is retired.\n'
                'The old fleet close flow is gone.\n')
        self.write(self.home / '.foxrun/AGENTS.md', text)
        self.assertFalse(self.findings())

    def test_archives_dated_logs_handoffs_plans_excluded(self):
        for relative in ('archive/AGENTS.md', 'sample-shop/archive/AGENTS.md', 'sample-shop/history/LOG.md',
                         'sample-shop/history/outputs/2026-09-07-plan.md', 'sample-shop/history/handoffs/2026-09-07/handoff.md',
                         'sample-shop/wiki/entities/archive/old.md', 'sample-shop/wiki/entities/2026-09-07-handoff.md'):
            self.write(self.vault / relative, 'Use fleet.\n')
        (self.vault / 'sample-shop/wiki/entities/archived.md').symlink_to(self.vault / 'archive/AGENTS.md')
        self.assertFalse(self.findings())

    def test_missing_and_malformed_configs(self):
        for path in (self.config, self.settings, self.local, self.codex):
            original = path.read_text()
            path.unlink()
            self.assertEqual(self.cli('--json').returncode, 1)
            self.write(path, '\x00secret-marker{')
            result = self.cli('--json')
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('secret-marker', result.stdout + result.stderr)
            self.write(path, original)

    def test_each_split_tool_owner(self):
        for folder in (self.home / '.foxrun/tools/cli', self.home / '.foxrun/tools/mcp', self.vault / 'sample-shop/config'):
            path = folder / 'synthetic.md'
            self.write(path, 'Run fleet spawn.\n')
            self.assertEqual([r['path'] for r in self.findings()], [str(path)])
            path.unlink()

    def test_read_only_and_no_binary_execution(self):
        def snapshot():
            return {str(p.relative_to(self.home)): (p.lstat().st_mode, p.lstat().st_mtime_ns,
                    os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                    for p in self.home.rglob('*')}
        before = snapshot()
        self.assertEqual(self.cli('--json').returncode, 0)
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(snapshot(), before)


class RowAliasTests(unittest.TestCase):
    def test_number_aliases_match_all_word_cells(self):
        words = ('quick', 'advise', 'review', 'fix', 'grill', 'converse', 'steer', 'parallel')
        for source, target, (number, word) in itertools.product(('claude', 'codex', 'hermes'),
                (None, 'claude', 'codex', 'hermes'), enumerate(words, 1)):
            with self.subTest(source=source, target=target, number=number):
                args = dict(source=source, to=target, task='check it', session_id='session',
                            desktop_owned=True, conversation='codex:test')
                self.assertEqual(orchestrate.resolve(want=str(number), **args), orchestrate.resolve(want=word, **args))

    def test_cli_accepts_all_numbers(self):
        for number in range(1, 9):
            result = subprocess.run([sys.executable, '-B', str(BIN), 'resolve', '--from', 'codex', '--want', str(number)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['row'], number)

    def test_cli_rejects_out_of_range_aliases(self):
        for number in ('0', '9', '-1', '01'):
            result = subprocess.run([sys.executable, '-B', str(BIN), 'resolve', '--from', 'codex', '--want', number],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
