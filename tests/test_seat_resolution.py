#!/usr/bin/env python3
"""Prove personal seat priority and protected installs in isolated homes."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / 'agents/tools'))
from base import paths, ownership, workspace_pages
from memory import start_context, state
from work import flow, standing
from agents.tools import agent_new, render_capabilities, profile_check, tool_probe


class SeatResolution(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='seat-resolution-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home, self.portfolio = self.root / 'system', self.root / 'portfolio'
        self.workspace = self.portfolio / 'fixture'
        for folder in ('agents', 'config', 'profile/agents', 'modules'):
            (self.home / folder).mkdir(parents=True, exist_ok=True)
        for folder in ('team', 'config'):
            (self.workspace / folder).mkdir(parents=True, exist_ok=True)
        self.environment = patch.dict(os.environ, FOXRUN_HOME=str(self.home),
                                      FOXRUN_PORTFOLIO=str(self.portfolio))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        (self.home / 'config/models.yaml').write_bytes((TREE / 'config/models.yaml').read_bytes())
        (self.home / 'config/catalog.yaml').write_text(json.dumps({
            'sets': {'base': {'skills': [], 'tools': []}, 'architect': {'skills': [], 'tools': []}}}))
        (self.home / 'config/standing-seats.json').write_text(json.dumps({
            'seats': {'architect': 'system:agents/architect.md'}}))
        self.shipped = self.home / 'agents/architect.md'
        self.shipped.write_bytes((TREE / 'agents/architect.md').read_bytes())
        self.personal = self.home / 'profile/agents/architect.md'

    def override(self):
        data, body = agent_new.split_identity(self.shipped.read_text())
        data['summary'] = 'Personal fixture seat.'
        data['owns'] = ['personal-data']
        self.personal.write_text('---\n' + json.dumps(data) + '\n---\n' + body)
        return self.personal

    def test_personal_copy_wins(self):
        self.override()
        self.assertEqual(paths.resolve_seat('architect'), self.personal)

    def test_standing_start_requires_global_contract_and_omits_system_home_rules(self):
        for target in (self.home / 'agents/soul.md', self.home / 'profile/AGENTS.md',
                       self.workspace / 'AGENTS.md', self.workspace / 'RESOLVER.md'):
            target.write_text('# Contract\n')
        record = dict(seat='architect', runtime='codex', workspace='fixture')
        output = standing.page(record).split('Read contracts in order:\n', 1)[1]
        self.assertEqual(output.splitlines(), [
            '  ' + str(self.home / 'agents/soul.md'),
            '  ' + str(self.home / 'profile/AGENTS.md'),
            '  ' + str(self.workspace / 'AGENTS.md'),
            '  ' + str(self.workspace / 'RESOLVER.md')])
        (self.home / 'profile/AGENTS.md').unlink()
        with self.assertRaisesRegex(ValueError, 'current contracts'):
            standing.page(record)

    def test_empty_personal_folder_loads_shipped(self):
        self.assertEqual(paths.resolve_seat('architect'), self.shipped)
        self.assertEqual(agent_new.load_identity('architect', self.home / 'agents').path, self.shipped)

    def test_missing_personal_folder_loads_shipped(self):
        (self.home / 'profile/agents').rmdir()
        self.assertEqual(paths.resolve_seat('architect'), self.shipped)

    def test_handoff_part_with_a_blank_twentieth_line_adds_no_hidden_line(self):
        folder = self.workspace / 'history/handoffs'
        folder.mkdir(parents=True)
        lines = ['---', 'session: s1', '---'] + ['line %d' % n for n in range(16)] + ['', 'after']
        (folder / '2026-10-23-001-fixture.md').write_text('\n'.join(lines) + '\n')
        with patch.dict(os.environ, FOXRUN_SESSION='s1'):
            output = start_context.handoff_part('fixture', 'architect', None, [])
        self.assertFalse(output.endswith('\n'))
        self.assertEqual(len(output.splitlines()), 20)

    def test_start_names_the_selected_file_and_content(self):
        self.override()
        output = start_context.seat_part('fixture', 'architect')
        self.assertEqual(output.splitlines().count('File: ' + str(self.personal)), 1)
        self.assertIn('Summary: Personal fixture seat.', output)
        self.assertNotIn('File: ' + str(self.shipped), output)

    def test_all_system_readers_use_personal_copy(self):
        self.override()
        self.assertEqual(start_context.seat_file('fixture', 'architect'), self.personal)
        self.assertEqual(flow.seat_file('architect', 'fixture'), self.personal)
        self.assertEqual(standing.identity('architect', 'codex')[0], self.personal)
        loaded = agent_new.load_identity('architect', self.home / 'agents')
        self.assertEqual(loaded.path, self.personal)
        self.assertEqual(loaded.data['summary'], 'Personal fixture seat.')
        self.assertEqual(ownership.owners(self.home), {'personal-data': 'architect'})
        profiles = profile_check._identities(self.home / 'agents', include_core=True)
        self.assertEqual(profiles[0]['source'], str(self.personal))
        with patch.dict(sys.modules, agent_new=agent_new):
            report = tool_probe.probe_profile('architect', hermes_home=self.root / 'hermes',
                                               agent_team_root=self.home / 'agents', write_reports=False)
        self.assertEqual(report['config'], str(self.personal))
        reader = render_capabilities.SourceReader(self.home / 'agents', self.portfolio,
                                                  self.home / 'modules', installed_layout=True)
        agents, gaps = render_capabilities.load_agents(reader, agent_new)
        self.assertEqual(gaps, [])
        self.assertEqual(agents['architect'].data['summary'], 'Personal fixture seat.')
        self.assertEqual(agents['architect'].source, 'personal:architect.md')
        (self.workspace / 'config/team.yaml').write_text('lead: architect\nworks_here: [architect]\n')
        self.assertIn('profile/agents/architect.md', state.works_here(self.workspace, self.home))
        page, _ = workspace_pages.team('fixture', self.home, self.portfolio)
        self.assertIn('profile/agents/architect.md', page)

    def test_builders_point_at_the_personal_identity(self):
        self.override()
        loaded = agent_new.load_identity('architect', self.home / 'agents')
        for build in (agent_new.claude_cape, agent_new.codex_cape):
            with self.subTest(builder=build.__name__):
                text = build(loaded, self.home / 'agents')
                self.assertIn(str(self.personal), text)
                self.assertNotIn('Read ' + str(self.shipped) + ' fully', text)

    def test_workspace_priority_stays_the_same(self):
        self.override()
        team = self.workspace / 'team/architect.md'
        team.write_text('# Fixture team seat\n')
        self.assertEqual(paths.resolve_seat('architect', workspace_root=self.workspace), team)
        self.assertEqual(start_context.seat_file('fixture', 'architect'), team)
        self.assertEqual(flow.seat_file('architect', 'fixture'), team)
        # A standing portfolio identity continues to name its explicit source.
        (self.home / 'config/standing-seats.json').write_text(json.dumps({
            'seats': {'architect': 'portfolio:fixture/team/architect.md'}}))
        team.write_bytes(self.personal.read_bytes())
        self.assertEqual(standing.identity('architect', 'codex')[0], team)

    def test_invalid_personal_copy_does_not_fall_back(self):
        self.personal.write_text('Invalid fixture identity.\n')
        with self.assertRaises(ValueError):
            agent_new.load_identity('architect', self.home / 'agents')

    def test_linked_personal_copy_is_refused(self):
        self.personal.symlink_to(self.shipped)
        with self.assertRaises(ValueError):
            paths.resolve_seat('architect')

    def test_directory_override_is_refused(self):
        self.personal.mkdir()
        with self.assertRaises(ValueError):
            paths.resolve_seat('architect')

    def test_unsafe_seat_names_are_refused(self):
        for name in ('../architect', '/architect', '..', 'a\\b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                paths.resolve_seat(name)


@unittest.skipUnless((TREE / 'install.py').is_file(), 'installer is source-only')
class PersonalSeatInstallProtection(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='seat-install-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        spec = importlib.util.spec_from_file_location('seat_fixture_installer', TREE / 'install.py')
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)

    def test_copy_and_update_never_write_personal_seats(self):
        source, target = self.root / 'source', self.root / 'target'
        for folder in ('agents', 'profile/agents', 'skillwright/workflows'):
            (source / folder).mkdir(parents=True, exist_ok=True)
        (source / 'agents/fixture.md').write_text('Shipped fixture version 1.\n')
        # Even a bad shipment list must not overwrite a person's seat.
        (source / 'profile/agents/fixture.md').write_text('Must never be copied.\n')
        (source / 'profile/agents/new-seat.md').write_text('Must never be created.\n')
        with (source / 'product-manifest.tsv').open('w') as stream:
            writer = csv.writer(stream, delimiter='\t')
            writer.writerow(('path', 'bytes', 'sha256'))
            for name in ('agents/fixture.md', 'profile/agents/fixture.md', 'profile/agents/new-seat.md'):
                writer.writerow((name, 0, 'fixture'))
        (target / 'skillwright/workflows').mkdir(parents=True)
        personal = target / 'profile/agents/fixture.md'
        personal.parent.mkdir(parents=True)
        personal.write_text('Personal fixture remains exact.\n')
        before = personal.read_bytes(), personal.stat().st_mtime_ns
        with patch.object(self.installer, 'STARTERS', ()):
            for version in (1, 2):
                (source / 'agents/fixture.md').write_text('Shipped fixture version ' + str(version) + '.\n')
                self.installer.copy_tree(source, target)
                self.assertEqual((personal.read_bytes(), personal.stat().st_mtime_ns), before)
                self.assertEqual(sorted(p.name for p in personal.parent.iterdir()), ['fixture.md'])
                self.assertEqual((target / 'agents/fixture.md').read_bytes(), (source / 'agents/fixture.md').read_bytes())

    def test_fresh_install_leaves_personal_agents_absent(self):
        source, target = self.root / 'source', self.root / 'target'
        (source / 'profile/agents').mkdir(parents=True)
        (source / 'profile/agents/fixture.md').write_text('Excluded fixture.\n')
        (source / 'product-manifest.tsv').write_text('path\tbytes\tsha256\nprofile/agents/fixture.md\t0\tfixture\n')
        (target / 'skillwright/workflows').mkdir(parents=True)
        with patch.object(self.installer, 'STARTERS', ()):
            self.installer.copy_tree(source, target)
        self.assertFalse((target / 'profile/agents').exists())


if __name__ == '__main__':
    unittest.main()
