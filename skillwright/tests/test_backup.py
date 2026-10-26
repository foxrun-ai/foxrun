import fcntl
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
BACKUP = PROJECT / "tools" / "skill_backup.py"


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.origin = self.root / "origin.git"
        self.dojo = self.root / "dojo"
        self.state = self.root / "state"
        self.receipts = self.state / "backups"
        self.active = self.root / "active"

        run("git", "init", "--bare", self.origin)
        run("git", "init", "-b", "main", self.dojo)
        run("git", "config", "user.email", "test@example.com", cwd=self.dojo)
        run("git", "config", "user.name", "Test", cwd=self.dojo)
        run("git", "remote", "add", "origin", self.origin, cwd=self.dojo)
        (self.dojo / "README.md").write_text("initial\n", encoding="utf-8")
        (self.dojo / ".gitignore").write_text("**/.env\n", encoding="utf-8")
        alpha = self.dojo / "alpha"
        alpha.mkdir()
        (alpha / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: test\n---\n", encoding="utf-8"
        )
        run("git", "add", ".", cwd=self.dojo)
        run("git", "commit", "-m", "initial", cwd=self.dojo)
        run("git", "push", "-u", "origin", "main", cwd=self.dojo)

        self.env = os.environ.copy()
        self.env.update(
            {
                "SKILLS_DOJO_ROOT": str(self.dojo),
                "SKILLS_DOJO_EXPECTED_REMOTE": str(self.origin),
                "SKILL_STATE_ROOT": str(self.state),
                "SKILLS_ACTIVE_PATH": str(self.active),
                "SKILLS_NOTIFY_COMMAND": "/usr/bin/true",
                "SKILLS_BACKUP_BRANCH": "backup/test-host",
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def backup(self, check=True, env=None):
        return run(BACKUP, "run", env=env or self.env, check=check)

    def source_state(self):
        return (
            run("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=self.dojo).stdout,
            run("git", "rev-parse", "HEAD", cwd=self.dojo).stdout,
            run("git", "branch", "--show-current", cwd=self.dojo).stdout,
        )

    def latest_receipt(self):
        receipt = sorted(self.receipts.glob("*.json"))[-1]
        return json.loads(receipt.read_text(encoding="utf-8"))

    def test_clean_backup_success_and_no_source_mutation(self):
        before = self.source_state()
        result = self.backup()
        self.assertIn("backup complete", result.stdout)
        self.assertEqual(before, self.source_state())
        remote = run(
            "git", "--git-dir", self.origin, "show", "backup/test-host:README.md"
        ).stdout
        self.assertEqual(remote, "initial\n")
        self.assertEqual(self.latest_receipt()["status"], "success")

    def test_dirty_allowlisted_snapshot_isolated_from_source(self):
        (self.dojo / "README.md").write_text("working copy\n", encoding="utf-8")
        new_skill = self.dojo / "new-skill"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text(
            "---\nname: new-skill\ndescription: test\n---\n", encoding="utf-8"
        )
        before = self.source_state()
        self.backup()
        self.assertEqual(before, self.source_state())
        remote = run(
            "git", "--git-dir", self.origin, "show", "backup/test-host:README.md"
        ).stdout
        self.assertEqual(remote, "working copy\n")
        names = run(
            "git", "--git-dir", self.origin, "ls-tree", "-r", "--name-only", "backup/test-host"
        ).stdout.splitlines()
        self.assertIn("new-skill/SKILL.md", names)
        # The commit message carries the time only, never this machine's name.
        message = run(
            "git", "--git-dir", self.origin, "log", "-1", "--format=%s", "backup/test-host"
        ).stdout.strip()
        self.assertRegex(message, r"^backup: \d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+$")
        self.assertNotIn(os.uname().nodename.split(".")[0], message.split(" ", 1)[1].rsplit(" ", 1)[0])

    def test_no_changes_is_successful_noop(self):
        self.backup()
        first = run(
            "git", "--git-dir", self.origin, "rev-parse", "backup/test-host"
        ).stdout
        result = self.backup()
        second = run(
            "git", "--git-dir", self.origin, "rev-parse", "backup/test-host"
        ).stdout
        self.assertEqual(first, second)
        self.assertIn("no changes", result.stdout)
        self.assertEqual(self.latest_receipt()["result"], "no_changes")

    def test_wrong_branch_fails_without_mutation_or_push(self):
        run("git", "switch", "-c", "feature", cwd=self.dojo)
        before = self.source_state()
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected branch", result.stderr)
        self.assertEqual(before, self.source_state())
        refs = run("git", "--git-dir", self.origin, "show-ref", check=False).stdout
        self.assertNotIn("backup/test-host", refs)
        self.assertEqual(self.latest_receipt()["status"], "failure")

    def test_detached_head_fails(self):
        run("git", "checkout", "--detach", cwd=self.dojo)
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("detached", result.stderr)

    def test_conflict_fails(self):
        run("git", "switch", "-c", "conflict", cwd=self.dojo)
        (self.dojo / "README.md").write_text("branch\n", encoding="utf-8")
        run("git", "commit", "-am", "branch", cwd=self.dojo)
        run("git", "switch", "main", cwd=self.dojo)
        (self.dojo / "README.md").write_text("main\n", encoding="utf-8")
        run("git", "commit", "-am", "main", cwd=self.dojo)
        run("git", "merge", "conflict", cwd=self.dojo, check=False)
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflict", result.stderr)

    def test_resolved_but_unfinished_merge_fails(self):
        run("git", "switch", "-c", "conflict", cwd=self.dojo)
        (self.dojo / "README.md").write_text("branch\n", encoding="utf-8")
        run("git", "commit", "-am", "branch", cwd=self.dojo)
        run("git", "switch", "main", cwd=self.dojo)
        (self.dojo / "README.md").write_text("main\n", encoding="utf-8")
        run("git", "commit", "-am", "main", cwd=self.dojo)
        run("git", "merge", "conflict", cwd=self.dojo, check=False)
        (self.dojo / "README.md").write_text("resolved\n", encoding="utf-8")
        run("git", "add", "README.md", cwd=self.dojo)
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unfinished Git operation", result.stderr)

    def test_divergent_main_fails(self):
        (self.dojo / "README.md").write_text("local commit\n", encoding="utf-8")
        run("git", "commit", "-am", "local", cwd=self.dojo)
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synchronized", result.stderr)

    def test_blocked_path_fails(self):
        (self.dojo / ".env").write_text("SECRET=value\n", encoding="utf-8")
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ignored sensitive path", result.stderr)

    def test_sensitive_file_inside_skill_fails(self):
        (self.dojo / "alpha" / "session.json").write_text("{}\n", encoding="utf-8")
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sensitive path", result.stderr)

    def test_credential_like_content_inside_skill_fails(self):
        fake = "ghp_" + "A" * 36
        (self.dojo / "alpha" / "notes.md").write_text(fake + "\n", encoding="utf-8")
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("credential-like content", result.stderr)

    def test_modern_credential_formats_inside_skill_fail(self):
        credentials = (
            "github_pat_" + "A" * 40,
            "glpat-" + "A" * 24,
            "AIza" + "A" * 35,
            "eyJ" + "A" * 12 + "." + "B" * 12 + "." + "C" * 12,
            "AWS_SECRET_ACCESS_KEY=" + "A" * 40,
        )
        for credential in credentials:
            with self.subTest(prefix=credential[:12]):
                (self.dojo / "alpha" / "notes.md").write_text(
                    credential + "\n", encoding="utf-8"
                )
                result = self.backup(check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("credential-like content", result.stderr)

    def test_nested_runtime_state_inside_skill_fails(self):
        runtime = self.dojo / "alpha" / ".claude"
        runtime.mkdir()
        (runtime / "settings.local.json").write_text("{}\n", encoding="utf-8")
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sensitive path", result.stderr)

    def test_lock_contention_fails(self):
        self.state.mkdir(parents=True)
        lock = self.state / "lifecycle.lock"
        with lock.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lock is busy", result.stderr)

    def test_runtime_path_is_rejected(self):
        env = self.env.copy()
        env["SKILLS_DOJO_ROOT"] = str(self.active)
        self.active.symlink_to(self.dojo, target_is_directory=True)
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime path", result.stderr)

    def test_notification_failure_does_not_hide_primary_failure(self):
        run("git", "switch", "-c", "feature", cwd=self.dojo)
        env = self.env.copy()
        env["SKILLS_NOTIFY_COMMAND"] = "/usr/bin/false"
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected branch", result.stderr)
        self.assertEqual(self.latest_receipt()["status"], "failure")

    def test_missing_notification_command_does_not_hide_primary_failure(self):
        run("git", "switch", "-c", "feature", cwd=self.dojo)
        env = self.env.copy()
        env["SKILLS_NOTIFY_COMMAND"] = str(self.root / "missing-notifier")
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected branch", result.stderr)
        self.assertEqual(self.latest_receipt()["status"], "failure")

    def test_non_backup_namespace_is_rejected(self):
        env = self.env.copy()
        env["SKILLS_BACKUP_BRANCH"] = "main"
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backup/ namespace", result.stderr)

    def test_linked_worktree_is_rejected(self):
        worktree = self.root / "worktree"
        run("git", "worktree", "add", "-b", "worktree-test", worktree, cwd=self.dojo)
        env = self.env.copy()
        env["SKILLS_DOJO_ROOT"] = str(worktree)
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a normal Git clone", result.stderr)

    def test_unallowlisted_root_file_is_rejected(self):
        (self.dojo / "notes.txt").write_text("not a skill\n", encoding="utf-8")
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowlisted", result.stderr)

    def test_symlink_is_preserved_without_copying_target(self):
        target = self.root / "outside.txt"
        target.write_text("outside secret\n", encoding="utf-8")
        link = self.dojo / "README-link"
        link.mkdir()
        (link / "SKILL.md").symlink_to(target)
        self.backup()
        mode = run(
            "git", "--git-dir", self.origin, "ls-tree", "backup/test-host", "README-link/SKILL.md"
        ).stdout
        payload = run(
            "git", "--git-dir", self.origin, "show", "backup/test-host:README-link/SKILL.md"
        ).stdout
        self.assertIn("120000", mode)
        self.assertEqual(payload.strip(), str(target))

    def test_argument_free_invocation_does_not_back_up(self):
        result = run(BACKUP, env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        refs = run("git", "--git-dir", self.origin, "show-ref", check=False).stdout
        self.assertNotIn("backup/test-host", refs)

    def test_branch_change_during_clone_is_rejected(self):
        run("git", "branch", "feature", cwd=self.dojo)
        wrapper_dir = self.root / "fake-bin"
        wrapper_dir.mkdir()
        wrapper = wrapper_dir / "git"
        real_git = run("sh", "-c", "command -v git").stdout.strip()
        wrapper.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = clone ]; then\n"
            "  \"$REAL_GIT\" -C \"$RACE_DOJO\" switch feature >/dev/null 2>&1\n"
            "fi\n"
            "exec \"$REAL_GIT\" \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        env = self.env.copy()
        env.update(
            {
                "PATH": str(wrapper_dir) + os.pathsep + env["PATH"],
                "REAL_GIT": real_git,
                "RACE_DOJO": str(self.dojo),
            }
        )
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected branch main", result.stderr)
        refs = run("git", "--git-dir", self.origin, "show-ref", check=False).stdout
        self.assertNotIn("backup/test-host", refs)

    def test_same_dirty_path_change_during_clone_is_rejected(self):
        (self.dojo / "README.md").write_text("snapshot-v1\n", encoding="utf-8")
        wrapper_dir = self.root / "race-bin"
        wrapper_dir.mkdir()
        wrapper = wrapper_dir / "git"
        real_git = run("sh", "-c", "command -v git").stdout.strip()
        wrapper.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = -C ] && [ \"$3\" = switch ] && [ \"$2\" != \"$RACE_DOJO\" ]; then\n"
            "  printf 'snapshot-v2\\n' > \"$RACE_DOJO/README.md\"\n"
            "fi\n"
            "exec \"$REAL_GIT\" \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        env = self.env.copy()
        env.update(
            {
                "PATH": str(wrapper_dir) + os.pathsep + env["PATH"],
                "REAL_GIT": real_git,
                "RACE_DOJO": str(self.dojo),
            }
        )
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source changed", result.stderr)
        refs = run("git", "--git-dir", self.origin, "show-ref", check=False).stdout
        self.assertNotIn("backup/test-host", refs)

    def test_git_timeout_is_nonzero_and_durable(self):
        wrapper_dir = self.root / "slow-bin"
        wrapper_dir.mkdir()
        wrapper = wrapper_dir / "git"
        real_git = run("sh", "-c", "command -v git").stdout.strip()
        wrapper.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = clone ]; then sleep 2; fi\n"
            "exec \"$REAL_GIT\" \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        env = self.env.copy()
        env.update(
            {
                "PATH": str(wrapper_dir) + os.pathsep + env["PATH"],
                "REAL_GIT": real_git,
                "SKILLS_BACKUP_GIT_TIMEOUT": "1",
            }
        )
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.latest_receipt()["status"], "failure")

    def test_missing_expected_remote_refuses(self):
        env = self.env.copy()
        env.pop("SKILLS_DOJO_EXPECTED_REMOTE")
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SKILLS_DOJO_EXPECTED_REMOTE", self.latest_receipt()["error"])

    def person_repo(self):
        """The person's own skill repo (T675): a tracked stray file, an untracked STATE.md page."""
        origin = self.root / "person.git"
        person = self.root / "person"
        run("git", "init", "--bare", origin)
        run("git", "init", "-b", "main", person)
        run("git", "config", "user.email", "test@example.com", cwd=person)
        run("git", "config", "user.name", "Test", cwd=person)
        run("git", "remote", "add", "origin", origin, cwd=person)
        (person / "skills" / "beta").mkdir(parents=True)
        (person / "skills" / "beta" / "SKILL.md").write_text(
            "---\nname: beta\ndescription: test\n---\n", encoding="utf-8"
        )
        (person / "skills" / "stray").write_text("tracked stray file\n", encoding="utf-8")
        run("git", "add", ".", cwd=person)
        run("git", "commit", "-m", "initial", cwd=person)
        run("git", "push", "-u", "origin", "main", cwd=person)
        (person / "STATE.md").write_text("# State\n", encoding="utf-8")
        return person, origin

    def test_person_repo_is_backed_up_too(self):
        person, origin = self.person_repo()
        (person / "skills" / "beta" / "notes.md").write_text("working copy\n", encoding="utf-8")
        env = dict(self.env, SKILLS_PERSON_ROOT=str(person), SKILLS_PERSON_EXPECTED_REMOTE=str(origin))
        result = self.backup(env=env)
        self.assertIn("backup complete", result.stdout)
        self.assertEqual(
            run("git", "--git-dir", self.origin, "show", "backup/test-host:README.md").stdout, "initial\n"
        )
        names = run(
            "git", "--git-dir", origin, "ls-tree", "-r", "--name-only", "backup/test-host"
        ).stdout.splitlines()
        self.assertEqual(sorted(names), ["STATE.md", "skills/beta/SKILL.md", "skills/beta/notes.md", "skills/stray"])
        receipts = [json.loads(path.read_text()) for path in sorted(self.receipts.glob("*.json"))]
        self.assertEqual(
            {(item["dojo"], item["status"]) for item in receipts},
            {(str(self.dojo.resolve()), "success"), (str(person.resolve()), "success")},
        )

    def test_person_repo_without_expected_remote_fails_after_the_dojo_backup(self):
        person, origin = self.person_repo()
        env = dict(self.env, SKILLS_PERSON_ROOT=str(person))
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SKILLS_PERSON_EXPECTED_REMOTE", result.stderr)
        self.assertIn("backup/test-host", run("git", "--git-dir", self.origin, "show-ref").stdout)
        self.assertNotIn("backup/test-host", run("git", "--git-dir", origin, "show-ref", check=False).stdout)

    def test_ignored_log_does_not_stop_the_backup(self):
        # The ship trigger writes skill-state/ships/trigger.log inside the Dojo; git ignores it.
        (self.dojo / ".gitignore").write_text("**/.env\nskill-state/\n", encoding="utf-8")
        (self.dojo / "skill-state" / "ships").mkdir(parents=True)
        (self.dojo / "skill-state" / "ships" / "trigger.log").write_text("ship started\n", encoding="utf-8")
        self.backup()
        names = run(
            "git", "--git-dir", self.origin, "ls-tree", "-r", "--name-only", "backup/test-host"
        ).stdout.splitlines()
        self.assertNotIn("skill-state/ships/trigger.log", names)

    def test_credential_bearing_remote_is_redacted(self):
        env = self.env.copy()
        env["SKILLS_DOJO_EXPECTED_REMOTE"] = "https://github.com/expected/repo.git"
        run(
            "git",
            "remote",
            "set-url",
            "origin",
            "https://super-secret-token@github.com/wrong/repo.git",
            cwd=self.dojo,
        )
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("super-secret-token", result.stderr)
        receipt = self.latest_receipt()
        self.assertNotIn("super-secret-token", json.dumps(receipt))

    def test_remote_query_and_fragment_are_redacted(self):
        env = self.env.copy()
        env["SKILLS_DOJO_EXPECTED_REMOTE"] = "https://github.com/expected/repo.git"
        run(
            "git",
            "remote",
            "set-url",
            "origin",
            "https://github.com/wrong/repo.git?access_token=TOPSECRET#FRAGMENTSECRET",
            cwd=self.dojo,
        )
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("TOPSECRET", result.stderr)
        self.assertNotIn("FRAGMENTSECRET", result.stderr)
        self.assertNotIn("TOPSECRET", json.dumps(self.latest_receipt()))

    def test_unwritable_receipt_path_fails_before_push(self):
        blocked = self.root / "receipt-file"
        blocked.write_text("not a directory\n", encoding="utf-8")
        env = self.env.copy()
        env["SKILLS_BACKUP_RECEIPTS"] = str(blocked)
        result = self.backup(check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("receipt storage unavailable", result.stderr)
        refs = run("git", "--git-dir", self.origin, "show-ref", check=False).stdout
        self.assertNotIn("backup/test-host", refs)

    def test_push_failure_is_nonzero_and_durable(self):
        hooks = self.origin / "hooks"
        hook = hooks / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("returned non-zero", result.stderr)
        self.assertEqual(self.latest_receipt()["status"], "failure")


if __name__ == "__main__":
    unittest.main()
