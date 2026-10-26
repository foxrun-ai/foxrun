#!/usr/bin/env python3
"""Table test for contract lint.

Each row is one line of contract text with its exact expected result. The lint must match
every row exactly: the findings, the references it resolved, and the text it did not check.
The rows are written, in order, into one contract file. Row N is line N + 1 of that file.
"""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import contract_lint as lint

TOOLS = Path(__file__).resolve().parent.parent
RULES = (Path(__file__).resolve().parent / '../contract-lint-rules.json')
COUNT = len(json.loads(RULES.read_text())["recognized_contracts"])  # one scanned contract per recognized name
CONTRACT = "CAPABILITIES.md"  # a recognized contract with no size limit and no tool-list rule

# (line of contract text,
#  findings   [(rule, target, state)]   these fail the lint,
#  resolved   [(kind, target)]          these were checked and are fine,
#  unchecked  [(rule, target)])         these could not be checked and never fail the lint
TABLE = [
    # Paths: dots, slashes, folders
    ("Read ./ok.md.", [], [("path", "./ok.md")], []),
    ("Read ../ok.md.", [], [("path", "../ok.md")], []),
    ("Read docs/missing.md.", [("path_reference", "docs/missing.md", "missing")], [], []),
    ("Read `docs/missing.md`.", [("path_reference", "docs/missing.md", "missing")], [], []),
    ("Read missing.md.", [("path_reference", "missing.md", "missing")], [], []),
    ("Read ok.md, then open tool.py and Open missing.py.", [("path_reference", "missing.py", "missing")], [("path", "ok.md"), ("path", "tool.py")], []),
    ("The file SKILL.md exists and missing.md is only named.", [], [], [("plain_name_text", "SKILL.md"), ("plain_name_text", "missing.md")]),
    ("Read ../parent.md and ../missing.md.", [("path_reference", "../missing.md", "missing")], [("path", "../parent.md")], []),
    ("Read docs/ok.md, then docs/missing.md.", [("path_reference", "docs/missing.md", "missing")], [("path", "docs/ok.md")], []),
    ("Open docs/read.me.md and v1.2/notes.md.", [], [("path", "docs/read.me.md"), ("path", "v1.2/notes.md")], []),
    ("Keep notes in notes/2026/ and drafts in drafts/2026/.", [("path_reference", "drafts/2026/", "missing")], [("path", "notes/2026/")], []),
    ("Use and/or, w/o, 24/7, docs/ and SKILL.md as plain names.", [], [], [("plain_name_text", "SKILL.md"), ("plain_name_text", "docs/"), ("plain_slash_text", "and/or"), ("plain_slash_text", "w/o")]),
    ("The folder `docs/` is here and `drafts/` is not.", [("path_reference", "drafts/", "missing")], [("path", "docs/")], []),
    ("Tables: `data/log.jsonl` and `data/missing.sqlite`.", [("path_reference", "data/missing.sqlite", "missing")], [("path", "data/log.jsonl")], []),
    ("Either `true/false` or `docs/ok` names a thing.", [], [("path", "docs/ok")], [("path_reference", "true/false")]),
    ("Bare names in code: `ok.md`, `missing.md`, `Node.js`.", [("path_reference", "missing.md", "missing")], [("path", "ok.md")], [("inline_code_uncheckable", "Node.js")]),
    ("**Bold docs/ok.md** and (docs/missing.md) and \"docs/missing.md\".", [("path_reference", "docs/missing.md", "missing")], [("path", "docs/ok.md")], []),
    ("| file a fact | `docs/ok.md`: where it lives. Unclear: `../inbox/`. |", [], [("path", "../inbox/"), ("path", "docs/ok.md")], []),
    ("Mail person@example.com, see Node.js notes, v2.0, and 10.05.", [], [], []),
    ("See docs/ok.md's notes, docs/missing.md's notes, and $fixture-skill's page.", [("path_reference", "docs/missing.md", "missing")], [("path", "docs/ok.md"), ("skill", "fixture-skill")], []),
    # Paths: tildes, absolute paths, globs, angle-bracket placeholders
    ("The file ~/outside/place.md and `~/outside/` are outside the vault.", [], [], [("path_reference", "~/outside/"), ("path_reference", "~/outside/place.md")]),
    ("Never write /tmp or /usr/local/bin/tool.", [], [], [("path_reference", "/tmp"), ("path_reference", "/usr/local/bin/tool")]),
    ("Glob: `docs/*.md` is not expanded.", [], [], [("path_reference", "docs/*.md")]),
    ("See <workspace>/AGENTS.md and <GLOSSARY.md> for <owner>.", [], [], [("path_reference", "<workspace>/AGENTS.md"), ("plain_name_text", "<GLOSSARY.md>")]),
    ("Soul: `../agents/<name>.md`; words: `<GLOSSARY.md>`; owner: `<owner>`.", [], [], [("inline_code_uncheckable", "<owner>"), ("path_reference", "../agents/<name>.md"), ("path_reference", "<GLOSSARY.md>")]),
    # Commands: dots, flags, placeholders, plain Run lines
    ("Run python3.99 tool.py.", [("command_reference", "python3.99", "missing")], [("command_path", "tool.py")], []),
    ("Run python3 tool.py.", [], [("command", "python3"), ("command_path", "tool.py")], []),
    ("Run python3 missing.py.", [("command_path_reference", "missing.py", "missing")], [("command", "python3")], []),
    ("Run fixture-missing-command.", [("command_reference", "fixture-missing-command", "missing")], [], []),
    ("Run missing-command.", [("command_reference", "missing-command", "missing")], [], []),
    ("Run `fixture-missing-command status`.", [("command_reference", "fixture-missing-command", "missing")], [], []),
    ("Run **`fixture-missing-command status`**.", [("command_reference", "fixture-missing-command", "missing")], [], []),
    ("Run *`fixture-missing-command status`*.", [("command_reference", "fixture-missing-command", "missing")], [], []),
    ("Run : `fixture-missing-command status`.", [("command_reference", "fixture-missing-command", "missing")], [], []),
    ("Read : missing.md.", [("path_reference", "missing.md", "missing")], [], []),
    ("Run **`python3 status`**, run : `rg`, Read : ok.md, and Open **tool.py**.", [], [("command", "python3"), ("command", "rg"), ("path", "ok.md"), ("path", "tool.py")], []),
    ("Run the missing.md file and Run the --now flag.", [], [], [("plain_name_text", "missing.md")]),
    ("Run: `fixture-missing-command now` and Read: missing.md.", [("command_reference", "fixture-missing-command", "missing"), ("path_reference", "missing.md", "missing")], [], []),
    ("Run the `fixture-missing-command status` command and read the missing.md file.", [], [], [("inline_code_uncheckable", "fixture-missing-command status"), ("plain_name_text", "missing.md")]),
    ("Read docs/missing.txt and `docs/missing.txt`.", [("path_reference", "docs/missing.txt", "missing")], [], [("plain_slash_text", "docs/missing.txt")]),
    ("Run `python3 status`, then run `rg` and Run `docs/tool.py`.", [], [("command", "python3"), ("command", "rg"), ("command_path", "docs/tool.py")], []),
    ("Then try `fixture-missing-command status` by hand.", [], [], [("inline_code_uncheckable", "fixture-missing-command status")]),
    ("Run the daily check.", [], [], []),
    ("Run it.", [], [], []),
    ("Run end-to-end tests by hand.", [], [], [("plain_run_text", "end-to-end")]),
    ("- [ ] Run python3.99 tool.py.", [("command_reference", "python3.99", "missing")], [("command_path", "tool.py")], []),
    ("> 2. Run fixture-missing-command --now", [("command_reference", "fixture-missing-command", "missing")], [], []),
    ("Run `python3 docs/tool.py --check`.", [], [("command", "python3"), ("command_path", "docs/tool.py")], []),
    ("Run `python3.99 docs/tool.py`.", [("command_reference", "python3.99", "missing")], [("command_path", "docs/tool.py")], []),
    ("Run `rg --files -g '*.md'`.", [], [("command", "rg")], []),
    ("A prompt form: `$ rg --files` and `$ absent --version`.", [("command_reference", "absent", "missing")], [("command", "rg")], []),
    ("Flags: `--readonly --no-input`.", [], [], []),
    ("First: `work claim <task> --by <you>`.", [("command_reference", "work", "missing")], [], []),
    ("Rows: `<module> list <table>`.", [], [], [("command_syntax_uncheckable", "<module> list <table>")]),
    ("Never run `rm -rf $(pwd)` or `cat > out.txt`.", [], [], [("command_syntax_uncheckable", "cat > out.txt"), ("command_syntax_uncheckable", "rm -rf $(pwd)")]),
    ("Word lists are not commands: `agents home index log`, `git status`.", [], [], [("inline_code_uncheckable", "agents home index log"), ("inline_code_uncheckable", "git status")]),
    # Skill names: hyphens, dollar and slash prefixes, stale names
    ("Use $fixture-skill and $missing-skill.", [("skill_reference", "missing-skill", "missing")], [("skill", "fixture-skill")], []),
    ("Use /fixture-skill, then /missing-skill.", [("skill_reference", "missing-skill", "missing")], [("skill", "fixture-skill")], []),
    ("Use /missing-skill.", [("skill_reference", "missing-skill", "missing")], [], []),
    ("Use `/missing-skill`.", [("skill_reference", "missing-skill", "missing")], [], []),
    ("Plays: `/log · /cedar-shop-email · /missing-skill`.", [("skill_reference", "missing-skill", "missing")], [("skill", "log"), ("skill", "cedar-shop-email")], []),
    ("Use $fx-log to write history.", [("stale_skill", "fx-log", "invalid")], [], []),
    ("The old name `fx-handoff` is stale; the words fx-handoff in prose are not.", [("stale_skill", "fx-handoff", "invalid")], [], []),
    ("The words fx-log and fx-handoff in plain prose are not checked.", [], [], []),
    ("The pack is `fixture pack (/log, /missing-skill…)`.", [("skill_reference", "missing-skill", "missing")], [("skill", "log")], [("inline_code_uncheckable", "fixture pack (/log, /missing-skill…)")]),
    ("It costs $5 and $HOME is not a skill; `cedar-shop-email` is a bare name.", [], [], [("inline_code_uncheckable", "cedar-shop-email")]),
    # Banned words: inside and outside quotes
    ("The old fleet name is still here.", [("banned_word", "fleet", "invalid")], [], []),
    ("Never say \"fleet\" or \"great question\" to anyone.", [], [], [("banned_word_quoted", "fleet"), ("banned_word_quoted", "great question")]),
    ("Never say “you’re absolutely right” here.", [], [], [("banned_word_quoted", "you're absolutely right")]),
    ("That was a great question, and \"fleet\" is quoted.", [("banned_word", "fleet", "invalid"), ("banned_word", "great question", "invalid")], [], []),
    ("Call the team \"fleet\".", [("banned_word", "fleet", "invalid")], [], []),
    ("Call it “fleet”, and never say otherwise.", [("banned_word", "fleet", "invalid")], [], []),
    ("The `fleet` command is gone, but fleet-wide and afleet are other words.", [("banned_word", "fleet", "invalid")], [], [("inline_code_uncheckable", "fleet")]),
    ("Never sound like a handbook. No \"great question\".", [], [], [("banned_word_quoted", "great question")]),
    ("The old foxrun-dev folder name is still here.", [("banned_word", "foxrun-dev", "invalid")], [], []),
    # Code fences: a shell fence is checked line by line; any other fence is inert
    ("```sh", [], [], []),
    ("python3 docs/tool.py", [], [("command", "python3"), ("command_path", "docs/tool.py")], []),
    ("python3 docs/missing.py", [("command_path_reference", "docs/missing.py", "missing")], [("command", "python3")], []),
    ("missing-fence-command --now", [("command_reference", "missing-fence-command", "missing")], [], []),
    ("fleet start", [("command_reference", "fleet", "missing")], [], []),
    ("work block <task> \"<what stopped you>\" --by <you>", [("command_reference", "work", "missing")], [], []),
    ("```", [], [], []),
    ("```python", [], [], [("fenced_block_uncheckable", "python")]),
    ("open(\"docs/missing.md\")", [], [], []),
    ("```", [], [], []),
    # Links, wikilinks, imports
    ("[ok](docs/ok.md) and [gone](docs/missing.md) and [web](https://example.com/a/b.md).", [("markdown_reference", "docs/missing.md", "missing")], [("markdown", "docs/ok.md")], [("markdown_reference", "https://example.com/a/b.md")]),
    ("See https://example.com/docs/missing.md and approval://row-1.", [], [], [("approval_reference", "row-1")]),
    ("[[docs/ok]] and [[docs/missing]] and ![[docs/ok.md]].", [("wikilink_reference", "docs/missing", "missing")], [("wikilink", "docs/ok"), ("wikilink", "docs/ok.md")], []),
    ("A wikilink with no folder, [[Missing Note]], is not checked.", [], [], [("wikilink_reference", "Missing Note")]),
    ("An image ![alt](docs/missing.png) and code `[x](docs/missing.md)` are inert.", [], [], [("inline_code_uncheckable", "[x](docs/missing.md)")]),
    ("@docs/ok.md", [], [("claude_import", "docs/ok.md")], []),
    ("@docs/missing.md", [("claude_import_reference", "docs/missing.md", "missing")], [], []),
    # Paths that are absent on purpose
    ("Do not create `plans/`, `bugs/`, or `built/` folders.", [("forbidden_path_exists", "built/", "invalid")], [("path", "bugs/"), ("path", "plans/")], []),
    ("Do not create `plans/` or `bugs/` folders.", [], [("path", "bugs/"), ("path", "plans/")], []),
    ("## What Is Not Built Yet", [], [], []),
    ("- `DESIGN.md` and `design/`. Today: `docs/ok.md`.", [], [("path", "docs/ok.md")], [("path_reference", "DESIGN.md"), ("path_reference", "design/")]),
    ("Today: [routing rules](docs/missing.md).", [("markdown_reference", "docs/missing.md", "missing")], [], []),
    ("## File homes", [], [], []),
    ("New files go to `docs/adr/`, `docs/`, and `wiki/raw/`.", [], [("path", "docs/")], [("path_reference", "docs/adr/"), ("path_reference", "wiki/raw/")]),
    ("Read [routing rules](docs/missing.md).", [("markdown_reference", "docs/missing.md", "missing")], [], []),
    ("Run `python3 docs/missing.py --now` and read docs/gone.md.", [("command_path_reference", "docs/missing.py", "missing"), ("path_reference", "docs/gone.md", "missing")], [("command", "python3")], []),
    ("## Later", [], [], []),
    ("Outside those sections `DESIGN.md` and `docs/adr/` are checked again.", [("path_reference", "DESIGN.md", "missing"), ("path_reference", "docs/adr/", "missing")], [], []),
]


# (line of contract text, unchecked instructions on that line)
INSTRUCTIONS = [
    ("Run the daily check.", 1),
    ("Read `docs/ok.md`.", 0),
    ("Use judgment. See the page. Then stop.", 2),
    ("Nothing to do on this line.", 0),
    ("Read `docs/missing.md` and run it twice.", 0),
    ("The words `run` and `read` in backticks are names. A runner reads nothing.", 0),
    ("```sh", 0),
    ("run it", 0),
    ("```", 0),
    ("| Before you | Read |", 1),
    ("Ask.", 1),
    ("Call the team \"fleet\".", 0),
    ("Read [guide].", 0),
    ("Read [gone].", 0),
    ("Run **`python3 status`** and Read : ok.md.", 0),
    ("Run `a. b` now. Check twice! Why ask? Send it.", 3),
    ("[guide]: docs/ok.md", 0),
    ("[gone]: docs/missing.md", 0),
]


class ContractLintTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="contract-lint-table-", dir=os.environ.get("CONTRACT_LINT_TEST_TMP"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.workspace = self.vault / "demo"
        for name in json.loads(RULES.read_text())["recognized_contracts"]:
            self.write(name, "# Fixture\n")
        for name in ("ok.md", "tool.py", "docs/ok.md", "docs/tool.py", "docs/read.me.md", "v1.2/notes.md", "notes/2026/keep.md", "data/log.jsonl", "built/keep.md"):
            self.write(name, "fixture\n")
        (self.vault / "parent.md").write_text("fixture\n")
        (self.vault / "ok.md").write_text("fixture\n")
        (self.vault / "inbox").mkdir()
        self.skills = self.root / "skills"
        for name in ("fixture-skill", "log", "cedar-shop-email"):
            (self.skills / name).mkdir(parents=True)
            (self.skills / name / "SKILL.md").write_text("# Fixture\n")
        self.commands = self.root / "commands.json"
        self.commands.write_text(json.dumps({"executables": ["python3", "rg"]}))
        self.write(CONTRACT, "# Table\n" + "".join(row[0] + "\n" for row in TABLE))

    def write(self, relative: str, body: str) -> Path:
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def scan(self, **overrides):
        values = {"rules_path": RULES, "vault_root": self.vault, "workspace": self.workspace, "skill_roots": [self.skills], "command_inventory": self.commands}
        values.update(overrides)
        return lint.scan(**values)

    def cli(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = lint.main(["--rules", str(RULES), "--vault-root", str(self.vault), "--skill-root", str(self.skills), "--command-inventory", str(self.commands), *arguments])
        return code, out.getvalue(), err.getvalue()

    def test_table_has_at_least_thirty_rows(self):
        self.assertGreaterEqual(len(TABLE), 30)

    def test_every_row_matches_exactly(self):
        report = self.scan()
        file = "demo/" + CONTRACT
        for index, (text, findings, resolved, unchecked) in enumerate(TABLE):
            line = index + 2
            with self.subTest(line=line, text=text):
                self.assertEqual(sorted(findings), sorted((row["rule"], row["target"], row["state"]) for row in report["findings"] if row["file"] == file and row["line"] == line), "findings")
                self.assertEqual(sorted(resolved), sorted((row["kind"], row["target"]) for row in report["references"] if row["file"] == file and row["line"] == line and row["state"] == "resolved"), "resolved references")
                self.assertEqual(sorted(unchecked), sorted((row["rule"], row["target"]) for row in report["unchecked"] if row["file"] == file and row["line"] == line), "unchecked")

    def test_nothing_outside_the_table_is_reported(self):
        report = self.scan()
        file = "demo/" + CONTRACT
        self.assertEqual(sum(len(row[1]) for row in TABLE), len(report["findings"]))
        self.assertEqual({file}, {row["file"] for row in report["findings"]})
        outside = [(row["file"], row["line"], row["rule"]) for row in report["unchecked"] if row["file"] != file or row["line"] == 1]
        self.assertEqual(sorted(("demo/" + name, 1, "approval_coverage") for name in json.loads(RULES.read_text())["recognized_contracts"]), sorted(outside))
        self.assertTrue(all(row["state"] == "uncheckable" for row in report["unchecked"]))
        self.assertFalse(any(row["state"] == "uncheckable" for row in report["findings"]))

    def test_command_prints_one_line_per_finding_and_fails(self):
        code, out, err = self.cli("--workspace", str(self.workspace))
        lines = [line for line in out.splitlines() if ": unchecked instructions: " not in line]
        self.assertEqual(1, code)
        self.assertEqual(COUNT, len(out.splitlines()) - len(lines))
        self.assertEqual(sum(len(row[1]) for row in TABLE), len(lines))
        for index, (_text, findings, _resolved, _unchecked) in enumerate(TABLE):
            for rule, target, state in findings:
                prefix = f"demo/{CONTRACT}:{index + 2}: {rule}: {target}: {state}: "
                self.assertEqual(1, sum(line.startswith(prefix) for line in lines), prefix)
        self.assertIn("not checked; add --unchecked to list them", err)

    def test_unchecked_instructions_are_counted_per_file(self):
        self.write("AGENTS.md", "---\ntype: agents\n---\n# Fixture\n" + "".join(row[0] + "\n" for row in INSTRUCTIONS))
        report = self.scan(workspace=None, paths=[self.workspace / "AGENTS.md"])
        scanned = report["scanned"][0]
        by_line = {}
        for row in scanned["unchecked_instruction_lines"]:
            by_line[row["line"]] = by_line.get(row["line"], 0) + 1
        self.assertEqual({index + 5: count for index, (_text, count) in enumerate(INSTRUCTIONS) if count}, by_line)
        self.assertEqual(sum(count for _text, count in INSTRUCTIONS), scanned["unchecked_instructions"])
        self.assertFalse(any(row["rule"] == "unchecked_instruction" for row in report["findings"]))
        code, out, _err = self.cli("--path", str(self.workspace / "AGENTS.md"))
        self.assertEqual(1, code)
        self.assertEqual("demo/AGENTS.md: unchecked instructions: 8", out.splitlines()[-1])
        code, out, _err = self.cli("--path", str(self.workspace / "AGENTS.md"), "--unchecked")
        self.assertIn("demo/AGENTS.md:5: unchecked_instruction: run: uncheckable: Run the daily check.", out)

    def test_unchecked_text_never_fails_the_command(self):
        self.write(CONTRACT, "# Table\n" + "".join(row[0] + "\n" for row in TABLE if not row[1] and not row[0].startswith(("```", "open("))))
        code, out, err = self.cli("--workspace", str(self.workspace))
        self.assertEqual(0, code, out)
        self.assertEqual(f"PASS {COUNT} contracts; no findings", out.splitlines()[0])
        self.assertEqual(COUNT, sum(": unchecked instructions: " in line for line in out.splitlines()[1:]))
        self.assertEqual(COUNT + 1, len(out.splitlines()))
        self.assertIn("not checked", err)
        code, out, _err = self.cli("--workspace", str(self.workspace), "--unchecked")
        self.assertEqual(0, code)
        self.assertIn(": plain_slash_text: and/or: uncheckable: ", out)

    def test_install_as_lints_a_file_where_it_will_live(self):
        template = self.root / "outside" / "agents-workspace.md"
        template.parent.mkdir()
        template.write_text("# AGENTS.md — <Workspace Name>\n1. `../parent.md`: one level up.\n2. `AGENTS.md` and `docs/ok.md` and `docs/missing.md`.\n<what this is>\n")
        with self.assertRaisesRegex(lint.LintError, "outside declared roots"):
            self.scan(workspace=None, paths=[template])
        report = self.scan(workspace=None, paths=[template], install_as=Path("demo/AGENTS.md"))
        self.assertEqual([("path_reference", "docs/missing.md", 3)], [(row["rule"], row["target"], row["line"]) for row in report["findings"]])
        self.assertEqual({str(template)}, {row["file"] for row in report["findings"] + report["unchecked"]})
        states = {row["target"]: row["state"] for row in report["references"]}
        self.assertEqual({"../parent.md": "resolved", "AGENTS.md": "resolved", "docs/ok.md": "resolved", "docs/missing.md": "missing"}, states)
        future = self.scan(workspace=None, paths=[template], install_as=Path("demo/GLOSSARY.md"))
        self.assertEqual(report["findings"], future["findings"])
        for bad in (Path("../escape.md"), Path("demo/archive/AGENTS.md"), Path("demo/AGENTS.txt")):
            with self.assertRaisesRegex(lint.LintError, "--as must name"):
                self.scan(workspace=None, paths=[template], install_as=bad)
        with self.assertRaisesRegex(lint.LintError, "exactly one --path"):
            self.scan(install_as=Path("demo/AGENTS.md"))

    def test_bare_file_name_rules_by_layer(self):
        other = self.vault / "other"
        other.mkdir()
        (other / "ideas.md").write_text("fixture\n")
        (self.vault / "AGENTS.md").write_text("# Portfolio\nIdeas go to the owning workspace's `ideas.md`. Never `nowhere.md`.\n")
        self.write("AGENTS.md", "# Workspace\nIdeas go to `ideas.md`.\n")
        report = self.scan(workspace=None, paths=[self.vault / "AGENTS.md", self.workspace / "AGENTS.md"])
        self.assertEqual([("AGENTS.md", "nowhere.md"), ("demo/AGENTS.md", "ideas.md")], [(row["file"], row["target"]) for row in report["findings"]])

    def test_protected_and_note_first_resolution(self):
        self.write("archive/old.md", "fixture\n")
        self.write("amazon.md", "fixture\n")
        self.write("amazon/keep.md", "fixture\n")
        self.write("AGENTS.md", "# Workspace\nHistory: `archive/`. Records: `amazon/`. Page: [[amazon]] and `amazon.md`.\n")
        report = self.scan(workspace=None, paths=[self.workspace / "AGENTS.md"])
        self.assertEqual([], report["findings"])
        self.assertEqual([("path_reference", "archive/")], [(row["rule"], row["target"]) for row in report["unchecked"] if row["line"] == 2])
        evidence = {(row["kind"], row["target"]): Path(row["resolution_evidence"]).name for row in report["references"] if row["state"] == "resolved"}
        self.assertEqual({("path", "amazon/"): "amazon", ("wikilink", "amazon"): "amazon.md", ("path", "amazon.md"): "amazon.md"}, evidence)


if __name__ == "__main__":
    unittest.main(verbosity=2)
