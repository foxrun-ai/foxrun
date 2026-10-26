import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TRIGGER = PROJECT / "tools" / "skill-ship-trigger.sh"
INSTALL = PROJECT / "tools" / "skill_ship.py"
OLD_HOOK = (
    "#!/bin/sh\n"
    "# Skills Dojo post-commit trigger (decision 3, Person 2026-09-07):\n"
    "exit 0\n"
)


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


class ShipTriggerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.origin = self.root / "origin.git"
        self.dojo = self.root / "skillwright"
        self.author = self.root / "author"
        self.state = self.root / "state"
        self.log = self.state / "ships" / "trigger.log"
        home = self.root / "home"
        home.mkdir()

        self.env = os.environ.copy()
        for name in [name for name in self.env if name.startswith("GIT_")]:
            del self.env[name]
        self.env.update(
            {
                "HOME": str(home),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
                "SKILLS_DOJO_ROOT": str(self.dojo),
                "SKILL_STATE_ROOT": str(self.state),
                "SKILLS_SHIP_SETTLE_SECONDS": "0",
            }
        )

        self.git("init", "--bare", "-b", "main", self.origin, cwd=self.root)
        self.git("init", "-b", "main", self.dojo, cwd=self.root)
        for repo in (self.dojo,):
            self.git("config", "user.email", "test@example.com", cwd=repo)
            self.git("config", "user.name", "Test", cwd=repo)
        self.git("remote", "add", "origin", self.origin, cwd=self.dojo)
        tools = self.dojo / "tools"
        tools.mkdir(parents=True)
        self.installer = tools / "skill_ship.py"
        shutil.copy(INSTALL, self.installer)
        for helper in ("skill_catalog.py", "catalog_state.py"):
            shutil.copy(PROJECT / "tools" / helper, tools / helper)
        shutil.copy(TRIGGER, tools / "skill-ship-trigger.sh")
        trigger = tools / "skill-ship-trigger.sh"
        trigger.write_text(trigger.read_text().replace("$TOOLS/skill_ship.py", "$TOOLS/test-ship"))
        trigger.chmod(0o755)
        release = tools / "test-ship"
        release.write_text('#!/bin/sh\necho "stub ship ran: $*"\n', encoding="utf-8")
        release.chmod(0o755)
        (self.dojo / "manifests").mkdir()
        (self.dojo / "manifests" / "shipped.yaml").write_text("{}\n", encoding="utf-8")
        (self.dojo / "README.md").write_text("initial\n", encoding="utf-8")
        alpha = self.dojo / "skills" / "alpha"
        alpha.mkdir(parents=True)
        (alpha / "SKILL.md").write_text("---\nname: alpha\ndescription: test\n---\n", encoding="utf-8")
        canonical = self.root / 'config/catalog.yaml'
        canonical.parent.mkdir(exist_ok=True); canonical.write_text('{"version":1,"where":{}}\n')
        alias = self.dojo / 'config/catalog.yaml'; alias.parent.mkdir()
        alias.symlink_to('../../config/catalog.yaml')
        run('python3', '-B', '-c', "from pathlib import Path; from catalog_state import approve_existing; approve_existing(Path('..'), 'Fixture baseline')", cwd=tools, env=self.env)
        self.git("add", ".", cwd=self.dojo)
        self.git("commit", "-m", "initial", cwd=self.dojo)
        self.git("push", "-u", "origin", "main", cwd=self.dojo)
        self.git("clone", self.origin, self.author, cwd=self.root)
        self.git("config", "user.email", "test@example.com", cwd=self.author)
        self.git("config", "user.name", "Test", cwd=self.author)
        self.install()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args, cwd):
        return run("git", *args, cwd=cwd, env=self.env)

    def install(self, *args, check=True):
        return run(self.installer, "install-trigger", *args, env=self.env, check=check)

    def started(self):
        if not self.log.is_file():
            return []
        return [line for line in self.log.read_text(encoding="utf-8").splitlines() if "ship started" in line]

    def wait_for_ship(self, count=1):
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.log.is_file() and self.log.read_text(encoding="utf-8").count("stub ship ran: ship") >= count:
                return
            time.sleep(0.1)
        self.fail(f"the ship command did not run: {self.log.read_text(encoding='utf-8') if self.log.is_file() else 'no log'}")

    def write(self, repo, relative, text):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def merge_pull_request(self, branch, files):
        """Do what a GitHub merge does: a merge commit on the remote main."""
        self.git("pull", "--ff-only", "origin", "main", cwd=self.author)
        self.git("checkout", "-b", branch, cwd=self.author)
        for relative, text in files.items():
            self.write(self.author, relative, text)
        self.git("add", ".", cwd=self.author)
        self.git("commit", "-m", f"{branch} change", cwd=self.author)
        self.git("checkout", "main", cwd=self.author)
        self.git("merge", "--no-ff", "-m", f"Merge pull request from {branch}", branch, cwd=self.author)
        self.git("push", "origin", "main", cwd=self.author)

    def head(self, *args):
        return self.git("rev-parse", *args, "HEAD", cwd=self.dojo).stdout.strip()

    def test_catalog_only_scope_change_starts_ship(self):
        catalog = self.dojo / 'config/catalog.yaml'
        before = self.head()
        old = __import__('hashlib').sha256(catalog.read_bytes()).hexdigest()
        payload = self.root / 'reviewed.json'
        payload.write_text('{"version":1,"where":{"alpha":"off"}}\n')
        # Run the real owner CLI. Its automatic notification calls a clearly labelled stub ship.
        run('python3', '-B', PROJECT.parent / 'base/catalog.py', '--system', self.dojo.parent,
            'apply', '--input', payload, '--expected-sha256', old, '--by', 'Fixture reviewer', env=self.env)
        self.wait_for_ship()
        self.assertEqual(before, self.head())
        self.assertEqual(os.readlink(catalog), '../../config/catalog.yaml')
        self.assertEqual(self.git('status', '--porcelain', '--', 'config/catalog.yaml', cwd=self.dojo).stdout, '')
        self.assertIn('ship --skill alpha', self.log.read_text())

    def test_unapproved_canonical_edit_stops_trigger(self):
        (self.root / 'config/catalog.yaml').write_text('{"version":1,"where":{"alpha":"off"}}\n')
        result = run(self.dojo / 'tools/skill-ship-trigger.sh', 'post-commit', env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('differs from its approved snapshot', result.stderr)
        self.assertEqual(self.started(), [])

    def test_changed_catalog_alias_fails_without_json_decode_error(self):
        catalog=self.dojo / 'config/catalog.yaml'; catalog.unlink(); catalog.symlink_to('../../config/missing.yaml')
        result=run(self.dojo / 'tools/skill-ship-trigger.sh', 'post-commit', env=self.env, check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Catalog alias must point',result.stderr)
        self.assertNotIn('JSONDecodeError',result.stderr)

    def test_merged_pull_request_starts_ship_on_fast_forward_pull(self):
        self.merge_pull_request("pr-skill", {"skills/alpha/SKILL.md": "changed\n"})
        self.git("pull", "--ff-only", cwd=self.dojo)

        parents = self.git("rev-list", "--parents", "-n", "1", "HEAD", cwd=self.dojo).stdout.split()
        self.assertEqual(len(parents), 3, "HEAD must be a merge commit for this case")
        self.assertEqual(len(self.started()), 1, self.started())
        self.assertIn(f"commit {self.head('--short')} on main touched a skill", self.started()[0])
        self.wait_for_ship()
        self.assertIn("ship --skill alpha", self.log.read_text())

    def test_pull_of_several_commits_reads_every_commit(self):
        self.git("pull", "--ff-only", "origin", "main", cwd=self.author)
        self.write(self.author, "skills/alpha/SKILL.md", "changed\n")
        self.git("commit", "-am", "skill change", cwd=self.author)
        self.write(self.author, "tools/note.txt", "tools only\n")
        self.git("add", ".", cwd=self.author)
        self.git("commit", "-m", "tools only", cwd=self.author)
        self.git("push", "origin", "main", cwd=self.author)
        self.git("pull", "--ff-only", cwd=self.dojo)

        self.assertEqual(len(self.started()), 1, self.started())
        self.wait_for_ship()
        self.assertIn("ship --skill alpha", self.log.read_text())

    def test_commit_on_main_starts_ship(self):
        self.write(self.dojo, "skills/alpha/SKILL.md", "changed\n")
        self.git("commit", "-am", "skill change", cwd=self.dojo)

        self.assertEqual(len(self.started()), 1, self.started())
        self.assertIn(f"commit {self.head('--short')} on main", self.started()[0])
        self.wait_for_ship()
        self.assertIn("ship --skill alpha", self.log.read_text())

    def test_change_outside_a_skill_starts_no_ship(self):
        outside = {
            "tools/note.txt": "x\n",
            "tests/test_note.py": "x\n",
            "manifests/shipped.yaml": '{"a": 1}\n',
            "README.md": "changed\n",
        }
        self.merge_pull_request("pr-tools", outside)
        self.git("pull", "--ff-only", cwd=self.dojo)
        self.write(self.dojo, "manifests/shipped.yaml", '{"a": 2}\n')
        self.git("commit", "-am", "chore: regen distribution manifest (ship)", cwd=self.dojo)

        self.assertEqual(self.started(), [])

    def test_skill_moved_to_retired_starts_ship(self):
        # A pure move out of a skill folder. With rename detection, `git diff --name-only`
        # prints only the new path under retired/, and the skill filter drops it.
        self.git("pull", "--ff-only", "origin", "main", cwd=self.author)
        (self.author / "retired").mkdir()
        self.git("mv", "skills/alpha", "retired/alpha", cwd=self.author)
        self.git("commit", "-m", "retire alpha", cwd=self.author)
        self.git("push", "origin", "main", cwd=self.author)
        self.git("pull", "--ff-only", cwd=self.dojo)

        self.assertEqual(len(self.started()), 1, self.started())
        self.wait_for_ship()
        self.assertIn("ship --skill alpha", self.log.read_text())

    def test_file_moved_out_of_a_skill_by_commit_starts_ship(self):
        self.write(self.dojo, "skills/alpha/helper.sh", "helper\n")
        self.git("add", ".", cwd=self.dojo)
        self.git("commit", "-m", "add helper", cwd=self.dojo)
        self.wait_for_ship(1)
        self.git("mv", "skills/alpha/helper.sh", "tools/helper.sh", cwd=self.dojo)
        self.git("commit", "-m", "move helper out of alpha", cwd=self.dojo)

        self.assertEqual(len(self.started()), 2, self.started())
        self.wait_for_ship(2)

    def test_commit_on_another_branch_starts_no_ship(self):
        self.git("checkout", "-b", "work", cwd=self.dojo)
        self.write(self.dojo, "skills/alpha/SKILL.md", "changed\n")
        self.git("commit", "-am", "skill change", cwd=self.dojo)

        self.assertEqual(self.started(), [])

    def test_install_writes_both_hooks_and_check_passes(self):
        report = json.loads(self.install("--check").stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["hooks"], {"post-commit": "current", "post-merge": "current"})
        for hook in ("post-commit", "post-merge"):
            path = self.dojo / ".git" / "hooks" / hook
            self.assertTrue(os.access(path, os.X_OK))
            self.assertIn(f'exec "$trigger" {hook} "$@"', path.read_text(encoding="utf-8"))

    def test_install_replaces_the_old_trigger_and_keeps_a_copy(self):
        hooks = self.dojo / ".git" / "hooks"
        for hook in ("post-commit", "post-merge"):
            (hooks / hook).write_text(OLD_HOOK, encoding="utf-8")
        check = self.install("--check", check=False)
        self.assertEqual(check.returncode, 1)
        self.assertEqual(json.loads(check.stdout)["hooks"]["post-merge"], "stale")

        dry = json.loads(self.install("--dry-run").stdout)
        self.assertEqual(len(dry["written"]), 2)
        self.assertEqual((hooks / "post-merge").read_text(encoding="utf-8"), OLD_HOOK)

        report = json.loads(self.install().stdout)
        self.assertEqual(report["hooks"], {"post-commit": "current", "post-merge": "current"})
        self.assertEqual(len(report["kept_copies"]), 2)
        for copy in report["kept_copies"]:
            self.assertEqual(Path(copy).read_text(encoding="utf-8"), OLD_HOOK)
        self.assertEqual(self.install("--check").returncode, 0)

    def test_install_refuses_an_unknown_hook(self):
        path = self.dojo / ".git" / "hooks" / "post-merge"
        path.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

        result = self.install(check=False)

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown hook, not replaced: post-merge", result.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), "#!/bin/sh\necho mine\n")


if __name__ == "__main__":
    unittest.main()
