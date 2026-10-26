#!/usr/bin/env python3
"""Synthetic tests for the CAPABILITIES preview renderer."""

from __future__ import annotations
import sys
from pathlib import Path as _SupportPath
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[2] / "base"))
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1]))
# agents/ goes ahead of base/ so tests.support is this folder, not base/tests (collision since 9e44892 T595)
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1] / "tools"))

from tests.support import function_suite

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import simple_yaml as yaml

import render_capabilities as renderer


class CapabilityRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="capabilities-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.vault = self.root / "vault"
        self.modules = self.root / "modules"
        previous_modules = os.environ.get("FOXRUN_HOME")
        os.environ["FOXRUN_HOME"] = str(self.modules.parent)
        self.addCleanup(lambda: os.environ.pop("FOXRUN_HOME", None) if previous_modules is None else os.environ.__setitem__("FOXRUN_HOME", previous_modules))
        self.workspace = self.vault / "alpha-work"
        self.unbound = self.vault / "unbound"
        self.release = self.root / "release"
        self.shelf = self.root / "shelf"
        self.output = self.root / "preview.md"
        for path in (
            self.repo  , self.repo / "execution" / "teams", self.repo / "execution" / "workflows",
            self.repo / "execution", self.repo, self.workspace, self.unbound,
            self.vault / "other", self.modules / "base/templates-v2",
            self.modules / "base/tools", self.vault / "system-workspace/docs",
            self.modules / "work/tools",
            self.release / "skill-a", self.release / "skill-b", self.release / "skill-c",
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.shelf.symlink_to(self.release, target_is_directory=True)
        (self.release / "skill-a/SKILL.md").write_text("not read", encoding="utf-8")
        (self.release / "skill-b/SKILL.md").write_text("not read", encoding="utf-8")
        (self.release / "skill-c/SKILL.md").write_text("not read", encoding="utf-8")
        self.make_repo()
        self.make_vault()

    def agent(self, agent_id: str, *, client: str | None = None, skills=None, tools=None, role=None) -> None:
        data = {
            "id": agent_id,
            "display_name": agent_id.title(),
            "role": role or "Owns synthetic work",
            "summary": "Synthetic identity",
            "tier": "work",
            "shared": False,
            "client_default": client,
            "runtimes": ["codex"],
            "hermes_mode": "child",
            "hermes_profile": None,
            "skills": skills or [],
            "tools": tools or [],
            "return_default": "lead",
            "version": 1,
            "type": "agent-soul",
            "workspace": client or "system",
            "timestamp": "2026-09-20T09:00:00-04:00",
        }
        text = "---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n# " + data["display_name"] + "\n"
        (self.repo / f"{agent_id}.md").write_text(text, encoding="utf-8")

    def make_repo(self) -> None:
        loader = r'''from pathlib import Path
from types import SimpleNamespace
import simple_yaml as yaml
def load_identity(agent_id, repo):
    text=(Path(repo)/(agent_id+".md")).read_text()
    front=text[4:].split("\n---\n",1)[0]
    return SimpleNamespace(data=yaml.safe_load(front))
def team_data(identity, repo):
    return {}
# the renderer calls resolve_capabilities since 4a024f1 (T740 catalog expansion)
def resolve_capabilities(data, path):
    return data
'''
        (self.repo / "agent_new.py").write_text(loader, encoding="utf-8")
        (self.repo.parent / "config").mkdir(parents=True, exist_ok=True)
        (self.repo.parent / "config/models.yaml").write_text("tiers:\n  work: {}\n", encoding="utf-8")
        self.agent(
            "alpha", client="alpha-work", skills=["skill-a", "missing-skill"], tools=["mcp-a"],
            role="Owns | synthetic <b>![x](evil)</b>",
        )
        self.agent("beta", skills=["skill-b"], tools=["mcp-b"])
        self.agent("gamma", client="other", skills=["skill-c"], tools=["mcp-gamma"])
        team = {
            "client": "alpha-work", "lead": "alpha", "workspace": str(self.workspace),
            "contract": str(self.workspace / "AGENTS.md"),
            "members": {"account": ["beta"], "shared": []},
        }
        (self.repo / "execution/teams/alpha-work.yaml").write_text(yaml.safe_dump(team, sort_keys=False), encoding="utf-8")
        other = {
            "client": "other", "lead": "gamma", "workspace": str(self.vault / "other"),
            "contract": str(self.vault / "other/AGENTS.md"),
            "members": {"account": [], "shared": []},
        }
        (self.repo / "execution/teams/other.yaml").write_text(yaml.safe_dump(other, sort_keys=False), encoding="utf-8")
        (self.repo / "execution/workflows/flow.md").write_text(
            "# Workflow — test\n\n"
            "| Step | Identity | Input | Output | Return |\n"
            "|---|---|---|---|---|\n"
            "| 1 Do | alpha | request | result | lead |\n",
            encoding="utf-8",
        )
        (self.repo / "execution/workflows/foreign.md").write_text(
            "# Workflow — foreign\n\n"
            "| Step | Identity | Input | Output | Return |\n"
            "|---|---|---|---|---|\n"
            "| 1 Do | gamma | other | foreign | outside |\n",
            encoding="utf-8",
        )
        # current behavior since 4a024f1 (T740): the skill registry and its gaps live in config/catalog.yaml beside the repo
        skills = {
            "sets": {"base": {"skills": [], "tools": []}},
            "shelf": str(self.shelf),
            "gaps": [{"id": "declared-gap", "needed_by": ["beta"], "note": "not built"}],
        }
        (self.repo.parent / "config/catalog.yaml").write_text(yaml.safe_dump(skills, sort_keys=False), encoding="utf-8")

    def make_vault(self) -> None:
        template = "---\ntype: capabilities\n---\n# CAPABILITIES\n\n" + "\n".join("## " + section for section in renderer.SECTIONS) + "\n"
        (self.modules / "base/templates-v2/CAPABILITIES.md").write_text(template, encoding="utf-8")
        decisions = [
            {"id": "pr-capabilities-md", "status": "ruled"},
            {"id": "workflow", "status": "ruled"},
        ]
        (self.vault / "system-workspace/docs/capability-decisions.jsonl").write_text(
            "\n".join(json.dumps(row) for row in decisions) + "\n", encoding="utf-8"
        )
        (self.modules / "base/install.json").write_text(
            json.dumps({"files": [], "blueprint": False}), encoding="utf-8"
        )
        wrapper = self.modules / "base/tools/cmd"
        wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
        wrapper.chmod(0o755)
        (self.modules / "work/install.json").write_text(
            json.dumps({"files": [], "blueprint": True}), encoding="utf-8"
        )
        work = self.modules / "work/tools/work.py"
        work.write_text(
            "def main():\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
            encoding="utf-8",
        )
        helper = self.modules / "work/tools/helper.py"
        helper.write_text("def helper():\n    return 1\n", encoding="utf-8")
        helper.chmod(0o755)
        (self.modules / "work/tools/README.md").write_text(
            "Run `python3 work.py --help`.\n", encoding="utf-8"
        )

    def args(self, workspace: Path | None = None, output: Path | None = None, *extra: str) -> list[str]:
        return [
            "--repo", str(self.repo), "--workspace", str(workspace or self.workspace),
            "--vault", str(self.vault), "--output", str(output or self.output),
            "--skill-shelf", str(self.shelf), "--timestamp", "2026-09-20T10:00:00Z", *extra,
        ]

    def test_team_filtering_sections_missing_skills_and_safe_escaping(self):
        self.assertEqual(0, renderer.main(self.args()))
        text = self.output.read_text(encoding="utf-8")
        positions = [text.index("## " + section) for section in renderer.SECTIONS]
        self.assertEqual(sorted(positions), positions)
        self.assertIn("Alpha", text)
        self.assertIn("assigned by exact team binding", text)
        self.assertNotIn("Gamma", text)
        self.assertNotIn("Workflow — foreign", text)
        self.assertNotIn("skill-c", text)
        self.assertNotIn("mcp-gamma", text)
        self.assertIn("missing-skill", text)
        self.assertIn("missing: SKILL.md is not present", text)
        self.assertIn("skill-a", text)
        self.assertIn("available: SKILL.md exists; body not read", text)
        self.assertIn("missing Skill column; implementation uncheckable", text)
        self.assertIn("candidate for exact team; workspace installation unverified", text)
        self.assertIn("Owns \\| synthetic &lt;b&gt;\\!\\[x\\]\\(evil\\)&lt;/b&gt;", text)
        self.assertNotIn("<b>", text)
        self.assertNotIn("![x](evil)", text)
        self.assertIn("runtime-unverified", text)
        self.assertIn("unverified: selected manifests do not declare workspace command installation", text)
        self.assertIn("python3 " + str(self.modules / "work/tools/work.py").replace("_", "\\_"), text)
        self.assertIn("Python \\_\\_main\\_\\_ entry point", text)
        self.assertIn("README: modules:work/tools/README.md:1", text)
        self.assertNotIn("helper.py", text)
        self.assertIn("not inventoried by selected safe sources; this does not mean absent", text)
        self.assertNotIn("status:", text)

    def test_undeclared_workspace_never_assigns_by_guessing(self):
        model, _ = renderer.build_model(self.repo, self.vault, self.unbound, self.shelf)
        self.assertEqual("unknown", model["binding"]["state"])
        text = renderer.render_markdown(model, {"sha256": "x"}, "2026-09-20T10:00:00Z")
        self.assertNotIn("assigned by team binding", text)
        self.assertIn("unknown: no exact team workspace binding", text)
        self.assertNotIn("Alpha", text)
        self.assertNotIn("Workflow — test", text)
        self.assertNotIn("skill-a", text)
        self.assertNotIn("mcp-a", text)
        self.assertIn("Source registry: `repo:execution/teams/`", text)

    def test_check_detects_changed_source(self):
        self.assertEqual(0, renderer.main(self.args()))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(0, renderer.main(self.args(None, None, "--check")))
        path = self.repo / "execution/workflows/flow.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSource changed.\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(1, renderer.main(self.args(None, None, "--check")))

    def test_duplicate_agent_ids_are_refused(self):
        original = (self.repo / "alpha.md").read_text(encoding="utf-8")
        (self.repo / "duplicate.md").write_text(original, encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args()))

    def test_unsafe_sources_and_workspace_escape_are_refused(self):
        outside = self.root / "outside.md"
        outside.write_text("---\nid: outside\n---\n", encoding="utf-8")
        (self.repo / "evil.md").symlink_to(outside)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args()))
        (self.repo / "evil.md").unlink()
        outside_workspace = self.root / "outside-workspace"
        outside_workspace.mkdir()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args(outside_workspace)))

    def test_authored_output_is_never_overwritten(self):
        self.output.write_text("# Human page\n", encoding="utf-8")
        before = self.output.read_text(encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args()))
        self.assertEqual(before, self.output.read_text(encoding="utf-8"))

    def test_output_parent_and_sidecar_aliases_are_refused_without_writes(self):
        target = self.root / "target"
        target.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(target, target_is_directory=True)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args(None, linked_parent / "preview.md")))
        self.assertFalse((target / "preview.md").exists())

        sidecar_target = self.root / "foreign-sidecar"
        sidecar_target.write_text("foreign", encoding="utf-8")
        sidecar = self.output.with_name(self.output.name + ".manifest.json")
        sidecar.symlink_to(sidecar_target)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args()))
        self.assertFalse(self.output.exists())
        self.assertEqual(b"foreign", sidecar_target.read_bytes())

    def test_authored_or_mismatched_sidecar_preserves_both_files(self):
        self.assertEqual(0, renderer.main(self.args()))
        sidecar = self.output.with_name(self.output.name + ".manifest.json")
        sidecar.write_text('{"format": 1, "output_sha256": "wrong"}\n', encoding="utf-8")
        output_before, sidecar_before = self.output.read_bytes(), sidecar.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args()))
        self.assertEqual(output_before, self.output.read_bytes())
        self.assertEqual(sidecar_before, sidecar.read_bytes())

    def test_duplicate_yaml_keys_and_invalid_gap_ids_are_refused(self):
        team = self.repo / "execution/teams/alpha-work.yaml"
        team.write_text(team.read_text(encoding="utf-8") + "client: duplicate\n", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args()))
        self.make_repo()
        # current behavior since 4a024f1 (T740): gap ids are read from config/catalog.yaml
        skills = self.repo.parent / "config/catalog.yaml"
        data = yaml.safe_load(skills.read_text(encoding="utf-8"))
        data["gaps"].append({"id": "../escape", "needed_by": ["alpha"]})
        skills.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(2, renderer.main(self.args()))

    def test_unsupported_team_shape_is_visible_uncheckable(self):
        path = self.repo / "execution/teams/alpha-work.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["members"] = ["beta"]
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        model, _ = renderer.build_model(self.repo, self.vault, self.workspace, self.shelf)
        reasons = [row["reason"] for row in model["gaps"]]
        self.assertIn("team members is not a mapping", reasons)
        self.assertEqual("unknown", model["binding"]["state"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
