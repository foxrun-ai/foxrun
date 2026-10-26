#!/usr/bin/env python3
"""Synthetic and selected-source tests for the create-only installer."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import hashlib
from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import install_workspace as installer


MODULES = ("base", "work", "people", "memory")


def parse_test_frontmatter(value: str) -> dict:
    result = {}
    for line in value.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        result[key] = json.loads(raw) if raw.startswith(('"', "[")) else raw
    return result


class InstallWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="install-candidate-")
        self.addCleanup(self.temp.cleanup)
        # Launch fix w3 (b52bd2f): the installer refuses a path through a symlink, and macOS /var is one.
        self.root = Path(self.temp.name).resolve()
        self.modules = self.root / "modules"
        self.target = self.root / "sandbox"
        self.live = self.root / "live-vault"
        self.target.mkdir()
        self.live.mkdir()
        self.make_modules()
        self.values = {"workspace": "fixture-workspace", "workspace_purpose": "test safely"}

    def make_modules(self) -> None:
        specs = {
            "base": ("templates/AGENTS.md", "AGENTS.md", "Workspace {{workspace}}\nPurpose {{workspace_purpose}}\n", False),
            "work": ("templates/work.md", "docs/work.md", "Work for {{workspace}}\n", True),
            "people": ("templates/people.md", "docs/people.md", "People\n", True),
            "memory": ("templates/wiki/index.md", "memory/index.md", "Wiki\n", False),
        }
        for module, (source, destination, content, blueprint) in specs.items():
            module_root = self.modules / ('memory' if module == 'memory' else module)
            source_path = module_root / source
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(content, encoding="utf-8")
            (module_root / "install.json").write_text(json.dumps({
                "files": [{"from": source, "to": destination, "if_exists": "skip"}],
                "blueprint": blueprint,
            }), encoding="utf-8")

    def plan(self, **overrides):
        arguments = {
            "modules_root": self.modules,
            "target": self.target,
            "live_vault": self.live,
            "workspace_type": "personal",
            "raw_modules": ",".join(MODULES),
            "values": self.values,
            "target_workspace": "fixture-workspace",
            "install_timestamp": "2026-09-20T10:00:00Z",
            "approved_tags": ["fixture"],
            "database": None,
            "actor": None,
        }
        arguments.update(overrides)
        return installer.plan_install(**arguments)

    def test_create_only_collision_preservation_and_fresh_retry(self):
        human = b"human contract\n"
        (self.target / "AGENTS.md").write_bytes(human)
        (self.target / "docs").mkdir()
        (self.target / "docs/people.md").write_bytes(b"")
        plan = self.plan()
        self.assertEqual(plan, self.plan())
        actions = {row["destination"]: row["action"] for row in plan["actions"]}
        self.assertEqual("preserve-existing", actions["AGENTS.md"])
        self.assertEqual("preserve-existing", actions["docs/people.md"])
        receipt = installer.apply_plan(plan)
        self.assertEqual(human, (self.target / "AGENTS.md").read_bytes())
        self.assertEqual(b"", (self.target / "docs/people.md").read_bytes())
        self.assertTrue((self.target / "docs/work.md").is_file())
        with self.assertRaises(installer.InstallError):
            installer.apply_plan(plan)
        second = self.plan()
        second_receipt = installer.apply_plan(second)
        self.assertEqual([], second_receipt["created_files"])
        self.assertIn("AGENTS.md", second_receipt["preserved"])
        self.assertEqual(receipt["after_tree"], second_receipt["after_tree"])

    def test_unsupported_metadata_cannot_produce_invalid_installed_yaml(self):
        source = self.modules / "base/templates/AGENTS.md"
        for metadata in ('tags:\n  - original\n', '"workspace": original\n'):
            with self.subTest(metadata=metadata):
                source.write_text("---\ntype: agents\n" + metadata + "---\nOriginal body\n", encoding="utf-8")
                before = installer.scan_tree(self.target)
                with self.assertRaises(installer.InstallError):
                    self.plan()
                self.assertEqual(before, installer.scan_tree(self.target))

    def test_default_cli_plans_and_explicit_apply_uses_saved_plan(self):
        values_path = self.root / "values.json"
        plan_path = self.root / "plan.json"
        values_path.write_text(json.dumps(self.values), encoding="utf-8")
        plan_args = [
            "--modules-root", str(self.modules),
            "--workspace-type", "personal",
            "--modules", ",".join(MODULES),
            "--target-workspace", "fixture-workspace",
            "--install-timestamp", "2026-09-20T10:00:00Z",
            "--approved-tags", '["fixture"]',
            "--target", str(self.target),
            "--live-vault-root", str(self.live),
            "--values-json", str(values_path),
            "--plan-out", str(plan_path),
        ]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(0, installer.main(plan_args))
        self.assertTrue(plan_path.is_file())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(0, installer.main(["--apply", str(plan_path)]))
        self.assertTrue((self.target / "AGENTS.md").is_file())

    def test_source_or_target_drift_fails_before_any_write(self):
        plan = self.plan()
        source = self.modules / "work/templates/work.md"
        source.write_text("changed\n", encoding="utf-8")
        before = installer.scan_tree(self.target)
        with self.assertRaises(installer.InstallError):
            installer.apply_plan(plan)
        self.assertEqual(before, installer.scan_tree(self.target))

        source.write_text("Work for {{workspace}}\n", encoding="utf-8")
        plan = self.plan()
        (self.target / "appeared.txt").write_text("race", encoding="utf-8")
        before = installer.scan_tree(self.target)
        with self.assertRaises(installer.InstallError):
            installer.apply_plan(plan)
        self.assertEqual(before, installer.scan_tree(self.target))

    def test_mid_apply_failure_rolls_back_created_files_and_directories(self):
        plan = self.plan()
        original = installer.publish_bytes
        calls = 0

        def fail_second(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise installer.InstallError("synthetic publish failure")
            return original(path, data)

        with mock.patch.object(installer, "publish_bytes", side_effect=fail_second):
            with self.assertRaisesRegex(installer.InstallError, "synthetic publish failure"):
                installer.apply_plan(plan)
        self.assertEqual([], installer.scan_tree(self.target))

    def test_changed_created_path_is_preserved_during_failed_rollback(self):
        plan = self.plan()
        original = installer.publish_bytes
        first_path = None
        calls = 0

        def replace_then_fail(path, data):
            nonlocal calls, first_path
            calls += 1
            if calls == 1:
                original(path, data)
                first_path = path
                return
            replacement = first_path.with_name("external-replacement")
            replacement.write_bytes(b"other writer\n")
            os.replace(replacement, first_path)
            raise installer.InstallError("synthetic failure after replacement")

        with mock.patch.object(installer, "publish_bytes", side_effect=replace_then_fail):
            with self.assertRaisesRegex(installer.InstallError, "rollback preserved changed paths"):
                installer.apply_plan(plan)
        self.assertEqual(b"other writer\n", first_path.read_bytes())

    def test_invalid_manifest_paths_and_symlink_sources_are_refused(self):
        manifest = self.modules / "memory/install.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["files"][0]["to"] = "../escape.md"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(installer.InstallError):
            self.plan()

        self.make_modules()
        source = self.modules / "memory/templates/wiki/index.md"
        source.unlink()
        outside = self.root / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        source.symlink_to(outside)
        with self.assertRaises(installer.InstallError):
            self.plan()

    def test_unresolved_placeholders_and_unsupported_policy_are_refused(self):
        with self.assertRaisesRegex(installer.InstallError, "workspace_purpose"):
            self.plan(values={"workspace": "fixture-workspace"})
        manifest = self.modules / "base/install.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["files"][0]["if_exists"] = "overwrite"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "unsupported if_exists"):
            self.plan()

    def test_needs_rows_are_listed_only_in_the_exact_shape(self):
        # T677: install.json may list outside programs; the installer installs none of them.
        manifest = self.modules / "base/install.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["needs"] = [{"program": "yt-dlp", "why": "Reads videos.", "get": "brew install yt-dlp", "reader": "youtube"}]
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(installer.load_manifest(self.modules, "base")[0]["needs"][0]["program"], "yt-dlp")
        for bad in ({"program": "yt-dlp"}, "yt-dlp"):
            data["needs"] = [bad]
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(installer.InstallError, "unsupported needs row"):
                installer.load_manifest(self.modules, "base")
        data["needs"] = "yt-dlp"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "unsupported needs list"):
            installer.load_manifest(self.modules, "base")

    def test_conflicting_duplicate_destinations_are_refused(self):
        manifest = self.modules / "people/install.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["files"][0]["to"] = "AGENTS.md"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "conflicting duplicate"):
            self.plan()

    def test_live_vault_and_symlink_target_are_refused(self):
        (self.live / "child").mkdir()
        with self.assertRaisesRegex(installer.InstallError, "overlaps"):
            self.plan(target=self.live / "child")
        linked = self.root / "linked-target"
        linked.symlink_to(self.target, target_is_directory=True)
        with self.assertRaisesRegex(installer.InstallError, "symlink"):
            self.plan(target=linked)

    def test_forbidden_destination_and_semantic_plan_edit_are_refused(self):
        manifest = self.modules / "memory/install.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["files"][0]["to"] = ".agents/skills/unsafe.md"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "runtime, skill, config, or auth"):
            self.plan()

        self.make_modules()
        plan = self.plan()
        action = next(row for row in plan["actions"] if row["action"] == "create-file")
        action["destination"] = "tampered.md"
        plan["plan_sha256"] = installer.plan_hash(plan)
        before = installer.scan_tree(self.target)
        with self.assertRaisesRegex(installer.InstallError, "reconstruction"):
            installer.apply_plan(plan)
        self.assertEqual(before, installer.scan_tree(self.target))

    def test_tree_limit_is_enforced_during_enumeration(self):
        for index in range(3):
            (self.target / f"{index}.txt").write_text("x", encoding="utf-8")
        with mock.patch.object(installer, "MAX_TREE_ENTRIES", 2):
            with self.assertRaisesRegex(installer.InstallError, "exceeds 2 entries"):
                installer.scan_tree(self.target)

    def test_real_manifests_and_reviewed_builder_create_new_only(self):
        modules = Path(os.environ.get("INSTALL_MODULES_ROOT", Path(__file__).resolve().parent.parent.parent)).resolve()
        self.assertIsNone(installer.infer_source_vault(modules))
        target = self.root / "real-sandbox"
        target.mkdir()
        original_contract = b"human stays\n"
        (target / "AGENTS.md").write_bytes(original_contract)
        (target / "CLAUDE.md").write_bytes(b"")
        declared_placeholders = (
            "approval_ref_or_pending", "approved_asset_path", "approved_copy", "approved_tags",
            "audience", "brand_review_ref", "brief_ref_and_hash", "business_terms", "captured_at",
            "checkable_rule", "color_exceptions", "component_library", "count_and_unit",
            "definition_root", "depth_tokens", "failure", "file_ref_and_hash",
            "forbidden_claims_and_phrases", "function_gates", "job", "job_id", "keep_rules",
            "layout_tokens", "observable_result", "observed_detail", "output_or_flow", "owner",
            "portfolio_agents", "primary_job", "promise", "proof_ref", "proof_refs", "purpose",
            "reading_context", "reject_rules", "rejected_copy_and_reason", "replacement", "result",
            "review_ref", "review_ref_or_pending", "reviewer", "reviewer_and_time",
            "rights_or_unknown", "shape_tokens", "shared_design_path", "source_creator", "source_id",
            "source_ref", "test", "token_file", "type_tokens", "user_words", "voice_rules",
            "workspace", "workspace_audience", "workspace_purpose",
        )
        values = {name: "fixture-" + name for name in declared_placeholders}
        values.update({
            "portfolio_agents": "../AGENTS.md",
            "definition_root": "../system-workspace/docs/data-model-definition",
        })
        values.pop("workspace", None)
        values.pop("approved_tags", None)
        # g-people-ships-with-small-talk (231264d): the product has no people module.
        plan = installer.plan_install(
            modules_root=modules, target=target, live_vault=self.live,
            workspace_type="personal", raw_modules="base,work,memory",
            values=values, target_workspace="fixture-workspace",
            install_timestamp="2026-09-20T10:00:00Z", approved_tags=["fixture"],
            database=None, actor=None,
        )
        self.assertIsNone(plan["database"])
        self.assertIn("first-pass templates", " ".join(plan["limitations"]))
        self.assertEqual("preserve-existing", next(
            row["action"] for row in plan["actions"] if row["destination"] == "AGENTS.md"
        ))
        receipt = installer.apply_plan(plan)
        self.assertEqual(original_contract, (target / "AGENTS.md").read_bytes())
        self.assertEqual(b"", (target / "CLAUDE.md").read_bytes())
        for destination in ("wiki/SCHEMA.md", "RESOLVER.md"):
            text = (target / destination).read_text(encoding="utf-8")
            front, body = text.split("---\n", 2)[1:]
            self.assertIn('workspace: "fixture-workspace"', front)
            self.assertIn('timestamp: "2026-09-20T10:00:00Z"', front)
            self.assertIn('tags: ["fixture"]', front)
            parsed_front = parse_test_frontmatter(front)
            self.assertEqual("fixture-workspace", parsed_front["workspace"])
            self.assertEqual("2026-09-20T10:00:00Z", parsed_front["timestamp"])
            self.assertEqual(["fixture"], parsed_front["tags"])
            action = next(row for row in plan["actions"] if row.get("destination") == destination)
            self.assertEqual("not accepted by installer", action["new_content_state"]["acceptance"])
            source_data = Path(action["source"]).read_bytes()
            rendered, _ = installer.render_template(source_data, plan["values"], Path(action["source"]))
            rendered_text = rendered.decode("utf-8")
            source_front, source_body = rendered_text.split("---\n", 2)[1:]
            source_status = next(line for line in source_front.splitlines() if line.startswith("status:"))
            target_status = next(line for line in front.splitlines() if line.startswith("status:"))
            self.assertEqual(source_status, target_status)
            self.assertEqual(source_body, body)
        # T714: one database, the system data.db. The workspace installer builds none.
        self.assertFalse(any(row["path"].endswith((".sqlite", ".db")) for row in receipt["after_tree"]))
        with self.assertRaisesRegex(installer.InstallError, "no database of its own"):
            installer.plan_install(
                modules_root=modules, target=target, live_vault=self.live,
                workspace_type="personal", raw_modules="base,work,memory",
                values=values, target_workspace="fixture-workspace",
                install_timestamp="2026-09-20T10:00:00Z", approved_tags=["fixture"],
                database="fixture-workspace.sqlite", actor="synthetic-test",
            )
        second = installer.plan_install(
            modules_root=modules, target=target, live_vault=self.live,
            workspace_type="personal", raw_modules="base,work,memory",
            values=values, target_workspace="fixture-workspace",
            install_timestamp="2026-09-20T10:00:00Z", approved_tags=["fixture"],
            database=None, actor=None,
        )
        second_receipt = installer.apply_plan(second)
        self.assertEqual([], second_receipt["created_files"])
        self.assertFalse((target / "fixture-workspace.sqlite").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
