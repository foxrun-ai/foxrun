"""thread checks on labeled fake data in a temporary home. No real app or thread is touched."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "thread"
# agent-new ships beside this skill: src/agents/tools in the source, ~/.foxrun/agents/tools when installed.
AGENT_NEW = next((folder / "agents/tools/agent_new.py" for folder in SCRIPT.parents
                  if (folder / "agents/tools/agent_new.py").is_file()), None)
MODELS = {"tiers": {tier: {"claude": {"model": "fake-claude-" + tier}, "codex": {"model": "fake-codex-" + tier},
                           "hermes": None} for tier in ("judgment", "work", "cheap", "code")},
          "allowed": ["fake-claude-judgment", "fake-claude-work", "fake-claude-cheap", "fake-claude-code",
                      "fake-codex-judgment", "fake-codex-work", "fake-codex-cheap", "fake-codex-code"],
          "banned": ["fake-banned"]}
CODEX_STUB = '''#!/usr/bin/env python3
import json, os, sys
log = open(os.environ["STUB_LOG"], "a")
for line in sys.stdin:
    message = json.loads(line)
    log.write(json.dumps(message) + "\\n"); log.flush()
    method = message.get("method")
    if "id" in message and method is None:
        continue
    if method == "initialize":
        print(json.dumps({"id": message["id"], "result": {}}), flush=True)
    elif method == "thread/start":
        print(json.dumps({"id": message["id"], "result": {"thread": {"id": "fake-thread-1"}}}), flush=True)
    elif method == "thread/name/set":
        print(json.dumps({"id": message["id"], "result": {}}), flush=True)
    elif method == "turn/start":
        print(json.dumps({"id": message["id"], "result": {"turn": {"id": "t1"}}}), flush=True)
        print(json.dumps({"id": 99, "method": "item/commandExecution/requestApproval", "params": {}}), flush=True)
        print(json.dumps({"method": "turn/completed", "params": {}}), flush=True)
'''
CLAUDE_STUB = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_LOG"], "w") as log:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd()}, log)
if os.environ.get("STUB_UNTRUSTED"):
    print("Error: this folder is not trusted", file=sys.stderr); sys.exit(1)
print("Started background session 0a1b2c3d-0000-4000-8000-000000000001")
'''


def seat(ident, name, tier="judgment", runtimes=("claude", "codex")):
    return "---\n" + json.dumps({"id": ident, "display_name": name, "tier": tier,
                                 "runtimes": list(runtimes)}) + "\n---\n# " + name + " (labeled fake)\n"


class ThreadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()  # agent_new refuses a portfolio behind a link, such as /var
        self.home, self.folder = root / "fake-home/.foxrun", root / "fake-home/foxrun"
        (self.home / "config").mkdir(parents=True)
        (self.home / "agents").mkdir()
        (self.home / "config/models.yaml").write_text(json.dumps(MODELS))
        (self.home / "agents/architect.md").write_text(seat("architect", "Architect"))
        (self.home / "agents/scout.md").write_text(seat("scout", "Scout", "work", ("claude",)))
        (self.home / "agents/soul.md").write_text("# soul, no frontmatter\n")
        (self.folder / "fake-hq").mkdir(parents=True)
        (self.folder / "fake-shop/team").mkdir(parents=True)
        (self.folder / "fake-shop/team/lead-fake-shop.md").write_text(seat("lead-fake-shop", "Lead", "work"))
        self.bin, self.log = root / "bin", root / "stub.log"
        self.bin.mkdir()
        for name, body in (("codex", CODEX_STUB), ("claude", CLAUDE_STUB)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.env = {**os.environ, "HOME": str(root / "fake-home"), "FOXRUN_HOME": str(self.home),
                    "FOXRUN_PORTFOLIO": str(self.folder), "STUB_LOG": str(self.log),
                    "THREAD_CODEX_BIN": str(self.bin / "codex"), "THREAD_CLAUDE_BIN": str(self.bin / "claude"),
                    "THREAD_CODEX_STATE_DB": str(root / "no-codex.sqlite")}

    def run_thread(self, *args, code=0, **env):
        done = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              env={**self.env, **env}, timeout=60)
        self.assertEqual(done.returncode, code, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def saved(self):
        return json.loads((self.home / "config/threads.json").read_text())["threads"]

    def test_list_names_agents_and_leads_and_skips_files_without_identity(self):
        result = self.run_thread("list")
        seats = {row["seat"]: row for row in result["agents"]}
        self.assertEqual(set(seats), {"architect", "scout", "lead-fake-shop"})
        self.assertEqual(seats["lead-fake-shop"]["emoji"], "🧭")
        self.assertEqual(sorted(result["without_thread"]), ["architect", "lead-fake-shop", "scout"])
        self.assertEqual({row["emoji_state"] for row in result["agents"]}, {"default"})

    def test_list_sees_a_saved_thread_and_a_codex_thread_by_title(self):
        (self.home / "config/threads.json").write_text(json.dumps({"emoji": {"scout": "🦊"}, "threads": {
            "scout@fake-hq": {"runtime": "claude-desktop", "id": "s-1", "title": "🦊 fake-hq · Scout"}}}))
        db = Path(self.temp.name) / "codex.sqlite"
        with sqlite3.connect(db) as connection:
            connection.execute("create table threads (id text, name text)")
            connection.execute("insert into threads values ('c-1', '📦 fake-hq · Architect')")
            connection.execute("insert into threads values ('c-2', '🧭 other · Lead')")
        result = self.run_thread("list", THREAD_CODEX_STATE_DB=str(db))
        seats = {row["seat"]: row for row in result["agents"]}
        self.assertTrue(seats["scout"]["has_thread"])
        self.assertEqual(seats["scout"]["emoji_state"], "default")
        self.assertEqual(seats["architect"]["threads"][0]["id"], "c-1")
        self.assertFalse(seats["lead-fake-shop"]["has_thread"])

    def test_personal_copy_wins_over_shipped_seat(self):
        (self.home / "profile/agents").mkdir(parents=True)
        (self.home / "profile/agents/architect.md").write_text(seat("architect", "Builder"))
        result = self.run_thread("plan", "architect", "--workspace", "fake-hq")
        self.assertEqual(result["title"], "🏛️ fake-hq · Builder")

    def test_plan_uses_the_config_default_and_seat_tier(self):
        (self.home / "config/threads.json").write_text(json.dumps({"emoji": {"architect": "🏗️"}}))
        result = self.run_thread("plan", "architect", "--workspace", "fake-hq", "--runtime", "claude-desktop")
        self.assertEqual(result["title"], "🏗️ fake-hq · Architect")
        self.assertEqual(result["model"], "fake-claude-judgment")
        self.assertEqual(result["cwd"], str(self.folder / "fake-hq"))
        self.assertIn("foxrun.py start --workspace fake-hq --seat architect", result["prompt"])
        self.assertIn("question tool", result["prompt"])
        self.assertIn("/skills/foxrun-setup/bin/setup status", result["prompt"])

    def test_emoji_flag_wins_over_both_maps_and_is_recorded(self):
        (self.home / "config/threads.json").write_text(json.dumps({"emoji": {"architect": "🏗️"}}))
        result = self.run_thread("plan", "architect", "--workspace", "fake-hq", "--emoji", "📦")
        self.assertEqual((result["title"], result["emoji_state"]), ("📦 fake-hq · Architect", "chosen"))
        lead = self.run_thread("plan", "lead", "fake-shop", "--emoji", "🛒")
        self.assertEqual(lead["title"], "🛒 fake-shop · Lead")
        self.run_thread("record", "architect", "--workspace", "fake-hq", "--runtime", "claude-desktop",
                        "--id", "s-2", "--emoji", "📦")
        saved = self.saved()["architect@fake-hq"]
        self.assertEqual((saved["emoji"], saved["title"]), ("📦", "📦 fake-hq · Architect"))
        self.assertEqual(json.loads((self.home / "config/threads.json").read_text())["emoji"], {"architect": "🏗️"})

    def test_unmapped_seat_gets_the_fallback(self):
        (self.home / "agents/stranger.md").write_text(seat("stranger", "Stranger"))
        result = self.run_thread("plan", "stranger", "--workspace", "fake-hq")
        self.assertEqual((result["emoji"], result["emoji_state"]), ("🤖", "fallback"))

    def test_refusals(self):
        cases = [
            (("plan", "architect", "--workspace", "fake-hq", "--model", "fake-banned"), "allowed list"),
            (("plan", "architect", "--workspace", "missing"), "no workspace folder"),
            (("plan", "lead", "fake-shop", "--workspace", "fake-hq"), "own workspace"),
            (("plan", "lead", "fake-hq"), "no lead"),
            (("plan", "scout", "--workspace", "fake-hq", "--runtime", "codex"), "does not run on codex"),
            (("plan", "nobody", "--workspace", "fake-hq"), "no agent named"),
            (("plan", "architect", "--workspace", "fake-hq", "--emoji", "box"), "--emoji takes one emoji"),
            (("plan", "architect", "--workspace", "fake-hq", "--emoji", "📦 📦"), "--emoji takes one emoji"),
        ]
        for args, text in cases:
            with self.subTest(args=args):
                self.assertIn(text, self.run_thread(*args, code=1)["error"])

    def test_dry_run_starts_and_writes_nothing(self):
        for runtime in ("codex", "claude-cli"):
            result = self.run_thread("make", "architect", "--workspace", "fake-hq", "--runtime", runtime, "--dry-run")
            self.assertFalse(result["made"])
        self.run_thread("record", "architect", "--workspace", "fake-hq", "--runtime", "claude-desktop",
                        "--id", "s-9", "--dry-run")
        self.assertFalse(self.log.exists())
        self.assertFalse((self.home / "config/threads.json").exists())

    def test_codex_make_sends_the_tested_sequence_and_records(self):
        result = self.run_thread("make", "architect", "--workspace", "fake-hq", "--runtime", "codex", "--tier", "work")
        self.assertTrue(result["made"])
        messages = [json.loads(line) for line in self.log.read_text().splitlines()]
        methods = [message.get("method") for message in messages if message.get("method")]
        self.assertEqual(methods, ["initialize", "initialized", "thread/start", "thread/name/set", "turn/start"])
        start = next(m for m in messages if m.get("method") == "thread/start")["params"]
        self.assertEqual(start, {"cwd": str(self.folder / "fake-hq"), "model": "fake-codex-work"})
        name = next(m for m in messages if m.get("method") == "thread/name/set")["params"]
        self.assertEqual(name, {"threadId": "fake-thread-1", "name": "🏛️ fake-hq · Architect"})
        declined = [m for m in messages if m.get("id") == 99]
        self.assertEqual(declined[0]["result"], {"decision": "decline"})
        self.assertEqual(self.saved()["architect@fake-hq"]["id"], "fake-thread-1")

    def test_claude_cli_make_runs_bg_in_the_workspace_and_records(self):
        result = self.run_thread("make", "lead", "fake-shop", "--runtime", "claude-cli")
        call = json.loads(self.log.read_text())
        self.assertEqual(call["argv"][:5], ["--bg", "-n", "🧭 fake-shop · Lead", "--model", "fake-claude-work"])
        self.assertIn("--seat lead-fake-shop", call["argv"][5])
        self.assertEqual(Path(call["cwd"]).resolve(), (self.folder / "fake-shop").resolve())
        self.assertEqual(result["recorded"]["id"], "0a1b2c3d-0000-4000-8000-000000000001")
        self.assertIn("lead-fake-shop@fake-shop", self.saved())

    def test_claude_cli_untrusted_folder_says_what_to_do(self):
        result = self.run_thread("make", "architect", "--workspace", "fake-hq", "--runtime", "claude-cli",
                                 code=1, STUB_UNTRUSTED="1")
        self.assertIn("Open `claude` once in", result["error"])
        self.assertFalse((self.home / "config/threads.json").exists())

    def test_record_saves_a_desktop_thread(self):
        self.run_thread("record", "architect", "--workspace", "fake-hq", "--runtime", "claude-desktop", "--id", "s-1")
        self.assertEqual(self.saved()["architect@fake-hq"]["runtime"], "claude-desktop")
        self.assertTrue(self.run_thread("list")["agents"][0]["has_thread"])

    def make_agent(self, ident, workspace):
        """Make a workspace agent the way a person does: agent_new create --client <ws>."""
        self.assertIsNotNone(AGENT_NEW, "agents/tools/agent_new.py not found above " + str(SCRIPT))
        models = json.loads((self.home / "config/models.yaml").read_text())
        for tier in models["tiers"].values():
            tier["codex"]["service_tier"] = "fake-tier"  # the Codex runtime file agent_new renders needs one
        (self.home / "config/models.yaml").write_text(json.dumps(models))
        (self.home / "config/catalog.yaml").write_text(json.dumps({"sets": {"base": {"skills": [], "tools": []}}}))
        # name, not id: the ownership guard reads it, and thread skips it as a seat.
        (self.home / "agents/test-owner.md").write_text('---\ntype: doc\nname: test-owner\nowns: ["runs", "agents"]\n---\n')
        (self.folder / workspace / "AGENTS.md").write_text("# " + workspace + " (labeled fake workspace)\n")
        done = subprocess.run([sys.executable, str(AGENT_NEW), "create", ident, "--role", "Packs fake orders",
                               "--summary", "Packs labeled fake orders.", "--tier", "work", "--client", workspace,
                               "--json"], capture_output=True, text=True, timeout=60,
                              env={**self.env, "FOXRUN_STATE": str(Path(self.temp.name) / "state"),
                                   "FOXRUN_SEAT": "test-owner"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["path"], str(self.folder / workspace / "team" / (ident + ".md")))

    def test_agent_made_by_agent_new_opens_a_thread_by_name(self):
        self.make_agent("packer", "fake-shop")
        row = {row["seat"]: row for row in self.run_thread("list")["agents"]}["packer"]
        self.assertEqual((row["workspace"], row["role"], row["has_thread"]), ("fake-shop", "Packer", False))
        for runtime in ("codex", "claude-cli", "claude-desktop"):
            with self.subTest(runtime=runtime):
                result = self.run_thread("make", "packer", "--runtime", runtime, "--dry-run")
                self.assertEqual((result["title"], result["key"], result["made"]),
                                 ("🤖 fake-shop · Packer", "packer@fake-shop", False))
                self.assertEqual(result["cwd"], str(self.folder / "fake-shop"))
                self.assertEqual(result["model"], ("fake-codex-work" if runtime == "codex" else "fake-claude-work"))
                self.assertIn("foxrun.py start --workspace fake-shop --seat packer", result["prompt"])
        self.assertEqual(self.run_thread("plan", "packer", "--workspace", "fake-shop")["key"], "packer@fake-shop")
        self.assertFalse(self.log.exists())
        self.assertFalse((self.home / "config/threads.json").exists())

    def test_workspace_agent_starts_only_in_its_own_workspace(self):
        self.make_agent("packer", "fake-shop")
        self.assertIn("starts in its own workspace: fake-shop",
                      self.run_thread("plan", "packer", "--workspace", "fake-hq", code=1)["error"])
        (self.folder / "fake-hq/team").mkdir()
        (self.folder / "fake-hq/team/packer.md").write_text(seat("packer", "Packer"))
        self.assertIn("several workspaces (fake-hq, fake-shop); pass --workspace",
                      self.run_thread("plan", "packer", code=1)["error"])
        self.assertEqual(self.run_thread("plan", "packer", "--workspace", "fake-hq")["cwd"], str(self.folder / "fake-hq"))
        # The start command loads a workspace's own team file first, so the thread names that seat there.
        (self.folder / "fake-hq/team/architect.md").write_text(seat("architect", "Hq Architect", "work"))
        self.assertEqual(self.run_thread("plan", "architect", "--workspace", "fake-hq")["title"], "🏛️ fake-hq · Hq Architect")
        self.assertEqual(self.run_thread("plan", "architect", "--workspace", "fake-shop")["title"], "🏛️ fake-shop · Architect")
        self.run_thread("record", "architect", "--workspace", "fake-hq", "--runtime", "claude-desktop", "--id", "s-3")
        seats = {(row["seat"], row["workspace"]): row for row in self.run_thread("list")["agents"]}
        self.assertTrue(seats[("architect", "fake-hq")]["has_thread"])
        self.assertFalse(seats[("architect", None)]["has_thread"])

    def test_help_never_prompts(self):
        done = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env=self.env, timeout=20)
        self.assertEqual(done.returncode, 0)
        self.assertIn("lead <ws>", done.stdout)


if __name__ == "__main__":
    unittest.main()
