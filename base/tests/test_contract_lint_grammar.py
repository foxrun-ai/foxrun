#!/usr/bin/env python3
"""Generated cases for every form of LINT-GRAMMAR.md.

FORMS is the grammar as data. For each form the test takes its flagged fragment and its clean
fragment and places each one alone, at the start of a sentence, in mid-sentence, in a list item,
in a block quote, in a table cell, and after every instruction verb of the rule file.
The lint must flag every flagged fragment where the form applies and must flag nothing else.
"""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import json
import os
from pathlib import Path
import tempfile
import unittest

import contract_lint as lint

TOOLS = Path(__file__).resolve().parent.parent
RULES = (Path(__file__).resolve().parent / '../contract-lint-rules.json')
VERBS = json.loads(RULES.read_text())["instruction_verbs"]
PLACES = {
    "alone": "{}",
    "start": "{} comes first.",
    "mid": "For this step, {} comes next.",
    "list": "- {}",
    "quote": "> {}",
    "cell": "| step | {} |",
}
EVERYWHERE = (*PLACES, "verb")
ANY_PLACE = "any place on a line outside a code fence"

# id: title, rule, flagged fragment, clean fragment, where the form applies, and three optional keys:
#   wrap             "fence" puts the cases in a sh fence; any other text is a heading above them
#   clean_flagged_by verbs that turn the clean fragment into another form when they stand before it
#   cues             more spellings of the flagged fragment that must be flagged too
FORMS = {
    "G1": {"title": "A path in backticks", "flagged": "`docs/missing.md`", "clean": "`true/false`", "places": EVERYWHERE,
           "rule": "Inline code that is one unbroken piece and starts with `~/`, `./`, `../`, or `/`, or ends with a slash, or ends with a known file ending. Dots inside a name are part of the name. Inline code with a slash and none of these signals counts only when it is on disk."},
    "G2": {"title": "A plain path with a folder", "flagged": "docs/missing.md", "clean": "and/or", "places": EVERYWHERE,
           "rule": "A plain word that has a folder before the name and a known file ending, or that starts with `./` or `../`, or that has two parts or more and a trailing slash."},
    "G3": {"title": "A plain file name right after Read or Open", "flagged": "Read missing.md", "clean": "the missing.md file", "places": EVERYWHERE,
           "cues": ["Read: missing.md", "Read : missing.md", "**Read** missing.md", "Read **missing.md**", "Read *missing.md*", "read missing.md", "Open missing.md", "open missing.md"],
           "rule": "The plain word right after `Read` or `Open`, any letter case, when it is a file name with a known file ending."},
    "G4": {"title": "A Markdown link or reference", "flagged": "[gone](docs/missing.md)", "clean": "![alt](docs/missing.png)", "places": EVERYWHERE,
           "rule": "`[text](target)`, `[text][label]`, and `[label]` with a one-line definition. The target is checked. A web address is not. An image and a link inside inline code are inert."},
    "G5": {"title": "A wikilink", "flagged": "[[docs/missing]]", "clean": "[[Missing Note]]", "places": EVERYWHERE,
           "rule": "`[[folder/note]]` and `![[folder/note]]`. A note with the same name wins over a folder. A wikilink with no folder is not checked."},
    "G6": {"title": "A Claude import", "flagged": "@docs/missing.md", "clean": "person@example.com", "places": EVERYWHERE,
           "rule": "A plain word that is `@` and a path: a whole line, or a word in a sentence."},
    "G7": {"title": "A command in backticks", "flagged": "`$ absent --version`", "clean": "`agents home index log`", "places": EVERYWHERE, "clean_flagged_by": ["run"],
           "rule": "Inline code that starts with `$ `, or where a flag, a placeholder, a quoted value, or a script path follows a lowercase first word. The whole first word is the command, dots included. A script path after it is checked too."},
    "G8": {"title": "A command in backticks right after Run", "flagged": "Run `fixture-missing-command status`", "clean": "try `fixture-missing-command status`", "places": EVERYWHERE,
           "cues": ["Run **`fixture-missing-command status`**", "Run *`fixture-missing-command status`*", "Run: `fixture-missing-command status`", "Run : `fixture-missing-command status`", "**Run** `fixture-missing-command status`", "run `fixture-missing-command status`", "RUN `fixture-missing-command status`"],
           "rule": "Inline code right after the word `Run`, any letter case. The first word is the command, even with plain subcommands. A path there is checked as a script."},
    "G9": {"title": "A plain Run phrase at the start of a line", "flagged": "Run python3.99 tool.py", "clean": "Run the daily check", "places": ("alone", "start", "list", "quote"),
           "rule": "`Run name` as the first words of a line, after a list or quote marker if there is one. The name is a command when it holds a digit, dot, hyphen, underscore, or plus, or is an interpreter name (`bash`, `node`, `perl`, `python`, `python3`, `ruby`, `sh`, `zsh`), and a flag or a script path follows it or it ends the sentence."},
    "G10": {"title": "A line in a shell fence", "flagged": "missing-fence-command --now", "clean": "python3 docs/tool.py", "places": ("alone",), "wrap": "fence",
            "rule": "A whole line inside a fence labeled `sh`, `bash`, `zsh`, or `shell`. The first word is the command. Every other fence is inert."},
    "G11": {"title": "A skill name with its prefix", "flagged": "/missing-skill", "clean": "$5", "places": EVERYWHERE,
            "rule": "`$name` or `/name`, in backticks or plain. A slash inside a path is never a skill. `/tmp` and other system folders are paths."},
    "G12": {"title": "A stale name", "flagged": "$fx-log", "clean": "fx-log", "places": EVERYWHERE, "clean_flagged_by": ["run"],
            "rule": "A name from `stale_names` in the rule file, written as `$name`, `/name`, or alone in backticks."},
    "G13": {"title": "A banned word", "flagged": "fleet", "clean": "Never say \"fleet\"", "places": EVERYWHERE,
            "rule": "A word from `banned_words`, as a whole word, any letter case. Quotation marks do not hide it. One exception: inside double quotes after a phrase from `banned_word_prohibition_cues` on the same line, the line bans the word."},
    "G14": {"title": "A reference under a declared-absent heading", "flagged": "[routing rules](docs/missing.md)", "clean": "`docs/adr/`", "places": EVERYWHERE, "wrap": "## File homes", "clean_flagged_by": ["run"],
            "rule": "Under a heading from `declared_absent_headings`, a missing path in backticks may be absent and is listed as not checked. Every link, import, script, and plain path there is checked as anywhere else. The rule holds for that section only."},
    "G15": {"title": "A path that must stay absent", "flagged": "Do not create `built/`", "clean": "Do not create `plans/`", "places": EVERYWHERE,
            "rule": "Paths in backticks listed right after a phrase from `absent_path_cues`. One that is on disk is a finding."},
}


def cases() -> list[tuple[str, str, str, bool]]:
    """Every generated case: (form, wrap, line of contract text, must the lint flag it)."""
    result = []
    for name, form in FORMS.items():
        wrap = form.get("wrap", "")
        places = PLACES if wrap != "fence" else {"alone": "{}"}
        for place, template in places.items():
            result.append((name, wrap, template.format(form["flagged"]), place in form["places"]))
            result.append((name, wrap, template.format(form["clean"]), False))
        for verb in VERBS if wrap != "fence" else []:
            result.append((name, wrap, f"{verb.capitalize()} {form['flagged']}.", "verb" in form["places"]))
            result.append((name, wrap, f"{verb.capitalize()} {form['clean']}.", verb in form.get("clean_flagged_by", [])))
        for cue in form.get("cues", []):
            for template in PLACES.values():
                result.append((name, wrap, template.format(cue), True))
    return result


class ContractLintGrammarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="contract-lint-grammar-", dir=os.environ.get("CONTRACT_LINT_TEST_TMP"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.workspace = self.vault / "demo"
        for name in ("ok.md", "tool.py", "docs/ok.md", "docs/tool.py", "built/keep.md"):
            path = self.workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")
        self.skills = self.root / "skills"
        (self.skills / "fixture-skill").mkdir(parents=True)
        (self.skills / "fixture-skill/SKILL.md").write_text("# Fixture\n")
        self.commands = self.root / "commands.json"
        self.commands.write_text(json.dumps({"executables": ["python3", "rg"]}))

    def lint_lines(self, lines: list[str]) -> dict[int, list[str]]:
        contract = self.workspace / "CAPABILITIES.md"
        contract.write_text("\n".join(lines) + "\n")
        report = lint.scan(rules_path=RULES, vault_root=self.vault, paths=[contract], skill_roots=[self.skills], command_inventory=self.commands)
        found: dict[int, list[str]] = {}
        for row in report["findings"]:
            found.setdefault(row["line"], []).append(row["rule"] + ": " + row["target"])
        return found

    def test_every_generated_case_matches(self):
        generated = cases()
        self.assertGreaterEqual(len(generated), 600)
        lines = ["# Generated cases"]
        expected = {}
        for wrap in sorted({case[1] for case in generated}, key=lambda value: (value != "", value)):
            if wrap == "fence":
                lines.append("```sh")
            elif wrap:
                lines.append(wrap)
            for name, case_wrap, text, flagged in generated:
                if case_wrap == wrap:
                    lines.append(text)
                    expected[len(lines)] = (name, text, flagged)
            if wrap == "fence":
                lines.append("```")
            elif wrap:
                lines.append("## After the section")
        found = self.lint_lines(lines)
        self.assertEqual(set(), set(found) - set(expected), "a finding on a line that is not a case")
        wrong = [f"{name}: {'missed' if flagged else 'flagged'}: {text} -> {found.get(number, [])}" for number, (name, text, flagged) in expected.items() if flagged != (number in found)]
        self.assertEqual([], wrong)

    def test_every_form_has_cases_of_both_kinds(self):
        generated = cases()
        for name in FORMS:
            with self.subTest(form=name):
                self.assertTrue(any(case[0] == name and case[3] for case in generated))
                self.assertTrue(any(case[0] == name and not case[3] for case in generated))

    def test_grammar_page_holds_the_same_forms(self):
        page = ((Path(__file__).resolve().parent / '../LINT-GRAMMAR.md')).read_text()
        found = {}
        form = None
        for line in page.splitlines():
            if line.startswith("## "):
                form = None
            elif line.startswith("### G"):
                form = line.split()[1]
                found[form] = {"title": line.split(" ", 2)[2], "examples": [], "cues": []}
            elif form and line.startswith(("+ ", "- ")):
                found[form]["examples"].append(line[2:])
            elif form and line.startswith("also + "):
                found[form]["cues"].append(line[7:])
            elif form and line.startswith("Where: "):
                found[form]["where"] = line[7:]
        want = {
            name: {"title": form["title"], "examples": [form["flagged"], form["clean"]], "cues": form.get("cues", []),
                   "where": ANY_PLACE if form["places"] == EVERYWHERE else where(form)}
            for name, form in FORMS.items()
        }
        self.assertEqual(want, found)
        self.assertIn("## Outside the grammar, not checked", page)
        self.assertIn("An instruction sentence is", page)


def where(form: dict) -> str:
    if form.get("wrap") == "fence":
        return "a whole line inside a shell fence"
    names = {"alone": "alone on a line", "start": "at the start of a line", "list": "in a list item", "quote": "in a block quote"}
    return "only " + ", ".join(names[place] for place in form["places"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
