#!/usr/bin/env python3
"""Cedar Shop acceptance checks for the private recovery bundle."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'not-shipped/his/base/catchup', 'not-shipped/his/base/migrations', 'not-shipped/his/base/staging', 'work', 'not-shipped/his/work', 'events', 'decisions', 'memory', 'people', 'design', 'capture', 'modules/commerce', 'modules/ugc', 'modules/amazon')]

_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _setup
_setup()

from collections import Counter
from contextlib import closing
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parent.parent
CANDIDATE = Path(__file__).resolve().parent.parent
ALL_MODULES = "work,people"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_database = load_module("recovery_bundle_test_build", (Path(__file__).resolve().parent / '../build_database.py'))
table = load_module("recovery_bundle_test_tablecmd", (Path(__file__).resolve().parent / '../table.py'))
recovery = load_module("recovery_bundle_candidate", (Path(__file__).resolve().parent / '../recovery_bundle.py'))

# People ships with Small Talk, not the core. The multi-module book uses the fixture copy as an add-on.
FIXTURE_ADDONS = Path(__file__).resolve().parent / 'fixtures/cedar-table'
_core_addon_folder = build_database._addon_folder
build_database._addon_folder = lambda name: FIXTURE_ADDONS / name if name == 'people' else _core_addon_folder(name)


def physical_tables(db: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def logical_rows(path: Path) -> dict[str, Counter]:
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        result = {}
        for table in physical_tables(db):
            info = recovery._columns(db, table)
            columns = [row["name"] for row in info]
            rowid_accessor = recovery._implicit_rowid_accessor(db, table, info)
            selected = [recovery.core.quote_identifier(value) for value in columns]
            if rowid_accessor is not None:
                selected.insert(0, recovery.core.quote_identifier(rowid_accessor))
            result[table] = Counter(
                tuple(row)
                for row in db.execute(
                    "SELECT "
                    + ",".join(selected)
                    + " FROM "
                    + recovery.core.quote_identifier(table)
                )
            )
        return result


def write_manifest(bundle: Path, manifest: dict) -> None:
    (bundle / "manifest.json").write_text(
        recovery.canonical_json(manifest) + "\n", encoding="utf-8"
    )


def full_source(root: Path) -> Path:
    source = root / "full-source.sqlite"
    build_database.build_database(source, ALL_MODULES, actor="fixture")
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA user_version = 17")
        db.execute("PRAGMA application_id = 424242")
        db.execute(
            "INSERT INTO projects(id,title,result,status,created_on) VALUES(?,?,?,?,?)",
            ("project-1", "Cedar Shop project 🦊", None, "in-progress", "2026-09-20"),
        )
        db.execute(
            "INSERT INTO tasks(id,title,status,project,created_by,created_on) VALUES(?,?,?,?,?,?)",
            ("task-1", "Cedar Shop task", "todo", "project-1", "fixture", "2026-09-20"),
        )
        db.execute(
            "INSERT INTO activity(subject_type,subject_id,field,new_value,actor,source,at,note) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("task", "task-1", "created", "todo", "fixture", "synthetic", "2026-09-20T04:00:00Z", "résumé"),
        )

        db.execute(
            "INSERT INTO persons(id,display_name,evidence_refs) VALUES(?,?,?)",
            ("person-1", "Cedar Shop Person", '["synthetic"]'),
        )
        db.execute("INSERT INTO organizations(id,name) VALUES(?,?)", ("org-1", "Cedar Shop Org"))
        db.execute(
            "INSERT INTO handles(id,person_id,channel,account,address) VALUES(?,?,?,?,?)",
            ("handle-1", "person-1", "email", "synthetic", "person@example.invalid"),
        )
        db.execute(
            "INSERT INTO threads(id,channel,source_account_id,source_thread_id,title) VALUES(?,?,?,?,?)",
            ("thread-1", "email", "synthetic", "outside-thread-1", "Cedar Shop thread"),
        )
        db.execute(
            "INSERT INTO participants(id,thread_id,person_id,handle_id) VALUES(?,?,?,?)",
            ("participant-1", "thread-1", "person-1", "handle-1"),
        )
        db.execute("INSERT INTO pipelines(id,name) VALUES(?,?)", ("pipeline-1", "Cedar Shop"))
        db.execute(
            "INSERT INTO pipeline_stages(pipeline,stage,ord) VALUES(?,?,?)",
            ("pipeline-1", "lead", 0),
        )
        db.execute(
            "INSERT INTO opportunities(id,title,person_id,pipeline,stage,evidence_refs) VALUES(?,?,?,?,?,?)",
            ("opportunity-1", "Cedar Shop Opportunity", "person-1", "pipeline-1", "lead", '["synthetic"]'),
        )
        db.execute(
            "INSERT INTO messages(channel,source_account_id,source_message_id,source_thread_id,"
            "source_system,pulled_at,recipient_handle_ids,workspace_tags,tags) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "email",
                "synthetic",
                "message-1",
                "outside-thread-1",
                "synthetic",
                "2026-09-20T04:01:00Z",
                "[]",
                '["synthetic"]',
                "[]",
            ),
        )
        db.execute(
            "INSERT INTO interactions(id,person_id,thread_id,summary_author,happened_at,summary,"
            "source_channel,source_account_id,source_message_id,evidence_refs) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "interaction-1",
                "person-1",
                "thread-1",
                "fixture",
                "2026-09-20T04:02:00Z",
                "Cedar Shop interaction",
                "email",
                "synthetic",
                "message-1",
                '["synthetic"]',
            ),
        )
        db.execute(
            "INSERT INTO meetings(id,title,happened_at,thread_id,person_id) VALUES(?,?,?,?,?)",
            ("meeting-1", "Cedar Shop meeting", "2026-09-20T04:03:00Z", "thread-1", "person-1"),
        )
        db.execute(
            "INSERT INTO agreements(id,agreement_family_id,version,counterparty_person_id,type,status,"
            "value,currency,evidence_refs) VALUES(?,?,?,?,?,?,?,?,?)",
            ("agreement-1", "family-1", "v1", "person-1", "creator", "draft", 125.5, "USD", '["synthetic"]'),
        )

        pulled = "2026-09-20T04:04:00Z"
        db.execute(table.PROPOSAL_DDL)
        db.execute(
            'INSERT INTO proposals(id,module,table_name,row_id,changes,why,"by",at,state) '
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("proposal-1", "people", "agreements", "agreement-1", '{"value":"125.50"}', "synthetic", "fixture", pulled, "pending"),
        )
        db.execute(
            "CREATE TABLE runtime_payloads("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, payload BLOB, note TEXT)"
        )
        db.execute(
            "INSERT INTO runtime_payloads(payload,note) VALUES(?,?)",
            (b"\x00\xffsynthetic\x10", "Zażółć 🦊"),
        )
        db.execute(
            "CREATE TABLE runtime_items("
            "id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE runtime_item_history("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "item_id INTEGER NOT NULL REFERENCES runtime_items(id), "
            "action TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TRIGGER runtime_items_audit AFTER INSERT ON runtime_items "
            "BEGIN INSERT INTO runtime_item_history(item_id,action) "
            "VALUES(NEW.id,'created'); END"
        )
        db.execute(
            "INSERT INTO runtime_items(id,value) VALUES(?,?)",
            (1, "trigger source"),
        )
        db.execute("CREATE TABLE runtime_sparse(label TEXT NOT NULL UNIQUE)")
        db.execute("INSERT INTO runtime_sparse(rowid,label) VALUES(?,?)", (3, "three"))
        db.execute("INSERT INTO runtime_sparse(rowid,label) VALUES(?,?)", (19, "nineteen"))
    return source


class RecoveryBundleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="private-recovery-test-", dir=os.environ.get("TMPDIR"))
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def create(self, source: Path, bundle: Path, modules: str = ALL_MODULES):
        return recovery.create_bundle(source, bundle, modules, build_tool=build_database)

    def restore(self, bundle: Path, target: Path, modules: str = ALL_MODULES):
        return recovery.restore_bundle(bundle, target, modules, build_tool=build_database)

    def test_full_multimodule_roundtrip_includes_mirrors_runtime_schema_and_metadata(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        created = self.create(source, bundle)
        target = self.root / "restored.sqlite"
        restored = self.restore(bundle, target)
        self.assertEqual("private_recovery_bundle_created", created["status"])
        self.assertEqual("logical_same_database_restored", restored["status"])
        self.assertEqual(logical_rows(source), logical_rows(target))
        with (
            closing(sqlite3.connect(source)) as source_db,
            closing(sqlite3.connect(target)) as target_db,
            source_db,
            target_db,
        ):
            source_db.row_factory = sqlite3.Row
            target_db.row_factory = sqlite3.Row
            self.assertEqual(recovery._schema_entries(source_db), recovery._schema_entries(target_db))
            self.assertEqual(recovery._sqlite_metadata(source_db), recovery._sqlite_metadata(target_db))
            self.assertEqual([], list(target_db.execute("PRAGMA foreign_key_check")))
            self.assertEqual("ok", target_db.execute("PRAGMA integrity_check").fetchone()[0])
            self.assertEqual(1, target_db.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
            self.assertEqual(1, target_db.execute("SELECT COUNT(*) FROM agreements").fetchone()[0])
            self.assertEqual(1, target_db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0])
            history = list(
                target_db.execute(
                    "SELECT id,item_id,action FROM runtime_item_history ORDER BY id"
                )
            )
            self.assertEqual([(1, 1, "created")], [tuple(row) for row in history])
            sparse = list(
                target_db.execute(
                    "SELECT rowid,label FROM runtime_sparse ORDER BY rowid"
                )
            )
            self.assertEqual([(3, "three"), (19, "nineteen")], [tuple(row) for row in sparse])
            blob = target_db.execute("SELECT payload,note,typeof(payload) FROM runtime_payloads").fetchone()
            self.assertEqual(
                (b"\x00\xffsynthetic\x10", "Zażółć 🦊", "blob"), tuple(blob)
            )
            source_next = source_db.execute(
                "INSERT INTO activity(subject_type,subject_id,actor,at) VALUES('test','next','fixture','t')"
            ).lastrowid
            target_next = target_db.execute(
                "INSERT INTO activity(subject_type,subject_id,actor,at) VALUES('test','next','fixture','t')"
            ).lastrowid
            self.assertEqual(source_next, target_next)

    def test_cli_creates_and_restores_private_bundle(self):
        source = self.root / "cli-source.sqlite"
        build_database.build_database(source, "work", actor="fixture")
        bundle = self.root / "cli-bundle"
        target = self.root / "cli-target.sqlite"
        common = [
            sys.executable,
            str((Path(__file__).resolve().parent / '../recovery_bundle.py')),
            "--build-tool",
            str((Path(__file__).resolve().parent / '../build_database.py')),
        ]
        created = subprocess.run(
            common + ["create", str(source), str(bundle), "--modules", "work"],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, created.returncode, created.stderr)
        restored = subprocess.run(
            common + ["restore", str(bundle), str(target), "--modules", "work"],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, restored.returncode, restored.stderr)
        self.assertEqual(logical_rows(source), logical_rows(target))

    def test_installed_modules_cannot_be_omitted_from_selection(self):
        source = full_source(self.root)
        bundle = self.root / "must-not-exist-bundle"
        with self.assertRaisesRegex(
            recovery.BundleError, "installed module set does not match selection"
        ):
            self.create(source, bundle, "work")
        self.assertFalse(bundle.exists())

    def test_corrupt_payload_fails_without_target(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        self.create(source, bundle)
        manifest = json.loads((bundle / "manifest.json").read_text())
        payload = bundle / manifest["tables"][0]["file"]
        payload.write_bytes(payload.read_bytes() + b"{}\n")
        target = self.root / "must-not-exist.sqlite"
        with self.assertRaisesRegex(recovery.BundleError, "payload digest mismatch"):
            self.restore(bundle, target)
        self.assertFalse(target.exists())

    def test_corrupt_manifest_fails_without_target(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        self.create(source, bundle)
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["row_count"] += 1
        write_manifest(bundle, manifest)
        target = self.root / "must-not-exist.sqlite"
        with self.assertRaisesRegex(recovery.BundleError, "manifest digest mismatch"):
            self.restore(bundle, target)
        self.assertFalse(target.exists())

    def test_corrupt_module_binding_fails_without_target(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        self.create(source, bundle)
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["blueprint_hashes"]["work"] = "0" * 64
        manifest["manifest_sha256"] = recovery._manifest_digest(manifest)
        write_manifest(bundle, manifest)
        target = self.root / "must-not-exist.sqlite"
        with self.assertRaisesRegex(recovery.BundleError, "blueprint hashes"):
            self.restore(bundle, target)
        self.assertFalse(target.exists())

    def test_case_sensitive_blueprint_literal_change_is_refused(self):
        source = self.root / "changed-literal.sqlite"
        build_database.build_database(source, "work", actor="fixture")
        with closing(sqlite3.connect(source)) as db, db:
            original = db.execute(
                "SELECT sql FROM sqlite_schema WHERE type='table' AND name='tasks'"
            ).fetchone()[0]
            changed = original.replace("'todo'", "'TODO'", 1)
            self.assertNotEqual(original, changed)
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
            definitions = db.execute("SELECT type,name,sql FROM sqlite_schema WHERE sql IS NOT NULL AND (type='view' OR (type IN ('index','trigger') AND tbl_name='tasks'))").fetchall()
            for kind,name,_ in definitions:
                db.execute('DROP ' + kind + ' "' + name.replace('"','""') + '"')
            db.execute('DROP TABLE tasks')
            db.execute(changed)
            for _,_,definition in definitions:
                db.execute(definition)
        bundle = self.root / "must-not-exist-bundle"
        with self.assertRaisesRegex(
            recovery.BundleError, "source module schema differs from blueprint"
        ):
            self.create(source, bundle, "work")
        self.assertFalse(bundle.exists())

    def test_forged_rehashed_side_effect_sql_is_refused_before_execution(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        self.create(source, bundle)
        external = self.root / "must-not-exist-external.sqlite"
        manifest = json.loads((bundle / "manifest.json").read_text())
        entry = next(
            item for item in manifest["schema"]
            if item["type"] == "table" and item["name"] == "runtime_payloads"
        )
        entry["sql"] = "ATTACH DATABASE " + repr(str(external)) + " AS forged"
        manifest["schema_digest"] = recovery._schema_digest(manifest["schema"])
        manifest["manifest_sha256"] = recovery._manifest_digest(manifest)
        write_manifest(bundle, manifest)
        target = self.root / "must-not-exist-target.sqlite"
        with self.assertRaisesRegex(
            recovery.BundleError, "unsafe or mismatched schema statement"
        ):
            self.restore(bundle, target)
        self.assertFalse(external.exists())
        self.assertFalse(target.exists())

    def test_trigger_generated_history_is_not_replayed(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        self.create(source, bundle)
        target = self.root / "restored.sqlite"
        self.restore(bundle, target)
        with (
            closing(sqlite3.connect(source)) as source_db,
            closing(sqlite3.connect(target)) as target_db,
        ):
            source_rows = list(
                source_db.execute(
                    "SELECT id,item_id,action FROM runtime_item_history ORDER BY id"
                )
            )
            target_rows = list(
                target_db.execute(
                    "SELECT id,item_id,action FROM runtime_item_history ORDER BY id"
                )
            )
        self.assertEqual([(1, 1, "created")], source_rows)
        self.assertEqual(source_rows, target_rows)

    def test_sparse_implicit_rowids_are_preserved(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        self.create(source, bundle)
        target = self.root / "restored.sqlite"
        self.restore(bundle, target)
        with closing(sqlite3.connect(target)) as db:
            rows = list(
                db.execute("SELECT rowid,label FROM runtime_sparse ORDER BY rowid")
            )
        self.assertEqual([(3, "three"), (19, "nineteen")], rows)

    def test_inaccessible_implicit_rowid_is_refused(self):
        source = self.root / "shadowed-rowid.sqlite"
        build_database.build_database(source, "work", actor="fixture")
        with closing(sqlite3.connect(source)) as db, db:
            db.execute(
                'CREATE TABLE runtime_shadowed('
                '"rowid" TEXT, "_rowid_" TEXT, "oid" TEXT)'
            )
        bundle = self.root / "must-not-exist-bundle"
        with self.assertRaisesRegex(
            recovery.BundleError, "implicit rowid is inaccessible"
        ):
            self.create(source, bundle, "work")
        self.assertFalse(bundle.exists())

    def test_existing_target_and_bundle_are_never_overwritten(self):
        source = full_source(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        marker = bundle / "marker"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(recovery.BundleError, "already exists"):
            self.create(source, bundle)
        self.assertEqual("keep", marker.read_text())

        fresh_bundle = self.root / "fresh-bundle"
        self.create(source, fresh_bundle)
        target = self.root / "existing.sqlite"
        target.write_bytes(b"keep target")
        with self.assertRaisesRegex(recovery.BundleError, "never overwrites"):
            self.restore(fresh_bundle, target)
        self.assertEqual(b"keep target", target.read_bytes())

    def test_legacy_fk_broken_source_is_named_and_refused(self):
        source = self.root / "broken.sqlite"
        build_database.build_database(source, "work", actor="fixture")
        with closing(sqlite3.connect(source)) as db, db:
            db.execute(
                "INSERT INTO tasks(id,title,status,project,created_by) VALUES(?,?,?,?,?)",
                ("dangling-task", "Dangling", "todo", "missing-project", "fixture"),
            )
        bundle = self.root / "must-not-exist-bundle"
        with self.assertRaisesRegex(
            recovery.BundleError, r"source foreign key defect: \('tasks', .*'projects'"
        ):
            self.create(source, bundle, "work")
        self.assertFalse(bundle.exists())

    def test_stale_source_module_identity_is_refused(self):
        source = self.root / "stale.sqlite"
        build_database.build_database(source, "work", actor="fixture")
        with closing(sqlite3.connect(source)) as db, db:
            db.execute(
                "UPDATE installed_modules SET blueprint_hash=? WHERE module='work'",
                ("0" * 64,),
            )
        bundle = self.root / "must-not-exist-bundle"
        with self.assertRaisesRegex(recovery.BundleError, "module identity"):
            self.create(source, bundle, "work")
        self.assertFalse(bundle.exists())

    def test_generated_and_virtual_schema_are_refused(self):
        for label, ddl in (
            (
                "generated",
                "CREATE TABLE runtime_generated(a INTEGER, b INTEGER GENERATED ALWAYS AS (a+1) VIRTUAL)",
            ),
            ("virtual", "CREATE VIRTUAL TABLE runtime_fts USING fts5(body)"),
        ):
            with self.subTest(label=label):
                case = self.root / label
                case.mkdir()
                source = case / "source.sqlite"
                build_database.build_database(source, "work", actor="fixture")
                with closing(sqlite3.connect(source)) as db, db:
                    db.execute(ddl)
                bundle = case / "bundle"
                with self.assertRaisesRegex(recovery.BundleError, "unsupported"):
                    self.create(source, bundle, "work")
                self.assertFalse(bundle.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
