"""Synthetic checks for the read-only workspace checker; no live fixture writes."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_workspace as checker


class WorkspaceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="t69-check-")
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / "demo"
        self.root.mkdir()
        for contract in checker.CONTRACTS:
            self.note(contract, "# Contract\n", kind="contract")
        self.note("index.md", "\n".join(checker.CONTRACTS) + "\nCAPABILITIES.md\ndemo.md\nnotes/\n")
        self.note("CAPABILITIES.md", "# Capabilities\n")
        self.note("demo.md", "# Demo\n")

    def note(self, rel, body, kind="doc"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntype: " + kind + "\nworkspace: demo\ntimestamp: 2026-09-18T12:00:00-04:00\n---\n" + body)
        return path

    def findings(self, report, code):
        return [f for f in report["findings"] if f["code"] == code]

    def test_required_root_frontmatter_and_context(self):
        # Missing contracts use a separate empty fixture, without removing anything.
        empty = self.parent / "empty"
        empty.mkdir()
        self.assertEqual(len(self.findings(checker.check(empty), "required_contract_missing")), 7)
        self.assertEqual(len(self.findings(checker.check(empty, "personal"), "required_contract_missing")), 5)
        self.note("CONTEXT.md", "# Context\n")
        (self.root / "records.md").write_text("# No metadata\n")
        report = checker.check(self.root)
        self.assertEqual(len(self.findings(report, "context_file")), 1)
        self.assertEqual(len(self.findings(report, "frontmatter_missing")), 3)
        self.assertIn("records.md", {f["path"] for f in self.findings(report, "root_entry_not_allowed")})

    def test_contract_and_table_thresholds_and_code_examples(self):
        self.note("docs/exact.md", "line\n" * 75, kind="contract")  # 80 including frontmatter
        self.note("docs/long.md", "line\n" * 76, kind="contract")
        header = "| Name | Status |\n| --- | --- |\n"
        self.note("notes/fifteen.md", header + "| Example | open |\n" * 15)
        self.note("notes/sixteen.md", header + "| Example | open |\n" * 16)
        self.note("notes/code.md", "```md\n[[missing]]\n" + header + "| Example | open |\n" * 20 + "```\n`[[also-missing]]`\n")
        report = checker.check(self.root)
        self.assertEqual([f["path"] for f in self.findings(report, "contract_too_long")], ["docs/long.md"])
        self.assertEqual([f["path"] for f in self.findings(report, "records_in_markdown")], ["notes/sixteen.md"])
        self.assertFalse(self.findings(report, "broken_wikilink"))

    def test_links_orphans_and_index_coverage(self):
        self.note("notes/start.md", "[[demo/notes/linked#Heading|Link]] ![[image.png]] [[absent]]\n[Markdown](md-linked.md)\n[[#Self]]\n")
        self.note("notes/linked.md", "# Heading\n")
        self.note("notes/md-linked.md", "# Linked\n")
        self.note("notes/orphan.md", "# Alone\n")
        (self.root / "notes/image.png").write_bytes(b"synthetic image")
        self.note("unmapped.md", "# New root file\n")
        report = checker.check(self.root)
        self.assertEqual([f["target"] for f in self.findings(report, "broken_wikilink")], ["absent"])
        orphans = {f["path"] for f in self.findings(report, "orphan_candidate")}
        self.assertIn("notes/orphan.md", orphans)
        self.assertNotIn("notes/linked.md", orphans)
        self.assertNotIn("notes/md-linked.md", orphans)
        self.assertIn("unmapped.md", {f["target"] for f in self.findings(report, "index_entry_missing")})

    def test_protected_paths_never_opened_and_no_workspace_changes(self):
        self.note(".codex/private.md", "do not open")
        self.note(".claude/mcp/private.md", "do not open")
        self.note("archive/private.md", "do not open")
        self.note("notes/credentials.md", "do not open")
        self.note("notes/ordinary.md", "# Ordinary\n")
        (self.root / "notes/link.md").symlink_to(self.root / ".codex/private.md")
        before = {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob("*") if p.is_file()}
        original = checker.read_bytes
        accessed = []

        def tracked(path, root):
            self.assertFalse(checker.protected(path, root))
            accessed.append(path.relative_to(root).as_posix())
            return original(path, root)

        with patch.object(checker, "read_bytes", side_effect=tracked):
            report = checker.check(self.root)
        after = {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertNotIn("notes/link.md", accessed)
        self.assertGreaterEqual(len(report["skipped"]), 5)

    def test_generation_receipts_detect_source_and_output_drift(self):
        source = self.note("notes/source.md", "# Source\n")
        output = self.root / "demo.md"
        receipt = self.root / "demo.md.sources.json"
        receipt.write_text(json.dumps({"output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                                      "sources": [{"path": "notes/source.md", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}))
        self.assertIn("demo.md", checker.check(self.root)["generated_byte_verified"])
        source.write_text(source.read_text() + "Changed\n")
        output.write_text(output.read_text() + "Changed\n")
        report = checker.check(self.root)
        self.assertEqual(len(self.findings(report, "generated_source_drift")), 1)
        self.assertEqual(len(self.findings(report, "generated_output_drift")), 1)
        self.assertNotIn("demo.md", report["generated_byte_verified"])
        self.assertTrue(self.findings(report, "generated_unverified"))

    def test_output_preservation_and_summary(self):
        report = checker.check(self.root)
        paths = checker.save_reports(report, self.parent / "result")
        originals = [p.read_bytes() for p in paths]
        next_paths = checker.save_reports(report, self.parent / "result")
        self.assertEqual([p.name for p in next_paths], ["result.new.json", "result.new.md"])
        self.assertEqual(originals, [p.read_bytes() for p in paths])
        with self.assertRaises(FileExistsError):
            checker.save_reports(report, self.parent / "result")
        with self.assertRaises(ValueError):
            checker.save_reports(report, self.root / "result")
        summary = paths[1].read_text()
        self.assertIn("## At a glance\n", summary)
        self.assertIn("workspace: system-workspace", summary)
        diagram = summary.split("```text\n")[1].split("```")[0]
        self.assertTrue(all(len(line) <= 60 for line in diagram.splitlines()))
        self.assertEqual(json.loads(paths[0].read_text())["summary"], report["summary"])


if __name__ == "__main__":
    unittest.main()
