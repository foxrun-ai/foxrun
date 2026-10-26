import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
INVENTORY = PROJECT / "tools" / "skill_inventory.py"
PARITY = PROJECT / "tools" / "skill_route.py"


def run(*args, env=None, check=True):
    return subprocess.run(
        [str(arg) for arg in args],
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


class ParityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dojo = self.root / "dojo"
        self.active = self.root / "active"
        self.claude = self.root / "claude"
        self.candidate = self.root / "candidate"
        self.state = self.root / "state"
        for path in (self.dojo, self.active, self.claude, self.candidate):
            path.mkdir()
        for name in ("alpha", "beta"):
            self.write_skill(self.dojo / name, f"{name} candidate")
            self.write_skill(self.candidate / name, f"{name} candidate")
        self.write_skill(self.active / "alpha", "alpha old")
        self.write_skill(self.claude / "alpha", "alpha old")
        self.write_skill(self.claude / "claude-only", "claude only")
        os.symlink(self.active / "missing-beta", self.claude / "beta")
        self.write_policy(["alpha", "beta"])
        run(
            INVENTORY,
            "distribution",
            "--candidate",
            self.dojo,
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            self.dojo / "manifests" / "shipped.yaml",
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "SKILLS_DOJO_ROOT": str(self.dojo),
                "SKILL_STATE_ROOT": str(self.state),
                "SKILLS_ACTIVE_PATH": str(self.active),
                "SKILLS_CLAUDE_ROOT": str(self.claude),
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def write_skill(path, body):
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(body + "\n", encoding="utf-8")

    def write_policy(self, publish, approval_required=None, app_owned=()):
        path = self.dojo / "config" / "catalog.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        policy = {
            "version": 1,
            "publish": sorted(publish),
            "exclude": {},
            "claude_preserve_physical": [],
            "claude_approval_required": approval_required or {},
            "host_specific": {},
        }
        if app_owned:
            policy["claude_app_owned"] = {
                name: {"reason": "The Claude app owns this folder."} for name in app_owned
            }
        path.write_text(
            json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def declare_app_folder(self):
        account = self.claude / "synced" / "account"
        account.mkdir(parents=True)
        (account / "manifest.json").write_text("round 1\n", encoding="utf-8")
        self.write_policy(["alpha", "beta"], app_owned=["synced"])
        self.regenerate_distribution()
        return account

    def dry_run(self, *extra):
        return run(
            PARITY, "dry-run", "--candidate", self.candidate, *extra,
            env=self.env, check=False,
        )

    def regenerate_distribution(self):
        run(
            INVENTORY,
            "distribution",
            "--candidate",
            self.dojo,
            "--active",
            self.active,
            "--claude",
            self.claude,
            "--output",
            self.dojo / "manifests" / "shipped.yaml",
        )

    def test_dry_run_and_disposable_mirror(self):
        result = run(PARITY, "dry-run", "--candidate", self.candidate, env=self.env)
        report = json.loads(result.stdout)
        self.assertEqual(report["actions"]["replace_physical_with_link"], 1)
        self.assertEqual(report["actions"]["repair_link"], 1)

        mirror = self.root / "mirror"
        run(
            PARITY,
            "prepare",
            "--candidate",
            self.candidate,
            "--output",
            mirror,
            env=self.env,
        )
        self.assertEqual((mirror / "alpha").resolve(), (self.candidate / "alpha").resolve())
        self.assertEqual(
            (mirror / "claude-only").resolve(),
            (self.claude / "claude-only").resolve(),
        )
        run(
            PARITY,
            "check",
            "--runtime",
            "codex",
            "--candidate",
            self.candidate,
            "--required",
            "alpha",
            "--required",
            "beta",
            env=self.env,
        )
        run(
            PARITY,
            "check",
            "--runtime",
            "claude",
            "--sandbox",
            mirror,
            "--required",
            "alpha",
            "--required",
            "beta",
            env=self.env,
        )

    def test_dry_run_rejects_claude_drift(self):
        (self.claude / "alpha" / "SKILL.md").write_text("changed\n", encoding="utf-8")
        result = run(
            PARITY,
            "dry-run",
            "--candidate",
            self.candidate,
            env=self.env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Claude entry drift", result.stderr)

    def test_dry_run_accepts_links_created_from_its_manifest(self):
        self.write_skill(self.dojo / "gamma", "gamma candidate")
        self.write_skill(self.candidate / "gamma", "gamma candidate")
        self.write_policy(["alpha", "beta", "gamma"])
        self.regenerate_distribution()
        shutil.rmtree(self.active)
        os.symlink(self.candidate, self.active)
        run(
            PARITY,
            "apply",
            "--candidate",
            self.candidate,
            "--archive",
            self.root / "archive",
            env=self.env,
        )

        result = run(PARITY, "dry-run", "--candidate", self.candidate, env=self.env)
        report = json.loads(result.stdout)

        self.assertEqual(report["changes"], [])
        self.assertEqual(report["actions"]["keep_link"], 3)

    def test_apply_and_rollback_preserve_physical_copy(self):
        archive = self.root / "archive"
        shutil.rmtree(self.active)
        os.symlink(self.candidate, self.active)
        run(
            PARITY,
            "apply",
            "--candidate",
            self.candidate,
            "--archive",
            archive,
            env=self.env,
        )
        self.assertTrue((self.claude / "alpha").is_symlink())
        self.assertTrue((archive / "alpha" / "SKILL.md").is_file())
        run(PARITY, "rollback", env=self.env)
        self.assertFalse((self.claude / "alpha").is_symlink())
        self.assertEqual(
            (self.claude / "alpha" / "SKILL.md").read_text(encoding="utf-8"),
            "alpha old\n",
        )

    def test_claude_check_tolerates_listed_broken_link_but_rejects_new_one(self):
        (self.claude / "beta").unlink()
        self.write_skill(self.active / "beta", "beta old")
        (self.claude / "beta").symlink_to(self.active / "beta")
        (self.claude / "shape").symlink_to(self.active / "missing-shape")
        self.regenerate_distribution()

        run(
            PARITY,
            "check",
            "--runtime",
            "claude",
            "--sandbox",
            self.claude,
            "--required",
            "alpha",
            "--required",
            "beta",
            env=self.env,
        )

        (self.claude / "surprise").symlink_to(self.active / "missing-surprise")
        result = run(
            PARITY,
            "check",
            "--runtime",
            "claude",
            "--sandbox",
            self.claude,
            env=self.env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("surprise", result.stderr)
        self.assertNotIn("shape", result.stderr)

    def test_dry_run_surfaces_approval_gated_physical_conversion(self):
        self.write_policy(
            ["alpha", "beta"],
            approval_required={
                "alpha": {
                    "action": "convert_to_shared_link",
                    "reason": "test decision",
                }
            },
        )
        self.regenerate_distribution()
        result = run(PARITY, "dry-run", "--candidate", self.candidate, env=self.env)
        report = json.loads(result.stdout)
        self.assertEqual(
            report["approval_required_changes"][0]["name"],
            "alpha",
        )

        shutil.rmtree(self.active)
        os.symlink(self.candidate, self.active)
        apply_result = run(
            PARITY,
            "apply",
            "--candidate",
            self.candidate,
            "--archive",
            self.root / "archive",
            env=self.env,
            check=False,
        )
        self.assertNotEqual(apply_result.returncode, 0)
        self.assertIn("require exact approval", apply_result.stderr)

    def test_app_owned_folder_pins_no_content_but_must_stay_a_folder(self):
        account = self.declare_app_folder()
        manifest = json.loads(
            (self.dojo / "manifests" / "shipped.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["unmanaged_claude"]["synced"],
            {"kind": "directory", "ownership": "app_owned"},
        )
        self.assertEqual(manifest["classification_counts"]["claude_app_owned"], 1)

        (account / "manifest.json").write_text("round 2\n", encoding="utf-8")
        self.write_skill(account / "new-account-skill", "added by the app")
        passed = self.dry_run()
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("synced", json.loads(passed.stdout)["unmanaged_preserved"])

        shutil.rmtree(self.claude / "synced")
        (self.claude / "synced").write_text("not a folder\n", encoding="utf-8")
        failed = self.dry_run()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Claude entry drift: synced", failed.stderr)

        (self.claude / "synced").unlink()
        os.symlink(self.active / "alpha", self.claude / "synced")
        linked = self.dry_run()
        self.assertNotEqual(linked.returncode, 0)
        self.assertIn("Claude entry drift: synced", linked.stderr)

    def test_other_folders_keep_their_content_check_when_an_app_folder_is_declared(self):
        self.declare_app_folder()
        manifest = json.loads(
            (self.dojo / "manifests" / "shipped.yaml").read_text(encoding="utf-8")
        )
        self.assertIn("digest", manifest["unmanaged_claude"]["claude-only"])
        self.assertIn("digest", manifest["skills"]["alpha"]["claude_before"])

        (self.claude / "claude-only" / "SKILL.md").write_text("changed\n", encoding="utf-8")
        unmanaged = self.dry_run()
        self.assertNotEqual(unmanaged.returncode, 0)
        self.assertIn("Claude entry drift: claude-only", unmanaged.stderr)

        self.write_skill(self.claude / "claude-only", "claude only")
        (self.claude / "alpha" / "SKILL.md").write_text("changed\n", encoding="utf-8")
        managed = self.dry_run()
        self.assertNotEqual(managed.returncode, 0)
        self.assertIn("Claude entry drift: alpha", managed.stderr)

    def test_dry_run_reads_the_distribution_it_is_given(self):
        (self.claude / "claude-only" / "SKILL.md").write_text("changed\n", encoding="utf-8")
        fresh = self.root / "fresh-shipped.yaml"
        run(
            INVENTORY, "distribution", "--candidate", self.dojo, "--active", self.active,
            "--claude", self.claude, "--output", fresh,
        )

        stale = self.dry_run()
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("Claude entry drift: claude-only", stale.stderr)

        current = self.dry_run("--distribution", fresh)
        self.assertEqual(current.returncode, 0, current.stderr)


if __name__ == "__main__":
    unittest.main()
