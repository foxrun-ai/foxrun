import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
# skillify is the person's own skill; after T675 its source is the person's repository.
_PERSON = Path(os.environ.get("SKILLS_PERSON_ROOT") or Path(os.environ.get("FOXRUN_PORTFOLIO", "~/foxrun")).expanduser() / "skillwright")
SKILLIFY = next((root / "skills/skillify/bin/skillify" for root in (PROJECT, _PERSON)
                 if (root / "skills/skillify/bin/skillify").is_file()), PROJECT / "skills/skillify/bin/skillify")
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


def seed_release_gate(system, source_system):
    """Use the real gate and engine with a labelled minimal skill-source fixture policy."""
    (system/'base').mkdir(parents=True,exist_ok=True)
    for name in ['lint.py','lint_gate.py']:shutil.copy2(source_system/'base'/name,system/'base'/name)
    shutil.copytree(source_system/'config/lint',system/'config/lint')
    (system/'config/lint/rules.tsv').write_text('id\twords\tkind\tscope\tlevel\nFIXTURE-BLANK-SKILL\tFixture skill pages contain text.\tblank_page\tsystem:*/skills/**/SKILL.md\terror\n')

class SkillifyCheckDryRunTest(unittest.TestCase):
    """`skillify check` runs the real ship dry run against the Claude root in HOME."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        seed_release_gate(self.root,PROJECT.parent)
        (self.root/"portfolio").mkdir()
        self.home = self.root / "home"
        self.claude = self.home / ".claude" / "skills"
        self.active = self.home / ".agents" / "skills"
        self.dojo = self.root / "dojo"
        self.claude.mkdir(parents=True)
        self.active.parent.mkdir(parents=True)

        self.env = os.environ.copy()
        uv = shutil.which("uv")
        if uv:
            # HOME moves below. Keep the real uv cache, or the ship's test step needs the network.
            self.env["UV_CACHE_DIR"] = run(uv, "cache", "dir").stdout.strip()
        self.env.update(
            {
                "HOME": str(self.home),
                "FOXRUN_HOME": str(self.root),
                "FOXRUN_PORTFOLIO": str(self.root/"portfolio"),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "SKILLIFY_DOJO_ROOT": str(self.dojo),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        for name in ("SKILLS_DOJO_ROOT", "SKILLIFY_RELEASE_TOOL"):
            self.env.pop(name, None)

        shutil.copytree(
            PROJECT / "tools", self.dojo / "tools",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        skill = self.dojo / "skills/demo-note"
        skill.mkdir(parents=True)
        shutil.copytree(SKILLIFY.parents[1], self.dojo / "skills/skillify")
        (skill / "SKILL.md").write_text(
            "---\nname: demo-note\n"
            "description: Read the demo note and report what it says.\n---\n\n"
            "# Demo note\n\nRead the demo note and report its stored text without changing the note.\n",
            encoding="utf-8",
        )
        tests = self.dojo / "tests"
        tests.mkdir()
        (tests / "test_smoke.py").write_text(
            "import unittest\n\n"
            "class SmokeTest(unittest.TestCase):\n"
            "    def test_smoke(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (self.dojo / "manifests").mkdir()
        (self.dojo / "config").mkdir()
        (self.dojo / "config" / "catalog.yaml").write_text(
            json.dumps(
                {
                    "version": 1,
                    "where": {"skillify": "off"},
                    "claude_preserve_physical": [],
                    "claude_approval_required": {},
                    "host_specific": {},
                    "claude_app_owned": {
                        "synced": {"reason": "The Claude app owns this folder."}
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return run("git", *args, cwd=self.dojo, env=self.env)

    def write_app_folder(self, sync_round):
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

    def commit_clean_main(self):
        """Clean main as the last ship left it: the manifest is committed."""
        run(
            INVENTORY, "distribution", "--candidate", self.dojo, "--active", self.active,
            "--claude", self.claude, "--output", self.dojo / "manifests" / "shipped.yaml",
            env=self.env,
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "clean main after the last ship")

    def check(self):
        return run(SKILLIFY, "check", "demo-note", cwd=self.dojo, env=self.env, check=False)

    def test_unchanged_skill_passes_after_the_app_rewrote_its_folder(self):
        self.write_app_folder(1)
        self.commit_clean_main()
        self.write_app_folder(2)

        result = self.check()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Claude entry drift", result.stderr)
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_unchanged_skill_passes_after_a_user_folder_changed(self):
        folder = self.claude / "claude-only"
        folder.mkdir()
        (folder / "SKILL.md").write_text("v1\n", encoding="utf-8")
        self.commit_clean_main()
        (folder / "SKILL.md").write_text("v2 written after the last ship\n", encoding="utf-8")

        result = self.check()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("status", "--porcelain").stdout, "")


if __name__ == "__main__":
    unittest.main()
