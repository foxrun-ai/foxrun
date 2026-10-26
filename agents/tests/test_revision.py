import sys
from pathlib import Path as _SupportPath
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[2] / "base"))
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1]))
# agents/ goes ahead of base/ so tests.support is this folder, not base/tests (collision since 9e44892 T595)
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1] / "tools"))
"""Strict defaults and explicit installed-layout behavior from the second brief."""
import builtins
from contextlib import redirect_stderr, redirect_stdout
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import agent_new
import eval_run
import profile_check
import render_capabilities as renderer
import tool_probe
from tests.support import MonkeyPatch
from tests import test_agent_new as agents
from tests import test_eval_run as evaluations
from tests import test_render_capabilities as renderer_tests

ROOT = Path(__file__).resolve().parents[1]


class BehaviorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.monkey = MonkeyPatch()
        self.addCleanup(self.monkey.undo)

    def world(self):
        return agents.world(self.base, self.monkey)

    def fixture(self):
        fixture = renderer_tests.CapabilityRendererTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_skill_exceptions_are_explicit_and_preserve_disable_rules(self):
        # current behavior since 4a024f1 (T740): core skills and exceptions come from config/catalog.yaml
        world = self.world()
        catalog = world.repo.parent / 'config/catalog.yaml'
        catalog.write_text(json.dumps({'sets': {'base': {'skills': ['core-skill'], 'tools': []}},
                                       'exceptions': agents.CORE['exceptions']}))
        identity = agents.write_identity(world, agent_id='example-lead', mode='profile')
        for name in ('tp-time-tracking', 'tp-weekly-review', 'spike', 'test-driven-development'):
            (world.shelf / name).mkdir()
        disabled = agent_new.disabled_skills(identity, world.repo, world.hermes, world.shelf)
        self.assertNotIn('tp-time-tracking', disabled)
        self.assertIn('spike', disabled)
        plain = agents.write_identity(world, agent_id='other-agent', mode='profile')
        self.assertIn('tp-time-tracking', agent_new.disabled_skills(plain, world.repo, world.hermes, world.shelf))
        catalog.write_text('{"sets": {"base": {"skills": [], "tools": []}}, "exceptions": {}}')
        self.assertIn('tp-time-tracking', agent_new.disabled_skills(identity, world.repo, world.hermes, world.shelf))

    def test_create_writes_by_default_and_dry_run_is_explicit(self):
        # current behavior since 4a024f1 (T740): a workspace client writes <portfolio>/<client>/team/<id>.md
        # Resolved roots so the portfolio link guard does not trip on macOS /var -> /private/var.
        world = agents.world(self.base.resolve(), self.monkey)
        # The portfolio sits outside the system home, as installed, with its workspace contract.
        portfolio_temp = tempfile.TemporaryDirectory()
        self.addCleanup(portfolio_temp.cleanup)
        portfolio = Path(portfolio_temp.name).resolve()
        (portfolio / 'example-work').mkdir()
        (portfolio / 'example-work/AGENTS.md').write_text('contract')
        self.monkey.setenv('FOXRUN_PORTFOLIO', str(portfolio))
        # System writes (runs/generated render receipts) pass the ownership guard via the world's owning seat.
        page = portfolio / 'example-work/team/sample-agent.md'
        args = ['create', 'sample-agent', '--role', 'Checks samples', '--summary', 'Checks samples.',
                '--tier', 'work', '--skills', '', '--tools', '', '--client', 'example-work',
                '--runtimes', 'claude,codex', '--hermes-mode', 'none']
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(agent_new.main(args + ['--dry-run']), 0)
            self.assertFalse(page.exists())
            self.assertEqual(agent_new.main(args), 0)
        self.assertTrue(page.is_file())
        self.assertFalse((world.repo / 'sample-agent.md').exists())

    def test_create_requires_all_original_options_and_accepts_no_hermes(self):
        # current behavior since 4a024f1 (T740): --client stays required; --runtimes defaults to claude,codex
        base = ['create', 'sample-agent', '--role', 'Checks samples', '--summary', 'Checks samples.',
                '--tier', 'work', '--skills', '', '--tools', '', '--client', 'example-work',
                '--runtimes', 'claude,codex', '--hermes-mode', 'none']
        parsed = agent_new.parser().parse_args(base)
        self.assertEqual(parsed.hermes_mode, 'none')
        self.assertEqual(parsed.runtimes, 'claude,codex')
        for option in ('--role', '--summary', '--tier', '--client'):
            args = base[:]
            index = args.index(option)
            del args[index:index + 2]
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                agent_new.parser().parse_args(args)
        args = base[:]
        index = args.index('--runtimes')
        del args[index:index + 2]
        self.assertEqual(agent_new.parser().parse_args(args).runtimes, 'claude,codex')
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            agent_new.parser().parse_args(base[:-1] + ['profile'])

    def test_state_uses_current_general_name(self):
        self.assertEqual(agent_new.WRITE_STATE_SECTION.count('--person-words'), 3)
        self.assertIn("`--person-words` records the person's exact words.", agent_new.WRITE_STATE_SECTION)
        self.assertIn('--call approve --person-words', agent_new.WRITE_STATE_SECTION)
        self.assertLessEqual(len(agent_new.WRITE_STATE_SECTION.rstrip().splitlines()), 25)

    def test_apply_requires_original_literal(self):
        args = SimpleNamespace(yes='apply', id='sample-agent')
        with self.assertRaisesRegex(agent_new.AgentNewError, '--yes person'):
            agent_new.apply_command(args, lambda *a: None)
        # The original word passes confirmation and reaches the identity lookup.
        args.yes = 'person'
        with patch.object(agent_new, 'load_identity', side_effect=RuntimeError('lookup reached')):
            with self.assertRaisesRegex(RuntimeError, 'lookup reached'):
                agent_new.apply_command(args, lambda *a: None)

    def test_discovery_keeps_profile_default_and_explicit_core_option(self):
        world = self.world()
        agents.write_identity(world, agent_id='core-agent', mode='none', runtimes=['claude'])
        agents.write_identity(world, agent_id='profile-agent', mode='profile')
        self.assertEqual([x['id'] for x in profile_check._identities(world.repo)], ['profile-agent'])
        self.assertEqual([x['id'] for x in profile_check._identities(world.repo, include_core=True)], ['core-agent', 'profile-agent'])

    def test_discovery_uses_filename_without_id_and_core_is_explicit(self):
        world = self.world()
        (world.repo / 'missing-id.md').write_text('---\nhermes_mode: profile\n---\n# Sample\n')
        (world.repo / 'kanban-id.md').write_text('---\nhermes_mode: kanban\nhermes_profile: selected-profile\n---\n# Sample\n')
        agents.write_identity(world, agent_id='core-agent', mode='none', runtimes=['claude', 'codex'])
        (world.repo / 'README.md').write_text('# Shared documentation\n')
        found = profile_check._identities(world.repo)
        self.assertEqual([(x['id'], x['profile']) for x in found],
                         [('kanban-id', 'selected-profile'), ('missing-id', 'missing-id')])
        self.assertEqual([x['id'] for x in profile_check._identities(world.repo, include_core=True)],
                         ['core-agent', 'kanban-id', 'missing-id'])

    def test_missing_declared_hermes_profile_fails_with_core_capes(self):
        world = self.world()
        for runtime, suffix in (('claude', '.md'), ('codex', '.toml')):
            cape = world.vault / ('.' + runtime) / 'agents' / ('sample-agent' + suffix)
            cape.parent.mkdir(parents=True)
            cape.write_text(agent_new.MARKER)
        for mode, runtimes in (('profile', ['hermes', 'claude', 'codex']),
                               ('kanban', ['hermes', 'claude', 'codex']),
                               ('none', ['hermes', 'claude', 'codex']),
                               ('profile', ['claude', 'codex'])):
            with self.subTest(mode=mode, runtimes=runtimes):
                agents.write_identity(world, agent_id='sample-agent', mode=mode, runtimes=runtimes)
                with self.assertRaisesRegex(FileNotFoundError, 'profile config not found'):
                    tool_probe.probe_profile('sample-agent', agent_team_root=world.repo,
                                             hermes_home=world.hermes)
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(tool_probe.main(['sample-agent', '--json']), 2)
                self.assertEqual('Claude and Codex on day one.\n', stdout.getvalue())

    def test_no_declared_hermes_skips_and_checks_core_capes(self):
        world = self.world()
        agents.write_identity(world, agent_id='core-agent', mode='none', runtimes=['claude', 'codex'])
        for runtime, suffix in (('claude', '.md'), ('codex', '.toml')):
            cape = world.vault / ('.' + runtime) / 'agents' / ('core-agent' + suffix)
            cape.parent.mkdir(parents=True)
            cape.write_text(agent_new.MARKER)
        def runner(*args, **kwargs):
            self.fail('Undeclared Hermes must not run')
        result = tool_probe.probe_profile('core-agent', agent_team_root=world.repo,
                                          hermes_home=world.hermes, runner=runner)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual([(x['tool'], x['state']) for x in result['tools']],
                         [('claude', 'ok'), ('codex', 'ok')])
        self.assertIn('not declared', result['hermes'])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(tool_probe.main(['core-agent', '--json']), 2)
        self.assertEqual('Claude and Codex on day one.\n', stdout.getvalue())

    def test_core_cape_checks_are_strict_unless_declared_option_selected(self):
        world = self.world()
        identity = {'id': 'core-agent', 'profile': 'core-agent', 'mode': 'none', 'runtimes': ['claude']}
        cape = world.vault / '.claude/agents/core-agent.md'
        cape.parent.mkdir(parents=True)
        cape.write_text('managed-by: agent-new')
        arguments = (identity, world.repo, world.vault, lambda *a: None, lambda *a: None, dt.datetime.now(dt.timezone.utc))
        strict = profile_check._identity_result(*arguments)
        self.assertEqual(strict['state'], 'red')
        self.assertIn('codex cape missing', strict['reasons'])
        selected = profile_check._identity_result(*arguments, declared_runtimes_only=True)
        self.assertEqual(selected['state'], 'green')
        self.assertEqual(set(selected['capes']), {'claude'})

    def test_symbolic_target_uses_configured_profile_and_explicit_override(self):
        world = self.world()
        (world.repo / 'execution/notifications.yaml').write_text('{"hermes_profile": "example-lead"}')
        commands = []
        # -1001234567890 is a synthetic Telegram chat id. No live test uses it.
        def runner(command, **kwargs):
            commands.append(command)
            return SimpleNamespace(returncode=0, stdout='Example -1001234567890 topic 1', stderr='')
        self.assertEqual(profile_check._resolve_target('telegram:example:1', runner), 'telegram:-1001234567890:1')
        self.assertEqual(commands[-1], ['hermes', '-p', 'example-lead', 'send', '--list', 'telegram'])
        profile_check._resolve_target('telegram:example:1', runner, 'other-profile')
        self.assertEqual(commands[-1][2], 'other-profile')
        (world.repo / 'execution/notifications.yaml').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'configured Hermes profile'):
            profile_check._resolve_target('telegram:example:1', runner)
        self.assertEqual(profile_check._resolve_target('telegram:-1001234567890:1', runner), 'telegram:-1001234567890:1')

    def test_missing_skill_pin_fails_and_real_pin_passes(self):
        roots, identities = evaluations.make_world(self.base)
        runner = evaluations.FakeRunner(identities)
        result = eval_run.run_eval(root_map=roots, runner=runner)
        self.assertTrue(evaluations.step(result, 'skill pin')['ok'])
        (roots['repo'] / 'execution/skills.yaml').write_text('{"gaps": []}')
        result = eval_run.run_eval(root_map=roots, runner=runner)
        self.assertFalse(evaluations.step(result, 'skill pin')['ok'])
        self.assertEqual(result['verdict'], 'FAIL')

    def test_probe_target_default_is_configured_and_argument_overrides_it(self):
        roots, identities = evaluations.make_world(self.base)
        (roots['repo'] / 'execution/notifications.yaml').write_text('{"probe_target": "example-lead"}')
        default_runner = evaluations.FakeRunner(identities)
        calls = []
        def runner(command, **kwargs):
            if command[1].endswith('tool_probe.py'):
                calls.append(command)
                return SimpleNamespace(returncode=0, stdout='{"tools": []}', stderr='')
            return default_runner(command, **kwargs)
        first = eval_run.run_eval(root_map=roots, runner=runner, tools=True)
        self.assertTrue(evaluations.step(first, 'tool probe')['ok'])
        self.assertEqual(calls[-1][2], 'example-lead')
        second = eval_run.run_eval(root_map=roots, runner=runner, tools=True, probe_target='other-agent')
        self.assertTrue(evaluations.step(second, 'tool probe')['ok'])
        self.assertEqual(calls[-1][2], 'other-agent')
        (roots['repo'] / 'execution/notifications.yaml').write_text('{}')
        third = eval_run.run_eval(root_map=roots, runner=runner, tools=True)
        self.assertFalse(evaluations.step(third, 'tool probe')['ok'])

    def test_missing_modules_is_strict_and_installed_option_reports_gap(self):
        f = self.fixture()
        shutil.rmtree(f.modules)
        with self.assertRaisesRegex(renderer.CapabilityError, 'modules root must exist'):
            renderer.SourceReader(f.repo, f.vault, f.modules)
        reader = renderer.SourceReader(f.repo, f.vault, f.modules, installed_layout=True)
        self.assertEqual(renderer.module_commands(reader)[1][0]['reason'], 'module directory missing')

    def test_markdown_without_frontmatter_is_a_gap_except_installed_shared_docs(self):
        f = self.fixture()
        for name in ('README.md', 'soul.md', 'broken-seat.md'):
            (f.repo / name).write_text('# Text without identity frontmatter')
        reader = renderer.SourceReader(f.repo, f.vault, f.modules)
        loader = renderer.load_agent_new(f.repo, f.repo / 'agent_new.py')
        _, strict = renderer.load_agents(reader, loader)
        self.assertTrue(all(any(name in x['item'] for x in strict) for name in ('README.md', 'soul.md', 'broken-seat.md')))
        reader = renderer.SourceReader(f.repo, f.vault, f.modules, installed_layout=True)
        _, installed = renderer.load_agents(reader, loader)
        # README and soul are shared documents at this level by installed design.
        self.assertFalse(any(x['item'] in ('README.md', 'soul.md') for x in installed))
        self.assertTrue(any(x['item'] == 'broken-seat.md' for x in installed))

    def test_missing_decisions_is_strict_and_installed_absence_stays_a_gap(self):
        f = self.fixture()
        (f.vault / 'system-workspace/docs/capability-decisions.jsonl').unlink()
        reader = renderer.SourceReader(f.repo, f.vault, f.modules)
        with self.assertRaisesRegex(renderer.CapabilityError, 'source is missing'):
            renderer.load_decisions(reader)
        # Installed decisions live in data.db, not this legacy JSONL registry.
        model, _ = renderer.build_model(f.repo, f.vault, f.workspace, f.shelf, installed_layout=True)
        self.assertTrue(all(any(x['item'] == name for x in model['gaps']) for name in ('pr-capabilities-md', 'workflow')))

    def test_missing_template_is_strict_and_installed_fallback_reports_gap(self):
        f = self.fixture()
        (f.modules / 'base/templates-v2/CAPABILITIES.md').unlink()
        (f.repo / 'docs').mkdir()
        shutil.copyfile(ROOT / 'docs/capabilities-template.md', f.repo / 'docs/capabilities-template.md')
        with self.assertRaisesRegex(renderer.CapabilityError, 'source is missing'):
            renderer.build_model(f.repo, f.vault, f.workspace, f.shelf)
        # The installed package includes its own template; legacy module templates do not ship here.
        model, _ = renderer.build_model(f.repo, f.vault, f.workspace, f.shelf, installed_layout=True)
        self.assertTrue(any(x['item'] == 'CAPABILITIES template' and 'bundled template used' in x['reason'] for x in model['gaps']))
