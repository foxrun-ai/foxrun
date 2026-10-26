#!/usr/bin/env python3
"""Checks for the judgment pass of contract lint. No model is called: the runner here is a stand-in."""

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
import sys
import tempfile
import unittest

import contract_judgment as judgment
import contract_lint as lint

TOOLS = Path(__file__).resolve().parent.parent
RULES = (Path(__file__).resolve().parent / '../contract-lint-rules.json')
STUB = sys.executable + " -B " + str((Path(__file__).resolve().parent / 'contract_judgment_stub.py'))
BODY = (
    "---\ntype: agents\n---\n# Fixture\nPlain opening line.\n"
    "## Gates\nMoney needs a yes. STUB-CONTRADICTION\n"
    "## Notes\nThis line says nothing. STUB-FILLER STUB-INVENTED-TERM\n"
    "## Quiet\nNothing to flag here.\n"
    "## Broken\nSTUB-NO-ANSWER\n"
)


class ContractJudgmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="contract-judgment-", dir=os.environ.get("CONTRACT_LINT_TEST_TMP"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.workspace = self.vault / "demo"
        self.workspace.mkdir(parents=True)
        self.contract = self.workspace / "AGENTS.md"
        self.contract.write_text(BODY)
        self.words = self.workspace / "CONCEPTS.md"
        self.words.write_text("# Concepts\n**Topic:** A subject.\n### Skill Release\nA snapshot.\n")
        self.out = self.root / "judgment"
        self.out.mkdir()

    def cli(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = lint.main(["--rules", str(RULES), "--vault-root", str(self.vault), "--path", str(self.contract), *arguments])
        return code, out.getvalue(), err.getvalue()

    def test_judgment_is_off_unless_asked(self):
        code, out, _err = self.cli()
        self.assertEqual((0, "PASS 1 contracts; no findings"), (code, out.splitlines()[0]))
        self.assertNotIn("judgment", out)
        self.assertEqual([], list(self.out.iterdir()))

    def test_request_holds_one_typed_request_per_section(self):
        request = judgment.build_request([("demo/AGENTS.md", BODY)], judgment.words([self.words]), Path("/db.sqlite"))
        self.assertEqual("batch", request["action"])
        states = [item["state"] for item in request["requests"]]
        self.assertEqual([(4, "Fixture"), (6, "Gates"), (8, "Notes"), (10, "Quiet"), (12, "Broken")], [(state["first_line"], state["heading"]) for state in states])
        self.assertEqual(["Concepts", "Skill Release", "Topic"], states[0]["words"])
        self.assertNotIn("type: agents", states[0]["section"])
        for item in request["requests"]:
            self.assertEqual({"contradiction", "filler", "invented_term"}, set(item["questions"]))
            self.assertTrue(all(question["type"] == "boolean" for question in item["questions"].values()))
            self.assertEqual({"database": "/db.sqlite", "required": True}, item["storage"])
        ids = [item["request_id"] for item in request["requests"]]
        self.assertEqual(len(ids), len(set(ids)))
        again = judgment.build_request([("demo/AGENTS.md", BODY)], judgment.words([self.words]), Path("/db.sqlite"))
        self.assertEqual(ids, [item["request_id"] for item in again["requests"]])
        changed = judgment.build_request([("demo/AGENTS.md", BODY.replace("Plain opening", "Changed opening"))], judgment.words([self.words]))
        self.assertNotEqual(ids[0], changed["requests"][0]["request_id"])
        self.assertNotIn("storage", changed["requests"][0])

    def test_flag_runs_the_runner_and_reports_each_yes_with_file_and_line(self):
        code, out, err = self.cli("--judgment", "--judgment-command", STUB, "--judgment-dir", str(self.out), "--judgment-words", str(self.words), "--unchecked")
        self.assertEqual(1, code, err)
        lines = out.splitlines()
        self.assertEqual([
            "demo/AGENTS.md:6: judgment_contradiction: Gates: invalid: Jev probability 0.90; question set contract-judgment-v1",
            "demo/AGENTS.md:8: judgment_filler: Notes: invalid: Jev probability 0.90; question set contract-judgment-v1",
            "demo/AGENTS.md:8: judgment_invented_term: Notes: invalid: Jev probability 0.90; question set contract-judgment-v1",
        ], [line for line in lines if ": invalid: " in line])
        self.assertEqual(3, sum(": judgment_" in line and ": uncheckable: Jev gave no answer" in line and line.startswith("demo/AGENTS.md:12: ") for line in lines))
        self.assertEqual(["progress.jsonl", "request.json"], sorted(path.name for path in self.out.iterdir()))
        code, _out, err = self.cli("--judgment", "--judgment-command", STUB, "--judgment-dir", str(self.out), "--judgment-words", str(self.words))
        self.assertEqual(2, code)
        self.assertIn("nothing was overwritten", err)

    def test_flag_refuses_missing_parts_and_a_folder_inside_the_vault(self):
        code, _out, err = self.cli("--judgment")
        self.assertEqual(2, code)
        self.assertIn("--judgment needs --judgment-command", err)
        code, _out, err = self.cli("--judgment", "--judgment-command", STUB, "--judgment-dir", str(self.workspace), "--judgment-words", str(self.words))
        self.assertEqual(2, code)
        self.assertIn("outside the vault", err)
        self.assertFalse((self.workspace / "request.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
