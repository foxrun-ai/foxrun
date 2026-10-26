#!/usr/bin/env python3
from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import closing
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import approve


FIXED_TIME = "2026-09-20T12:00:00Z"
ACTOR = "test-actor"
APPROVAL_REF = "fixture://simulated-consent/T9"
APPROVAL_TEXT = "SIMULATED CONSENT: yes for this exact fixture version"
MODULES_ROOT = Path(__file__).resolve().parent.parent.parent


class ApproveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="approve-candidate-")
        self.addCleanup(self.temp.cleanup)
        # macOS exposes /tmp through a system symlink.  Use the physical path so
        # these fixtures do not weaken the candidate's symlink boundary.
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "workspace"
        for path in (
            self.root, self.root / "drafts", self.root / "live",
            self.root / ".approve-archive", self.root / ".approve-journals",
        ):
            path.mkdir()
        self.control = self.base / "private-control"
        for path in (
            self.control, self.control / "drafts", self.control / "archives",
            self.control / "journals", self.control / "plans",
        ):
            path.mkdir()
        self.identity_root = self.base / "agent-team"
        (self.identity_root / "agents").mkdir(parents=True)
        self.db = self.base / "work.sqlite"
        schema = ((Path(__file__).resolve().parent / '../blueprint.sql')).read_text(encoding="utf-8")
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript(schema)
            con.commit()

    def write(self, relative: str, value: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def plan(self, items=None, journal=".approve-journals/run.json"):
        return approve.build_plan(
            root=self.root,
            database=self.db,
            items=items or [("drafts/AGENTS.md", "live/AGENTS.md", "none")],
            archive_root=".approve-archive",
            journal=journal,
            clock=lambda: FIXED_TIME,
        )

    def apply(self, plan, **overrides):
        values = {
            "root": self.root,
            "database": self.db,
            "plan": plan,
            "confirmation": plan["plan_digest"],
            "actor": ACTOR,
            "approval_ref": APPROVAL_REF,
            "approval_text": APPROVAL_TEXT,
            "clock": lambda: FIXED_TIME,
        }
        values.update(overrides)
        return approve.apply_plan(**values)

    def private_write(self, relative: str, value: str) -> Path:
        path = self.control / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def private_plan(self, items=None, journal="journals/run.json"):
        return approve.build_plan(
            root=self.root,
            control_root=self.control,
            database=self.db,
            items=items or [("drafts/AGENTS.md", "live/AGENTS.md", "none")],
            archive_root="archives",
            journal=journal,
            clock=lambda: FIXED_TIME,
        )

    def private_apply(self, plan, **overrides):
        return self.apply(plan, control_root=self.control, **overrides)

    def identity_plan(self, agent_id="amazon-operator", journal="journals/identity.json"):
        return approve.build_plan(
            root=self.identity_root,
            control_root=self.control,
            database=self.db,
            items=[(f"drafts/{agent_id}.md", f"agents/{agent_id}.md", "none")],
            archive_root="archives",
            journal=journal,
            identity_source=True,
            clock=lambda: FIXED_TIME,
        )

    def identity_apply(self, plan, **overrides):
        values = {
            "root": self.identity_root,
            "control_root": self.control,
            "identity_source": True,
        }
        values.update(overrides)
        return self.apply(plan, **values)

    def rows(self, table: str):
        with closing(sqlite3.connect(self.db)) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY id")]

    def test_success_preserves_prior_records_exact_version_and_lint_binding(self):
        draft = self.write(
            "drafts/AGENTS.md",
            "---\ntype: agents\ntags: [staged]\n---\n# New contract\n",
        )
        prior = b"---\ntype: agents\n---\n# Old contract\n"
        live = self.root / "live/AGENTS.md"
        live.write_bytes(prior)
        draft_before = draft.read_bytes()
        plan = self.plan(items=[("drafts/AGENTS.md", "live/AGENTS.md", "remove-staged-tag")])
        self.assertIn("-tags: [staged]", plan["items"][0]["diff"])
        self.assertIn("-# Old contract", plan["items"][0]["diff"])
        result = self.apply(plan)
        self.assertEqual("applied", result["status"])
        self.assertEqual(draft_before, draft.read_bytes())
        proposed = b"---\ntype: agents\n---\n# New contract\n"
        self.assertEqual(proposed, live.read_bytes())
        archive = self.root / plan["items"][0]["archive"]
        self.assertEqual(prior, archive.read_bytes())

        approvals = self.rows("approvals")
        activities = self.rows("activity")
        self.assertEqual(1, len(approvals))
        self.assertEqual(hashlib.sha256(proposed).hexdigest(), approvals[0]["version"])
        self.assertEqual(APPROVAL_REF, approvals[0]["source"])
        self.assertEqual(APPROVAL_TEXT, approvals[0]["person_words"])
        self.assertEqual("document", approvals[0]["subject_type"])
        self.assertEqual("live/AGENTS.md", approvals[0]["subject_id"])
        self.assertEqual(1, len(activities))
        self.assertEqual(ACTOR, activities[0]["actor"])
        self.assertEqual(plan["items"][0]["prior_sha256"], activities[0]["old_value"])
        self.assertEqual(plan["items"][0]["proposed_sha256"], activities[0]["new_value"])

        report = approve.lint_documents(root=self.root, database=self.db, paths=["live/AGENTS.md"])
        self.assertEqual([], report["findings"])
        self.assertEqual(
            {"file": "live/AGENTS.md", "sha256": approvals[0]["version"], "approval": f"approval-row:{approvals[0]['id']}"},
            report["approval_source"]["approvals"][0],
        )

    def test_confirmation_is_required_and_mismatch_is_denied(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        before = live.read_bytes()
        plan = self.plan()
        for confirmation in (None, "0" * 64):
            with self.subTest(confirmation=confirmation):
                with self.assertRaisesRegex(approve.ApproveError, "confirmation"):
                    self.apply(plan, confirmation=confirmation)
                self.assertEqual(before, live.read_bytes())
                self.assertEqual([], self.rows("approvals"))
                self.assertFalse((self.root / plan["journal"]).exists())

    def test_stale_sources_targets_and_tampered_plan_fail_before_writes(self):
        draft = self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        draft.write_text("# Changed draft\n")
        with self.assertRaisesRegex(approve.ApproveError, "draft is stale"):
            self.apply(plan)
        self.assertEqual(b"# Old\n", live.read_bytes())
        self.assertFalse((self.root / plan["journal"]).exists())

        self.root.joinpath("drafts/AGENTS.md").write_text("# New\n")
        plan = self.plan()
        live.write_text("# Concurrent target\n")
        with self.assertRaisesRegex(approve.ApproveError, "live target is stale"):
            self.apply(plan)
        self.assertFalse((self.root / plan["journal"]).exists())

        live.write_text("# Old\n")
        plan = self.plan()
        plan["items"][0]["proposed_sha256"] = "0" * 64
        with self.assertRaisesRegex(approve.ApproveError, "plan digest"):
            self.apply(plan)

    def test_resealed_forged_bytes_diff_and_structure_fail_semantic_validation(self):
        self.write("drafts/AGENTS.md", "# Intended\n")
        live = self.write("live/AGENTS.md", "# Prior\n")
        plan = self.plan()

        forged = copy.deepcopy(plan)
        forged_bytes = b"# Forged replacement\n"
        item = forged["items"][0]
        item["proposed_base64"] = approve.base64.b64encode(forged_bytes).decode("ascii")
        item["proposed_sha256"] = approve.sha256_bytes(forged_bytes)
        item["proposed_bytes"] = len(forged_bytes)
        prior = approve.base64.b64decode(item["prior_base64"])
        draft = (self.root / item["draft"]).read_bytes()
        item["diff"] = approve.diff_text(prior, draft, forged_bytes, item["live"], item["draft"])
        forged["plan_digest"] = approve.plan_digest(forged)
        with self.assertRaisesRegex(approve.ApproveError, "proposed semantics"):
            self.apply(forged)

        misleading = copy.deepcopy(plan)
        misleading["items"][0]["diff"] = "No changes.\n"
        misleading["plan_digest"] = approve.plan_digest(misleading)
        with self.assertRaisesRegex(approve.ApproveError, "displayed diff"):
            self.apply(misleading)

        extra = copy.deepcopy(plan)
        extra["items"][0]["unreviewed"] = True
        extra["plan_digest"] = approve.plan_digest(extra)
        with self.assertRaisesRegex(approve.ApproveError, "unsupported fields"):
            self.apply(extra)

        bad_type = copy.deepcopy(plan)
        bad_type["items"][0]["draft_bytes"] = True
        bad_type["plan_digest"] = approve.plan_digest(bad_type)
        with self.assertRaisesRegex(approve.ApproveError, "draft_bytes is invalid"):
            self.apply(bad_type)

        bad_archive = copy.deepcopy(plan)
        bad_archive["items"][0]["archive"] = ".approve-archive/forged.prior"
        bad_archive["plan_digest"] = approve.plan_digest(bad_archive)
        with self.assertRaisesRegex(approve.ApproveError, "archive path is invalid"):
            self.apply(bad_archive)
        self.assertEqual(b"# Prior\n", live.read_bytes())
        self.assertFalse((self.root / plan["journal"]).exists())

    def test_idempotent_replay_does_not_duplicate_rows(self):
        self.write("drafts/AGENTS.md", "# New\n")
        self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        self.assertEqual("applied", self.apply(plan)["status"])
        before = (len(self.rows("approvals")), len(self.rows("activity")))
        self.assertEqual("duplicate", self.apply(plan)["status"])
        self.assertEqual(before, (len(self.rows("approvals")), len(self.rows("activity"))))

    def test_lint_requires_current_exact_version(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        self.apply(plan)
        live.write_text("# Newer unapproved bytes\n")
        report = approve.lint_documents(root=self.root, database=self.db, paths=["live/AGENTS.md"])
        self.assertEqual(1, report["summary"]["missing"])
        self.assertEqual("missing", report["findings"][0]["state"])
        self.assertEqual([], report["approval_source"]["approvals"])

    def test_explicit_metadata_transforms_only(self):
        source = "---\nstatus: draft\ntags: [staged]\n---\n# Candidate\n"
        self.write("drafts/AGENTS.md", source)
        self.write("live/AGENTS.md", "# Old\n")
        plain = self.plan()
        self.assertEqual(source.encode(), approve.base64.b64decode(plain["items"][0]["proposed_base64"]))
        self.assertFalse(plain["items"][0]["transform_applied"])

        status_plan = self.plan(
            items=[("drafts/AGENTS.md", "live/AGENTS.md", "remove-status")],
            journal=".approve-journals/status.json",
        )
        self.assertIn("-status: draft", status_plan["items"][0]["diff"])
        self.assertIn("tags: [staged]", approve.base64.b64decode(status_plan["items"][0]["proposed_base64"]).decode())

        tag_plan = self.plan(
            items=[("drafts/AGENTS.md", "live/AGENTS.md", "remove-staged-tag")],
            journal=".approve-journals/tag.json",
        )
        self.assertIn("-tags: [staged]", tag_plan["items"][0]["diff"])
        self.assertIn("status: draft", approve.base64.b64decode(tag_plan["items"][0]["proposed_base64"]).decode())

        self.write("drafts/AGENTS.md", "---\nstatus: |\n  draft\n---\n# Candidate\n")
        with self.assertRaisesRegex(approve.ApproveError, "multiline"):
            self.plan(items=[("drafts/AGENTS.md", "live/AGENTS.md", "remove-status")])

    def test_path_hazards_duplicates_hardlinks_symlinks_and_schema(self):
        self.write("drafts/AGENTS.md", "# New\n")
        self.write("live/AGENTS.md", "# Old\n")
        with self.assertRaisesRegex(approve.ApproveError, "relative path"):
            self.plan(items=[("../escape.md", "live/AGENTS.md", "none")])
        with self.assertRaisesRegex(approve.ApproveError, "conflicting"):
            self.plan(items=[
                ("drafts/AGENTS.md", "live/AGENTS.md", "none"),
                ("drafts/AGENTS.md", "live/AGENTS.md", "none"),
            ])

        linked = self.root / "drafts/LINK.md"
        linked.symlink_to(self.root / "drafts/AGENTS.md")
        with self.assertRaisesRegex(approve.ApproveError, "symlink"):
            self.plan(items=[("drafts/LINK.md", "live/LINK.md", "none")])

        hard = self.root / "drafts/HARD.md"
        os.link(self.root / "drafts/AGENTS.md", hard)
        with self.assertRaisesRegex(approve.ApproveError, "hard links"):
            self.plan(items=[("drafts/HARD.md", "live/HARD.md", "none")])
        hard.unlink()

        bad = self.base / "bad.sqlite"
        with closing(sqlite3.connect(bad)) as con:
            con.execute("CREATE TABLE approvals(id INTEGER PRIMARY KEY)")
        with self.assertRaisesRegex(approve.ApproveError, "unsupported work schema"):
            approve.build_plan(
                root=self.root, database=bad,
                items=[("drafts/AGENTS.md", "live/AGENTS.md", "none")],
                archive_root=".approve-archive", journal=".approve-journals/bad.json",
            )

    def test_same_column_names_do_not_admit_changed_identity_or_conflict_policy(self):
        self.write("drafts/AGENTS.md", "# Proposed\n")
        self.write("live/AGENTS.md", "# Original\n")
        with closing(sqlite3.connect(self.db)) as con:
            original = con.execute("SELECT sql FROM sqlite_schema WHERE name='approvals'").fetchone()[0]
        for changed in (
            original.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id TEXT PRIMARY KEY"),
            original.replace("subject_id TEXT NOT NULL", "subject_id TEXT NOT NULL UNIQUE ON CONFLICT REPLACE"),
        ):
            with self.subTest(definition=changed):
                with closing(sqlite3.connect(self.db)) as con:
                    con.execute("DROP TABLE approvals")
                    con.execute(changed)
                    con.commit()
                with self.assertRaisesRegex(approve.ApproveError, "unsupported work schema definition"):
                    self.plan()
                self.assertEqual((self.root / "live/AGENTS.md").read_text(), "# Original\n")
                self.assertEqual(self.rows("activity"), [])

    def test_archive_collision_is_refused(self):
        self.write("drafts/AGENTS.md", "# New\n")
        self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        archive = self.root / plan["items"][0]["archive"]
        archive.write_text("occupied")
        with self.assertRaisesRegex(approve.ApproveError, "archive collision"):
            self.apply(plan)
        self.assertEqual([], self.rows("approvals"))

    def test_foreign_key_defect_drift_is_refused_without_repair(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("PRAGMA foreign_keys=OFF")
            con.execute(
                "INSERT INTO tasks(id,title,status,function) VALUES ('T-broken','Broken fixture','todo','F-missing')"
            )
            con.commit()
        with self.assertRaisesRegex(approve.ApproveError, "database approval or activity state is stale"):
            self.apply(plan)
        self.assertEqual(b"# Old\n", live.read_bytes())
        self.assertFalse((self.root / plan["journal"]).exists())
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual("F-missing", con.execute("SELECT function FROM tasks WHERE id='T-broken'").fetchone()[0])

    def test_write_side_trigger_is_refused_before_document_mutation(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with closing(sqlite3.connect(self.db)) as con:
            con.execute(
                "CREATE TRIGGER approval_side_effect AFTER INSERT ON approvals BEGIN "
                "INSERT INTO activity(subject_type,subject_id,actor,at,note) "
                "VALUES ('trigger','unexpected','trigger','2026-09-20T00:00:00Z','side effect'); END"
            )
            con.commit()
        with self.assertRaisesRegex(approve.ApproveError, "write-side triggers"):
            self.apply(plan)
        self.assertEqual(b"# Old\n", live.read_bytes())
        self.assertFalse((self.root / plan["journal"]).exists())
        self.assertEqual([], self.rows("activity"))

    def test_combined_batch_supports_forty_documents(self):
        items = []
        for index in range(40):
            relative = f"Contract-{index:02d}.md"
            self.write("drafts/" + relative, f"# Candidate {index}\n")
            items.append(("drafts/" + relative, "live/" + relative, "none"))
        plan = self.plan(items=items)
        self.assertEqual(40, len(plan["items"]))
        self.assertEqual("applied", self.apply(plan)["status"])
        self.assertEqual(40, len(self.rows("approvals")))
        self.assertEqual(40, len(self.rows("activity")))

    def test_batch_bound_refuses_sixty_five_documents(self):
        items = []
        for index in range(65):
            relative = f"Bound-{index:02d}.md"
            self.write("drafts/" + relative, f"# Candidate {index}\n")
            items.append(("drafts/" + relative, "live/" + relative, "none"))
        with self.assertRaisesRegex(approve.ApproveError, "1-64"):
            self.plan(items=items)

    def test_injected_batch_failure_is_recoverable(self):
        for name in ("A", "B"):
            self.write(f"drafts/{name}.md", f"# New {name}\n")
            self.write(f"live/{name}.md", f"# Old {name}\n")
        plan = self.plan(
            items=[
                ("drafts/A.md", "live/A.md", "none"),
                ("drafts/B.md", "live/B.md", "none"),
            ]
        )
        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.apply(plan, inject_failure="after_target:0")
        self.assertEqual(b"# New A\n", (self.root / "live/A.md").read_bytes())
        self.assertEqual(b"# Old B\n", (self.root / "live/B.md").read_bytes())
        self.assertEqual([], self.rows("approvals"))
        result = approve.recover_plan(
            root=self.root, plan=plan, confirmation=plan["plan_digest"], clock=lambda: FIXED_TIME
        )
        self.assertEqual("recovered", result["status"])
        self.assertEqual(b"# Old A\n", (self.root / "live/A.md").read_bytes())
        self.assertEqual(b"# Old B\n", (self.root / "live/B.md").read_bytes())
        repeat = approve.recover_plan(
            root=self.root, plan=plan, confirmation=plan["plan_digest"], clock=lambda: FIXED_TIME
        )
        self.assertEqual("duplicate-recovery", repeat["status"])

    def test_failure_before_first_write_recovers_as_untouched_and_repeats(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()

        def stop_before_write(_index):
            raise RuntimeError("fixture stop before first write")

        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.apply(plan, before_item_write=stop_before_write)
        first = approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("recovered", first["status"])
        journal = json.loads((self.root / plan["journal"]).read_text())
        self.assertEqual("untouched", journal["items"][0]["state"])
        self.assertEqual("# Old\n", live.read_text())
        self.assertFalse((self.root / plan["items"][0]["archive"]).exists())
        second = approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("duplicate-recovery", second["status"])

    def test_recovery_preserves_concurrent_target_change(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with self.assertRaises(approve.ApproveError):
            self.apply(plan, inject_failure="after_target:0")
        live.write_text("# Concurrent after failure\n")
        with self.assertRaisesRegex(approve.ApproveError, "manual review"):
            approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("# Concurrent after failure\n", live.read_text())

    def test_unrecorded_target_write_never_reports_recovered(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with self.assertRaises(approve.ApproveError):
            self.apply(plan, inject_failure="after_target:0")
        journal_path = self.root / plan["journal"]
        journal = json.loads(journal_path.read_text())
        journal["items"][0]["state"] = "archive_written"
        journal["items"][0].pop("written_identity", None)
        journal_path.write_text(json.dumps(journal, indent=2) + "\n")
        with self.assertRaisesRegex(approve.ApproveError, "unrecorded candidate write"):
            approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("# New\n", live.read_text())

    def test_unrecorded_new_target_write_never_reports_recovered(self):
        self.write("drafts/NEW.md", "# New target\n")
        plan = self.plan(items=[("drafts/NEW.md", "live/NEW.md", "none")])
        with self.assertRaises(approve.ApproveError):
            self.apply(plan, inject_failure="after_target:0")
        journal_path = self.root / plan["journal"]
        journal = json.loads(journal_path.read_text())
        journal["items"][0]["state"] = "pending"
        journal["items"][0].pop("written_identity", None)
        journal_path.write_text(json.dumps(journal, indent=2) + "\n")
        with self.assertRaisesRegex(approve.ApproveError, "unrecorded candidate write"):
            approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("# New target\n", (self.root / "live/NEW.md").read_text())

    def test_target_replaced_during_archive_is_not_overwritten(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()

        def replace_target(_index):
            live.write_text("# Concurrent during archive\n")

        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.apply(plan, after_archive_write=replace_target)
        self.assertEqual("# Concurrent during archive\n", live.read_text())
        self.assertEqual([], self.rows("approvals"))
        with self.assertRaisesRegex(approve.ApproveError, "manual review"):
            approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])

    def test_recovery_rechecks_recorded_target_at_mutation_window(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with self.assertRaises(approve.ApproveError):
            self.apply(plan, inject_failure="after_target:0")

        def change_after_preflight(_index):
            live.write_text("# Same-inode concurrent edit\n")

        with self.assertRaisesRegex(approve.ApproveError, "changed before restore"):
            approve.recover_plan(
                root=self.root, plan=plan, confirmation=plan["plan_digest"],
                before_recovery_write=change_after_preflight,
            )
        self.assertEqual("# Same-inode concurrent edit\n", live.read_text())

    def test_recovery_rechecks_archive_at_mutation_window(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with self.assertRaises(approve.ApproveError):
            self.apply(plan, inject_failure="after_target:0")
        archive = self.root / plan["items"][0]["archive"]

        def change_archive_after_preflight(_index):
            archive.write_text("# Same-inode archive edit\n")

        with self.assertRaisesRegex(approve.ApproveError, "archive.*changed before restore"):
            approve.recover_plan(
                root=self.root, plan=plan, confirmation=plan["plan_digest"],
                before_recovery_write=change_archive_after_preflight,
            )
        self.assertEqual("# New\n", live.read_text())
        self.assertEqual("# Same-inode archive edit\n", archive.read_text())

    def test_recovery_rechecks_new_target_full_identity_before_unlink(self):
        self.write("drafts/NEW.md", "# New target\n")
        live = self.root / "live/NEW.md"
        plan = self.plan(items=[("drafts/NEW.md", "live/NEW.md", "none")])
        with self.assertRaises(approve.ApproveError):
            self.apply(plan, inject_failure="after_target:0")

        def edit_same_inode_after_preflight(_index):
            live.write_text("# Same inode, changed bytes\n")

        with self.assertRaisesRegex(approve.ApproveError, "changed before restore"):
            approve.recover_plan(
                root=self.root, plan=plan, confirmation=plan["plan_digest"],
                before_recovery_write=edit_same_inode_after_preflight,
            )
        self.assertEqual("# Same inode, changed bytes\n", live.read_text())

    def test_rechecks_each_target_before_write_and_recovers_prior_item(self):
        for name in ("A", "B"):
            self.write(f"drafts/{name}.md", f"# New {name}\n")
            self.write(f"live/{name}.md", f"# Old {name}\n")
        plan = self.plan(items=[
            ("drafts/A.md", "live/A.md", "none"),
            ("drafts/B.md", "live/B.md", "none"),
        ])

        def change_second(index):
            if index == 1:
                (self.root / "live/B.md").write_text("# Concurrent B\n")

        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.apply(plan, before_item_write=change_second)
        with self.assertRaisesRegex(approve.ApproveError, "manual review"):
            approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("# New A\n", (self.root / "live/A.md").read_text())
        self.assertEqual("# Concurrent B\n", (self.root / "live/B.md").read_text())

    def test_earlier_target_change_blocks_database_commit(self):
        for name in ("A", "B"):
            self.write(f"drafts/{name}.md", f"# New {name}\n")
            self.write(f"live/{name}.md", f"# Old {name}\n")
        live_a = self.root / "live/A.md"
        plan = self.plan(items=[
            ("drafts/A.md", "live/A.md", "none"),
            ("drafts/B.md", "live/B.md", "none"),
        ])

        def change_earlier(index):
            if index == 1:
                live_a.write_text("# Concurrent A after its write\n")

        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.apply(plan, before_item_write=change_earlier)
        self.assertEqual([], self.rows("approvals"))
        self.assertEqual([], self.rows("activity"))
        self.assertEqual("# Concurrent A after its write\n", live_a.read_text())

    def test_database_rollback_then_filesystem_recovery(self):
        self.write("drafts/AGENTS.md", "# New\n")
        self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.apply(plan, inject_failure="before_database_commit")
        self.assertEqual([], self.rows("approvals"))
        approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("# Old\n", (self.root / "live/AGENTS.md").read_text())

    def test_crash_after_database_commit_finishes_without_rollback(self):
        self.write("drafts/AGENTS.md", "# New\n")
        self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.apply(plan, inject_failure="after_database_commit")
        self.assertEqual(1, len(self.rows("approvals")))
        result = approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        self.assertEqual("completed-after-crash", result["status"])
        self.assertEqual("# New\n", (self.root / "live/AGENTS.md").read_text())
        self.assertEqual("duplicate", self.apply(plan)["status"])

    def test_completed_after_crash_verifies_target_and_archive(self):
        self.write("drafts/AGENTS.md", "# New\n")
        live = self.write("live/AGENTS.md", "# Old\n")
        plan = self.plan()
        with self.assertRaises(approve.ApproveError):
            self.apply(plan, inject_failure="after_database_commit")
        archive = self.root / plan["items"][0]["archive"]
        archive.write_text("# Corrupt archive\n")
        with self.assertRaisesRegex(approve.ApproveError, "archive needs manual review"):
            approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])
        archive.write_bytes(approve.base64.b64decode(plan["items"][0]["prior_base64"]))
        live.write_text("# Corrupt target\n")
        with self.assertRaisesRegex(approve.ApproveError, "target needs manual review"):
            approve.recover_plan(root=self.root, plan=plan, confirmation=plan["plan_digest"])

    def test_cli_plan_prints_full_diff_before_digest(self):
        self.write("drafts/AGENTS.md", "# New\n")
        self.write("live/AGENTS.md", "# Old\n")
        output = self.base / "plan.json"
        out, err = io.StringIO(), io.StringIO()
        code = approve.run([
            "plan", "--root", str(self.root), "--db", str(self.db),
            "--item", "drafts/AGENTS.md::live/AGENTS.md",
            "--archive-root", ".approve-archive",
            "--journal", ".approve-journals/cli.json",
            "--output", str(output),
        ], stdout=out, stderr=err)
        self.assertEqual(0, code, err.getvalue())
        self.assertIn("-# Old", out.getvalue())
        self.assertIn("+# New", out.getvalue())
        self.assertLess(out.getvalue().index("-# Old"), out.getvalue().index("plan digest:"))
        self.assertEqual(approve.load_plan(output)["plan_digest"], json.loads(output.read_text())["plan_digest"])

    def test_private_control_root_keeps_draft_archive_journal_and_prior_bytes_private(self):
        draft = self.private_write("drafts/AGENTS.md", "# Private candidate\n")
        live = self.write("live/AGENTS.md", "# Prior live bytes\n")
        plan = self.private_plan()
        self.assertEqual(approve.PRIVATE_FORMAT, plan["format"])
        self.assertEqual(str(self.control), plan["control_root"])
        result = self.private_apply(plan)
        self.assertEqual("applied", result["status"])
        self.assertEqual("# Private candidate\n", live.read_text())
        self.assertEqual("# Private candidate\n", draft.read_text())
        self.assertEqual(b"# Prior live bytes\n", (self.control / plan["items"][0]["archive"]).read_bytes())
        self.assertTrue((self.control / plan["journal"]).is_file())
        self.assertFalse((self.root / "archives").exists())
        self.assertFalse((self.root / "journals").exists())

    def test_private_control_root_revalidates_stale_draft_and_root_identity(self):
        draft = self.private_write("drafts/AGENTS.md", "# Candidate\n")
        self.write("live/AGENTS.md", "# Old\n")
        plan = self.private_plan()
        draft.write_text("# Stale\n")
        with self.assertRaisesRegex(approve.ApproveError, "draft is stale"):
            self.private_apply(plan)
        draft.write_text("# Candidate\n")
        plan = self.private_plan(journal="journals/replaced.json")
        old = self.base / "private-control-old"
        self.control.rename(old)
        self.control.mkdir()
        with self.assertRaisesRegex(approve.ApproveError, "control root identity changed"):
            self.private_apply(plan)
        self.control.rmdir()
        old.rename(self.control)
        self.assertEqual("# Old\n", (self.root / "live/AGENTS.md").read_text())

    def test_private_plan_metadata_tamper_and_v1_reinterpretation_are_refused(self):
        self.private_write("drafts/AGENTS.md", "# Candidate\n")
        self.write("live/AGENTS.md", "# Old\n")
        plan = self.private_plan()
        forged = copy.deepcopy(plan)
        forged["control_root_identity"]["inode"] += 1
        forged["plan_digest"] = approve.plan_digest(forged)
        with self.assertRaisesRegex(approve.ApproveError, "control root identity changed"):
            self.private_apply(forged)
        with self.assertRaisesRegex(approve.ApproveError, "requires the exact control root"):
            self.apply(plan)

        self.write("drafts/AGENTS.md", "# Legacy candidate\n")
        legacy = self.plan(journal=".approve-journals/legacy.json")
        with self.assertRaisesRegex(approve.ApproveError, "v1 plan does not support"):
            self.apply(legacy, control_root=self.control)

    def test_private_control_root_rejects_overlap_symlinks_and_cross_root_hardlinks(self):
        self.private_write("drafts/AGENTS.md", "# Candidate\n")
        self.write("live/AGENTS.md", "# Old\n")
        with self.assertRaisesRegex(approve.ApproveError, "non-overlapping"):
            approve.build_plan(
                root=self.root, control_root=self.root / "drafts", database=self.db,
                items=[("AGENTS.md", "live/AGENTS.md", "none")],
                archive_root="../never", journal="../never.json",
            )
        alias = self.base / "control-alias"
        alias.symlink_to(self.control, target_is_directory=True)
        with self.assertRaisesRegex(approve.ApproveError, "non-symlink"):
            approve.build_plan(
                root=self.root, control_root=alias, database=self.db,
                items=[("drafts/AGENTS.md", "live/AGENTS.md", "none")],
                archive_root="archives", journal="journals/alias.json",
            )
        hard = self.root / "live/HARD.md"
        os.link(self.control / "drafts/AGENTS.md", hard)
        with self.assertRaisesRegex(approve.ApproveError, "hard links"):
            self.private_plan(items=[("drafts/AGENTS.md", "live/HARD.md", "none")])

    def test_private_failure_recovery_uses_private_journal_and_preserves_prior(self):
        self.private_write("drafts/AGENTS.md", "# Candidate\n")
        live = self.write("live/AGENTS.md", "# Prior\n")
        plan = self.private_plan()
        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.private_apply(plan, inject_failure="after_target:0")
        self.assertEqual("# Candidate\n", live.read_text())
        old = self.base / "private-control-old"
        self.control.rename(old)
        self.control.mkdir()
        with self.assertRaisesRegex(approve.ApproveError, "control root identity changed"):
            approve.recover_plan(
                root=self.root, control_root=self.control, plan=plan,
                confirmation=plan["plan_digest"], clock=lambda: FIXED_TIME,
            )
        self.control.rmdir()
        old.rename(self.control)
        result = approve.recover_plan(
            root=self.root, control_root=self.control, plan=plan,
            confirmation=plan["plan_digest"], clock=lambda: FIXED_TIME,
        )
        self.assertEqual("recovered", result["status"])
        self.assertEqual("# Prior\n", live.read_text())
        self.assertTrue((self.control / plan["journal"]).is_file())

    def test_private_cli_plan_apply_and_recover_require_private_plan_location(self):
        self.private_write("drafts/AGENTS.md", "# Candidate\n")
        self.write("live/AGENTS.md", "# Prior\n")
        plan_path = self.control / "plans/cli.json"
        out, err = io.StringIO(), io.StringIO()
        code = approve.run([
            "plan", "--root", str(self.root), "--control-root", str(self.control),
            "--db", str(self.db), "--item", "drafts/AGENTS.md::live/AGENTS.md",
            "--archive-root", "archives", "--journal", "journals/cli.json",
            "--output", str(plan_path),
        ], stdout=out, stderr=err)
        self.assertEqual(0, code, err.getvalue())
        plan = approve.load_plan(plan_path)
        code = approve.run([
            "apply", "--root", str(self.root), "--control-root", str(self.control),
            "--db", str(self.db), "--plan", str(plan_path),
            "--confirm-digest", plan["plan_digest"], "--actor", ACTOR,
            "--approval-ref", APPROVAL_REF, "--approval-text", APPROVAL_TEXT,
        ], stdout=io.StringIO(), stderr=err)
        self.assertEqual(0, code, err.getvalue())

        outside = self.base / "outside-plan.json"
        outside.write_bytes(plan_path.read_bytes())
        code = approve.run([
            "apply", "--root", str(self.root), "--control-root", str(self.control),
            "--db", str(self.db), "--plan", str(outside),
            "--confirm-digest", plan["plan_digest"], "--actor", ACTOR,
            "--approval-ref", APPROVAL_REF, "--approval-text", APPROVAL_TEXT,
        ], stdout=io.StringIO(), stderr=err)
        self.assertEqual(2, code)
        self.assertIn("plan file must stay below", err.getvalue())

        self.private_write("drafts/RECOVER.md", "# Recover candidate\n")
        self.write("live/RECOVER.md", "# Recover prior\n")
        recover_plan = self.private_plan(
            items=[("drafts/RECOVER.md", "live/RECOVER.md", "none")],
            journal="journals/recover-cli.json",
        )
        recover_path = self.control / "plans/recover-cli.json"
        recover_path.write_text(json.dumps(recover_plan, indent=2) + "\n")
        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.private_apply(recover_plan, inject_failure="after_target:0")
        code = approve.run([
            "recover", "--root", str(self.root), "--control-root", str(self.control),
            "--plan", str(recover_path), "--confirm-digest", recover_plan["plan_digest"],
        ], stdout=io.StringIO(), stderr=err)
        self.assertEqual(0, code, err.getvalue())
        self.assertEqual("# Recover prior\n", (self.root / "live/RECOVER.md").read_text())

    def test_private_cli_rejects_plan_output_outside_control_root(self):
        self.private_write("drafts/AGENTS.md", "# Candidate\n")
        self.write("live/AGENTS.md", "# Prior\n")
        outside = self.base / "outside.json"
        err = io.StringIO()
        code = approve.run([
            "plan", "--root", str(self.root), "--control-root", str(self.control),
            "--db", str(self.db), "--item", "drafts/AGENTS.md::live/AGENTS.md",
            "--archive-root", "archives", "--journal", "journals/outside.json",
            "--output", str(outside),
        ], stdout=io.StringIO(), stderr=err)
        self.assertEqual(2, code)
        self.assertIn("output must stay below", err.getvalue())
        self.assertFalse(outside.exists())

    def test_identity_source_records_exact_contract_subject_and_full_file_hash(self):
        candidate = self.private_write("drafts/amazon-operator.md", "---\nid: amazon-operator\nversion: 4\n---\n# Who you are\n")
        live = self.identity_root / "agents/amazon-operator.md"
        live.write_text("---\nid: amazon-operator\nversion: 3\n---\n# Who you are\n")
        plan = self.identity_plan()
        self.assertEqual(approve.IDENTITY_FORMAT, plan["format"])
        self.assertEqual(approve.IDENTITY_MODE, plan["approval_mode"])
        self.assertEqual("contract", plan["items"][0]["subject_type"])
        self.assertEqual("agent-team/agents/amazon-operator.md", plan["items"][0]["subject_id"])
        expected = hashlib.sha256(candidate.read_bytes()).hexdigest()
        self.assertEqual(expected, plan["items"][0]["proposed_sha256"])
        self.assertEqual("applied", self.identity_apply(plan)["status"])
        approval = self.rows("approvals")[0]
        self.assertEqual("contract", approval["subject_type"])
        self.assertEqual("agent-team/agents/amazon-operator.md", approval["subject_id"])
        self.assertEqual(expected, approval["version"])
        activity = self.rows("activity")[0]
        self.assertEqual(("contract", approval["subject_id"]), (activity["subject_type"], activity["subject_id"]))
        report = approve.lint_documents(
            root=self.identity_root, control_root=self.control, database=self.db,
            paths=["agents/amazon-operator.md"], identity_source=True,
        )
        self.assertEqual([], report["findings"])
        self.assertEqual("contract", report["documents"][0]["subject_type"])
        self.assertEqual(approval["subject_id"], report["documents"][0]["subject_id"])

    def test_identity_source_preserves_legacy_reviewer_contract_approval(self):
        reviewer = self.identity_root / "agents/reviewer.md"
        reviewer.write_text("---\nid: reviewer\nversion: 5\n---\n# Who you are\n")
        with closing(sqlite3.connect(self.db)) as con:
            con.execute(
                "INSERT INTO approvals(id,subject_type,subject_id,version,call,person_words,given_at,source) "
                "VALUES (20,'contract','agent-team/agents/reviewer.md',?,'approve','legacy exact approval','2026-09-19T00:00:00Z','legacy')",
                ("v5 cbe0e34",),
            )
            con.commit()
        before = self.rows("approvals")[0]
        report = approve.lint_documents(
            root=self.identity_root, control_root=self.control, database=self.db,
            paths=["agents/reviewer.md"], identity_source=True,
        )
        self.assertEqual(1, report["summary"]["missing"])
        self.assertEqual([], report["approval_source"]["approvals"])

        self.private_write("drafts/designer.md", "# New designer\n")
        (self.identity_root / "agents/designer.md").write_text("# Old designer\n")
        plan = self.identity_plan("designer", "journals/legacy-preserve.json")
        self.assertEqual("applied", self.identity_apply(plan)["status"])
        self.assertEqual("duplicate", self.identity_apply(plan)["status"])

        self.private_write("drafts/video-producer.md", "# New video producer\n")
        recovery_live = self.identity_root / "agents/video-producer.md"
        recovery_live.write_text("# Old video producer\n")
        recovery_plan = self.identity_plan("video-producer", "journals/legacy-recovery.json")
        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.identity_apply(recovery_plan, inject_failure="after_target:0")
        self.assertEqual(
            "recovered",
            approve.recover_plan(
                root=self.identity_root, control_root=self.control, plan=recovery_plan,
                confirmation=recovery_plan["plan_digest"], identity_source=True,
            )["status"],
        )
        self.assertEqual("# Old video producer\n", recovery_live.read_text())
        legacy_after = next(row for row in self.rows("approvals") if row["id"] == 20)
        self.assertEqual(before, legacy_after)

    def test_identity_and_document_approval_namespaces_do_not_cross(self):
        identity = self.identity_root / "agents/designer.md"
        identity.write_text("# Designer\n")
        version = hashlib.sha256(identity.read_bytes()).hexdigest()
        with closing(sqlite3.connect(self.db)) as con:
            con.execute(
                "INSERT INTO approvals(subject_type,subject_id,version,call,given_at,source) "
                "VALUES ('document','agent-team/agents/designer.md',?,'approve',?,'fixture')",
                (version, FIXED_TIME),
            )
            con.commit()
        identity_report = approve.lint_documents(
            root=self.identity_root, control_root=self.control, database=self.db,
            paths=["agents/designer.md"], identity_source=True,
        )
        self.assertEqual(1, identity_report["summary"]["missing"])

        document = self.write("live/DESIGNER.md", "# Designer\n")
        with closing(sqlite3.connect(self.db)) as con:
            con.execute(
                "INSERT INTO approvals(subject_type,subject_id,version,call,given_at,source) "
                "VALUES ('contract','live/DESIGNER.md',?,'approve',?,'fixture')",
                (hashlib.sha256(document.read_bytes()).hexdigest(), FIXED_TIME),
            )
            con.commit()
        document_report = approve.lint_documents(
            root=self.root, database=self.db, paths=["live/DESIGNER.md"],
        )
        self.assertEqual(1, document_report["summary"]["missing"])

    def test_identity_source_refuses_stale_draft_and_target(self):
        draft = self.private_write("drafts/creative-reviewer.md", "# New reviewer\n")
        live = self.identity_root / "agents/creative-reviewer.md"
        live.write_text("# Old reviewer\n")
        plan = self.identity_plan("creative-reviewer")
        draft.write_text("# Stale reviewer\n")
        with self.assertRaisesRegex(approve.ApproveError, "draft is stale"):
            self.identity_apply(plan)
        draft.write_text("# New reviewer\n")
        plan = self.identity_plan("creative-reviewer", "journals/target-stale.json")
        live.write_text("# Concurrent reviewer\n")
        with self.assertRaisesRegex(approve.ApproveError, "live target is stale"):
            self.identity_apply(plan)
        self.assertEqual([], self.rows("approvals"))

    def test_identity_source_replay_and_recovery_preserve_contract_subject(self):
        self.private_write("drafts/designer.md", "# New designer\n")
        live = self.identity_root / "agents/designer.md"
        live.write_text("# Old designer\n")
        plan = self.identity_plan("designer")
        self.assertEqual("applied", self.identity_apply(plan)["status"])
        self.assertEqual("duplicate", self.identity_apply(plan)["status"])
        self.assertEqual(1, len(self.rows("approvals")))

        self.private_write("drafts/video-producer.md", "# New video producer\n")
        recover_live = self.identity_root / "agents/video-producer.md"
        recover_live.write_text("# Old video producer\n")
        recovery_plan = self.identity_plan("video-producer", "journals/recover-identity.json")
        with self.assertRaisesRegex(approve.ApproveError, "recoverable partial"):
            self.identity_apply(recovery_plan, inject_failure="after_target:0")
        result = approve.recover_plan(
            root=self.identity_root, control_root=self.control, plan=recovery_plan,
            confirmation=recovery_plan["plan_digest"], identity_source=True,
        )
        self.assertEqual("recovered", result["status"])
        self.assertEqual("# Old video producer\n", recover_live.read_text())
        self.assertEqual(1, len(self.rows("approvals")))

    def test_identity_source_rejects_runtime_and_ambiguous_paths(self):
        (self.identity_root / "generated").mkdir()
        (self.identity_root / "agents/runtime").mkdir()
        for path in (
            "SOUL.md", "agents/SOUL.md", "generated/designer.md",
            "agents/runtime/designer.md", "agents/Designer.md",
        ):
            with self.subTest(path=path):
                safe_name = path.replace("/", "-").lower()
                self.private_write("drafts/" + safe_name, "# Candidate\n")
                with self.assertRaises(approve.ApproveError):
                    approve.build_plan(
                        root=self.identity_root, control_root=self.control, database=self.db,
                        items=[("drafts/" + safe_name, path, "none")],
                        archive_root="archives", journal="journals/reject.json",
                        identity_source=True,
                    )
        self.assertFalse((self.identity_root / "SOUL.md").exists())
        self.assertEqual([], list((self.identity_root / "generated").iterdir()))
        self.assertEqual([], list((self.identity_root / "agents/runtime").iterdir()))

    def test_identity_source_mode_tampering_and_reinterpretation_fail_closed(self):
        self.private_write("drafts/sample-finance.md", "# sample-finance\n")
        (self.identity_root / "agents/sample-finance.md").write_text("# Old sample-finance\n")
        plan = self.identity_plan("sample-finance")
        forged = copy.deepcopy(plan)
        forged["approval_mode"] = "document"
        forged["plan_digest"] = approve.plan_digest(forged)
        with self.assertRaisesRegex(approve.ApproveError, "approval mode is invalid"):
            self.identity_apply(forged)
        forged_subject = copy.deepcopy(plan)
        forged_subject["items"][0]["subject_type"] = "document"
        forged_subject["plan_digest"] = approve.plan_digest(forged_subject)
        with self.assertRaisesRegex(approve.ApproveError, "identity subject is invalid"):
            self.identity_apply(forged_subject)
        with self.assertRaisesRegex(approve.ApproveError, "mode does not match"):
            self.private_apply(plan)
        reinterpreted = copy.deepcopy(plan)
        reinterpreted["format"] = approve.PRIVATE_FORMAT
        reinterpreted.pop("approval_mode")
        reinterpreted["items"][0].pop("subject_type")
        reinterpreted["items"][0].pop("subject_id")
        reinterpreted["plan_digest"] = approve.plan_digest(reinterpreted)
        with self.assertRaisesRegex(approve.ApproveError, "require explicit identity-source"):
            self.apply(reinterpreted, root=self.identity_root, control_root=self.control)
        with self.assertRaisesRegex(approve.ApproveError, "requires a private control root"):
            approve.build_plan(
                root=self.identity_root, database=self.db,
                items=[("agents/sample-finance.md", "agents/sample-finance.md", "none")],
                archive_root="archives", journal="journals/no-control.json",
                identity_source=True,
            )
        self.assertEqual("# Old sample-finance\n", (self.identity_root / "agents/sample-finance.md").read_text())
        self.assertEqual([], self.rows("approvals"))

    def test_identity_source_cli_plan_apply_and_lint_are_explicit(self):
        self.private_write("drafts/ugc-producer.md", "# UGC producer v4\n")
        (self.identity_root / "agents/ugc-producer.md").write_text("# UGC producer v3\n")
        plan_path = self.control / "plans/identity-cli.json"
        out, err = io.StringIO(), io.StringIO()
        code = approve.run([
            "plan", "--identity-source", "--root", str(self.identity_root),
            "--control-root", str(self.control), "--db", str(self.db),
            "--item", "drafts/ugc-producer.md::agents/ugc-producer.md",
            "--archive-root", "archives", "--journal", "journals/identity-cli.json",
            "--output", str(plan_path),
        ], stdout=out, stderr=err)
        self.assertEqual(0, code, err.getvalue())
        plan = approve.load_plan(plan_path)
        code = approve.run([
            "apply", "--identity-source", "--root", str(self.identity_root),
            "--control-root", str(self.control), "--db", str(self.db),
            "--plan", str(plan_path), "--confirm-digest", plan["plan_digest"],
            "--actor", ACTOR, "--approval-ref", APPROVAL_REF,
            "--approval-text", APPROVAL_TEXT,
        ], stdout=io.StringIO(), stderr=err)
        self.assertEqual(0, code, err.getvalue())
        lint_out = io.StringIO()
        code = approve.run([
            "lint", "--identity-source", "--root", str(self.identity_root),
            "--control-root", str(self.control), "--db", str(self.db),
            "--path", "agents/ugc-producer.md",
        ], stdout=lint_out, stderr=err)
        self.assertEqual(0, code, err.getvalue())
        report = json.loads(lint_out.getvalue())
        self.assertEqual(approve.IDENTITY_MODE, report["approval_mode"])
        self.assertEqual(0, report["summary"]["missing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
