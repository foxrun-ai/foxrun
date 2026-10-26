#!/usr/bin/env python3
"""Synthetic checks for the bounded contract lint candidate."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import contract_lint as lint


CANDIDATE = Path(__file__).resolve().parent.parent
RULES = Path(os.environ.get("CONTRACT_LINT_RULES", (Path(__file__).resolve().parent / '../contract-lint-rules.json')))
CONTRACTS = tuple(json.loads(RULES.read_text())["recognized_contracts"])
MODULES_ROOT = Path(__file__).resolve().parent.parent.parent
system_workspace_ROOT = Path(os.environ.get("FOXRUN_system_workspace", _fox_root / "test-fixtures/system-workspace"))


def load_checkout_module(name: str, relative: str):
    for directory in (
        Path(__file__).resolve().parent.parent,
        system_workspace_ROOT / "scripts",
        system_workspace_ROOT / "scripts/tests",
    ):
        value = str(directory)
        if value not in sys.path:
            sys.path.insert(0, value)
    path = (MODULES_ROOT if relative.startswith("base/") else system_workspace_ROOT) / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load checkout module: " + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractLintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="contract-lint-test-", dir=os.environ.get("CONTRACT_LINT_TEST_TMP"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.workspace = self.vault / "demo"
        self.workspace.mkdir(parents=True)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        self.commands = self.root / "commands.json"
        self.commands.write_text(json.dumps({"executables": ["rg", "python3"]}))
        for name in CONTRACTS:
            self.write(name, "# " + name.removesuffix(".md") + "\n")

    def write(self, relative: str, body: str) -> Path:
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def skill(self, name: str):
        path = self.skills / name
        path.mkdir()
        (path / "SKILL.md").write_text("# Synthetic\n", encoding="utf-8")

    def scan(self, **overrides):
        values = {
            "rules_path": RULES,
            "vault_root": self.vault,
            "workspace": self.workspace,
            "skill_roots": [self.skills],
            "command_inventory": self.commands,
        }
        values.update(overrides)
        return lint.scan(**values)

    def findings(self, report, rule):
        """Rows for one rule: findings, plus the text that could not be checked."""
        return [row for row in report["findings"] + report["unchecked"] if row["rule"] == rule]

    def test_literal_links_paths_wikilinks_and_claude_imports(self):
        self.write("docs/ok.md", "synthetic\n")
        self.write("docs/wiki.md", "synthetic\n")
        self.write("docs/tool.py", "synthetic\n")
        self.write("docs/space file.md", "synthetic\n")
        parent = self.vault / "parent.md"
        parent.write_text("synthetic\n")
        agents = self.write(
            "AGENTS.md",
            "# Agent\n"
            "[relative](docs/ok.md)\n"
            "[[docs/wiki]]\n"
            "`docs/tool.py`\n"
            "[space](<docs/space file.md> \"Local title\")\n"
            "@./soul.md\n"
            "[parent](../parent.md)\n"
            "[broken](docs/missing.md)\n"
            "[placeholder]({workspace}/file.md)\n",
        )
        report = self.scan()
        missing = self.findings(report, "markdown_reference")
        self.assertEqual("docs/missing.md", missing[0]["target"])
        self.assertEqual("missing", missing[0]["state"])
        self.assertEqual(8, missing[0]["line"])
        placeholders = [row for row in missing if row["state"] == "uncheckable"]
        self.assertEqual("{workspace}/file.md", placeholders[0]["target"])
        states = {
            (row["kind"], row["target"]): row["state"]
            for row in report["references"]
            if row["file"] == "demo/AGENTS.md"
        }
        self.assertEqual("resolved", states[("markdown", "docs/ok.md")])
        self.assertEqual("resolved", states[("wikilink", "docs/wiki")])
        self.assertEqual("resolved", states[("path", "docs/tool.py")])
        self.assertEqual("resolved", states[("markdown", "docs/space file.md")])
        self.assertEqual("resolved", states[("claude_import", "./soul.md")])
        self.assertEqual("resolved", states[("markdown", "../parent.md")])
        self.assertEqual(agents.read_text().count("\n"), 9)

    def test_stale_and_valid_skills_and_declared_commands(self):
        self.skill("log")
        self.write("tools/check.py", "# synthetic\n")
        injection_target = self.root / "must-not-exist"
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "Use $fx-log and $log.\n"
            "Use `/log · /missing-skill`.\n"
            "Run `$ rg --files` and `$ absent --version`.\n"
            "Run `python3 tools/check.py` without a shell.\n"
            "Run `python3 tools/missing.py` without a shell.\n"
            f"Keep `$ echo $(touch {injection_target})` inert.\n"
            "The words fx-log is stale are explanatory.\n",
        )
        report = self.scan()
        self.assertEqual(["fx-log"], [row["target"] for row in self.findings(report, "stale_skill")])
        self.assertEqual(["absent"], [row["target"] for row in self.findings(report, "command_reference")])
        syntax = self.findings(report, "command_syntax_uncheckable")
        self.assertEqual(1, len(syntax))
        self.assertFalse(injection_target.exists())
        valid = {(row["kind"], row["target"], row["state"]) for row in report["references"]}
        self.assertIn(("skill", "log", "resolved"), valid)
        self.assertIn(("skill", "missing-skill", "missing"), valid)
        self.assertIn(("command", "rg", "resolved"), valid)
        self.assertIn(("command", "python3", "resolved"), valid)
        self.assertIn(("command_path", "tools/check.py", "resolved"), valid)
        self.assertIn(("command_path", "tools/missing.py", "missing"), valid)

    def test_status_size_and_tool_inventory_policies(self):
        self.write("SCHEMA.md", "---\nstatus: draft\n---\n# Schema\n")
        self.write("soul.md", "# Soul\n## Tools\n- one\n")
        self.write("CAPABILITIES.md", "# Capabilities\n## Tools\n- one\n- two\n- three\n")
        self.write("AGENTS.md", "# Agent\n## Commands\n- source: `CAPABILITIES.md`\n")
        rules = json.loads(RULES.read_text())
        rules["recognized_contracts"]["GLOSSARY.md"]["max_lines"] = 2
        local_rules = self.root / "rules.json"
        local_rules.write_text(json.dumps(rules))
        self.write("GLOSSARY.md", "# Glossary\none\ntwo\n")
        report = self.scan(rules_path=local_rules)
        self.assertEqual(1, len(self.findings(report, "frontmatter_status_forbidden")))
        inventory = self.findings(report, "tool_inventory_prohibited")
        self.assertEqual(["demo/soul.md"], [row["file"] for row in inventory])
        self.assertFalse(any(row["file"] == "demo/CAPABILITIES.md" for row in inventory))
        self.assertFalse(any(row["file"] == "demo/AGENTS.md" for row in inventory))
        size = self.findings(report, "contract_size_policy")
        self.assertEqual("existing 80-line checker policy for listed legacy contract types; configurable, not an approved one-screen definition; configured limit=2", size[0]["resolution_evidence"])

    def test_optional_soul_generated_sizes_and_resolver_writers_policy(self):
        (self.workspace / "soul.md").unlink()
        self.write("CLAUDE.md", "# Claude\n" + "line\n" * 79)
        self.write("CAPABILITIES.md", "# Capabilities\n" + "line\n" * 150)
        self.write("index.md", "# Index\n" + "line\n" * 150)
        self.write("RESOLVER.md", "# Resolver\n## Canonical writers\n- tasks: table\n")
        report = self.scan()
        required = self.findings(report, "required_contract_missing")
        self.assertFalse(any(row["target"] == "soul.md" for row in required))
        self.assertFalse(any(row["file"].endswith(("CLAUDE.md", "CAPABILITIES.md", "index.md")) for row in self.findings(report, "contract_size_policy")))
        self.assertFalse(any(row["file"].endswith("RESOLVER.md") for row in self.findings(report, "tool_inventory_prohibited")))

    def test_approval_is_uncheckable_without_explicit_source(self):
        agents = self.write("AGENTS.md", "# Agent\nRequires approval://release-1.\n")
        report = self.scan()
        finding = self.findings(report, "approval_reference")[0]
        self.assertEqual("uncheckable", finding["state"])
        coverage = [row for row in self.findings(report, "approval_coverage") if row["file"] == "demo/AGENTS.md"]
        self.assertEqual(1, len(coverage))
        source = self.root / "approvals.json"
        source.write_text(json.dumps({"approvals": ["release-1"]}))
        with self.assertRaisesRegex(lint.LintError, "invalid binding"):
            self.scan(approval_source=source)
        source.write_text(json.dumps({"approvals": [{
            "file": "demo/AGENTS.md",
            "sha256": hashlib.sha256(agents.read_bytes()).hexdigest(),
            "approval": "release-1",
        }]}))
        report = self.scan(approval_source=source)
        self.assertFalse([row for row in self.findings(report, "approval_reference") if row["file"] == "demo/AGENTS.md"])
        self.assertFalse([row for row in self.findings(report, "approval_coverage") if row["file"] == "demo/AGENTS.md"])

        source.write_text(json.dumps({"approvals": [{
            "file": "demo/AGENTS.md",
            "sha256": "0" * 64,
            "approval": "release-1",
        }]}))
        report = self.scan(approval_source=source)
        self.assertEqual("uncheckable", [row for row in self.findings(report, "approval_reference") if row["file"] == "demo/AGENTS.md"][0]["state"])
        self.assertEqual(1, len([row for row in self.findings(report, "approval_coverage") if row["file"] == "demo/AGENTS.md"]))

    def test_workspace_scan_does_not_crawl_archives_or_unrecognized_files(self):
        archived = self.write("archive/AGENTS.md", "$fx-log\n")
        unrecognized = self.write("notes.md", "$fx-log\n")
        before = {path: path.read_bytes() for path in (archived, unrecognized)}
        report = self.scan()
        self.assertEqual(set(CONTRACTS), {Path(row["file"]).relative_to("demo").as_posix() for row in report["scanned"]})
        self.assertFalse(self.findings(report, "stale_skill"))
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_explicit_nested_contract_allowed_but_runtime_secret_and_symlink_refused(self):
        nested = self.workspace / "agents/synthetic/soul.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("# Voice\n")
        report = self.scan(workspace=None, paths=[nested])
        self.assertEqual(["demo/agents/synthetic/soul.md"], [row["file"] for row in report["scanned"]])

        runtime = self.workspace / ".claude/agents/synthetic/soul.md"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("# Voice\n")
        with self.assertRaisesRegex(lint.LintError, "protected path part"):
            self.scan(workspace=None, paths=[runtime])

        secret = self.workspace / "secrets/soul.md"
        secret.parent.mkdir()
        secret.write_text("# Secret\n")
        with self.assertRaisesRegex(lint.LintError, "protected path part"):
            self.scan(workspace=None, paths=[secret])

        target = self.workspace / "soul.md"
        linked = self.workspace / "agents/synthetic/AGENTS.md"
        linked.parent.mkdir(parents=True, exist_ok=True)
        linked.symlink_to(target)
        with self.assertRaisesRegex(lint.LintError, "symlink boundary"):
            self.scan(workspace=None, paths=[linked])

    def test_dot_segments_and_symlink_parents_cannot_escape_boundaries(self):
        outside = self.root / "outside/soul.md"
        outside.parent.mkdir()
        outside.write_text("# Outside\n")
        escaped = self.workspace / "../.." / "outside/soul.md"
        with self.assertRaisesRegex(lint.LintError, "outside declared roots"):
            self.scan(workspace=None, paths=[escaped])

        vault_alias = self.root / "vault-alias"
        vault_alias.symlink_to(self.vault, target_is_directory=True)
        with self.assertRaisesRegex(lint.LintError, "non-symlink directory"):
            self.scan(vault_root=vault_alias, workspace=vault_alias / "demo")

        report = self.scan()
        out = self.root / "out"
        out.mkdir()
        with self.assertRaisesRegex(lint.LintError, "outside scanned roots"):
            lint.save_report(report, out / ".." / "vault/demo/escaped.json")
        out_alias = self.root / "out-alias"
        out_alias.symlink_to(out, target_is_directory=True)
        with self.assertRaisesRegex(lint.LintError, "report parent"):
            lint.save_report(report, out_alias / "lint.json")

    def test_skill_symlink_is_uncheckable_not_missing(self):
        external = self.root / "external-log"
        external.mkdir()
        (external / "SKILL.md").write_text("# Synthetic\n")
        (self.skills / "log").symlink_to(external, target_is_directory=True)
        self.write("AGENTS.md", "# Agent\nUse $log.\n")
        report = self.scan()
        finding = self.findings(report, "skill_reference")[0]
        self.assertEqual("uncheckable", finding["state"])
        self.assertIn("symlink boundary", finding["resolution_evidence"])

    def test_undeclared_skill_shelf_does_not_prove_missing_skill(self):
        self.write("AGENTS.md", "# Agent\nUse $log.\n")
        report = self.scan(skill_roots=[])
        finding = self.findings(report, "skill_reference")[0]
        self.assertEqual("uncheckable", finding["state"])
        self.assertEqual("no skill shelf was declared", finding["resolution_evidence"])

    def test_duplicate_roots_and_paths_are_refused(self):
        with self.assertRaisesRegex(lint.LintError, "duplicate skill root"):
            self.scan(skill_roots=[self.skills, self.skills])
        with self.assertRaisesRegex(lint.LintError, "duplicate explicit contract path"):
            self.scan(workspace=None, paths=[self.workspace / "AGENTS.md", self.workspace / "AGENTS.md"])

    def test_safe_report_output_preserves_existing_files(self):
        report = self.scan()
        out = self.root / "out"
        out.mkdir()
        first = lint.save_report(report, out / "lint.json")
        original = first.read_bytes()
        second = lint.save_report(report, out / "lint.json")
        self.assertEqual("lint.new.json", second.name)
        self.assertEqual(original, first.read_bytes())
        with self.assertRaises(FileExistsError):
            lint.save_report(report, out / "lint.json")
        with self.assertRaisesRegex(lint.LintError, "outside scanned roots"):
            lint.save_report(report, self.workspace / "lint.json")

    def test_reference_links_resolve_full_collapsed_and_shortcut_at_use_lines(self):
        self.write("docs/one file.md", "one\n")
        self.write("docs/two.md", "two\n")
        self.write("docs/three.md", "three\n")
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "Read [one][First ref].\n"
            "Read [Second ref][].\n"
            "Read [third ref].\n"
            "[first ref]: <docs/one file.md> \"One title\"\n"
            "[second ref]: docs/two.md 'Two title'\n"
            "[THIRD REF]: docs/three.md (Three title)\n",
        )
        report = self.scan()
        refs = [row for row in report["references"] if row["file"] == "demo/AGENTS.md"]
        observed = [(row["target"], row["line"], row["state"]) for row in refs]
        self.assertEqual([
            ("docs/one file.md", 2, "resolved"),
            ("docs/two.md", 3, "resolved"),
            ("docs/three.md", 4, "resolved"),
        ], observed)
        self.assertFalse(self.findings(report, "reference_syntax_uncheckable"))

    def test_unresolved_and_duplicate_reference_definitions_are_visible(self):
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "Read [missing][not-defined].\n"
            "Read [duplicate].\n"
            "Read [web] and [jump].\n"
            "[duplicate]: docs/one.md\n"
            "[DUPLICATE]: docs/two.md\n"
            "[web]: https://example.invalid/page\n"
            "[jump]: #section\n",
        )
        report = self.scan()
        findings = self.findings(report, "reference_syntax_uncheckable")
        self.assertEqual([(2, "not-defined"), (3, "duplicate")], [(row["line"], row["target"]) for row in findings])
        self.assertIn("lines 5, 6", findings[1]["resolution_evidence"])
        self.assertFalse(any(row["target"] in {"https://example.invalid/page", "#section"} for row in report["references"]))

        self.write("AGENTS.md", "# Agent\n[ref]: docs/ok.md\n[site](https://example.invalid)\n[[Unknown Name]]\n[Unknown Name]: docs/ok.md\n`docs/*.md`\n")
        report = self.scan()
        external = self.findings(report, "markdown_reference")[0]
        self.assertEqual("uncheckable", external["state"])
        self.assertEqual("uncheckable", self.findings(report, "wikilink_reference")[0]["state"])
        self.assertEqual("uncheckable", self.findings(report, "path_reference")[0]["state"])
        self.assertFalse(any(row["kind"] == "markdown" and row["target"] == "docs/ok.md" for row in report["references"]))

    def test_reference_examples_in_inline_code_and_escaped_brackets_are_inert(self):
        self.write("docs/live.md", "live\n")
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "Use `[sample][doc]` as an example.\n"
            "Use ``[sample][doc]`` as another example.\n"
            "Escaped: \\[sample][doc].\n"
            "Live: [sample][doc].\n"
            "[doc]: docs/live.md\n",
        )
        report = self.scan()
        refs = [row for row in report["references"] if row["kind"] == "markdown"]
        self.assertEqual([("docs/live.md", 5)], [(row["target"], row["line"]) for row in refs])

    def test_fenced_shell_literal_scripts_are_checked_and_dynamic_syntax_is_inert(self):
        self.write("tools/check.py", "# synthetic\n")
        self.write("tools/run.sh", "# synthetic\n")
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "Use `bare-name`.\n"
            "```bash\n"
            "python3 tools/check.py\n"
            "./tools/run.sh --dry-run\n"
            "python3 $SCRIPT\n"
            "python3 $(resolve-script)\n"
            "python3 $1\n"
            "python3 ${1}\n"
            "python3 $?\n"
            "python3 $@\n"
            "python3 ${@}\n"
            "python3 $$\n"
            "python3 $!\n"
            "python3 tools/check.py &\n"
            "if python3 tools/check.py\n"
            "# python3 tools/comment.py\n"
            "```\n"
            "```python\n"
            "python3 tools/not-shell.py\n"
            "```\n",
        )
        report = self.scan()
        bare = self.findings(report, "inline_code_uncheckable")
        fenced = self.findings(report, "fenced_block_uncheckable")
        syntax = self.findings(report, "command_syntax_uncheckable")
        self.assertEqual(["bare-name"], [row["target"] for row in bare])
        self.assertEqual(["python"], [row["target"] for row in fenced])
        self.assertEqual(list(range(6, 17)), [row["line"] for row in syntax])
        refs = {(row["kind"], row["target"], row["line"], row["state"]) for row in report["references"]}
        self.assertIn(("command", "python3", 4, "resolved"), refs)
        self.assertIn(("command_path", "tools/check.py", 4, "resolved"), refs)
        self.assertIn(("command_path", "./tools/run.sh", 5, "resolved"), refs)
        self.assertFalse(any(row["target"] in {"$SCRIPT", "tools/comment.py", "tools/not-shell.py"} for row in report["references"]))

    def test_fence_length_and_tilde_fences_preserve_inert_examples(self):
        self.write("docs/live.md", "live\n")
        self.write("tools/check.py", "# synthetic\n")
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "````markdown\n"
            "```\n"
            "[hidden][doc]\n"
            "python3 tools/hidden.py\n"
            "````\n"
            "[doc]: docs/live.md\n"
            "~~~sh\n"
            "python3 tools/check.py\n"
            "~~~\n",
        )
        report = self.scan()
        self.assertFalse(any(row["target"] in {"docs/live.md", "tools/hidden.py"} for row in report["references"]))
        self.assertIn(
            ("command_path", "tools/check.py", 9, "resolved"),
            {(row["kind"], row["target"], row["line"], row["state"]) for row in report["references"]},
        )

    def test_shell_prose_and_python_code_strings_are_not_script_paths(self):
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "```bash\n"
            "echo tools/not-required.py\n"
            "printf '%s' tools/not-required.sh\n"
            "python3 -c \"print('tools/not-required.py')\"\n"
            "```\n",
        )
        report = self.scan()
        self.assertFalse(any(row["kind"] == "command_path" for row in report["references"]))
        syntax = self.findings(report, "command_syntax_uncheckable")
        self.assertEqual([(5, "python3 -c \"print('tools/not-required.py')\"")], [(row["line"], row["target"]) for row in syntax])

    def test_source_builtins_are_uncheckable_while_literal_paths_are_checked(self):
        self.write("tools/load.sh", "# synthetic\n")
        self.write(
            "AGENTS.md",
            "# Agent\n"
            "```sh\n"
            "source tools/load.sh\n"
            ". tools/load.sh\n"
            "```\n",
        )
        report = self.scan()
        builtins = self.findings(report, "command_builtin_uncheckable")
        self.assertEqual([(3, "source"), (4, ".")], [(row["line"], row["target"]) for row in builtins])
        paths = [row for row in report["references"] if row["kind"] == "command_path"]
        self.assertEqual([(3, "tools/load.sh", "resolved"), (4, "tools/load.sh", "resolved")], [(row["line"], row["target"], row["state"]) for row in paths])
        self.assertFalse(any(row["kind"] == "command" and row["target"] in {"source", "."} for row in report["references"]))

    def test_base_checker_opt_in_attachment_is_checkout_relative(self):
        module = load_checkout_module(
            "contract_lint_test_check_workspace",
            "base/check_workspace.py",
        )
        source = Path(module.__file__)
        before = hashlib.sha256(source.read_bytes()).hexdigest()

        plain_output = io.StringIO()
        with redirect_stdout(plain_output), redirect_stderr(io.StringIO()):
            plain_exit = module.main([str(self.workspace)])
        plain = json.loads(plain_output.getvalue())
        self.assertEqual(1, plain_exit)
        self.assertNotIn("contract_lint", plain)

        lint_output = io.StringIO()
        with redirect_stdout(lint_output), redirect_stderr(io.StringIO()):
            lint_exit = module.main([
                str(self.workspace),
                "--contract-lint-rules", str(RULES),
                "--contract-lint-vault-root", str(self.vault),
                "--contract-lint-skill-root", str(self.skills),
                "--contract-lint-command-inventory", str(self.commands),
            ])
        attached = json.loads(lint_output.getvalue())
        self.assertEqual(1, lint_exit)
        self.assertEqual("foxrun-contract-lint/v1", attached["contract_lint"]["format"])
        self.assertTrue(any(row["rule"] == "approval_coverage" for row in attached["contract_lint"]["unchecked"]))
        self.assertFalse(any(row["state"] == "uncheckable" for row in attached["contract_lint"]["findings"]))
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_daily_checker_opt_in_keeps_no_notify_default(self):
        try:
            import yaml  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("PyYAML is not installed for the vault checker integration")
        fixtures = load_checkout_module(
            "contract_lint_test_schema_fixtures",
            "scripts/tests/schema_fixtures.py",
        )
        module = load_checkout_module(
            "contract_lint_test_workspace_check",
            "scripts/workspace_check.py",
        )
        built = fixtures.build(self.root / "daily-source")
        vault = self.root / "daily-vault"
        shutil.copytree(built / "cedar-shop", vault / "cedar-shop")
        shutil.copytree(built / "system-workspace", vault / "system-workspace")
        contract = json.loads((built / "contract.json").read_text())
        contract["wiki_roots"] = {
            key: value for key, value in contract["wiki_roots"].items()
            if key.startswith("cedar-shop/")
        }
        contract["immutable_bodies"] = {
            key: value for key, value in contract["immutable_bodies"].items()
            if key.startswith("cedar-shop/")
        }
        config = self.root / "daily-config"
        config.mkdir()
        contract_path = config / "contract.json"
        protected_path = config / "protected.json"
        provenance_path = config / "provenance.json"
        contract_path.write_text(json.dumps(contract))
        protected_path.write_text("[]")
        provenance_path.write_text(json.dumps({"rows": []}))
        out = self.root / "daily-out"
        args = module.build_parser().parse_args([
            "run",
            "--workspace", "cedar-shop",
            "--vault", str(vault),
            "--contract", str(contract_path),
            "--protected", str(protected_path),
            "--provenance", str(provenance_path),
            "--out-root", str(out),
            "--contract-lint-rules", str(RULES),
            "--contract-lint-skill-root", str(self.skills),
            "--contract-lint-command-inventory", str(self.commands),
        ])
        self.assertFalse(args.notify)
        sent = []
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            exit_code = module.run_from_args(args, sender=sent.append)
        report = json.loads((out / "latest.json").read_text())
        self.assertEqual(1, exit_code)
        self.assertEqual([], sent)
        self.assertEqual("foxrun-contract-lint/v1", report["contract_lint"]["format"])
        self.assertGreater(report["contract_lint_count"], 0)
        self.assertEqual(report["contract_lint_count"], len(report["contract_lint"]["findings"]))
        self.assertTrue(any(row["rule"] == "required_contract_missing" for row in report["contract_lint"]["findings"]))
        self.assertTrue(any(row["rule"] == "approval_coverage" for row in report["contract_lint"]["unchecked"]))

    def test_explicit_runtime_contract_allowed_but_secret_and_symlink_refused(self):
        runtime = self.workspace / ".claude/agents/synthetic/soul.md"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("# Voice\n")
        with self.assertRaisesRegex(lint.LintError, "protected path part"):
            self.scan(workspace=None, paths=[runtime])

        secret = self.workspace / "secrets/soul.md"
        secret.parent.mkdir()
        secret.write_text("# Secret\n")
        with self.assertRaisesRegex(lint.LintError, "protected path part"):
            self.scan(workspace=None, paths=[secret])

        target = self.workspace / "soul.md"
        linked = self.workspace / "agents/synthetic/AGENTS.md"
        linked.parent.mkdir(parents=True, exist_ok=True)
        linked.symlink_to(target)
        with self.assertRaisesRegex(lint.LintError, "symlink boundary"):
            self.scan(workspace=None, paths=[linked])



class ContractRequestTests(unittest.TestCase):
    def test_current_shared_contracts_are_explicit_inputs(self):
        from base import contract_test
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ('profile/AGENTS.md', 'agents/soul.md', 'demo/AGENTS.md'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('# Contract\n')
            names = ['agents/soul.md', 'profile/AGENTS.md', 'demo/AGENTS.md']
            result = contract_test.request(root, 'demo', names, [])
            self.assertEqual([row['path'] for row in result['contracts']], names)
            for name in ('profile/nested/AGENTS.md', 'agents/nested/soul.md', '../AGENTS.md'):
                with self.subTest(path=name), self.assertRaises(ValueError):
                    contract_test.request(root, 'demo', [name], [])
            (root / 'profile/AGENTS.md').unlink()
            (root / 'profile/AGENTS.md').symlink_to(root / 'demo/AGENTS.md')
            with self.assertRaisesRegex(ValueError, 'symlink boundary'):
                contract_test.request(root, 'demo', ['profile/AGENTS.md'], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
