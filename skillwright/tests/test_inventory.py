import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tools" / "skill_inventory.py"


def run(*args, cwd=None, check=True):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.active = self.root / "active"
        self.claude = self.root / "claude"
        self.repo.mkdir()
        self.active.mkdir()
        self.claude.mkdir()

        run("git", "init", "-b", "main", cwd=self.repo)
        run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        run("git", "config", "user.name", "Test", cwd=self.repo)
        self.write_skill(self.repo / "skills/alpha", "alpha v1")
        run("git", "add", "skills/alpha", cwd=self.repo)
        run("git", "commit", "-m", "alpha v1", cwd=self.repo)
        run("git", "switch", "-c", "alternate", cwd=self.repo)
        self.write_skill(self.repo / "skills/alpha", "alpha v2")
        self.write_skill(self.repo / "skills/beta", "beta")
        self.write_skill(self.repo / "skills/gamma", "gamma candidate")
        run("git", "add", "skills/alpha", "skills/beta", "skills/gamma", cwd=self.repo)
        run("git", "commit", "-m", "alternate", cwd=self.repo)

        self.write_skill(self.active / "alpha", "alpha v1")
        self.write_skill(self.claude / "claude-only", "claude only")
        self.write_skill(self.claude / "gamma", "gamma old copy")
        os.symlink(self.active / "alpha", self.claude / "alpha")
        os.symlink(self.active / "missing", self.claude / "broken")
        self.write_policy(["alpha", "beta", "gamma"])

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def write_skill(path, body):
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(body + "\n", encoding="utf-8")

    def write_policy(
        self,
        publish,
        exclude=None,
        preserve=None,
        host_specific=None,
        approval_required=None,
        where=None,
    ):
        path = self.repo / "config" / "catalog.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "where": where or {name: "off" for name in (exclude or {})},
                    "claude_preserve_physical": sorted(preserve or []),
                    "claude_approval_required": approval_required or {},
                    "host_specific": host_specific or {},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_build_detects_variants_and_claude_ownership(self):
        output = self.root / "baseline.yaml"
        run(
            INVENTORY,
            "build",
            "--repo",
            self.repo,
            "--ref",
            "main",
            "--ref",
            "alternate",
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            output,
        )

        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(manifest["skills"]["alpha"]["conflict"])
        self.assertFalse(manifest["skills"]["beta"]["conflict"])
        self.assertEqual(
            manifest["claude_entries"]["alpha"]["ownership"], "shared_link"
        )
        self.assertEqual(
            manifest["claude_entries"]["broken"]["ownership"], "broken_link"
        )
        self.assertEqual(
            manifest["claude_entries"]["claude-only"]["ownership"],
            "physical_copy",
        )

    def test_verify_fails_for_unresolved_conflicts(self):
        output = self.root / "baseline.yaml"
        run(
            INVENTORY,
            "build",
            "--repo",
            self.repo,
            "--ref",
            "main",
            "--ref",
            "alternate",
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            output,
        )
        result = run(INVENTORY, "verify", "--manifest", output, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unresolved conflicts: alpha", result.stderr)

    def test_resolve_selects_candidate_and_verifies(self):
        recovery = self.root / "baseline.yaml"
        resolved = self.root / "resolved.yaml"
        run(
            INVENTORY,
            "build",
            "--repo",
            self.repo,
            "--ref",
            "main",
            "--ref",
            "alternate",
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--candidate",
            self.repo,
            "--output",
            recovery,
        )
        run(
            INVENTORY,
            "resolve",
            "--manifest",
            recovery,
            "--output",
            resolved,
        )
        run(INVENTORY, "verify", "--manifest", resolved)
        manifest = json.loads(resolved.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["skills"]["alpha"]["resolution"]["selected_source"],
            "candidate",
        )

    def test_distribution_plans_only_candidate_owned_changes(self):
        output = self.root / "shipped.yaml"
        run(
            INVENTORY,
            "distribution",
            "--candidate",
            self.repo,
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            output,
        )
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"]["alpha"]["claude_action"], "keep_link")
        self.assertEqual(
            manifest["skills"]["gamma"]["claude_action"],
            "replace_physical_with_link",
        )
        self.assertEqual(manifest["skills"]["beta"]["claude_action"], "create_link")
        self.assertEqual(
            manifest["unmanaged_claude"]["claude-only"]["ownership"],
            "physical_copy",
        )

    def test_distribution_includes_a_new_source_without_a_rule(self):
        self.write_skill(self.repo / "skills/delta", "delta")
        result = run(
            INVENTORY,
            "distribution",
            "--candidate",
            self.repo,
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            self.root / "shipped.yaml",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.root / "shipped.yaml").read_text())
        self.assertIn("delta", manifest["skills"])

    def test_distribution_rejects_invalid_scope(self):
        self.write_policy([], where={"alpha": "global"})
        result = run(
            INVENTORY,
            "distribution",
            "--candidate",
            self.repo,
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            self.root / "shipped.yaml",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("where must be off or a nonempty workspace list: alpha", result.stderr)

    def test_distribution_off_rule_excludes_shared_source(self):
        self.write_policy(
            ["alpha", "beta", "gamma"],
            exclude={
                "beta": {
                    "status": "retired",
                    "reason": "test",
                    "claude": "absent",
                }
            },
        )
        result = run(
            INVENTORY,
            "distribution",
            "--candidate",
            self.repo,
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            self.root / "shipped.yaml",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.root / "shipped.yaml").read_text())
        self.assertNotIn("beta", manifest["skills"])
        self.assertIn("beta", manifest["excluded"])

    def test_distribution_preserves_declared_physical_and_host_skills(self):
        host = self.root / "host"
        self.write_skill(host, "host")
        self.write_skill(self.claude / "host", "host physical")
        self.write_policy(
            ["alpha", "beta", "gamma"],
            preserve=["gamma"],
            host_specific={
                "host": {
                    "codex_source": str(host),
                    "claude_source": str(self.claude / "host"),
                }
            },
        )
        output = self.root / "shipped.yaml"
        run(
            INVENTORY,
            "distribution",
            "--candidate",
            self.repo,
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            output,
        )
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"]["gamma"]["claude_action"], "preserve_physical")
        self.assertEqual(
            manifest["skills"]["host"]["claude_action"],
            "preserve_host_specific",
        )


if __name__ == "__main__":
    unittest.main()
