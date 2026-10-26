"""setup checks on labeled fake data in a temporary home. No live settings or jobs are touched."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "setup"
# The product tree in a checkout, or the system home once installed. Both hold foxrun.py.
PRODUCT = Path(__file__).resolve().parents[4]
MODELS = {"tiers": {tier: {"claude": {"model": "fake-claude"}, "codex": {"model": "fake-codex"}, "hermes": None}
                    for tier in ("judgment", "work", "cheap", "code")},
          "allowed": ["fake-claude", "fake-codex"], "banned": ["fake-banned"]}


QUESTION = ("Turn on automatic memory? Your agent loads your open work at the start of every chat, "
            "and saves where it left off before a long chat gets trimmed. Recommended.")


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "fake-home"
        self.home = self.root / ".foxrun"
        (self.home / "config").mkdir(parents=True)
        (self.home / "agents").mkdir()
        (self.home / "hooks/claude").mkdir(parents=True)
        (self.home / "config/models.yaml").write_text(json.dumps(MODELS))
        (self.home / "agents/architect.md").write_text(
            "---\n" + json.dumps({"id": "architect", "display_name": "Architect", "tier": "judgment",
                                  "runtimes": ["claude", "codex"]}) + "\n---\n# fake\n")
        for name in ("fake-hq", "fake-shop"):
            (self.root / "foxrun" / name).mkdir(parents=True)
            (self.root / "foxrun" / name / "AGENTS.md").write_text("# " + name + " (labeled fake)\n")
        self.write_person(name="fake-person", runtime="claude", default_workspace="fake-hq",
                          workspaces=["fake-hq", "fake-shop"], portfolio="../foxrun")
        self.env = {**os.environ, "HOME": str(self.root), "FOXRUN_HOME": str(self.home),
                    "THREAD_CODEX_STATE_DB": str(self.root / "none.sqlite")}
        for key in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "FOXRUN_PORTFOLIO"):
            self.env.pop(key, None)

    def write_person(self, **data):
        (self.home / "config/person.json").write_text(json.dumps(data))

    def run_setup(self, *args, code=0):
        done = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              env=self.env, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, code, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def part(self, result, name):
        return next(part for part in result["parts"] if part["part"] == name)

    def test_status_walks_parts_in_order_and_names_the_next_question(self):
        result = self.run_setup("status")
        self.assertEqual([part["part"] for part in result["parts"]], ["questions", "threads", "hooks", "backup"])
        self.assertEqual(self.part(result, "questions")["open"], [])
        self.assertEqual(result["next"]["part"], "threads")
        self.assertEqual(result["next"]["seat"], "architect")

    def test_missing_answers_come_first(self):
        self.write_person(portfolio="../foxrun")
        result = self.run_setup("status")
        fields = [item["field"] for item in self.part(result, "questions")["open"]]
        self.assertEqual(fields, ["name", "runtime", "default_workspace"])
        self.assertEqual(result["next"]["field"], "name")
        workspace = self.part(result, "questions")["open"][2]
        self.assertEqual(workspace["choices"], ["fake-hq", "fake-shop"])

    def test_hooks_found_by_script_path(self):
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir()
        command = "FOXRUN_HOME={0} sh {0}/hooks/claude/".format(self.home)
        settings.write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": command + "session-start"}]},
                             {"hooks": [{"type": "command", "command": command + "after-compact"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]}}))
        hooks = self.part(self.run_setup("status", "--part", "hooks"), "hooks")
        missing = hooks["runtimes"][0]["missing"]
        self.assertEqual(missing, [{"event": "PreCompact", "script": str(self.home / "hooks/claude/before-compact")}])

    def wire_all_kept_hooks(self, runtime="claude"):
        (self.home / "hooks/start-rules.py").write_text("# Hermes only (labeled fake)\n")
        (self.home / "hooks" / runtime / (runtime + "_session_end.sh")).write_text("# fake\n")
        command = "FOXRUN_HOME={0} sh {0}/hooks/{1}/".format(self.home, runtime)
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir(exist_ok=True)
        settings.write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": command + "session-start"}]},
                             {"hooks": [{"type": "command", "command": command + "after-compact"}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": command + "before-compact"}]}],
            "SessionEnd": [{"hooks": [{"type": "command", "command": command + runtime + "_session_end.sh"}]}]}}))
        return settings

    def test_start_rules_is_never_missing_on_claude_or_codex(self):
        self.wire_all_kept_hooks()
        hooks = self.part(self.run_setup("status", "--part", "hooks"), "hooks")
        self.assertEqual(hooks["runtimes"][0]["missing"], [])
        self.assertEqual(hooks["open"], [])
        self.write_person(name="fake-person", runtime="codex", default_workspace="fake-hq",
                          workspaces=["fake-hq"], portfolio="../foxrun")
        (self.home / "hooks/codex").mkdir()
        codex = self.part(self.run_setup("status", "--part", "hooks"), "hooks")["runtimes"][0]
        scripts = [item["script"] for item in codex["missing"]]
        self.assertNotIn(str(self.home / "hooks/start-rules.py"), scripts)
        self.assertEqual(sorted(Path(script).name for script in scripts), ["after-compact", "before-compact", "session-start"])

    def test_missing_hooks_ask_the_memory_question_with_yes_recommended(self):
        hooks = self.part(self.run_setup("status", "--part", "hooks"), "hooks")
        self.assertEqual(len(hooks["open"]), 1)
        item = hooks["open"][0]
        self.assertEqual(item["question"], QUESTION)
        self.assertEqual((item["choices"][0], item["recommended"]), ("Yes (recommended)", "yes"))
        self.assertEqual(self.run_setup("status")["parts"][2]["open"][0]["question"], QUESTION)

    def install_core(self):
        """The fake home runs the real launcher from this product tree, and holds labeled fake hook scripts."""
        for name in ("session-start", "after-compact", "before-compact"):
            (self.home / "hooks/claude" / name).write_text("# labeled fake hook\n")
        (self.home / "foxrun.py").write_text("import runpy, sys\nsys.argv[0] = {0!r}\nrunpy.run_path({0!r}, run_name='__main__')\n"
                                             .format(str(PRODUCT / "foxrun.py")))

    def backups(self):
        folder = self.home / "backups"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []

    def test_no_writes_nothing(self):
        self.install_core()
        self.assertFalse(self.run_setup("hooks", "--answer", "no")["written"])
        self.assertFalse((self.root / ".claude").exists())
        self.assertEqual(self.backups(), [])

    def test_yes_connects_the_hooks_backs_up_and_keeps_the_persons_entries(self):
        self.install_core()
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir()
        mine = {"type": "command", "command": "echo mine (labeled fake)"}
        before = json.dumps({"theme": "keep", "hooks": {"SessionStart": [{"hooks": [mine]}],
                                                       "Stop": [{"hooks": [mine]}]}}).encode()
        settings.write_bytes(before)
        result = self.run_setup("hooks", "--answer", "yes")
        self.assertTrue(result["written"])
        self.assertIn("saves where the agent left off", result["what_it_does"]["PreCompact"])
        self.assertEqual(result["still_missing"], [])
        self.assertEqual([row["settings"] for row in result["connected"]], [str(settings)])
        data = json.loads(settings.read_text())
        self.assertEqual(data["theme"], "keep")
        self.assertEqual(data["hooks"]["Stop"], [{"hooks": [mine]}])
        self.assertEqual(data["hooks"]["SessionStart"][0], {"hooks": [mine]})
        self.assertEqual(len(data["hooks"]["SessionStart"]), 3)
        self.assertNotIn("start-rules", settings.read_text())
        self.assertEqual(self.part(self.run_setup("status", "--part", "hooks"), "hooks")["open"], [])
        # The backup holds the old bytes, and names where they came from.
        self.assertEqual(len(result["backups"]), 1)
        backup = Path(result["backups"][0])
        self.assertEqual((backup / "claude/settings.json").read_bytes(), before)
        self.assertEqual(json.loads((backup / "sources.json").read_text()), {"claude/settings.json": str(settings)})
        # A second yes finds every hook and writes nothing.
        after = settings.read_bytes()
        again = self.run_setup("hooks", "--answer", "yes")
        self.assertEqual(again["note"], "Automatic memory is already on.")
        self.assertEqual(settings.read_bytes(), after)
        self.assertEqual(self.backups(), [backup.name])

    def test_yes_makes_a_new_settings_file_with_no_backup(self):
        self.install_core()
        result = self.run_setup("hooks", "--answer", "yes")
        self.assertTrue(result["written"])
        self.assertEqual(result["backups"], [])
        hooks = json.loads((self.root / ".claude/settings.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "PreCompact"})
        self.assertEqual(self.backups(), [])

    def test_yes_on_an_older_core_says_to_update_first(self):
        (self.home / "foxrun.py").write_text("import sys\nsys.stderr.write(\"foxrun.py: error: argument command: invalid choice: 'hookup'\\n\")\n"
                                             "raise SystemExit(2)\n")
        error = self.run_setup("hooks", "--answer", "yes", code=1)["error"]
        self.assertIn("Update the core first", error)
        self.assertFalse((self.root / ".claude").exists())

    def test_yes_with_no_core_writes_nothing(self):
        error = self.run_setup("hooks", "--answer", "yes", code=1)["error"]
        self.assertIn("not installed", error)
        self.assertFalse((self.root / ".claude").exists())

    def test_yes_when_memory_is_already_on(self):
        settings = self.wire_all_kept_hooks()
        before = settings.read_text()
        result = self.run_setup("hooks", "--answer", "yes")
        self.assertEqual(result["note"], "Automatic memory is already on.")
        self.assertEqual(settings.read_text(), before)

    def test_bad_settings_file_is_an_open_item(self):
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir()
        settings.write_text("[]")
        hooks = self.part(self.run_setup("status", "--part", "hooks"), "hooks")
        self.assertIn("not a JSON object", hooks["open"][0]["question"])

    def test_backup_open_items(self):
        backup = self.part(self.run_setup("status", "--part", "backup"), "backup")
        self.assertFalse(backup["nightly_on"])
        self.assertEqual([item["question"] for item in backup["open"]],
                         ["Turn on the nightly job?", "Push the state backup to a private remote repository?"])

    def test_set_dry_run_writes_nothing_and_real_run_writes(self):
        before = (self.home / "config/person.json").read_text()
        dry = self.run_setup("set", "--field", "runtime=both", "--dry-run")
        self.assertEqual(dry["changes"]["runtime"], {"from": "claude", "to": "both"})
        self.assertEqual((self.home / "config/person.json").read_text(), before)
        self.run_setup("set", "--field", "default_workspace=fake-shop")
        data = json.loads((self.home / "config/person.json").read_text())
        self.assertEqual(data["default_workspace"], "fake-shop")
        self.assertEqual(data["name"], "fake-person")

    def test_set_refusals(self):
        for field, text in (("name=x", "set takes"), ("runtime=hermes", "runtime must be"),
                            ("default_workspace=missing", "no workspace folder")):
            with self.subTest(field=field):
                self.assertIn(text, self.run_setup("set", "--field", field, code=1)["error"])

    def test_help_never_prompts(self):
        done = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                              env=self.env, stdin=subprocess.DEVNULL, timeout=20)
        self.assertEqual(done.returncode, 0)
        self.assertIn("questions, threads, hooks, backup", done.stdout)


if __name__ == "__main__":
    unittest.main()
