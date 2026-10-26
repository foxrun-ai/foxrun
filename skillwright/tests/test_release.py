import json
import fcntl
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
RELEASE = PROJECT / "tools" / "skill_ship.py"
INVENTORY = PROJECT / "tools" / "skill_inventory.py"


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.origin = self.root / "origin.git"
        self.dojo = self.root / "dojo"
        self.active = self.root / "active"
        self.claude = self.root / "claude"
        self.codex = self.root / "codex"
        self.releases = self.root / "releases"
        self.state = self.root / "state"
        self.app_owned = []
        self.claude.mkdir()

        run("git", "init", "--bare", self.origin)
        run("git", "init", "-b", "main", self.dojo)
        run("git", "config", "user.email", "test@example.com", cwd=self.dojo)
        run("git", "config", "user.name", "Test", cwd=self.dojo)
        run("git", "remote", "add", "origin", self.origin, cwd=self.dojo)
        self.write_skill("alpha", "alpha v1")
        self.write_policy(["alpha"])
        run("git", "add", ".", cwd=self.dojo)
        run("git", "commit", "-m", "initial", cwd=self.dojo)
        run("git", "push", "-u", "origin", "main", cwd=self.dojo)
        self.write_distribution()
        run("git", "add", "manifests", cwd=self.dojo)
        run("git", "commit", "-m", "distribution", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)

        self.env = os.environ.copy()
        self.env.update(
            {
                "SKILLS_DOJO_ROOT": str(self.dojo),
                "SKILL_RELEASES_ROOT": str(self.releases),
                "SKILL_STATE_ROOT": str(self.state),
                "SKILLS_ACTIVE_PATH": str(self.active),
                "SKILLS_CLAUDE_ROOT": str(self.claude),
                "SKILLS_CODEX_ROOT": str(self.codex),
            }
        )

    def tearDown(self):
        for path in (self.releases, self.state):
            if path.exists():
                for root, dirs, files in os.walk(path):
                    os.chmod(root, stat.S_IRWXU)
                    for name in files:
                        os.chmod(Path(root) / name, stat.S_IRWXU)
        self.temp.cleanup()

    def test_prune_keeps_live_four_newest_and_unproved_release(self):
        self.releases.mkdir()
        for number in range(7):
            (self.releases / f"r{number}").mkdir()
        self.active.symlink_to(self.releases / "r6")
        script = (
            "import skill_ship as tool\n"
            "def proof(path):\n"
            " if path.name == 'r1': raise RuntimeError('hash mismatch')\n"
            "tool.prove_git_rebuild = proof\n"
            "tool.prune_old_releases()\n"
        )
        result = run(sys.executable, "-c", script, env=self.env, cwd=RELEASE.parent)
        self.assertIn("pruned rebuilt release r0", result.stdout)
        self.assertIn("kept release r1: hash mismatch", result.stderr)
        self.assertFalse((self.releases / "r0").exists())
        self.assertTrue((self.releases / "r1").is_dir())
        self.assertEqual(self.active.resolve(), (self.releases / "r6").resolve())
        self.assertEqual(len(list(self.releases.iterdir())), 6)

    def write_skill(self, name, body):
        path = self.dojo / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {json.dumps(body)}\n---\n\n{body}\n",
            encoding="utf-8",
        )

    def write_policy(self, publish, exclude=None, where=None):
        path = self.dojo / "config" / "catalog.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        policy = {
            "version": 1,
            "publish": sorted(publish),
            "exclude": exclude or {},
            "claude_preserve_physical": [],
            "claude_approval_required": {},
            "host_specific": {},
        }
        if where:
            # d6d9aec: the catalog's where map decides scope; absent means global.
            policy["where"] = where
        if self.app_owned:
            policy["claude_app_owned"] = {
                name: {"reason": "The Claude app owns this folder."}
                for name in self.app_owned
            }
        path.write_text(
            json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def write_app_folder(self, sync_round):
        """The Claude app's own folder in the Claude root, as one sync round leaves it."""
        account = self.claude / "synced" / "account"
        (account / "docx").mkdir(parents=True, exist_ok=True)
        (account / "docx" / "SKILL.md").write_text("docx\n", encoding="utf-8")
        (account / "manifest.json").write_text(
            json.dumps({"lastUpdated": sync_round, "skills": ["docx"]}) + "\n",
            encoding="utf-8",
        )
        (account / ".last-complete-round").write_text(
            f"round-{sync_round} cli,claude-desktop\n", encoding="utf-8"
        )

    def write_user_folder(self, body):
        """A folder in the Claude root that the shelf does not manage and the app does not own."""
        folder = self.claude / "claude-only"
        folder.mkdir(exist_ok=True)
        (folder / "SKILL.md").write_text(body + "\n", encoding="utf-8")

    def write_rewriting_repo_test(self, relative):
        """A repository test that rewrites a file in the Claude root while the ship
        runs its tests. That is after the manifest step and before the parity step."""
        tests = self.dojo / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_rewrite.py").write_text(
            "import os\nimport unittest\nfrom pathlib import Path\n\n"
            "class RewriteTest(unittest.TestCase):\n"
            "    def test_rewrite(self):\n"
            f"        target = Path(os.environ['SKILLS_CLAUDE_ROOT']) / {relative!r}\n"
            "        self.assertTrue(target.is_file())\n"
            "        target.write_text('rewritten while the ship ran\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )

    def declare_app_folder(self):
        self.app_owned = ["synced"]
        self.write_app_folder(1)
        self.write_policy(["alpha"])
        self.write_distribution()
        self.commit_all("declare the app folder; the last ship's manifest")

    def write_distribution(self):
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

    def commit_skill(self, body):
        self.write_skill("alpha", body)
        self.write_distribution()
        run("git", "add", "alpha", "manifests", cwd=self.dojo)
        run("git", "commit", "-m", body, cwd=self.dojo)
        run("git", "push", cwd=self.dojo)

    def write_repo_test(self, passing=True):
        tests = self.dojo / "tests"
        tests.mkdir(exist_ok=True)
        assertion = "self.assertTrue(True)" if passing else "self.fail('injected failure')"
        (tests / "test_smoke.py").write_text(
            "import unittest\n\n"
            "class SmokeTest(unittest.TestCase):\n"
            "    def test_smoke(self):\n"
            f"        {assertion}\n",
            encoding="utf-8",
        )

    def commit_all(self, message, push=True):
        run("git", "add", ".", cwd=self.dojo)
        run("git", "commit", "-m", message, cwd=self.dojo)
        if push:
            run("git", "push", cwd=self.dojo)

    def write_canary_stub(self, absent=False):
        stub = self.root / "canary-stub.py"
        status = "absent" if absent else "present"
        stub.write_text(
            "import sys\n"
            "prompt = sys.argv[2]\n"
            "names = prompt.split('Required skills: ', 1)[1].split(', ')\n"
            f"print('\\n'.join(name + ': {status}' for name in names))\n",
            encoding="utf-8",
        )
        self.env["SKILLS_CANARY_COMMAND"] = (
            f"{sys.executable} {stub} {{runtime}} {{prompt}}"
        )

    def prepare_ship_update(self, absent=False):
        self.write_repo_test()
        self.commit_all("add passing tests")
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(
            RELEASE,
            "publish",
            "--candidate",
            "r1",
            "--authorize-reviewed",
            "r1",
            env=self.env,
        )
        (self.claude / "alpha").symlink_to(self.active / "alpha")
        self.write_distribution()
        self.commit_all("record alpha consumer")
        self.write_skill("beta", "beta v1")
        self.write_policy(["alpha", "beta"])
        self.write_distribution()
        self.commit_all("add beta", push=False)
        self.write_canary_stub(absent=absent)

    def ship_receipt(self):
        receipts = list((self.state / "ships").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        return json.loads(receipts[0].read_text(encoding="utf-8"))

    def kill_after_pointer_switch(self, operation, target, authorization,
                                  candidate=None, accept_digest=None):
        marker = self.root / f"{operation}-{target}.switched"
        script = (
            "import argparse,pathlib,runpy,sys,time\n"
            "tool=pathlib.Path(sys.argv[1])\n"
            "sys.path.insert(0,str(tool.parent))\n"
            "module=runpy.run_path(str(tool))\n"
            "original=module['switch_link']\n"
            "def pause_after_switch(target):\n"
            " original(target)\n"
            " if pathlib.Path(target).name == sys.argv[3]:\n"
            "  pathlib.Path(sys.argv[2]).write_text('switched')\n"
            "  time.sleep(60)\n"
            "module['switch_link'].__globals__['switch_link']=pause_after_switch\n"
            "args=argparse.Namespace(candidate=sys.argv[5] or None, "
            "authorize_reviewed=sys.argv[4], preserve_existing_to=None, "
            "accept_active_drift_digest=sys.argv[6] or None)\n"
            "module[sys.argv[7]](args)\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script, RELEASE, marker, target,
             authorization, candidate or "", accept_digest or "", operation],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not marker.exists():
            stdout, stderr = process.communicate(timeout=2)
            self.fail(f"subprocess did not reach pointer switch: {stdout} {stderr}")
        process.kill()
        process.wait(timeout=5)
        process.communicate()
        self.assertLess(process.returncode, 0)

    def test_build_and_validate_leave_active_unchanged(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "validate", "--candidate", "r1", env=self.env)
        self.assertFalse(self.active.exists())
        self.assertTrue((self.releases / "r1" / "alpha" / "SKILL.md").is_file())
        self.assertFalse((self.releases / "r1" / ".git").exists())
        mode = (self.releases / "r1" / "alpha" / "SKILL.md").stat().st_mode
        self.assertFalse(mode & stat.S_IWUSR)

    def test_build_preserves_a_tracked_absolute_symlink(self):
        external = self.root / "external.md"
        external.write_text("external\n", encoding="utf-8")
        link = self.dojo / "alpha" / "EXTERNAL.md"
        link.symlink_to(external)
        self.write_distribution()
        self.commit_all("add absolute symlink")

        run(RELEASE, "build", "--release-id", "r1", env=self.env)

        built = self.releases / "r1" / "alpha" / "EXTERNAL.md"
        self.assertTrue(built.is_symlink())
        self.assertEqual(built.readlink(), external)

    def test_ship_test_failure_builds_nothing(self):
        self.write_repo_test(passing=False)
        self.commit_all("add failing tests", push=False)

        result = run(RELEASE, "ship", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        # Preflight pushed the ahead commit before the tests ran, so the message says so.
        self.assertIn("failed tests — no release published; main was already pushed to its upstream", result.stdout)
        self.assertIn("ship: pushing 1 commit(s) on main to origin/main:\n", result.stderr)
        self.assertIn(" add failing tests\n", result.stderr)
        self.assertEqual(
            run("git", "-C", self.origin, "rev-parse", "refs/heads/main").stdout,
            run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout,
        )
        self.assertFalse(self.releases.exists())
        receipt = self.ship_receipt()
        self.assertEqual(receipt["result"], "failed")
        self.assertEqual(receipt["failure_step"], "tests")

    def test_ship_refuses_to_push_an_outgoing_secret_and_names_what_it_pushes(self):
        self.write_repo_test()
        self.commit_all("add passing tests", push=False)
        # A synthetic token pattern, labeled fake; never a real credential.
        (self.dojo / "alpha" / "notes.md").write_text(
            "token (labeled fake): ghp_" + "A" * 36 + "\n", encoding="utf-8"
        )
        self.commit_all("add alpha notes", push=False)
        remote_before = run("git", "-C", self.origin, "rev-parse", "refs/heads/main").stdout.strip()

        result = run(RELEASE, "ship", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            run("git", "-C", self.origin, "rev-parse", "refs/heads/main").stdout.strip(),
            remote_before,
        )
        self.assertIn("secret-looking value", result.stdout + result.stderr)
        self.assertIn("alpha/notes.md", result.stdout + result.stderr)
        receipt = self.ship_receipt()
        self.assertEqual(receipt["failure_step"], "preflight")
        preflight = next(step for step in receipt["steps"] if step["name"] == "preflight")
        self.assertEqual(
            [line.split(" ", 1)[1] for line in preflight["output"]["outgoing"]],
            ["add alpha notes", "add passing tests"],
        )
        self.assertFalse(preflight["output"]["pushed"])
        self.assertFalse(self.releases.exists())

    def test_ship_dry_run_reports_stale_manifest_without_changing_git(self):
        self.write_repo_test(passing=True)
        self.write_skill("alpha", "alpha edited without touching the manifest\n")
        self.commit_all("edit alpha only", push=True)
        head_before = run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout.strip()
        remote_before = run(
            "git", "-C", self.origin, "rev-parse", "refs/heads/main"
        ).stdout.strip()
        manifest_before = (self.dojo / "manifests" / "shipped.yaml").read_bytes()

        result = run(RELEASE, "ship", "--dry-run", env=self.env)

        self.assertIn("manifest would change: alpha", result.stdout)
        receipt = self.ship_receipt()
        manifest_step = next(step for step in receipt["steps"] if step["name"] == "manifest")
        self.assertEqual(manifest_step["result"], "passed")
        self.assertTrue(manifest_step["output"]["changed"])
        self.assertTrue(manifest_step["output"]["would_change"])
        self.assertEqual(manifest_step["output"]["changed_skills"], ["alpha"])
        self.assertIsNone(manifest_step["output"]["committed"])
        self.assertFalse(manifest_step["output"]["manifest_worktree_left_dirty"])
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout.strip(), head_before)
        self.assertEqual(
            run("git", "-C", self.origin, "rev-parse", "refs/heads/main").stdout.strip(),
            remote_before,
        )
        self.assertEqual((self.dojo / "manifests" / "shipped.yaml").read_bytes(), manifest_before)
        self.assertEqual(run("git", "diff", "--cached", "--name-only", cwd=self.dojo).stdout, "")
        self.assertEqual(run("git", "-C", self.dojo, "status", "--porcelain").stdout, "")

    def test_manifest_push_rejection_preserves_main_index_and_worktree(self):
        self.write_repo_test()
        self.write_skill("alpha", "alpha edited without touching the manifest\n")
        self.commit_all("edit alpha only", push=True)
        reject = self.origin / "hooks/pre-receive"
        reject.write_text("#!/bin/sh\necho 'Reject manifest push for this test.' >&2\nexit 1\n")
        reject.chmod(0o755)
        head_before = run("git", "rev-parse", "refs/heads/main", cwd=self.dojo).stdout.strip()
        index = self.dojo / ".git/index"
        index_before = index.read_bytes()
        manifest = self.dojo / "manifests/shipped.yaml"
        manifest_before = manifest.read_bytes()
        worktree_before = {str(path.relative_to(self.dojo)): path.read_bytes()
                           for path in self.dojo.rglob("*")
                           if path.is_file() and ".git" not in path.relative_to(self.dojo).parts}

        result = run(RELEASE, "ship", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        with self.subTest("main ref"):
            self.assertEqual(run("git", "rev-parse", "refs/heads/main", cwd=self.dojo).stdout.strip(),
                             head_before)
        with self.subTest("index bytes"):
            self.assertEqual(index.read_bytes(), index_before)
        with self.subTest("manifest bytes"):
            self.assertEqual(manifest.read_bytes(), manifest_before)
        with self.subTest("worktree bytes"):
            self.assertEqual({str(path.relative_to(self.dojo)): path.read_bytes()
                              for path in self.dojo.rglob("*")
                              if path.is_file() and ".git" not in path.relative_to(self.dojo).parts},
                             worktree_before)
        self.assertEqual(run("git", "rev-parse", "refs/heads/main", cwd=self.origin).stdout.strip(),
                         head_before)
        receipt = self.ship_receipt()
        self.assertEqual(receipt["result"], "failed")
        self.assertEqual(receipt["failure_step"], "manifest")
        step = receipt["steps"][-1]
        self.assertEqual(step["name"], "manifest")
        self.assertEqual(step["result"], "failed")
        self.assertTrue(step["output"]["local_state_unchanged"])
        self.assertIn("local main, index, and manifest worktree unchanged", step["error"])
        self.assertIsNone(step["output"]["committed"])
        self.assertIn("Reject manifest push for this test.", step["output"]["commands"][-1]["stderr"])
        self.assertFalse(self.releases.exists())
        self.assertFalse(self.active.exists())

    def test_ship_refreshes_stale_manifest_and_commits_it(self):
        self.prepare_ship_update()
        self.write_skill("alpha", "alpha edited without touching the manifest\n")
        self.commit_all("edit alpha only", push=True)
        head_before = run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout.strip()

        result = run(RELEASE, "ship", env=self.env)

        self.assertIn("shipped", result.stdout)
        receipt = self.ship_receipt()
        manifest_step = next(step for step in receipt["steps"] if step["name"] == "manifest")
        self.assertTrue(manifest_step["output"]["changed"])
        self.assertFalse(manifest_step["output"]["would_change"])
        self.assertEqual(manifest_step["output"]["changed_skills"], ["alpha"])
        self.assertNotEqual(receipt["dojo_commit"], head_before)
        subject = run("git", "-C", self.origin, "log", "--format=%s", "-1").stdout.strip()
        self.assertEqual(subject, "chore: regen distribution manifest (ship)")
        self.assertEqual(run("git", "-C", self.dojo, "status", "--porcelain").stdout, "")

    def test_ship_publishes_applies_new_link_and_writes_receipt(self):
        self.prepare_ship_update()

        result = run(RELEASE, "ship", env=self.env)

        receipt = self.ship_receipt()
        release_id = receipt["release_id"]
        self.assertIn(f"shipped {release_id}", result.stdout)
        self.assertEqual(self.active.resolve(), (self.releases / release_id).resolve())
        self.assertTrue((self.claude / "beta").is_symlink())
        self.assertEqual((self.claude / "beta").resolve(), (self.active / "beta").resolve())
        self.assertEqual((self.codex / "alpha").readlink(), self.active / "alpha")
        self.assertEqual((self.codex / "beta").readlink(), self.active / "beta")
        self.assertEqual(receipt["result"], "shipped")
        self.assertEqual(receipt["previous_release_id"], "r1")
        self.assertEqual(receipt["required_skills"], ["beta"])
        self.assertEqual(receipt["codex_links"]["created"], ["alpha", "beta"])
        self.assertEqual(receipt["codex_links"]["refreshed"], [])
        self.assertEqual(receipt["codex_links"]["kept"], [])
        self.assertEqual(set(receipt["canary_outputs"]), {"claude", "codex", "hermes"})
        self.assertTrue(
            {
                "started_at",
                "finished_at",
                "dojo_commit",
                "upstream_commit",
                "previous_dojo_commit",
                "steps",
                "canary_outputs",
                "result",
            }.issubset(receipt)
        )
        self.assertTrue(
            all(
                {"name", "started_at", "finished_at", "result", "output"}.issubset(step)
                for step in receipt["steps"]
            )
        )
        self.assertEqual(
            [step["name"] for step in receipt["steps"]],
            [
                "preflight",
                "manifest",
                "tests",
                "build_validate_parity",
                "publish",
                "claude_links",
                "codex_links",
                "consumer_checks",
                "canaries",
            ],
        )
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout,
                         run("git", "rev-parse", "origin/main", cwd=self.dojo).stdout)

    def test_ship_canary_absent_rolls_back_release_and_links(self):
        self.prepare_ship_update(absent=True)

        result = run(RELEASE, "ship", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed canaries — rolled back to r1", result.stdout)
        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())
        self.assertFalse((self.claude / "beta").exists())
        self.assertFalse((self.claude / "beta").is_symlink())
        self.assertFalse((self.codex / "alpha").exists())
        self.assertFalse((self.codex / "alpha").is_symlink())
        self.assertFalse((self.codex / "beta").exists())
        self.assertFalse((self.codex / "beta").is_symlink())
        receipt = self.ship_receipt()
        self.assertEqual(receipt["result"], "failed")
        self.assertEqual(receipt["failure_step"], "canaries")
        self.assertTrue(receipt["rollback"]["complete"])
        self.assertEqual(set(receipt["canary_outputs"]), {"claude", "codex", "hermes"})
        self.assertTrue((self.releases / receipt["release_id"]).is_dir())

    def test_ship_dry_run_builds_candidate_but_publishes_nothing(self):
        self.write_repo_test()
        self.commit_all("add passing tests", push=False)
        remote_before = run(
            "git", "-C", self.origin, "rev-parse", "refs/heads/main"
        ).stdout.strip()

        result = run(RELEASE, "ship", "--dry-run", env=self.env)

        receipt = self.ship_receipt()
        self.assertIn("nothing published", result.stdout)
        self.assertEqual(receipt["result"], "dry_run")
        self.assertTrue((self.releases / receipt["release_id"]).is_dir())
        self.assertFalse(self.active.exists())
        self.assertFalse(self.active.is_symlink())
        self.assertFalse((self.claude / "alpha").exists())
        self.assertFalse(self.codex.exists())
        self.assertEqual(
            run("git", "-C", self.origin, "rev-parse", "refs/heads/main").stdout.strip(),
            remote_before,
        )
        preflight = next(step for step in receipt["steps"] if step["name"] == "preflight")
        self.assertEqual(preflight["output"]["ahead"], 1)
        self.assertFalse(preflight["output"]["pushed"])

    def test_ship_dry_run_ignores_untracked_root_skill_and_records_it(self):
        self.write_repo_test()
        self.commit_all("add passing tests")
        self.write_skill("stray", "untracked and excluded")

        result = run(RELEASE, "ship", "--dry-run", env=self.env)

        receipt = self.ship_receipt()
        self.assertIn("dry-run", result.stdout)
        self.assertEqual(receipt["ignored_untracked"], ["stray/"])
        self.assertEqual(
            receipt["source"],
            {
                "kind": "git-archive",
                "commit": run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout.strip(),
            },
        )
        candidate = self.releases / receipt["release_id"]
        self.assertFalse((candidate / "stray").exists())
        manifest = json.loads(
            (candidate / ".release-manifest.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("stray", manifest["skills"])

    def test_ship_preflight_ignores_modified_and_untracked_entries(self):
        self.write_repo_test()
        self.commit_all("add passing tests")
        self.write_skill("alpha", "tracked modification")
        self.write_skill("stray", "untracked folder")

        result = run(RELEASE, "ship", "--dry-run", env=self.env)

        receipt = self.ship_receipt()
        self.assertEqual(receipt["result"], "dry_run")
        self.assertEqual(receipt["ignored_modified"], ["alpha/SKILL.md"])
        self.assertEqual(receipt["ignored_untracked"], ["stray/"])

    def test_manifest_dry_run_preserves_a_dirty_index(self):
        self.write_repo_test()
        self.commit_all("add passing tests")
        self.write_skill("alpha", "committed without manifest")
        run("git", "add", "alpha", cwd=self.dojo)
        run("git", "commit", "-m", "edit alpha only", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        foreign = self.dojo / "foreign.txt"
        foreign.write_text("staged neighbor work\n", encoding="utf-8")
        run("git", "add", "foreign.txt", cwd=self.dojo)
        index_before = run(
            "git", "ls-files", "--stage", "foreign.txt", cwd=self.dojo
        ).stdout

        head_before = run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout.strip()
        remote_before = run("git", "-C", self.origin, "rev-parse", "refs/heads/main").stdout.strip()

        run(RELEASE, "ship", "--dry-run", env=self.env)

        receipt = self.ship_receipt()
        self.assertEqual(receipt["ignored_modified"], ["foreign.txt"])
        self.assertFalse(receipt["manifest_worktree_left_dirty"])
        self.assertEqual(
            run("git", "ls-files", "--stage", "foreign.txt", cwd=self.dojo).stdout,
            index_before,
        )
        self.assertNotEqual(
            run("git", "show", "HEAD:foreign.txt", cwd=self.dojo, check=False).returncode,
            0,
        )
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout.strip(), head_before)
        self.assertEqual(
            run("git", "-C", self.origin, "rev-parse", "refs/heads/main").stdout.strip(),
            remote_before,
        )

    def test_codex_canary_reads_by_name_and_uses_devnull(self):
        script = (
            "import json,pathlib,runpy,subprocess,sys\n"
            "sys.path.insert(0,str(pathlib.Path(sys.argv[1]).parent))\n"
            "module=runpy.run_path(sys.argv[1])\n"
            "prompt=module['canary_prompt'](['alpha'])\n"
            "command=module['canary_command']('codex',prompt,{})\n"
            "devnull=[]\n"
            "def fake(command,**kwargs):\n"
            " devnull.append(kwargs.get('stdin') is subprocess.DEVNULL)\n"
            " return {'command':command,'stdout':'alpha: present\\n',"
            "'stderr':'','returncode':0,'timed_out':False}\n"
            "module['run_fresh_canaries'].__globals__['run_checked_command']=fake\n"
            "module['run_fresh_canaries'](['alpha'],prompt,{})\n"
            "print(json.dumps({'command':command,'devnull':devnull}))\n"
        )

        result = run(sys.executable, "-c", script, RELEASE, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        command = report["command"]
        from base.agent_catalog import resolve_model
        self.assertEqual(command[3], resolve_model('code', 'codex'))
        self.assertIn("-s", command)
        self.assertIn("read-only", command)
        self.assertIn("--ephemeral", command)
        self.assertIn(
            # 3a4b3ff: the canary reads the shelf at ~/.foxrun/skills, not ~/.agents/skills.
            "read ~/.foxrun/skills/<name>/SKILL.md", command[-1]
        )
        self.assertIn("has a `name:` line", command[-1])
        self.assertEqual(report["devnull"], [True, True, True])

    def test_failed_publish_restores_previous_active_release(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1", env=self.env)
        self.commit_skill("alpha v2")
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        previous_state = (self.state / "release-state.json").read_bytes()
        # A directory at the atomic write destination forces a real write error.
        state_file = self.state / "release-state.json"
        state_file.rename(self.state / "saved-state.json")
        state_file.mkdir()
        result = run(RELEASE, "publish", "--candidate", "r2", "--authorize-reviewed", "r2",
                     env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.active.is_symlink())
        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())
        self.assertEqual((self.state / "saved-state.json").read_bytes(), previous_state)

    def test_sigkill_during_publish_recovers_previous_release_and_state(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            env=self.env)
        self.commit_skill("alpha v2")
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        state_before = (self.state / "release-state.json").read_bytes()

        self.kill_after_pointer_switch("publish", "r2", "r2", candidate="r2")

        self.assertEqual(self.active.resolve(), (self.releases / "r2").resolve())
        self.assertTrue((self.state / "release-transaction.json").is_file())
        run(RELEASE, "recover", env=self.env)
        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())
        self.assertEqual((self.state / "release-state.json").read_bytes(), state_before)
        self.assertFalse((self.state / "release-transaction.json").exists())

    def test_sigkill_during_rollback_recovers_newer_release_and_state(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            env=self.env)
        self.commit_skill("alpha v2")
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        run(RELEASE, "publish", "--candidate", "r2", "--authorize-reviewed", "r2",
            env=self.env)
        state_before = (self.state / "release-state.json").read_bytes()

        self.kill_after_pointer_switch("rollback", "r1", "r2")

        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())
        self.assertTrue((self.state / "release-transaction.json").is_file())
        run(RELEASE, "recover", env=self.env)
        self.assertEqual(self.active.resolve(), (self.releases / "r2").resolve())
        self.assertEqual((self.state / "release-state.json").read_bytes(), state_before)
        self.assertFalse((self.state / "release-transaction.json").exists())

    def test_recovery_refuses_pointer_drift_and_keeps_journal(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            env=self.env)
        self.commit_skill("alpha v2")
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        run(RELEASE, "build", "--release-id", "r3", env=self.env)
        self.kill_after_pointer_switch("publish", "r2", "r2", candidate="r2")
        self.active.unlink()
        self.active.symlink_to(self.releases / "r3")

        result = run(RELEASE, "recover", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("drifted after interruption", result.stderr)
        self.assertEqual(self.active.resolve(), (self.releases / "r3").resolve())
        self.assertTrue((self.state / "release-transaction.json").is_file())

    def test_recovery_checks_old_tree_before_touching_working_new_pointer(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            env=self.env)
        self.commit_skill("alpha v2")
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        self.kill_after_pointer_switch("publish", "r2", "r2", candidate="r2")
        old_skill = self.releases / "r1" / "alpha"
        old_skill.chmod(stat.S_IRWXU)
        old_file = old_skill / "SKILL.md"
        old_file.chmod(stat.S_IRWXU)
        old_file.write_text("changed after interruption\n", encoding="utf-8")

        result = run(RELEASE, "recover", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preserved release snapshot changed", result.stderr)
        self.assertEqual(self.active.resolve(), (self.releases / "r2").resolve())
        self.assertTrue((self.state / "release-transaction.json").is_file())

    def test_recovery_rejects_symlinked_control_files(self):
        self.state.mkdir(parents=True)
        external = self.root / "external.json"
        external.write_text("{}\n", encoding="utf-8")
        (self.state / "release-transaction.json").symlink_to(external)

        result = run(RELEASE, "recover", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be a symlink", result.stderr)
        self.assertEqual(external.read_text(encoding="utf-8"), "{}\n")

    def test_recovery_rejects_transaction_paths_outside_release_root(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            env=self.env)
        self.commit_skill("alpha v2")
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        self.kill_after_pointer_switch("publish", "r2", "r2", candidate="r2")
        journal_path = self.state / "release-transaction.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        journal["active_before"]["path"] = str(self.root / "outside")
        journal_path.write_text(json.dumps(journal) + "\n", encoding="utf-8")

        result = run(RELEASE, "recover", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the release root", result.stderr)
        self.assertEqual(self.active.resolve(), (self.releases / "r2").resolve())
        self.assertTrue(journal_path.is_file())

    def test_rollback_rejects_symlinked_state_file(self):
        self.state.mkdir(parents=True)
        external = self.root / "external-state.json"
        external.write_text("{}\n", encoding="utf-8")
        (self.state / "release-state.json").symlink_to(external)

        result = run(RELEASE, "rollback", "--authorize-reviewed", "unused",
                     env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be a symlink", result.stderr)
        self.assertEqual(external.read_text(encoding="utf-8"), "{}\n")

    def test_readiness_reports_clean_source_without_creating_runtime_state(self):
        result = run(RELEASE, "readiness", env=self.env)
        report = json.loads(result.stdout)
        self.assertTrue(report["ready_to_build"])
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(report["publish_skills"], ["alpha"])
        self.assertFalse(self.state.exists())
        self.assertFalse(self.releases.exists())
        self.assertFalse(self.active.exists())

    def test_readiness_uses_head_when_worktree_is_dirty(self):
        self.write_skill("alpha", "changed but not inventoried")
        result = run(RELEASE, "readiness", env=self.env)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(report["ready_to_build"])
        self.assertEqual(report["blockers"], [])
        self.assertFalse(self.state.exists())

    def test_readiness_does_not_claim_broken_active_release_is_usable(self):
        self.active.symlink_to(self.releases / "missing")
        result = run(RELEASE, "readiness", env=self.env, check=False)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(report["ready_to_build"])
        self.assertEqual(report["active_valid"], False)
        self.assertEqual(report["blockers"][0]["check"], "active_release")

    def test_failed_first_publish_restores_original_directory(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        self.active.mkdir()
        (self.active / "keep.txt").write_text("original")
        self.state.mkdir(exist_ok=True)
        (self.state / "release-state.json").mkdir()
        preserved = self.root / "preserved"
        result = run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
                     "--preserve-existing-to", preserved, env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.active.is_symlink())
        self.assertEqual((self.active / "keep.txt").read_text(), "original")
        self.assertFalse(preserved.exists())

    def test_publish_and_rollback_switch_release_pointer(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1", env=self.env)
        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())
        self.commit_skill("alpha v2")
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        run(RELEASE, "publish", "--candidate", "r2", "--authorize-reviewed", "r2", env=self.env)
        self.assertEqual(self.active.resolve(), (self.releases / "r2").resolve())
        run(RELEASE, "rollback", "--authorize-reviewed", "r2", env=self.env)
        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())

    def test_rollback_state_failure_restores_active_and_state(self):
        for original_directory in (False, True):
            with self.subTest(original_directory=original_directory):
                # Each attempt uses independent runtime paths and a candidate.
                suffix = "directory" if original_directory else "release"
                env = dict(self.env)
                active = self.root / ("active-" + suffix)
                state = self.root / ("state-" + suffix)
                env.update(SKILLS_ACTIVE_PATH=str(active), SKILL_STATE_ROOT=str(state))
                run(RELEASE, "build", "--release-id", suffix, env=env)
                if original_directory:
                    active.mkdir()
                    (active / "keep.txt").write_text("original")
                    run(RELEASE, "publish", "--candidate", suffix,
                        "--authorize-reviewed", suffix,
                        "--preserve-existing-to", self.root / "preserved", env=env)
                else:
                    run(RELEASE, "publish", "--candidate", suffix,
                        "--authorize-reviewed", suffix, env=env)
                    run(RELEASE, "build", "--release-id", "release-next", env=env)
                    run(RELEASE, "publish", "--candidate", "release-next",
                        "--authorize-reviewed", "release-next", env=env)
                before_target = active.resolve()
                before_state = (state / "release-state.json").read_bytes()
                script = (
                    "import runpy,sys,pathlib\n"
                    "sys.path.insert(0,str(pathlib.Path(sys.argv[1]).parent))\n"
                    "module=runpy.run_path(sys.argv[1])\n"
                    "def fail(*args): raise OSError('injected state-write failure')\n"
                    "module['rollback'].__globals__['write_json']=fail\n"
                    "import argparse\n"
                    "module['rollback'](argparse.Namespace(authorize_reviewed=sys.argv[2], accept_active_drift_digest=None))\n"
                )
                authorization = "release-next" if not original_directory else suffix
                result = run(sys.executable, "-c", script, RELEASE, authorization,
                             env=env, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("injected state-write failure", result.stderr)
                self.assertEqual(active.resolve(), before_target)
                self.assertEqual((state / "release-state.json").read_bytes(), before_state)
                if original_directory:
                    self.assertEqual((self.root / "preserved/keep.txt").read_text(), "original")

    def test_directory_rollback_can_return_to_release_without_losing_directory(self):
        self.active.mkdir()
        (self.active / "keep.txt").write_text("original")
        preserved = self.root / "preserved"
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            "--preserve-existing-to", preserved, env=self.env)
        run(RELEASE, "rollback", "--authorize-reviewed", "r1", env=self.env)
        self.assertEqual((self.active / "keep.txt").read_text(), "original")
        directory_digest = json.loads(
            (self.state / "release-state.json").read_text(encoding="utf-8")
        )["current"]["digest"]
        run(RELEASE, "rollback", "--authorize-reviewed", directory_digest, env=self.env)
        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())
        self.assertEqual((preserved / "keep.txt").read_text(), "original")

    def test_rollback_refuses_active_pointer_drift(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1", env=self.env)
        run(RELEASE, "build", "--release-id", "r2", env=self.env)
        run(RELEASE, "publish", "--candidate", "r2", "--authorize-reviewed", "r2", env=self.env)
        self.active.unlink()
        self.active.symlink_to(self.releases / "r1")
        state = (self.state / "release-state.json").read_bytes()
        result = run(RELEASE, "rollback", "--authorize-reviewed", "r2",
                     env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active release drift", result.stderr)
        self.assertEqual((self.state / "release-state.json").read_bytes(), state)
        self.assertEqual(self.active.resolve(), (self.releases / "r1").resolve())

    def test_existing_directory_requires_explicit_preservation_path(self):
        self.active.mkdir()
        (self.active / "do-not-lose.txt").write_text("keep\n", encoding="utf-8")
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        result = run(
            RELEASE,
            "publish",
            "--candidate",
            "r1",
            env=self.env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.active / "do-not-lose.txt").is_file())

    def test_validation_rejects_candidate_drift(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        skill = self.releases / "r1" / "alpha"
        skill.chmod(stat.S_IRWXU)
        target = skill / "SKILL.md"
        target.chmod(stat.S_IRWXU)
        target.write_text(
            "---\nname: alpha\ndescription: tampered\n---\n\ntampered\n",
            encoding="utf-8",
        )
        result = run(
            RELEASE,
            "validate",
            "--candidate",
            "r1",
            env=self.env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("content drift", result.stderr)

    def test_validation_rejects_candidate_from_older_source_commit(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        self.commit_skill("alpha v2")

        result = run(RELEASE, "validate", "--candidate", "r1",
                     env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not built from the current Dojo commit", result.stderr)

    def test_reviewed_digest_repairs_invalid_active_release_and_preserves_rollback(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            env=self.env)
        release = self.releases / "r1"
        release.chmod(stat.S_IRWXU)
        self.write_skill("beta", "same content available in source")
        extra = release / "beta"
        shutil.copytree(self.dojo / "beta", extra)
        digest_script = run(RELEASE, "readiness", env=self.env, check=False)
        observed = json.loads(digest_script.stdout)["active_tree_digest"]
        run("git", "add", "beta", cwd=self.dojo)
        self.write_policy(["alpha", "beta"])
        self.write_distribution()
        # d6d9aec: the policy moved to config/catalog.yaml, so it is staged too.
        run("git", "add", "manifests", "config", cwd=self.dojo)
        run("git", "commit", "-m", "classify beta", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        run(RELEASE, "build", "--release-id", "r2", env=self.env)

        blocked = run(RELEASE, "publish", "--candidate", "r2",
                      "--authorize-reviewed", "r2", env=self.env, check=False)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("--accept-active-drift-digest", blocked.stderr)
        run(RELEASE, "publish", "--candidate", "r2", "--authorize-reviewed", "r2",
            "--accept-active-drift-digest", observed,
            "--accept-active-drift-skill", "beta", env=self.env)
        state = json.loads((self.state / "release-state.json").read_text())
        self.assertEqual(state["previous"]["kind"], "release_snapshot")
        self.assertEqual(state["previous"]["digest"], observed)

        rollback_blocked = run(RELEASE, "rollback", "--authorize-reviewed", "r2",
                               env=self.env, check=False)
        self.assertNotEqual(rollback_blocked.returncode, 0)
        self.assertIn("--accept-active-drift-digest", rollback_blocked.stderr)
        run(RELEASE, "rollback", "--authorize-reviewed", "r2",
            "--accept-active-drift-digest", observed, env=self.env)
        self.assertEqual(self.active.resolve(), release.resolve())
        restored_digest = json.loads(
            run(RELEASE, "readiness", env=self.env, check=False).stdout
        )["active_tree_digest"]
        self.assertEqual(restored_digest, observed)
        run(RELEASE, "rollback", "--authorize-reviewed", "r1",
            "--accept-active-drift-digest", observed, env=self.env)
        self.assertEqual(self.active.resolve(), (self.releases / "r2").resolve())

    def test_deliver_updates_existing_consumers_and_rollback_restores_v1(self):
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        run(RELEASE, "publish", "--candidate", "r1", "--authorize-reviewed", "r1",
            env=self.env)
        (self.claude / "alpha").symlink_to(self.active / "alpha")
        self.write_distribution()
        run("git", "add", "manifests", cwd=self.dojo)
        run("git", "commit", "-m", "record consumer link", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        self.commit_skill("alpha v2")

        delivered = run(RELEASE, "deliver", "--release-id", "r2",
                        "--authorize-reviewed", "r2", env=self.env)
        report = json.loads(delivered.stdout)

        self.assertTrue(report["candidate_valid"])
        self.assertTrue(report["consumer_parity_ready"])
        self.assertTrue(report["published"])
        self.assertFalse(report["activation_complete"])
        self.assertIn("alpha v2", (self.active / "alpha" / "SKILL.md").read_text())
        self.assertIn("alpha v2", (self.claude / "alpha" / "SKILL.md").read_text())
        run(RELEASE, "rollback", "--authorize-reviewed", "r2", env=self.env)
        self.assertIn("alpha v1", (self.active / "alpha" / "SKILL.md").read_text())
        self.assertIn("alpha v1", (self.claude / "alpha" / "SKILL.md").read_text())

    def test_deliver_stops_before_publish_when_consumer_parity_needs_changes(self):
        result = run(RELEASE, "deliver", "--release-id", "r1",
                     "--authorize-reviewed", "r1", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["consumer_parity_ready"])
        self.assertFalse(report["published"])
        self.assertTrue(report["parity_changes"])
        self.assertFalse(self.active.exists())
        self.assertTrue((self.releases / "r1").is_dir())

    def test_lifecycle_lock_contention_stops_build(self):
        self.state.mkdir(parents=True, exist_ok=True)
        lock_path = self.state / "lifecycle.lock"
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run(
                RELEASE,
                "build",
                "--release-id",
                "r1",
                env=self.env,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lock is busy", result.stderr)

    def test_build_rejects_duplicate_frontmatter_keys(self):
        duplicate = "---\nname: alpha\ndescription: first\nname: duplicate\n---\n"
        (self.dojo / "alpha" / "SKILL.md").write_text(duplicate, encoding="utf-8")
        self.write_distribution()
        run("git", "add", "alpha", "manifests", cwd=self.dojo)
        run("git", "commit", "-m", "duplicate", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        result = run(
            RELEASE,
            "build",
            "--release-id",
            "bad",
            env=self.env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate frontmatter key", result.stderr)

    def test_build_publishes_unclassified_new_root_skill(self):
        # d6d9aec: a root skill absent from the catalog's where map is global; it publishes.
        self.write_skill("beta", "beta")
        self.write_distribution()
        run("git", "add", "beta", "manifests", cwd=self.dojo)
        run("git", "commit", "-m", "unclassified beta", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        self.assertTrue((self.releases / "r1" / "beta" / "SKILL.md").is_file())

    def test_build_rejects_publishable_source_omitted_from_distribution(self):
        self.write_skill("beta", "beta")
        self.write_policy(["alpha", "beta"])
        self.write_distribution()
        distribution_path = self.dojo / "manifests" / "shipped.yaml"
        distribution = json.loads(distribution_path.read_text(encoding="utf-8"))
        del distribution["skills"]["beta"]
        distribution_path.write_text(
            json.dumps(distribution, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        run("git", "add", ".", cwd=self.dojo)
        run("git", "commit", "-m", "omit beta", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        result = run(
            RELEASE,
            "build",
            "--release-id",
            "bad",
            env=self.env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("distribution completeness failure", result.stderr)
        self.assertIn("beta", result.stderr)

    def test_explicit_exclusion_stays_out_and_receipt_requires_fresh_canaries(self):
        self.write_skill("beta", "beta")
        self.write_policy(
            ["alpha"],
            exclude={
                "beta": {
                    "status": "source_only",
                    "reason": "test exclusion",
                    "claude": "absent",
                }
            },
            # d6d9aec: exclusion now comes from where: off; the exclude map only adds the reason.
            where={"beta": "off"},
        )
        self.write_distribution()
        run("git", "add", ".", cwd=self.dojo)
        run("git", "commit", "-m", "exclude beta", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        self.assertFalse((self.releases / "r1" / "beta").exists())
        manifest = json.loads(
            (self.releases / "r1" / ".release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["classifications"]["exclude"], ["beta"])
        self.assertTrue(manifest["canary_checklist"]["fresh_sessions_required"])
        self.assertEqual(
            manifest["canary_checklist"]["runtimes"],
            ["hermes", "codex", "claude"],
        )

    def test_build_ignores_policy_name_without_source(self):
        # d6d9aec: publish is derived from root skills; a catalog name with no source is ignored.
        self.write_policy(["alpha", "missing"])
        self.write_distribution()
        run("git", "add", "config/catalog.yaml", "manifests", cwd=self.dojo)
        run("git", "commit", "-m", "missing source", cwd=self.dojo)
        run("git", "push", cwd=self.dojo)
        run(RELEASE, "build", "--release-id", "r1", env=self.env)
        manifest = json.loads(
            (self.releases / "r1" / ".release-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["classifications"]["publish"], ["alpha"])
        self.assertFalse((self.releases / "r1" / "missing").exists())

    def test_ship_dry_run_passes_when_the_app_folder_changed_after_the_last_ship(self):
        self.write_repo_test()
        self.declare_app_folder()
        manifest = json.loads(
            (self.dojo / "manifests" / "shipped.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["unmanaged_claude"]["synced"],
            {"kind": "directory", "ownership": "app_owned"},
        )
        self.write_app_folder(2)

        result = run(RELEASE, "ship", "--dry-run", env=self.env, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ship_receipt()["result"], "dry_run")
        self.assertIn("manifest unchanged", result.stdout)

    def test_ship_dry_run_passes_when_the_app_folder_changes_during_the_run(self):
        self.write_repo_test()
        self.write_rewriting_repo_test("synced/account/manifest.json")
        self.declare_app_folder()

        result = run(RELEASE, "ship", "--dry-run", env=self.env, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ship_receipt()["result"], "dry_run")
        self.assertEqual(
            (self.claude / "synced" / "account" / "manifest.json").read_text(encoding="utf-8"),
            "rewritten while the ship ran\n",
        )

    def test_ship_passes_when_the_app_folder_changes_during_the_ship(self):
        self.declare_app_folder()
        self.prepare_ship_update()
        self.write_rewriting_repo_test("synced/account/manifest.json")
        self.commit_all("a sync round lands while the ship runs", push=False)

        result = run(RELEASE, "ship", env=self.env, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shipped", result.stdout)
        self.assertEqual(self.ship_receipt()["result"], "shipped")
        self.assertEqual(
            (self.claude / "synced" / "account" / "manifest.json").read_text(encoding="utf-8"),
            "rewritten while the ship ran\n",
        )

    def test_ship_dry_run_checks_parity_against_its_fresh_manifest(self):
        self.write_repo_test()
        self.write_user_folder("v1")
        self.write_distribution()
        self.commit_all("the last ship's manifest")
        self.write_user_folder("v2 written after the last ship")
        manifest_before = (self.dojo / "manifests" / "shipped.yaml").read_bytes()

        result = run(RELEASE, "ship", "--dry-run", env=self.env, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ship_receipt()["result"], "dry_run")
        self.assertEqual(
            (self.dojo / "manifests" / "shipped.yaml").read_bytes(), manifest_before
        )

    def test_ship_dry_run_still_stops_when_a_user_folder_changes_during_the_run(self):
        self.write_repo_test()
        self.write_user_folder("v1")
        self.write_rewriting_repo_test("claude-only/SKILL.md")
        self.declare_app_folder()

        result = run(RELEASE, "ship", "--dry-run", env=self.env, check=False)

        self.assertNotEqual(result.returncode, 0)
        receipt = self.ship_receipt()
        self.assertEqual(receipt["failure_step"], "build_validate_parity")
        self.assertIn("Claude entry drift: claude-only", json.dumps(receipt))
        self.assertNotIn("claude-only, synced", json.dumps(receipt))

    def test_ship_passes_when_a_user_folder_changed_before_the_ship(self):
        self.write_user_folder("v1")
        self.prepare_ship_update()
        self.write_user_folder("v2 written after the last manifest")

        result = run(RELEASE, "ship", env=self.env, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ship_receipt()["result"], "shipped")


if __name__ == "__main__":
    unittest.main()
